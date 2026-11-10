import csv
import json
import os
import pickle
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock, patch
import osintnator as app
import scrapers
import api_sources
from bounded_runner import scrape_worker
from graph_export import export_graphml, NS
from settings_store import save_settings, load_settings

class WorkflowTests(unittest.TestCase):
    def test_graph_preserves_uncertainty_and_escapes_markup(self):
        hit=app.OSINTHit('Example', '<Title & text>', 'Unverified\x00', 'https://example.org/?a=1&b=2', {'kind':'manual','checked_at':'2026-11-06'})
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'graph.graphml'
            export_graphml([hit],path,include_diagnostics=True)
            root=ET.parse(path).getroot()
        self.assertEqual(len(root.findall('.//{'+NS+'}node')),2)
        values=[x.text for x in root.findall('.//{'+NS+'}data')]
        self.assertIn('manual',values)
        self.assertIn('<Title & text>',values)
        self.assertIn('diagnostic; not evidence',values)

    def test_graph_imports_in_networkx(self):
        try:
            import networkx
        except ImportError:
            self.skipTest('networkx not installed')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'graph.graphml'
            export_graphml([app.OSINTHit('A','Title','','https://example.org',{'kind':'record'})],path)
            graph=networkx.read_graphml(path)
            self.assertEqual(graph.number_of_nodes(),2)
            self.assertEqual(graph.number_of_edges(),1)

    def test_settings_only_store_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings.json'
            save_settings(path,100,500,True,['A','B'])
            loaded=load_settings(path,{'A'})
            self.assertEqual(loaded,dict(workers=12,timeout=60,dark=True,selected=['A'],engine='DuckDuckGo',search_fallback=True))
            self.assertEqual(set(json.loads(path.read_text())),{'version','workers','timeout','dark','selected','engine','search_fallback'})

    def test_settings_reject_malformed(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings.json'; path.write_text('[]')
            with self.assertRaises(ValueError): load_settings(path,{'A'})

    def test_report_preserves_status_and_unique_filenames(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(app,'REPORTS_DIR',folder):
            hit=app.OSINTHit('A','Manual','','https://example.org',{'kind':'manual','checked_at':'2026-11-06','source':'A'})
            first=app.save_reports([hit]); second=app.save_reports([hit])
            self.assertNotEqual(first,second)
            with open(first[0]) as stream: row=list(csv.DictReader(stream))[0]
            self.assertEqual(row['status'],'manual')
            self.assertEqual(row['checked_at'],'2026-11-06')

    def test_streaming_hits_sent_as_serializable_list(self):
        session=Mock(); session.__enter__=Mock(return_value=session); session.__exit__=Mock()
        hits=scrapers.StreamingHits(session)
        hits.emit=lambda hit: None
        hits.append(scrapers.OSINTHit('A','Title','','https://example.org',{}))
        pipe=Mock()
        with patch.object(scrapers,'get_session',return_value=session), patch.object(scrapers,'run_scraper',return_value=hits):
            scrape_worker(pipe,'A',None)
        kind,payload=pipe.send.call_args.args[0]
        self.assertEqual(kind,'done')
        self.assertIs(type(payload),list)
        pickle.dumps(payload)

    def test_virustotal_disabled_without_explicit_opt_in(self):
        session=Mock()
        with patch.dict(os.environ,{'VIRUSTOTAL_API_KEY':'test-key','OSINTNATOR_VT_ENABLE':'0'}):
            hit=api_sources.virustotal_domain(session,app.OSINTQuery(domain='example.org'))[0]
        session.get.assert_not_called()
        self.assertEqual(hit.raw['kind'],'needs_input')

    def test_virustotal_keeps_provider_timestamp(self):
        session=Mock()
        session.get.return_value=Mock(status_code=200,json=Mock(return_value={'data':{'type':'domain','id':'example.org','attributes':{'last_analysis_date':1000,'last_analysis_stats':{'malicious':0}}}}))
        with patch.dict(os.environ,{'VIRUSTOTAL_API_KEY':'test-key','OSINTNATOR_VT_ENABLE':'1'}):
            hit=api_sources.virustotal_domain(session,app.OSINTQuery(domain='example.org'))[0]
        self.assertEqual(hit.raw['kind'],'record')
        self.assertIn('1970',hit.raw['provider_analysis_at'])
        self.assertNotIn('test-key',str(hit))

class GuiTests(unittest.TestCase):
    def setUp(self):
        try: self.ui=app.App(); self.ui.update()
        except app.tk.TclError as exc: self.skipTest(str(exc))
    def tearDown(self):
        if hasattr(self,'ui'): self.ui.destroy()
    def test_filter_changes_view_not_saved_results(self):
        self.ui.results=[app.OSINTHit('A','Example candidate','','https://example.org',{'kind':'candidate'}),app.OSINTHit('B','Manual step','','https://example.net',{'kind':'manual'})]
        self.ui.filter_var.set('candidate')
        text=self.ui.txt.get('1.0','end')
        self.assertIn('Example candidate',text); self.assertNotIn('Manual step',text)
        self.ui.filter_var.set(''); self.ui.kind_var.set('manual')
        text=self.ui.txt.get('1.0','end')
        self.assertIn('Manual step',text); self.assertNotIn('Example candidate',text)
        self.assertEqual(len(self.ui.results),2)
    def test_empty_search_does_not_start_worker(self):
        with patch.object(app.messagebox,'showinfo') as message:
            self.ui._run_sites(['GitHub Profile API'])
        self.assertFalse(self.ui._running); message.assert_called_once()
    def test_cancel_and_progress_controls_are_visible(self):
        self.assertTrue(self.ui.progress.winfo_ismapped())
        self.assertTrue(self.ui.status_lbl.winfo_ismapped())
        self.ui._running=True; self.ui._cancel()
        self.assertTrue(self.ui.cancel_event.is_set())

    def test_input_filter_keeps_coverage_and_all_saved_rows(self):
        self.ui.coverage_plan={'name':1,'email':1,'phone':1,'domain':1}
        self.ui.results=[app.OSINTHit('Search','Name candidate','','https://example.org/person',{'kind':'candidate','input_fields':['name']}),
                         app.OSINTHit('Search','Email blocked','','',{'kind':'blocked','input_fields':['email']}),
                         app.OSINTHit('Search','Phone candidate','','https://example.org/contact',{'kind':'candidate','input_fields':['phone']}),
                         app.OSINTHit('Web','Website record','','https://example.org',{'kind':'record','input_fields':['domain']})]
        self.ui._update_coverage()
        self.ui.input_filter_var.set('Phone')
        text=self.ui.txt.get('1.0','end')
        self.assertIn('Phone candidate',text)
        self.assertNotIn('Website record',text)
        self.assertNotIn('Name candidate',text)
        self.assertIn('Email: no findings; source unavailable',self.ui.coverage_var.get())
        self.assertEqual(len(self.ui.results),4)
        self.ui.input_filter_var.set('Email')
        self.assertIn('No findings match this view',self.ui.txt.get('1.0','end'))
        self.ui.kind_var.set('All')
        self.assertIn('Email blocked',self.ui.txt.get('1.0','end'))

    def test_shared_evidence_filter_uses_returned_fields(self):
        self.ui.results=[app.OSINTHit('Test','Shared contact','','https://example.org',{'kind':'candidate','input_fields':['phone'],'matched_inputs':['name','phone']}),
                         app.OSINTHit('Test','Name only','','https://example.net',{'kind':'candidate','input_fields':['name'],'matched_inputs':['name']})]
        self.ui.kind_var.set('Shared evidence')
        self.assertIn('Shared contact',self.ui.txt.get('1.0','end'))
        self.assertNotIn('Name only',self.ui.txt.get('1.0','end'))
        self.ui.input_filter_var.set('Name')
        self.assertIn('Shared contact',self.ui.txt.get('1.0','end'))

    def test_source_panel_cannot_be_collapsed_away(self):
        self.ui.geometry('1100x800');self.ui.update()
        self.ui.pw.sashpos(0,80);self.ui._reset_pane_bounds();self.ui.update()
        self.assertGreaterEqual(self.ui.pw.sashpos(0),440)
        self.assertGreater(self.ui.source_canvases[0].winfo_height(),40)
        self.assertGreater(self.ui.txt.winfo_height(),40)

if __name__ == '__main__': unittest.main()
