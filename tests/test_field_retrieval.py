"""Regression checks for complete field routing and real search-result structures."""
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from models import OSINTQuery,OSINTHit
from source_catalog import CATS
from query_inputs import search_inputs
from research_plan import plan_lookups
from web_catalog import CATALOG
from web_service import JobStore,CapacityError,ENGINE_SOURCES,ordered_tasks,run_budget
from web_search import parse_results,web_search
from public_web import parse_page

ALL_INPUTS=dict(first='Example',last='Researcher',username='examplehandle',email='contact@example.org',phone='2025550100',address1='10 Main St',city='Example City',state='WA',zip='98000',domain='example.org')
META={'source_url':'https://search.yahoo.com/search?p=test'}


class RetrievalRegressionTests(unittest.TestCase):
    def test_yahoo_contact_snippet_is_retrieved_without_breadcrumb_title(self):
        body='<div class="algo"><div class="compTitle"><a href="https://example.org/contact"><div>Example breadcrumb</div><h3>Contact us</h3></a></div><div class="compText"><p>Email contact@example.org or call (202) 555-0100.</p></div></div>'
        for field,term in [('email','contact@example.org'),('phone','2025550100')]:
            rows=parse_results(body,META,term,'Yahoo',field=field)
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0].title,'Contact us')
            self.assertIn('contact@example.org',rows[0].snippet)

    def test_number_in_unrelated_asset_url_is_not_a_phone_finding(self):
        body='<h3><a href="https://example.org/stock/2025550100">Engineering icons</a></h3>'
        self.assertEqual(parse_results(body,META,'2025550100','Yahoo',field='phone'),[])

    def test_unmatched_search_link_requires_exact_original_page_evidence(self):
        body='<div class="algo"><div class="compTitle"><a href="https://example.org/contact"><h3>Contact us</h3></a></div><div class="compText"><p>Our contact information.</p></div></div>'
        q=OSINTQuery(email='contact@example.org');q.search_engine='Yahoo';q.search_fallback=False;q.fetch_result_pages=True
        for page,expected in [('<p>Write to contact@example.org</p>',1),('<p>Write to somebody@example.org</p>',0)]:
            with patch('web_search.fetch_page',return_value=(body,META)),patch('contact_sources.public_page',return_value=(page,{'source_url':'https://example.org/contact'})):
                hits=web_search(SimpleNamespace(),q)
            records=[h for h in hits if h.raw['kind'] in ('record','candidate')]
            self.assertEqual(len(records),expected)
            self.assertTrue(all('contact@example.org' in h.snippet for h in records))

    def test_name_is_searched_with_and_without_location(self):
        q=OSINTQuery(**ALL_INPUTS)
        tasks=plan_lookups(['Public Web Search'],q,CATS)
        names=[t for t in tasks if t.fields==('name',)]
        self.assertEqual(len(names),2)
        expressions=[search_inputs(t.query)[0] for t in names]
        self.assertEqual(expressions[0]['query'],'"Example Researcher"')
        self.assertEqual(expressions[0]['context_fields'],[])
        self.assertIn('"Example City"',expressions[1]['query'])
        self.assertIn('"WA"',expressions[1]['query'])

    def test_primary_inputs_precede_obituary_and_location_refinement(self):
        tasks=ordered_tasks(plan_lookups(list(CATALOG),OSINTQuery(**ALL_INPUTS),CATS))
        web=[t for t in tasks if t.site in ENGINE_SOURCES]
        self.assertEqual({t.fields[0] for t in web[:6]}, {'name','username','email','phone','address','domain'})
        self.assertTrue(all(t.site=='Public Web Search' for t in web[:6]))
        self.assertFalse(any(t.task_id.endswith('_location') for t in web[:6]))
        self.assertEqual(len({t.task_id for t in tasks}),len(tasks))
        self.assertTrue(180<run_budget(tasks,30,900)<=900)

    def test_contact_page_precedes_general_about_navigation(self):
        body=''.join('<a href="'+url+'">Page</a>' for url in ['/about/elections','/about/programs','/about/support','/about/contact-us'])
        _,follow=parse_page(body,{'source_url':'https://example.org/'},'example.org')
        self.assertEqual(follow[0],'https://example.org/about/contact-us')

    def test_all_83_selected_sources_get_terminal_task_status(self):
        calls=[]
        def collect(task,budget,cancel):
            calls.append((task.task_id,budget))
            return [OSINTHit(task.site,'Checked','','',{'kind':'not_found'})]
        store=JobStore(collector=collect)
        try:
            job=store.create('fixture','test-ip',{'inputs':ALL_INPUTS,'sources':list(CATALOG),'budget':20})
            end=time.monotonic()+3
            while job.state=='running' and time.monotonic()<end:time.sleep(.01)
            snap=job.snapshot()
            self.assertEqual(snap['state'],'complete')
            self.assertEqual(len(calls),len(job.tasks))
            self.assertEqual({b for _,b in calls},{20})
            self.assertTrue(all(t['state']=='complete' for t in snap['tasks']))
            self.assertEqual(set(snap['coverage']),{'name','username','email','phone','address','domain'})
            self.assertTrue(all(c['checks']==c['planned_checks'] for c in snap['coverage'].values()))
        finally:store.close()

    def test_queued_and_running_fields_remain_visible(self):
        started=threading.Event();release=threading.Event()
        def held(task,budget,cancel):
            started.set();release.wait(2)
            return [OSINTHit(task.site,'Checked','','',{'kind':'not_found'})]
        store=JobStore(collector=held)
        try:
            job=store.create('fixture','test-ip',{'inputs':ALL_INPUTS,'sources':['Public Web Search']})
            self.assertTrue(started.wait(1))
            states=[t['state'] for t in job.snapshot()['tasks']]
            self.assertEqual(states.count('running'),1)
            self.assertEqual(states.count('queued'),len(job.tasks)-1)
        finally:release.set();store.close()

    def test_five_search_limit_expires_and_is_shared_across_sessions(self):
        store=JobStore(collector=lambda *args:[])
        payload={'inputs':{'username':'example'},'sources':['GitHub Profile API']}
        try:
            for n in range(5):
                job=store.create(str(n),'shared-ip',payload)
                end=time.monotonic()+2
                while store.active and time.monotonic()<end:time.sleep(.005)
            with self.assertRaisesRegex(CapacityError,'five searches'):store.create('sixth','shared-ip',payload)
            for key in store.limits:store.limits[key]=[time.monotonic()-601]*5
            self.assertIsNotNone(store.create('after-window','shared-ip',payload))
        finally:store.close()


if __name__=='__main__':unittest.main()
