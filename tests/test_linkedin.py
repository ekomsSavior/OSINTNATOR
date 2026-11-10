import base64
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import quote, parse_qs, urlsplit

from linkedin_sources import SITE, linkedin_name_search, name_matches, profile_url, profile_candidates, search_expression
from models import OSINTQuery
from research_plan import plan_lookups
from source_catalog import CATS
from web_catalog import CATALOG
from web_fetch import FetchError
from web_service import ENGINE_SOURCES, clean_hit, collect, ordered_tasks

META = {'source_url': 'https://www.bing.com/search?q=test', 'checked_at': '2026-11-09T12:00:00Z', 'content_sha256': 'fixture'}


def block(url='https://www.linkedin.com/in/jane-doe-123/', title='Jane M. Doe - Researcher | LinkedIn', snippet='Researcher in Seattle'):
    return '<li class="b_algo"><h2><a href="'+url+'">'+title+'</a></h2><div class="b_caption"><p>'+snippet+'</p></div></li>'


class LinkedInTests(unittest.TestCase):
    def query(self, **kwargs):
        q = OSINTQuery(first='Jane', last='Doe', **kwargs)
        q.search_engine = 'Bing'
        q.search_fallback = False
        return q

    def test_names_with_middle_initials_accents_and_punctuation(self):
        for title, first, last in [('Jane M. Doe | LinkedIn','Jane','Doe'), ('Doe, Jane - Engineer','Jane','Doe'),
                                   ('José Pérez - Engineer','Jose','Perez'), ("Mary O’Neil - Writer",'Mary',"O'Neil")]:
            self.assertTrue(name_matches(title, first, last))
        for title in ['Janette Doe', 'Jane Doerr', 'John Doe', 'Jane runs a large team with Doe']:
            self.assertFalse(name_matches(title, 'Jane', 'Doe'))

    def test_person_url_validation_and_region_deduplication(self):
        self.assertEqual(profile_url('https://uk.linkedin.com/in/jane-doe?trk=abc#about'), 'https://www.linkedin.com/in/jane-doe/')
        self.assertTrue(profile_url('https://www.linkedin.com/pub/jane-doe/1/2/3'))
        for url in ['https://linkedin.com.evil.test/in/jane', 'https://evil.test/in/jane', 'https://www.linkedin.com/company/jane',
                    'https://www.linkedin.com/pub/dir/Jane/Doe', 'https://www.linkedin.com/in/jane/posts',
                    'https://www.linkedin.com/in/jane%2fadmin', 'https://www.linkedin.com/in/%252f',
                    'https://user@www.linkedin.com/in/jane', 'https://www.linkedin.com:444/in/jane',
                    'https://www.linkedin.com:bad/in/jane', 'https://www.linkedin.com/login', 'javascript:alert(1)']:
            self.assertEqual(profile_url(url), '', url)

    def test_returned_evidence_and_source_are_preserved(self):
        rows = profile_candidates(block(), META, self.query(), 'Bing')
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.raw['kind'], 'candidate')
        self.assertFalse(row.raw['identity_verified'])
        self.assertEqual(row.raw['source_url'], META['source_url'])
        self.assertIn('Seattle', row.raw['fields']['indexed_snippet'])
        self.assertEqual(row.raw['entity_value'], row.url)
        self.assertEqual(clean_hit(row).raw['fields'], row.raw['fields'])

    def test_only_person_profiles_and_matching_names_returned(self):
        body = block(title='John Doe')+block(url='https://linkedin.com/company/jane-doe')+block(url='https://evil.test/in/jane-doe')
        self.assertEqual(profile_candidates(body, META, self.query(), 'Bing'), [])
        self.assertEqual(profile_candidates('<h1>Jane Doe</h1>'+block(title='No name',snippet='Other profile'), META, self.query(), 'Bing'), [])

    def test_query_or_slug_alone_is_not_name_evidence(self):
        self.assertEqual(profile_candidates(block(title='Professional profile',snippet='No name in result'),META,self.query(),'Bing'),[])

    def test_real_snippet_name_can_be_a_labeled_candidate(self):
        row = profile_candidates(block(title='Professional profile',snippet='Jane Doe works in research'),META,self.query(),'Bing')[0]
        self.assertEqual(row.raw['fields']['name_match_in'],'snippet')
        self.assertFalse(row.raw['identity_verified'])

    def test_redirect_results_and_regional_duplicates(self):
        target='https://uk.linkedin.com/in/jane-doe-123?trk=search'
        encoded='a1'+base64.urlsafe_b64encode(target.encode()).decode().rstrip('=')
        body=block(url='https://www.bing.com/ck/a?u='+encoded)+block()
        self.assertEqual(len(profile_candidates(body,META,self.query(),'Bing')),1)
        body=block(url='https://www.google.com/url?q='+quote(target,safe=''))
        self.assertEqual(len(profile_candidates(body,META,self.query(),'Google')),1)

    def test_profile_after_ten_non_profile_results_not_lost(self):
        body=''.join(block(url='https://example.org/'+str(i)) for i in range(12))+block()
        self.assertEqual(len(profile_candidates(body,META,self.query(),'Bing')),1)

    def test_missing_name_makes_no_network_request(self):
        with patch('linkedin_sources.fetch_page') as fetch:
            rows=linkedin_name_search(SimpleNamespace(),OSINTQuery(first='Jane',username='jane'))
        fetch.assert_not_called()
        self.assertEqual(rows[0].raw['kind'],'needs_input')

    def test_only_search_engine_is_fetched_and_success_streams(self):
        emitted=[]
        with patch('linkedin_sources.fetch_page',return_value=(block(),META)) as fetch:
            rows=linkedin_name_search(SimpleNamespace(emit_hit=emitted.append),self.query())
        self.assertEqual(fetch.call_count,1)
        url=fetch.call_args.args[1]
        self.assertEqual(urlsplit(url).hostname,'www.bing.com')
        self.assertIn('site:linkedin.com/in/',parse_qs(urlsplit(url).query)['q'][0])
        self.assertEqual(emitted,rows)

    def test_failure_fallback_and_manual_navigation_are_honest(self):
        q=self.query();q.search_fallback=True
        with patch('linkedin_sources.fetch_page',side_effect=[FetchError('HTTP 403 from Bing'),(block(),META)]) as fetch:
            rows=linkedin_name_search(SimpleNamespace(),q)
        self.assertEqual(fetch.call_count,2)
        self.assertEqual(rows[0].raw['http_status'],403)
        self.assertEqual(rows[-1].raw['fallback_from'],'Bing')
        self.assertEqual(rows[-1].raw['engine'],'Yahoo')
        q.search_fallback=False
        with patch('linkedin_sources.fetch_page',return_value=('<h1>No results</h1>',META)) as fetch:
            rows=linkedin_name_search(SimpleNamespace(),q)
        self.assertEqual(fetch.call_count,2)
        self.assertFalse(any(row.raw['kind']=='candidate' for row in rows))
        self.assertEqual(rows[-1].raw['kind'],'manual')

    def test_empty_index_response_tries_one_broader_query(self):
        with patch('linkedin_sources.fetch_page',side_effect=[('<h1>No results</h1>',META),(block(),META)]) as fetch:
            rows=linkedin_name_search(SimpleNamespace(),self.query())
        self.assertEqual(fetch.call_count,2)
        expressions=[parse_qs(urlsplit(call.args[1]).query)['q'][0] for call in fetch.call_args_list]
        self.assertIn('site:linkedin.com/in/',expressions[0])
        self.assertEqual(expressions[1],'"Jane Doe" site:linkedin.com')
        self.assertEqual(rows[-1].raw['kind'],'candidate')
        self.assertEqual(rows[-1].raw['engine'],'Bing')

    def test_server_failure_does_not_trigger_same_engine_retry(self):
        with patch('linkedin_sources.fetch_page',side_effect=FetchError('HTTP 500 from Bing')) as fetch:
            rows=linkedin_name_search(SimpleNamespace(),self.query())
        self.assertEqual(fetch.call_count,1)
        self.assertEqual(rows[0].raw['kind'],'unavailable')

    def test_paused_engine_not_retried(self):
        q=self.query();q.search_skip_engines=('Bing',)
        with patch('linkedin_sources.fetch_page') as fetch:
            rows=linkedin_name_search(SimpleNamespace(),q)
        fetch.assert_not_called()
        self.assertEqual(rows[0].raw['kind'],'blocked')

    def test_name_and_location_have_independent_budgets(self):
        q=self.query(city='Seattle',state='WA',domain='example.org',email='person@example.org')
        tasks=plan_lookups([SITE],q,CATS)
        self.assertEqual([t.task_id for t in tasks],[SITE+':name',SITE+':name_location'])
        broad,refined=[search_expression(t.query) for t in tasks]
        self.assertNotIn('Seattle',broad[0]);self.assertEqual(broad[1],[])
        self.assertIn('"Seattle"',refined[0]);self.assertEqual(refined[1],['city','state'])
        self.assertNotIn('example.org',broad[0]+refined[0])
        with patch('web_service.run_bounded',return_value=SimpleNamespace(hits=[],status='complete')) as run:
            for task in tasks:collect(task,20,threading.Event())
        self.assertEqual([c.args[2] for c in run.call_args_list],[20,20])

    def test_hosted_catalog_and_all_field_scheduling(self):
        self.assertEqual(CATALOG[SITE]['mode'],'collector')
        self.assertEqual(CATALOG[SITE]['fields'],['name'])
        self.assertIn(SITE,ENGINE_SOURCES)
        q=self.query(username='handle',email='person@example.org',phone='2025550100',address1='10 Main St',city='Seattle',state='WA',domain='example.org')
        tasks=ordered_tasks(plan_lookups(list(CATALOG),q,CATS))
        primary=[t for t in tasks if t.site=='Public Web Search' and not t.task_id.endswith('_location')]
        self.assertEqual({t.fields[0] for t in primary},{'name','username','email','phone','address','domain'})
        self.assertEqual(sum(t.site==SITE for t in tasks),2)


if __name__ == '__main__':
    unittest.main()
