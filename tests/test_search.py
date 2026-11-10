import queue
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import osintnator as app
import scrapers


class SearchTests(unittest.TestCase):
    def test_cache_is_scoped_and_clear_removes_all_variants(self):
        q = app.OSINTQuery(username='example')
        hit = app.OSINTHit('source', 'title', '', 'https://example.org', {})
        with tempfile.TemporaryDirectory() as folder, patch.object(app, 'CACHE_DIR', folder):
            app.save_cache(q, [hit], ['A'], 'Google')
            self.assertEqual(len(app.load_cache(q, ['A'], 'Google')), 1)
            self.assertEqual(app.load_cache(q, ['B'], 'Google'), [])
            self.assertEqual(app.load_cache(q, ['A'], 'Bing'), [])
            self.assertTrue(app.clear_cache_for_query(q))
            self.assertEqual(app.load_cache(q, ['A'], 'Google'), [])

    def test_worker_reaches_scraper_without_tk_or_generated_datasets(self):
        fake = SimpleNamespace(ui_queue=queue.Queue())
        hit = app.OSINTHit('A', 'Candidate', '', 'https://example.org', {})
        with patch.object(app, 'load_cache', return_value=[]), \
             patch.object(app, '_run_site_with_timeout', return_value=[hit]) as run, \
             patch.object(app, 'save_cache'), patch.object(app, 'save_reports', return_value=('a','b','c')):
            app.App._background_run(fake, ['A'], False, app.OSINTQuery(username='example'), 2, 3, 'Google')
        run.assert_called_once()
        events = list(fake.ui_queue.queue)
        self.assertIn(('hit', hit), events)
        self.assertIn(('done', 1), events)

    def test_blocked_lookup_keeps_direct_path(self):
        response = SimpleNamespace(status_code=403, text='captcha')
        with patch.object(scrapers, '_fetch', return_value=response):
            hits = scrapers.scrape_whocallsme(Mock(), scrapers.OSINTQuery(phone='202-555-0100'))
        self.assertEqual(hits[0].raw['kind'], 'manual')
        self.assertIn('2025550100', hits[0].url)
        self.assertNotIn('google', hits[0].url)

    def test_challenge_with_success_status_is_manual(self):
        response = SimpleNamespace(status_code=200, text='captcha example')
        with patch.object(scrapers, '_fetch', return_value=response):
            hits = scrapers.probe_site_for_terms(Mock(), 'A', scrapers.OSINTQuery(username='example'), ['https://example.org'])
        self.assertEqual(hits[0].raw['kind'], 'manual')

    def test_username_generic_success_is_not_found_profile(self):
        response = SimpleNamespace(status_code=200, text='<title>Welcome</title>')
        with patch.object(scrapers, '_head_or_get', return_value=response):
            hits = scrapers.scrape_username_pack(Mock(), scrapers.OSINTQuery(username='example'))
        self.assertFalse(any(h.raw.get('exists') is True for h in hits))
        self.assertTrue(all(h.raw.get('kind') == 'manual' for h in hits[1:]))

    def test_network_failure_does_not_mean_missing(self):
        self.assertIsNone(scrapers._mk_negative('A', 'https://example.org', 'blocked', 403).raw['exists'])
        self.assertIs(scrapers._mk_negative('A', 'https://example.org', 'missing', 404).raw['exists'], False)

    def test_official_path_does_not_make_network_request(self):
        with patch.object(scrapers, 'get_session') as session:
            hits = app._run_site_with_timeout('PACER (federal index)', app.OSINTQuery(first='Example'), 3)
        session.assert_not_called()
        self.assertEqual(hits[0].raw['kind'], 'manual')
        self.assertIn('/find-case', hits[0].url)

if __name__ == '__main__':
    unittest.main()
