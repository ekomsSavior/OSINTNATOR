"""Web behavior and isolation; deterministic collectors, no external requests."""
import io
import json
import threading
import subprocess
import sys
import time
import unittest
import xml.etree.ElementTree as ET
from dataclasses import asdict
from unittest.mock import patch

from models import OSINTQuery, OSINTHit
from bounded_runner import run_bounded
from graph_export import canonical_url, export_graphml
from research_plan import plan_lookups
from source_catalog import CATS
from web_guard import validate_destination
from web_catalog import SOURCE_NAMES
from web_service import JobStore, CapacityError, validate_request, clean_hit, FINISHED

try:
    from fastapi.testclient import TestClient
    from web_app import create_app
    HAVE_WEB = True
except ImportError:
    HAVE_WEB = False


def fixture(task,budget,cancel):
    return [OSINTHit(task.site,'Public fixture','A test-only returned record.','https://example.org/',
                    {'kind':'record','fields':{'fixture':True},'evidence_file':'/private/server/path','html':'hidden'})]


def wait(job):
    deadline=time.monotonic()+3
    while job.state not in FINISHED and time.monotonic()<deadline:time.sleep(.005)
    if job.state not in FINISHED:raise AssertionError('Fixture job did not finish')
    return job.snapshot()


def restricted_worker(connection, site, query):
    from web_guard import restrict_worker
    import socket
    restrict_worker()
    try:
        with socket.socket() as sock:sock.connect(('127.0.0.1',80))
    except OSError:
        connection.send(('done',['blocked']))
    else:connection.send(('done',['incorrectly allowed']))
    connection.close()


class ValidationTests(unittest.TestCase):
    def test_rejects_empty_unknown_source_and_unknown_keys(self):
        base={'inputs':{'username':'example'},'sources':['GitHub Profile API']}
        for payload in ({},dict(base,inputs={}),dict(base,sources=['Unconfigured provider']),dict(base,unknown=True),dict(base,inputs={'password':'secret'}),dict(base,budget=True),dict(base,fallback='false'),dict(base,engine=[])):
            with self.subTest(payload=payload),self.assertRaises(ValueError):validate_request(payload)

    def test_validates_identifiers_without_echo(self):
        for values in ({'domain':'http://127.0.0.1'},{'email':'not-email'},{'phone':'123'}, {'username':'a'*255},{'first':'\x00test'}):
            with self.subTest(values=values),self.assertRaises(ValueError):validate_request({'inputs':values,'sources':['Public Web Search']})

    def test_all_fields_get_independent_web_tasks(self):
        values={'first':'Example','last':'Researcher','username':'example','email':'hello@example.org','phone':'8005550100','address1':'10 Main St','city':'El Paso','state':'TX','zip':'79901','domain':'https://EXAMPLE.org/path'}
        q,sources,settings=validate_request({'inputs':values,'sources':['Public Web Search','GitHub Public Discovery'],'engine':'Yandex','budget':30,'fallback':False})
        tasks=plan_lookups(sources,q,CATS)
        self.assertEqual({t.fields[0] for t in tasks if t.site=='Public Web Search'},{'name','username','email','phone','address','domain'})
        self.assertEqual(q.domain,'example.org')
        self.assertTrue(all(t.query.search_engine=='Yandex' and not t.query.search_fallback for t in tasks if t.site=='Public Web Search'))

    def test_private_special_and_rebound_destinations_blocked(self):
        for ip in ('127.0.0.1','10.0.0.1','169.254.169.254','0.0.0.0','192.168.1.1','100.64.0.1','::1','::ffff:127.0.0.1','fe80::1','224.0.0.1','2002:7f00:1::','64:ff9b::7f00:1','hostname.example'):
            with self.subTest(ip=ip),self.assertRaises(OSError):validate_destination((ip,443))
        for port in (22,8080,6379):
            with self.assertRaises(OSError):validate_destination(('1.1.1.1',port))
        validate_destination(('1.1.1.1',443))

    def test_worker_guard_blocks_at_socket_connection(self):
        outcome=run_bounded('test',OSINTQuery(),2,worker=restricted_worker)
        self.assertEqual(outcome.status,'complete')
        self.assertEqual(outcome.hits,['blocked'])

    def test_host_infrastructure_is_denied_even_with_public_ip(self):
        with patch.dict('os.environ',{'OSINTNATOR_DENY_NETWORKS':'1.1.1.1/32,2606:4700:4700::1111/128'}):
            for ip in ('1.1.1.1','2606:4700:4700::1111'):
                with self.assertRaises(OSError):validate_destination((ip,443))

    def test_clean_result_drops_internal_paths_and_bounds_payload(self):
        hit=OSINTHit('site','title','text','https://example.org',{'kind':'record','evidence_file':'/private','html':'<secret>','fields':{str(i):'a'*5000 for i in range(100)}})
        clean=asdict(clean_hit(hit))
        self.assertNotIn('/private',json.dumps(clean))
        self.assertNotIn('<secret>',json.dumps(clean))
        self.assertLess(len(json.dumps(clean)),25000)

    def test_graph_deduplicates_tracking_but_keeps_semantic_query(self):
        self.assertEqual(canonical_url('https://example.org/?id=7&msockid=x&utm_source=bing'),canonical_url('https://example.org/?id=7'))
        self.assertNotEqual(canonical_url('https://example.org/?id=7'),canonical_url('https://example.org/?id=8'))


class JobTests(unittest.TestCase):
    def setUp(self):self.store=JobStore(collector=fixture)
    def tearDown(self):self.store.close()
    def payload(self):return {'inputs':{'username':'example'},'sources':['GitHub Profile API']}

    def test_results_private_to_owner_and_include_run_settings(self):
        job=self.store.create('alice','ip1',self.payload());snap=wait(job)
        self.assertIsNone(self.store.get(job.id,'bob'))
        self.assertFalse(self.store.forget(job.id,'bob'))
        self.assertEqual(snap['coverage']['username']['findings'],1)
        self.assertEqual(snap['settings']['engine'],'Bing')
        self.assertEqual(snap['settings']['cache'],'off')
        self.assertEqual(snap['progress'],{'completed':1,'total':1})
        self.assertNotIn('evidence_file',snap['hits'][0]['raw'])

    def test_new_run_replaces_previous_session_results(self):
        first=self.store.create('alice','ip1',self.payload());wait(first)
        second=self.store.create('alice','ip1',self.payload());wait(second)
        self.assertIsNone(self.store.get(first.id,'alice'))
        self.assertIsNotNone(self.store.get(second.id,'alice'))

    def test_expired_results_are_unavailable(self):
        job=self.store.create('alice','ip1',self.payload());wait(job)
        job.expires=time.monotonic()-1;self.store.prune()
        self.assertIsNone(self.store.get(job.id,'alice'))

    def test_rate_limit_applies_across_sessions(self):
        for i in range(5):wait(self.store.create(str(i),'shared-ip',self.payload()))
        with self.assertRaises(CapacityError):self.store.create('new-owner','shared-ip',self.payload())

    def test_cancellation_preserves_completed_results_and_frees_capacity(self):
        def slow(task,budget,cancel):
            cancel.wait(1)
            return fixture(task,budget,cancel)
        self.store.collector=slow
        job=self.store.create('alice','ip1',self.payload());job.cancel.set();snap=wait(job)
        self.assertEqual(snap['state'],'cancelled')
        self.assertEqual(self.store.active,0)

    def test_forget_does_not_release_running_slot_early(self):
        entered=threading.Event();release=threading.Event()
        def held(task,budget,cancel):entered.set();release.wait(1);return fixture(task,budget,cancel)
        self.store.collector=held;self.store.max_active=1
        job=self.store.create('alice','ip1',self.payload());self.assertTrue(entered.wait(1))
        self.assertTrue(self.store.forget(job.id,'alice'))
        with self.assertRaises(CapacityError):self.store.create('bob','ip2',self.payload())
        release.set();wait(job)

    def test_total_run_deadline(self):
        self.store.max_seconds=.03
        def slow(task,budget,cancel):cancel.wait(1);return fixture(task,budget,cancel)
        self.store.collector=slow
        job=self.store.create('alice','ip1',self.payload());snap=wait(job)
        self.assertEqual(snap['state'],'timed_out')

    def test_all_fields_have_results_in_the_same_run(self):
        payload={'inputs':{'first':'Example','username':'example','email':'hello@example.org','phone':'8005550100','address1':'10 Main','city':'City','state':'TX','domain':'example.org'},'sources':['Public Web Search']}
        snap=wait(self.store.create('owner','ip',payload))
        self.assertEqual(set(snap['coverage']),{'name','username','email','phone','address','domain'})
        self.assertTrue(all(c['findings'] and c['checks']==c['planned_checks'] for c in snap['coverage'].values()))


@unittest.skipUnless(HAVE_WEB,'Install requirements-web.txt and httpx for web API tests')
class APITests(unittest.TestCase):
    def setUp(self):
        self.store=JobStore(collector=fixture)
        self.app=create_app(self.store,origin='https://osintnator.example.org')
        self.client=TestClient(self.app,base_url='https://osintnator.example.org')
        self.client.__enter__();self.client.get('/api/config')
        self.headers={'Origin':'https://osintnator.example.org','X-OSINTNATOR':'1'}
        self.payload={'inputs':{'username':'example'},'sources':['GitHub Profile API']}
    def tearDown(self):self.client.__exit__(None,None,None)
    def start(self):
        response=self.client.post('/api/jobs',json=self.payload,headers=self.headers)
        self.assertEqual(response.status_code,202,response.text)
        return response.json()['id']

    def test_cookie_and_headers(self):
        with TestClient(self.app,base_url='https://osintnator.example.org') as other:
            response=other.get('/api/config')
            self.assertIn('HttpOnly',response.headers['set-cookie'])
            self.assertIn('__Host-osintnator_session=',response.headers['set-cookie'])
            self.assertNotIn('Domain=',response.headers['set-cookie'])
            self.assertIn('Secure',response.headers['set-cookie'])
            self.assertIn('SameSite=strict',response.headers['set-cookie'])
            self.assertEqual(response.headers['cache-control'],'no-store')
            self.assertIn("frame-ancestors 'none'",response.headers['content-security-policy'])

    def test_csrf_unknown_host_and_large_body_rejected(self):
        self.assertEqual(self.client.post('/api/jobs',json=self.payload).status_code,403)
        self.assertEqual(self.client.post('/api/jobs',json=self.payload,headers={**self.headers,'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.client.get('/api/config',headers={'host':'evil.example'}).status_code,400)
        self.assertEqual(self.client.post('/api/jobs',content='x'*8193,headers={**self.headers,'content-type':'application/json'}).status_code,413)

    def test_invalid_bytes_and_unknown_sources_are_safe(self):
        response=self.client.post('/api/jobs',content=b'\xff',headers={**self.headers,'content-type':'application/json'})
        self.assertEqual(response.status_code,422)
        self.assertEqual(response.json()['detail'],'Invalid JSON request.')
        self.payload['sources']=['Unconfigured provider']
        self.assertEqual(self.client.post('/api/jobs',json=self.payload,headers=self.headers).status_code,422)

    def test_session_isolation_in_status_cancel_delete_and_exports(self):
        job_id=self.start()
        stranger=TestClient(self.app,base_url='https://osintnator.example.org')
        for suffix in ('','/report/json','/report/html','/report/graphml'):
            self.assertEqual(stranger.get('/api/jobs/'+job_id+suffix).status_code,404)
        self.assertEqual(stranger.post('/api/jobs/'+job_id+'/cancel',headers=self.headers).status_code,404)
        self.assertEqual(stranger.delete('/api/jobs/'+job_id,headers=self.headers).status_code,404)
        self.assertEqual(self.client.get('/api/jobs/'+job_id).status_code,200)

    def test_exports_include_configuration_and_escape_source_text(self):
        def unsafe_text(task,budget,cancel):return [OSINTHit(task.site,'<script>alert(1)</script>','fixture','javascript:alert(1)',{'kind':'record'})]
        self.store.collector=unsafe_text
        job_id=self.start();wait(self.store.jobs[job_id])
        html=self.client.get('/api/jobs/'+job_id+'/report/html')
        self.assertEqual(html.status_code,200)
        self.assertNotIn('<script>alert',html.text)
        self.assertNotIn('href="javascript:',html.text)
        self.assertIn('Run settings and input details',html.text)
        self.assertIn('attachment',html.headers['content-disposition'])
        report=self.client.get('/api/jobs/'+job_id+'/report/json').json()
        self.assertEqual(report['settings']['engine'],'Bing')
        graph=self.client.get('/api/jobs/'+job_id+'/report/graphml')
        self.assertEqual(graph.status_code,200)
        root=ET.fromstring(graph.content)
        self.assertIsNotNone(root.find('.//{*}data[@key="run_metadata"]'))

    def test_cancel_and_forget(self):
        job_id=self.start()
        self.assertEqual(self.client.post('/api/jobs/'+job_id+'/cancel',headers=self.headers).status_code,200)
        self.assertEqual(self.client.delete('/api/jobs/'+job_id,headers=self.headers).status_code,204)
        self.assertEqual(self.client.get('/api/jobs/'+job_id).status_code,404)

    def test_no_local_files_or_history_exposed(self):
        for path in ('/reports/','/logs/scrapers.log','/api/jobs','/.env','/../osintnator.py'):
            self.assertIn(self.client.get(path).status_code,(404,405))

    def test_full_catalog_and_public_jurisdiction_directory(self):
        config=self.client.get('/api/config').json()
        self.assertEqual(len(config['sources']),len(SOURCE_NAMES))
        self.assertEqual({s['mode'] for s in config['sources']},{'collector','page_check','portal'})
        index=self.client.get('/api/property-directory').json()
        self.assertEqual(len(index['states']),51)
        self.assertNotIn('inputs',index)
        self.assertIn('Obituary Web Search',{s['id'] for s in config['sources']})
        linkedin=next(s for s in config['sources'] if s['id']=='LinkedIn Name Search')
        self.assertEqual(linkedin['mode'],'collector')
        self.assertEqual(linkedin['fields'],['name'])

    def test_parent_import_and_portals_do_not_initialize_collectors_or_disk_logs(self):
        code="import sys,threading; import web_app; from web_service import collect; from models import OSINTQuery; from research_plan import LookupTask; collect(LookupTask('PACER (federal index)',OSINTQuery(first='Example'),('name',),'fixture'),10,threading.Event()); assert 'scrapers' not in sys.modules"
        check=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True)
        self.assertEqual(check.returncode,0,check.stderr)


if __name__=='__main__':unittest.main()
