import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
import osintnator as app
import free_sources

class FreeSourceTests(unittest.TestCase):
    def test_username_discovery_keeps_only_exact_handle(self):
        data={'items':[{'login':'Example','id':1},{'login':'example-fan','id':2},{'login':'notexample','id':3}]}
        with patch.object(free_sources,'get_json',side_effect=[(data,None),({'id':1,'login':'Example'},None)]):
            hits=free_sources.github_discovery(SimpleNamespace(),app.OSINTQuery(username='example'))
        self.assertEqual([h.title for h in hits],['Example'])

    def test_similar_handles_do_not_count_as_a_match(self):
        with patch.object(free_sources,'get_json',return_value=({'items':[{'login':'example-fan','id':2}]},None)):
            hits=free_sources.github_discovery(SimpleNamespace(),app.OSINTQuery(username='example'))
        self.assertEqual(hits[0].raw['kind'],'not_found')

    def test_domain_is_in_engine_fallback_query(self):
        from urllib.parse import unquote_plus
        self.assertIn('example.org',unquote_plus(app.dork_url('Domain DNS Records',app.OSINTQuery(domain='example.org'),'Bing')))

    def test_email_lookup_sends_domain_only(self):
        session=Mock(); session.get.return_value=Mock(status_code=200,json=Mock(return_value={'Status':0,'Answer':[{'name':'example.org','type':15,'data':'10 mail.example.org','TTL':60}]}))
        hits=free_sources.email_domain(session,app.OSINTQuery(email='private@example.org'))
        self.assertEqual(len(hits),2)
        for call in session.get.call_args_list: self.assertEqual(call.kwargs['params']['name'],'example.org')
        self.assertNotIn('private',str(session.get.call_args_list))
    def test_dns_errors_are_not_success(self):
        session=Mock(); session.get.return_value=Mock(status_code=200,json=Mock(return_value={'Status':2}))
        hits=free_sources.domain_dns(session,app.OSINTQuery(domain='example.org'))
        self.assertTrue(all(h.raw['kind']=='error' for h in hits))
    def test_public_name_matches_remain_candidates(self):
        session=Mock(); session.get.return_value=Mock(status_code=200,json=Mock(return_value={'items':[{'login':'example','id':1,'type':'User'}]}))
        hits=free_sources.github_discovery(session,app.OSINTQuery(first='Example',last='Name'))
        self.assertEqual(hits[0].raw['kind'],'candidate')
        self.assertIn('fullname',session.get.call_args_list[0].kwargs['params']['q'])
    def test_hackernews_null_is_not_found(self):
        session=Mock(); session.get.return_value=Mock(json=Mock(return_value=None))
        self.assertEqual(free_sources.hackernews(session,app.OSINTQuery(username='nobody'))[0].raw['kind'],'not_found')

    def test_candidates_stream_before_optional_enrichment(self):
        emitted=[]
        session=SimpleNamespace(emit_hit=lambda hit: emitted.append(hit.title))
        def fetch(session,site,endpoint,page,**kwargs):
            if endpoint.endswith('/search/users'):
                return {'items':[{'login':'one','id':1},{'login':'two','id':2}]},None
            self.assertEqual(emitted,['one','two','one','two'])
            return {'id':1,'bio':'Public biography'},None
        with patch.object(free_sources,'get_json',side_effect=fetch) as request:
            hits=free_sources.github_discovery(session,app.OSINTQuery(first='Example',last='Name',email='example@example.org'))
        self.assertEqual(request.call_count,4)
        self.assertEqual(hits[0].raw['profile']['bio'],'Public biography')
        self.assertEqual(hits[1].raw['profile'],{})

    def test_failed_enrichment_preserves_public_search_candidates(self):
        response={'items':[{'login':'one','id':1},{'login':'two','id':2}]}
        with patch.object(free_sources,'get_json',side_effect=[(response,None),(None,[]) ]):
            hits=free_sources.github_discovery(SimpleNamespace(),app.OSINTQuery(first='Example'))
        self.assertEqual([h.title for h in hits],['one','two'])
        self.assertTrue(all(h.raw['kind']=='candidate' for h in hits))

if __name__=='__main__': unittest.main()
