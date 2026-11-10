import hashlib
import json
import queue
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
import osintnator as app
import identity_sources as ids
import property_sources as prop
import contact_sources as contact
import web_search
from web_fetch import FetchError
from research_plan import plan_lookups,coverage
from evidence_matching import annotate_hit,matches
from query_inputs import search_inputs

META={'source_url':'https://example.org/source','checked_at':'2026-11-07','content_sha256':'hash'}

class CollectorTests(unittest.TestCase):
    def test_email_hash_and_returned_profile_fields(self):
        q=app.OSINTQuery(email=' Example@Example.org ')
        with patch.object(ids,'read_json',return_value=({'display_name':'Example Person','profile_url':'https://gravatar.com/example'},META)) as read:
            hit=ids.gravatar_email(None,q)[0]
        self.assertTrue(read.call_args.args[1].endswith(hashlib.sha256(b'example@example.org').hexdigest()))
        self.assertEqual(hit.raw['fields']['display_name'],'Example Person')
        self.assertEqual(hit.raw['kind'],'record')
        self.assertFalse(hit.raw['identity_verified'])

    def test_profile_absence_and_rate_limit_are_distinct(self):
        for message,kind in [('HTTP 404 from source','not_found'),('HTTP 429 from source','unavailable')]:
            with patch.object(ids,'read_json',side_effect=FetchError(message)):
                self.assertEqual(ids.gravatar_email(None,app.OSINTQuery(email='a@example.org'))[0].raw['kind'],kind)

    def test_json_api_uses_correct_accept_header(self):
        with patch.object(ids,'fetch_page',return_value=('{}',META)) as fetch:
            ids.read_json(None,'https://api.github.com/search/commits?q=test')
        self.assertEqual(fetch.call_args.kwargs['accept'],'application/vnd.github+json')

    def test_commit_requires_exact_author_email_and_stays_candidate(self):
        def item(email):return {'commit':{'author':{'name':'Example Person','email':email,'date':'2026-01-01'}},
                               'html_url':'https://github.com/example/repo/commit/abc','repository':{'full_name':'example/repo'}}
        with patch.object(ids,'read_json',return_value=({'items':[item('a@example.org'),item('b@example.org')]},META)):
            rows=ids.email_commits(None,app.OSINTQuery(email='a@example.org'))
        self.assertEqual(len(rows),1);self.assertEqual(rows[0].raw['kind'],'candidate')
        self.assertEqual(rows[0].raw['fields']['published_author_email'],'a@example.org')

    def test_unexpected_commit_response_is_not_absence(self):
        with patch.object(ids,'read_json',return_value=({},META)):
            self.assertEqual(ids.email_commits(None,app.OSINTQuery(email='a@example.org'))[0].raw['kind'],'unavailable')

    def test_missing_email_makes_no_request(self):
        with patch.object(ids,'read_json') as read:
            self.assertEqual(ids.email_commits(None,app.OSINTQuery())[0].raw['kind'],'needs_input')
            self.assertEqual(ids.gravatar_email(None,app.OSINTQuery(email='invalid'))[0].raw['kind'],'needs_input')
        read.assert_not_called()

    def test_census_returns_address_and_county_not_ownership(self):
        data={'result':{'addressMatches':[{'matchedAddress':'123 EXAMPLE ST, EL PASO, TX, 79903',
                'geographies':{'Counties':[{'NAME':'El Paso County','GEOID':'48141'}]}}]}}
        with patch.object(prop,'read_json',return_value=(data,META)):
            hit=prop.census_address(None,app.OSINTQuery(address1='123 Example St',zip='79903'))[0]
        self.assertEqual(hit.raw['fields']['county_fips'],'48141')
        self.assertNotIn('owner',hit.raw['fields'])

    def test_property_record_is_labeled_historical_and_keeps_fields(self):
        data={'features':[{'attributes':{'PROP_ID':42,'SITUS_NUM':'123','SITUS_STRE':'EXAMPLE','PROP_VAL_Y':2023,
              'LAND_ACRES':.5,'YR_BLT':'1985','TOTAL_ASSE':100000,'LEGAL_DESC':'Example parcel'}}]}
        with patch.object(prop,'read_json',return_value=(data,META)) as read:
            hit=prop.el_paso_property(None,app.OSINTQuery(address1='123 Example St',city='El Paso',state='TX'))[0]
        self.assertEqual(hit.raw['dataset_year'],2023)
        self.assertEqual(hit.raw['fields']['year_built'],'1985')
        self.assertIn('2023',hit.title)
        self.assertTrue(hit.url.startswith(prop.EL_PASO))
        params=parse_qs(urlsplit(read.call_args.args[1]).query)
        self.assertEqual(params['returnGeometry'],['false'])
        self.assertEqual(params['resultRecordCount'],['10'])

    def test_wrong_house_number_is_not_property_match(self):
        data={'features':[{'attributes':{'PROP_ID':42,'SITUS_NUM':'124','SITUS_STRE':'EXAMPLE'}}]}
        with patch.object(prop,'read_json',return_value=(data,META)):
            rows=prop.el_paso_property(None,app.OSINTQuery(address1='123 Example St'))
        self.assertEqual(rows[0].raw['kind'],'not_found')

    def test_unsupported_county_does_not_search_wrong_state(self):
        with patch.object(prop,'address_geography',return_value=([{'geographies':{'Counties':[{'GEOID':'53035'}]}}],META)),patch.object(prop,'el_paso_property') as search,patch('parcel_sources.query_layer',side_effect=FetchError('fixture source unavailable')):
            hit=prop.official_property(None,app.OSINTQuery(address1='123 Example St',city='Port Orchard',state='WA'))[0]
        search.assert_not_called();self.assertEqual(hit.raw['kind'],'unavailable')

    def test_property_api_error_is_not_absence(self):
        with patch.object(ids,'fetch_page',return_value=(json.dumps({'error':{'code':499,'message':'Token Required'}}),META)):
            with self.assertRaises(FetchError):ids.read_json(None,'https://example.org/query')

    def test_contact_structured_record_matches_multiple_inputs(self):
        data={'@type':'Person','name':'Example Person','telephone':'+1-202-555-0100','email':'a@example.org'}
        body='<script type="application/ld+json">'+json.dumps(data)+'</script>'
        q=app.OSINTQuery(first='Example',last='Person',email='a@example.org',phone='2025550100')
        hit=contact.extract_contacts(body,META,q,required_field='phone')[0]
        self.assertEqual(set(hit.raw['matched_inputs']),{'name','email','phone'})
        self.assertEqual(hit.raw['kind'],'candidate')

    def test_contact_point_and_published_phone_link(self):
        q=app.OSINTQuery(phone='2025550100')
        body='<script type="application/ld+json">{"@type":"Organization","name":"Example","contactPoint":{"telephone":"+12025550100"}}</script><a href="tel:+12025550100">Call</a>'
        rows=contact.extract_contacts(body,META,q,required_field='phone')
        self.assertEqual({h.raw['kind'] for h in rows},{'candidate','record'})

    def test_echo_or_wrong_number_is_not_contact_record(self):
        q=app.OSINTQuery(phone='2025550100')
        body='<title>Search 2025550100</title><input value="2025550100"><a href="tel:2025550199">Call</a>'
        self.assertEqual(contact.extract_contacts(body,META,q,required_field='phone'),[])

    def test_robots_disallow_prevents_contact_request(self):
        with patch.object(contact,'fetch_page',return_value=('User-agent: *\nDisallow: /',META)) as fetch:
            with self.assertRaises(FetchError):contact.public_page(None,'https://example.org/contact')
        self.assertEqual(fetch.call_count,1)

    def test_matches_ignore_request_url_and_query_echo_metadata(self):
        q=app.OSINTQuery(first='Example',last='Person',email='a@example.org')
        hit=app.OSINTHit('Test','Example Person','Other data','https://example.org/?email=a@example.org',
                         {'kind':'candidate','query':'a@example.org','fields':{'name':'Example Person'}})
        annotate_hit(hit,q)
        self.assertEqual(hit.raw['matched_inputs'],['name'])
        self.assertFalse(matches('different-a@example.org','email','a@example.org'))

    def test_legacy_multi_input_sources_have_separate_budgets(self):
        q=app.OSINTQuery(first='Example',last='Person',email='a@example.org',phone='2025550100',address1='123 Example St',city='Town',state='TX')
        tasks=plan_lookups(['TruePeopleSearch','That’sThem'],q,app.CATS)
        self.assertEqual(len(tasks),6)
        for task in tasks:
            self.assertEqual(sum(bool(v) for v in (task.query.full_name,task.query.phone,task.query.email,task.query.address1)),1)
            if task.fields[0]=='address':self.assertEqual(task.query.city,'Town')

    def test_duckduckgo_failure_tries_another_engine(self):
        q=app.OSINTQuery(phone='2025550100');q.search_engine='DuckDuckGo'
        body='<h2><a href="https://example.org/contact">Call (202) 555-0100</a></h2>'
        with patch.object(web_search,'fetch_page',side_effect=[FetchError('HTTP 202 from source'),(body,{**META,'source_url':'https://www.bing.com/search?q=test'})]) as fetch:
            rows=web_search.web_search(None,q)
        self.assertEqual(fetch.call_count,2)
        self.assertEqual(rows[-1].raw['engine'],'Bing')
        self.assertEqual(rows[-1].raw['kind'],'candidate')

    def test_rate_limited_engine_is_not_retried_for_every_input(self):
        fake=SimpleNamespace(ui_queue=queue.Queue());calls=[]
        def run(site,q,budget,cancel):
            calls.append(q.search_skip_engines)
            return [app.OSINTHit(site,'Rate limited','','',{'kind':'blocked','http_status':429,'engine':'DuckDuckGo'})]
        with patch.object(app,'_run_site_with_timeout',side_effect=run),patch.object(app,'save_reports',return_value=('a','b','c')),patch.object(app,'load_cache',return_value=[]):
            app.App._background_run(fake,['Public Web Search'],False,app.OSINTQuery(first='Example',email='a@example.org'),4,5,'DuckDuckGo')
        self.assertEqual(calls[0],())
        self.assertEqual(calls[1],('DuckDuckGo',))

    def test_phone_query_uses_the_number_without_boolean_dork(self):
        self.assertEqual(search_inputs(app.OSINTQuery(phone='(202) 555-0100'))[0]['query'],'2025550100')

    def test_yahoo_tracking_links_are_unwrapped(self):
        body='<h3><a href="https://r.search.yahoo.com/test/RU=https%3A%2F%2Fexample.org%2Fcontact/RK=2/">Call 202-555-0100</a></h3>'
        rows=web_search.parse_results(body,{'source_url':'https://search.yahoo.com/search?p=test'},'2025550100','Yahoo',field='phone')
        self.assertEqual(rows[0].url,'https://example.org/contact')

    def test_plain_contacts_with_unicode_dashes_are_retrieved(self):
        q=app.OSINTQuery(email='a@example.org',phone='2025550100')
        rows=contact.extract_contacts('<p>Contact us: a@example.org or +1–202–555–0100.</p>',META,q)
        self.assertEqual(set(rows[0].raw['matched_inputs']),{'email','phone'})
        self.assertEqual(rows[0].raw['kind'],'record')

    def test_search_form_echo_is_not_plain_contact(self):
        body='<form><p>2025550100</p></form><p>No results for 2025550100</p>'
        self.assertEqual(contact.extract_contacts(body,META,app.OSINTQuery(phone='2025550100')),[])

    def test_evidence_from_other_inputs_contributes_to_coverage(self):
        hit=app.OSINTHit('Website','Published contact','','https://example.org',{'kind':'record','input_fields':['domain'],'matched_inputs':['email'],'task_id':'website'})
        stats=coverage([hit],{'domain':1,'email':0})
        self.assertEqual(stats['email']['findings'],1)
        self.assertEqual(stats['email']['planned_checks'],0)
        self.assertEqual(stats['email']['checks'],0)

if __name__=='__main__':unittest.main()
