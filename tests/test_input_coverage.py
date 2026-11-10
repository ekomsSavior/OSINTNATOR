import json
import queue
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import unquote_plus
import xml.etree.ElementTree as ET

import osintnator as app
import web_search
from query_inputs import search_inputs
from research_plan import plan_lookups,coverage_plan,coverage,balanced_findings
from web_fetch import FetchError
from graph_export import export_graphml,NS
from report_html import export_html
from settings_store import save_settings,load_settings

def query():
    return app.OSINTQuery(first='Example',last='Person',username='examplehandle',email='example@example.org',
                         phone='2025550100',address1='123 SE Example Ln',city='Example City',state='WA',zip='98000',domain='example.org')

class InputCoverageTests(unittest.TestCase):
    def test_all_identifiers_are_separate_and_location_is_used(self):
        inputs={item['field']:item for item in search_inputs(query())}
        self.assertEqual(set(inputs),{'name','username','email','phone','address','domain'})
        self.assertEqual(inputs['name']['context_fields'],['city','state'])
        self.assertEqual(inputs['address']['context_fields'],['city','state','zip'])
        self.assertIn('98000',inputs['address']['query'])
        self.assertIn('123 southeast example lane',inputs['address']['query'])
        self.assertNotIn('examplehandle',inputs['name']['query'])
        self.assertNotIn('example.org',inputs['phone']['query'])

    def test_only_selected_collectors_run_with_independent_input_tasks(self):
        q=query();q.search_engine='Yandex';q.search_fallback=False
        tasks=plan_lookups(['Public Web Search','GitHub Public Discovery'],q,app.CATS)
        self.assertEqual(len(tasks),10)
        self.assertEqual({t.site for t in tasks},{'Public Web Search','GitHub Public Discovery'})
        for task in tasks:
            if task.site=='Public Web Search':
                self.assertEqual(len(search_inputs(task.query)),1)
                self.assertFalse(task.query.search_fallback)
                self.assertEqual(task.query.search_engine,'Yandex')
            else:
                supplied=[bool(task.query.full_name),bool(task.query.username),bool(task.query.email)]
                self.assertEqual(sum(supplied),1)

    def test_timeout_on_one_field_does_not_prevent_other_fields(self):
        fake=SimpleNamespace(ui_queue=queue.Queue())
        calls=[]
        def run(site,q,budget,cancel):
            field=q.search_field;calls.append((field,budget))
            kind='timeout' if field=='name' else 'candidate'
            return [app.OSINTHit(site,field,'','https://example.org/'+field,{'kind':kind})]
        with patch.object(app,'_run_site_with_timeout',side_effect=run),patch.object(app,'load_cache',return_value=[]),patch.object(app,'save_reports',return_value=('a','b','c')):
            app.App._background_run(fake,['Public Web Search'],False,query(),4,7,'Yandex')
        self.assertEqual({field for field,budget in calls},{'name','username','email','phone','address','domain'})
        self.assertTrue(all(budget==7 for field,budget in calls))
        rows=[value for kind,value in fake.ui_queue.queue if kind=='hit']
        self.assertEqual(len({h.raw['task_id'] for h in rows}),7)
        self.assertEqual(sum(kind=='inc_progress' for kind,value in fake.ui_queue.queue),1)

    def test_failed_engine_falls_back_with_correct_attribution(self):
        q=app.OSINTQuery(first='Example',last='Person');q.search_engine='Yandex'
        body='<h2><a class="result__a" href="https://example.org/person">Example Person profile</a></h2>'
        meta={'source_url':'https://html.duckduckgo.com/html/?q=test','checked_at':'2026-11-07'}
        with patch.object(web_search,'fetch_page',side_effect=[FetchError('blocked'),(body,meta)]) as fetch:
            hits=web_search.web_search(SimpleNamespace(),q)
        self.assertEqual(fetch.call_count,2)
        self.assertEqual(hits[0].raw['kind'],'blocked')
        self.assertEqual(hits[1].raw['engine'],'DuckDuckGo')
        self.assertEqual(hits[1].raw['fallback_from'],'Yandex')
        self.assertEqual(hits[1].raw['input_fields'],['name'])

    def test_fallback_does_not_run_when_disabled_or_primary_succeeds(self):
        q=app.OSINTQuery(first='Example');q.search_engine='Yandex';q.search_fallback=False
        with patch.object(web_search,'fetch_page',side_effect=FetchError('blocked')) as fetch:
            web_search.web_search(SimpleNamespace(),q)
        self.assertEqual(fetch.call_count,1)
        q.search_fallback=True
        body='<h2><a href="https://example.org/profile">Example profile</a></h2>'
        with patch.object(web_search,'fetch_page',return_value=(body,{'source_url':'https://yandex.com/search/?text=Example'})) as fetch:
            web_search.web_search(SimpleNamespace(),q)
        self.assertEqual(fetch.call_count,1)

    def test_phone_and_street_formats_can_match(self):
        meta={'source_url':'https://html.duckduckgo.com/html/?q=test'}
        phone='<h2><a href="https://example.org/contact">Contact (202) 555-0100</a></h2>'
        rows=web_search.parse_results(phone,meta,'2025550100','DuckDuckGo',field='phone')
        self.assertEqual(len(rows),1)
        street='<h2><a href="https://example.org/place">123 Southeast Example Lane</a></h2>'
        rows=web_search.parse_results(street,meta,'123 SE Example Ln','DuckDuckGo',field='address')
        self.assertEqual(len(rows),1)
        self.assertEqual(web_search.parse_results(phone,meta,'2025550199','DuckDuckGo',field='phone'),[])

    def test_coverage_does_not_call_unsearched_or_manual_fields_successful(self):
        rows=[app.OSINTHit('A','Web','','https://example.org',{'kind':'record','input_fields':['domain'],'task_id':'web'}),
              app.OSINTHit('B','Blocked','','',{'kind':'blocked','input_fields':['name'],'task_id':'name'}),
              app.OSINTHit('C','Manual','','',{'kind':'manual','input_fields':['phone'],'task_id':'phone'})]
        stats=coverage(rows,{'domain':1,'name':1,'phone':1,'email':0})
        self.assertEqual(stats['domain']['findings'],1)
        self.assertIn('unavailable',stats['name']['status'])
        self.assertEqual(stats['phone']['status'],'manual paths only')
        self.assertEqual(stats['email']['status'],'no selected collector')

    def test_website_rows_do_not_bury_other_inputs(self):
        web=[app.OSINTHit('Web',str(i),'','',{'kind':'record','input_fields':['domain']}) for i in range(20)]
        name=app.OSINTHit('Search','Name','','',{'kind':'candidate','input_fields':['name']})
        phone=app.OSINTHit('Search','Phone','','',{'kind':'candidate','input_fields':['phone']})
        ordered=balanced_findings(web+[name,phone])
        self.assertEqual([h.title for h in ordered[:3]],['Name','Phone','0'])

    def test_graph_and_html_preserve_failed_field_coverage(self):
        plan={'name':1,'domain':1}
        rows=[app.OSINTHit('Search','No name results','','',{'kind':'blocked','input_fields':['name'],'coverage_plan':plan,'task_id':'name'}),
              app.OSINTHit('Web','Web page','','https://example.org',{'kind':'record','input_fields':['domain'],'coverage_plan':plan,'task_id':'web'})]
        with tempfile.TemporaryDirectory() as folder:
            graph=Path(folder)/'graph.graphml';html=Path(folder)/'report.html'
            export_graphml(rows,graph);export_html(rows,html)
            root=ET.parse(graph).getroot()
            data=root.find('.//{'+NS+'}graph/{'+NS+'}data[@key="coverage"]')
            self.assertEqual(json.loads(data.text)['name']['findings'],0)
            self.assertEqual(len(root.findall('.//{'+NS+'}edge')),1)
            self.assertIn('Input coverage',html.read_text())
            self.assertIn('no findings; source unavailable',html.read_text())

    def test_fallback_preference_is_saved_without_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings.json'
            save_settings(path,4,30,True,['Public Web Search'],'Yandex',False)
            self.assertFalse(load_settings(path,{'Public Web Search'})['search_fallback'])
            self.assertNotIn('email',path.read_text())

    def test_phone_fallback_link_uses_phone_not_other_identifiers(self):
        q=query();q.search_field='phone'
        url=unquote_plus(app.dork_url('Public Web Search',q,'Yandex'))
        self.assertIn('2025550100',url)
        self.assertNotIn('examplehandle',url)

if __name__=='__main__':unittest.main()
