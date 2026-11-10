import hashlib
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch

import osintnator as app
import api_sources
import free_sources
import public_web
import web_fetch
import web_search
import scrapers
from bounded_runner import Outcome
from graph_export import export_graphml,NS
from query_inputs import normalize_domain,github_handle,search_terms
from report_html import export_html

META={'source_url':'https://example.org/','checked_at':'2026-11-06T00:00:00Z','content_sha256':'abc'}

class RetrievalTests(unittest.TestCase):
    def test_generic_youtube_shell_is_not_a_profile_finding(self):
        body='<title>YouTube</title><meta property="og:type" content="profile"><link rel="canonical" href="https://www.youtube.com/@example"><meta name="description" content="Share your videos with friends, family, and the world">'
        self.assertIsNone(scrapers.profile_details(body,'YouTube','example','https://www.youtube.com/@example'))

    def test_html_report_escapes_source_content_and_separates_diagnostics(self):
        hits=[app.OSINTHit('A','<script>alert(1)</script>','Text','javascript:alert(1)',{'kind':'candidate'}),
              app.OSINTHit('B','Unavailable','Blocked','https://example.org',{'kind':'blocked'})]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'report.html';export_html(hits,path);text=path.read_text()
        self.assertNotIn('<script>',text)
        self.assertNotIn('href="javascript:',text)
        self.assertGreater(text.index('Unavailable'),text.index('<details>'))

    def test_profile_checker_rejects_username_echo_and_accepts_profile_marker(self):
        echo='<title>GitHub</title><input value="example">Search for example'
        self.assertIsNone(scrapers.profile_details(echo,'GitHub','example','https://github.com/example'))
        profile='<title>Example on GitHub</title><span class="p-nickname">example</span><meta name="description" content="Public bio">'
        self.assertEqual(scrapers.profile_details(profile,'GitHub','example','https://github.com/example'),('Example on GitHub','Public bio'))
    def test_website_url_and_profile_url_are_accepted(self):
        self.assertEqual(normalize_domain('https://Example.org/about?x=1'),'example.org')
        self.assertEqual(github_handle('https://github.com/Example'),('Example',False))
        self.assertEqual(github_handle('@example'),('example',False))
        self.assertEqual(github_handle('example person'),('exampleperson',True))
        for url in ('https://example.org@localhost/','file:///etc/passwd','https://github.com/login'):
            with self.assertRaises(ValueError): github_handle(url)

    def test_spaced_handle_is_candidate_with_real_profile_fields(self):
        response={'login':'exampleperson','id':42,'bio':'Public bio','blog':'https://example.org','public_repos':3}
        with patch.object(api_sources,'get_json',return_value=(response,None)) as request:
            hits=api_sources.github_profile(Mock(),app.OSINTQuery(username='example person'))
        self.assertTrue(request.call_args.args[2].endswith('/exampleperson'))
        self.assertEqual(hits[0].raw['kind'],'candidate')
        self.assertEqual(hits[0].raw['fields']['bio'],'Public bio')
        self.assertEqual(hits[1].raw['relationship'],'profile_links_to')

    def test_public_page_yields_observed_links_and_contacts(self):
        body='''<html><title>Example team</title><meta name="description" content="Our public project">
        <h1>About the project</h1><a href="https://github.com/example">Source account</a>
        <a href="https://github.com/example">Duplicate</a><a href="mailto:contact@example.org">Contact</a>
        <a href="/about">About</a><a href="https://code.example.org/user/login">Login</a>
        <input value="hidden@example.org"><script>secret@example.org</script></html>'''
        hits,follow=public_web.parse_page(body,META,'example.org')
        self.assertEqual(len(hits),3)
        self.assertEqual(follow,['https://example.org/about'])
        self.assertEqual(hits[0].raw['fields']['description'],'Our public project')
        self.assertEqual({h.raw['relationship'] for h in hits},{'page_metadata','publishes_contact','links_to'})
        self.assertNotIn('secret@example.org',str(hits))
        self.assertTrue(all(h.raw['source_url']==META['source_url'] for h in hits))

    def test_access_challenge_is_not_metadata_finding(self):
        with self.assertRaises(web_fetch.FetchError):
            public_web.parse_page('<title>Just a moment</title>Verify you are human',META,'example.org')

    def test_crawler_obeys_robots(self):
        with patch.object(public_web,'fetch_page',return_value=('User-agent: *\nDisallow: /',META)) as request:
            hits=public_web.website_collection(Mock(),app.OSINTQuery(domain='https://example.org'))
        self.assertEqual(request.call_count,1)
        self.assertEqual(hits[0].raw['kind'],'blocked')

    def test_private_redirect_is_rejected_before_request(self):
        response=Mock(status_code=302,headers={'Location':'http://127.0.0.1/private'})
        response.__enter__=Mock(return_value=response);response.__exit__=Mock()
        session=Mock();session.get.return_value=response;session._osint_last_request=0
        answers=[[(2,1,6,'',('8.8.8.8',443))],[(2,1,6,'',('127.0.0.1',80))]]
        with patch.object(web_fetch.socket,'getaddrinfo',side_effect=answers),patch.object(web_fetch.time,'sleep'):
            with self.assertRaises(web_fetch.FetchError): web_fetch.fetch_page(session,'https://example.org')
        self.assertEqual(session.get.call_count,1)

    def test_page_evidence_hash_matches_saved_bytes(self):
        body=b'<html><title>Public page</title></html>'
        response=Mock(status_code=200,headers={'Content-Type':'text/html'},encoding='utf-8')
        response.iter_content.return_value=[body]
        response.__enter__=Mock(return_value=response);response.__exit__=Mock()
        session=Mock();session.get.return_value=response;session._osint_last_request=0
        with tempfile.TemporaryDirectory() as folder,patch.object(web_fetch,'EVIDENCE_DIR',Path(folder)),patch.object(web_fetch,'public_url'),patch.object(web_fetch.time,'sleep'):
            text,metadata=web_fetch.fetch_page(session,'https://example.org')
            self.assertEqual(Path(metadata['evidence_file']).read_bytes(),body)
            self.assertEqual(metadata['content_sha256'],hashlib.sha256(body).hexdigest())

    def test_separate_search_terms_never_combine_identity_fields(self):
        q=app.OSINTQuery(first='Example',last='Person',username='exampleperson',email='example@example.org',domain='https://example.org/')
        self.assertEqual(search_terms(q),['Example Person','exampleperson','example@example.org','example.org'])
        from urllib.parse import unquote_plus
        fallback=unquote_plus(app.dork_url('FastPeopleSearch',q,'Google'))
        self.assertIn('"Example Person"',fallback)
        self.assertNotIn('example@example.org',fallback)
        self.assertNotIn('exampleperson',fallback)

    def test_search_extracts_snippet_not_query_echo(self):
        body='''<p>Search: Example Person</p><div class="result"><h2><a class="result__a" href="https://example.org/about">Example Person biography</a></h2><p class="result__snippet">Project maintainer.</p></div><h2><a href="https://irrelevant.example">Something else</a></h2>'''
        hits=web_search.parse_results(body,{**META,'source_url':'https://html.duckduckgo.com/html/?q=x'},'Example Person','DuckDuckGo')
        self.assertEqual(len(hits),1)
        self.assertEqual(hits[0].snippet,'Project maintainer.')
        self.assertEqual(hits[0].raw['kind'],'candidate')

    def test_search_engine_selection_reaches_request(self):
        for engine,prefix in app.ENGINES.items():
            q=app.OSINTQuery(first='Example');q.search_engine=engine
            q.search_fallback=False
            with patch.object(web_search,'fetch_page',side_effect=web_fetch.FetchError('blocked')) as request:
                web_search.web_search(SimpleNamespace(),q)
            expected='https://html.duckduckgo.com/html/?q=' if engine=='DuckDuckGo' else prefix
            self.assertTrue(request.call_args.args[1].startswith(expected))

    def test_search_does_not_borrow_another_results_snippet(self):
        body='''<div><h2><a href="https://example.org">Example Person</a></h2><p class="result__snippet">Example Person biography.</p></div><h2><a href="https://unrelated.example">Unrelated page</a></h2>'''
        hits=web_search.parse_results(body,{**META,'source_url':'https://html.duckduckgo.com/html/?q=x'},'Example Person','DuckDuckGo')
        self.assertEqual([h.url for h in hits],['https://example.org'])

    def test_shared_email_provider_is_context_without_dns_requests(self):
        session=Mock()
        hit=free_sources.email_domain(session,app.OSINTQuery(email='example@gmail.com'))[0]
        session.get.assert_not_called()
        self.assertEqual(hit.raw['kind'],'context')

    def test_manual_result_is_not_duplicated_by_runner(self):
        hit=app.OSINTHit('GitHub Profile API','Unavailable','','https://github.com',{'kind':'manual'})
        with patch.object(app,'run_bounded',return_value=Outcome('complete',[hit])):
            hits=app._run_site_with_timeout('GitHub Profile API',app.OSINTQuery(username='example'),1)
        self.assertEqual(len(hits),1)

    def test_graph_keeps_sourced_links_and_excludes_navigation(self):
        rows=[app.OSINTHit('Web','Published link','','https://github.com/example',{'kind':'record','subject_url':'https://example.org','entity_type':'url','entity_value':'https://github.com/example','relationship':'links_to','source_url':'https://example.org/'}),
              app.OSINTHit('GitHub','Profile website','','https://example.org/',{'kind':'record','subject_url':'https://github.com/example','entity_type':'url','entity_value':'https://example.org/','relationship':'profile_links_to'}),
              app.OSINTHit('Legacy','Manual','','https://unused.example',{'kind':'manual'}),
              app.OSINTHit('DNS','Gmail','','https://gmail.com',{'kind':'context'})]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'graph.graphml';export_graphml(rows,path)
            root=ET.parse(path).getroot()
        self.assertEqual(len(root.findall('.//{'+NS+'}node')),2)
        self.assertEqual(len(root.findall('.//{'+NS+'}edge')),2)
        values=[x.text for x in root.findall('.//{'+NS+'}data')]
        self.assertIn('links_to',values);self.assertIn('profile_links_to',values)
        self.assertNotIn('Manual',values);self.assertNotIn('Gmail',values)

if __name__=='__main__': unittest.main()
