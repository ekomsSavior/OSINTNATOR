import multiprocessing
import queue
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import urlparse
import osintnator as app
import api_sources
import scrapers
from bounded_runner import run_bounded, Outcome
from lookup_paths import manual_path, input_hint


def stalled_worker(pipe, site, query):
    pipe.send(('hit', scrapers.OSINTHit(site, 'Partial', '', 'https://example.org', {'kind': 'candidate'})))
    time.sleep(30)


def done_worker(pipe, site, query):
    pipe.send(('done', [scrapers.OSINTHit(site, 'Complete', '', 'https://example.org', {})]))
    pipe.close()

class ReliabilityTests(unittest.TestCase):
    def test_concurrent_worker_lifecycles_preserve_results(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(6) as pool:
            runs=list(pool.map(lambda _:run_bounded('test',None,5,worker=done_worker),range(24)))
        self.assertTrue(all(run.status=='complete' for run in runs))
        self.assertTrue(all(run.hits[0].title=='Complete' for run in runs))

    def test_hard_timeout_preserves_partial_and_reaps_worker(self):
        before = {p.pid for p in multiprocessing.active_children()}
        started = time.monotonic()
        outcome = run_bounded('test', None, 1, worker=stalled_worker)
        self.assertEqual(outcome.status, 'timeout')
        self.assertEqual(len(outcome.hits), 1)
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual({p.pid for p in multiprocessing.active_children()}, before)

    def test_cancel_terminates_active_worker(self):
        event = threading.Event()
        timer = threading.Timer(0.7, event.set)
        timer.start()
        try:
            started = time.monotonic()
            result = run_bounded('test', None, 20, event, worker=stalled_worker)
            self.assertEqual(result.status, 'cancelled')
            self.assertLess(time.monotonic() - started, 3)
        finally:
            timer.join()

    def test_successful_worker_returns_result(self):
        self.assertEqual(run_bounded('test', None, 3, worker=done_worker).hits[0].title, 'Complete')

    def test_every_catalog_entry_has_manual_path(self):
        q = app.OSINTQuery(first='Example', username='example', phone='2025550100', address1='Example Street', domain='example.org')
        for category, sites in app.CATS.items():
            for site in sites:
                with self.subTest(site=site):
                    hit = manual_path(site, q, app.SITE_DOMAIN, app.SITE_URL, app.CATS)
                    parsed = urlparse(hit.url)
                    self.assertEqual(parsed.scheme, 'https')
                    self.assertTrue(parsed.netloc)
                    self.assertGreater(len(hit.snippet), 20)

    def test_full_catalog_finishes_with_one_or_more_rows_per_source(self):
        q = app.OSINTQuery(first='Example', username='example', email='example@example.org', phone='2025550100', address1='Example Street', domain='example.org')
        sites = [s for group in app.CATS.values() for s in group]
        fake = SimpleNamespace(ui_queue=queue.Queue())
        with patch.object(app, 'run_bounded', side_effect=lambda *a: Outcome('timeout')), \
             patch.object(app, 'load_cache', return_value=[]), patch.object(app, 'save_cache'), \
             patch.object(app, 'save_reports', return_value=('a', 'b', 'c')):
            app.App._background_run(fake, sites, False, q, 4, 1, 'DuckDuckGo')
        events = list(fake.ui_queue.queue)
        rows = [v for k,v in events if k == 'hit']
        self.assertEqual({h.raw['source'] for h in rows}, set(sites))
        self.assertEqual(sum(k == 'inc_progress' for k,v in events), len(sites))

    def test_timeout_retains_every_username_path(self):
        q = app.OSINTQuery(username='example')
        with patch.object(app, 'run_bounded', return_value=Outcome('timeout')):
            hits = app._run_site_with_timeout('Username Pack (direct)', q, 1)
        self.assertTrue({h.url for h in scrapers.username_paths(q)} <= {h.url for h in hits})

    def test_missing_input_skips_network(self):
        with patch.object(app, 'run_bounded') as run:
            hit = app._run_site_with_timeout('GitHub Profile API', app.OSINTQuery(first='Example'), 1)[0]
        run.assert_not_called()
        self.assertEqual(hit.raw['kind'], 'needs_input')

    def test_all_theme_colors_are_grayscale(self):
        for palette in (app.DARK, app.LIGHT):
            for value in palette.values():
                self.assertEqual(value[1:3], value[3:5])
                self.assertEqual(value[3:5], value[5:7])

    def test_profile_check_uses_one_get_not_head_plus_get(self):
        session=Mock()
        session.get.return_value=SimpleNamespace(status_code=200,text='A normal profile')
        with patch.object(scrapers.time,'sleep'):
            scrapers._head_or_get(session,'https://example.org/profile')
        session.get.assert_called_once()
        session.head.assert_not_called()

    def test_username_pack_does_not_stop_at_eight_candidates(self):
        response = SimpleNamespace(status_code=200, text='example github twitch pinterest steam soundcloud medium dev.to keybase gitlab kaggle flickr gravatar youtube behance producthunt created profile instagram twitter facebook linkedin @example /user/example <title>github</title>')
        with patch.object(scrapers, '_head_or_get', return_value=response) as request:
            scrapers.scrape_username_pack(Mock(), scrapers.OSINTQuery(username='example'))
        self.assertEqual(request.call_count, len(scrapers.username_services('example')))

class ApiTests(unittest.TestCase):
    def session(self, data, code=200):
        session = Mock()
        session.get.return_value = Mock(status_code=code, headers={}, json=Mock(return_value=data))
        return session

    def test_github_validated_record(self):
        hit = api_sources.github_profile(self.session({'login':'example', 'id':42}), app.OSINTQuery(username='example'))[0]
        self.assertEqual(hit.raw['kind'], 'record')
        self.assertFalse(hit.raw['identity_verified'])

    def test_github_wrong_login_is_not_match(self):
        hit = api_sources.github_profile(self.session({'login':'wrong', 'id':42}), app.OSINTQuery(username='example'))[0]
        self.assertEqual(hit.raw['kind'], 'manual')

    def test_rate_limit_is_not_not_found(self):
        hit = api_sources.github_profile(self.session({}, 429), app.OSINTQuery(username='example'))[0]
        self.assertEqual(hit.raw['kind'], 'manual')
        self.assertIn('Rate limited', hit.snippet)

    def test_bluesky_did_record(self):
        hit = api_sources.bluesky_profile(self.session({'handle':'bsky.app', 'did':'did:plc:abc'}), app.OSINTQuery(username='bsky.app'))[0]
        self.assertEqual(hit.raw['did'], 'did:plc:abc')

    def test_rdap_domain_normalization_and_validation(self):
        self.assertEqual(api_sources.normalize_domain('Example.ORG.'), 'example.org')
        self.assertEqual(api_sources.normalize_domain('https://example.org/path'), 'example.org')
        for value in ('127.0.0.1', 'me@example.org', 'a/b.com', '-abc.org'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                api_sources.normalize_domain(value)

    def test_rdap_record(self):
        hit = api_sources.domain_rdap(self.session({'objectClassName':'domain','ldhName':'EXAMPLE.ORG','events':[]}), app.OSINTQuery(domain='example.org'))[0]
        self.assertEqual(hit.raw['kind'], 'record')

if __name__ == '__main__':
    unittest.main()
