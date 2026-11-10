"""Bounded, in-memory search jobs shared by the web API and its tests."""
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone

from bounded_runner import run_bounded
from evidence_matching import annotate_hit
from lookup_paths import input_hint, manual_path
from models import OSINTQuery, OSINTHit
from query_inputs import ENGINES, normalize_domain
from research_plan import plan_lookups, coverage_plan, coverage, balanced_findings
from source_catalog import CATS, SITE_DOMAIN, SITE_URL, ENGINE_SOURCES
from web_catalog import SOURCE_NAMES, CATALOG

VERSION = 'web-0.4.1'
SEARCHES_PER_WINDOW = 5
SEARCH_WINDOW_SECONDS = 600
FINISHED = {'complete', 'cancelled', 'timed_out', 'failed'}


def ordered_tasks(tasks):
    """Give every input an early turn before another input gets extra sources."""
    portals=[t for t in tasks if CATALOG[t.site]['mode']=='portal']
    buckets=defaultdict(deque)
    for task in sorted((t for t in tasks if CATALOG[t.site]['mode']!='portal'),
                       key=lambda t:(CATALOG[t.site]['mode']=='page_check',t.site in ENGINE_SOURCES and t.site!='Public Web Search',t.task_id.endswith('_location'))):
        buckets[task.fields[0]].append(task)
    ordered=list(portals)
    while any(buckets.values()):
        for bucket in buckets.values():
            if bucket:ordered.append(bucket.popleft())
    # All primary identifier searches precede location refinement and obituary extras.
    engine=[t for t in ordered if t.site in ENGINE_SOURCES]
    engine.sort(key=lambda t:(t.site!='Public Web Search',t.task_id.endswith('_location')))
    pending=iter(engine)
    return [next(pending) if t.site in ENGINE_SOURCES else t for t in ordered]


def run_budget(tasks, lookup_budget, ceiling):
    """Bound the entire run without cutting off selected tasks in a long queue."""
    web=sum(t.site in ENGINE_SOURCES for t in tasks)
    normal=sum(CATALOG[t.site]['mode']!='portal' and t.site not in ENGINE_SOURCES for t in tasks)
    # Include worker startup/cleanup and the serialized directory crawl delay.
    estimate=max(web, (normal+1)//2)*(lookup_budget+3)+30
    return min(ceiling,max(60,estimate))


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def validate_request(payload):
    if not isinstance(payload, dict) or set(payload) - {'inputs','sources','engine','fallback','budget'}:
        raise ValueError('Unrecognized search settings.')
    values = payload.get('inputs', {})
    keys = {f.name for f in fields(OSINTQuery)}
    if not isinstance(values, dict) or set(values) - keys:
        raise ValueError('Unrecognized input fields.')
    if any(not isinstance(v, str) or len(v) > 254 or any(ord(c)<32 for c in v) for v in values.values()):
        raise ValueError('Input fields must be text, at most 254 characters each.')
    q = OSINTQuery(**{k:v.strip() for k,v in values.items()})
    if not any(asdict(q).values()):
        raise ValueError('Enter at least one search detail.')
    if q.domain:
        q.domain = normalize_domain(q.domain)
    if q.email and ('@' not in q.email or ' ' in q.email):
        raise ValueError('Enter a complete email address.')
    if q.phone and not 7 <= sum(c.isdigit() for c in q.phone) <= 15:
        raise ValueError('Enter a phone number with 7 to 15 digits, including country code if needed.')
    sources = payload.get('sources')
    if not isinstance(sources, list) or not sources or len(sources)>len(SOURCE_NAMES) or any(not isinstance(s,str) or s not in SOURCE_NAMES for s in sources):
        raise ValueError('Select at least one available collector.')
    engine = payload.get('engine', 'Bing')
    budget = payload.get('budget', 20)
    fallback = payload.get('fallback', True)
    if not isinstance(engine,str) or engine not in ENGINES:
        raise ValueError('Select an available search engine.')
    if type(budget) is not int or budget not in (10,20,30):
        raise ValueError('Choose a 10, 20 or 30 second lookup budget.')
    if type(fallback) is not bool:
        raise ValueError('Fallback must be on or off.')
    q.search_engine, q.search_fallback = engine, fallback
    return q, list(dict.fromkeys(sources)), {'engine':engine, 'fallback':fallback, 'lookup_budget_seconds':budget,
                                            'workers':3, 'cache':'off', 'version':VERSION}


def diagnostic(task, kind, text):
    return OSINTHit(task.site, task.site, text, '', {'kind':kind})


def collect(task, budget, cancel):
    if cancel.is_set():
        return [diagnostic(task, 'cancelled', 'Lookup cancelled before collection.')]
    if CATALOG[task.site]['mode']=='portal':
        return [manual_path(task.site,task.query,SITE_DOMAIN,SITE_URL,CATS)]
    missing = input_hint(task.site, task.query, CATS)
    if missing:
        return [diagnostic(task, 'needs_input', missing)]
    task.query.web_mode = True  # installed inside the isolated child before collector imports
    result = run_bounded(task.site, task.query, budget, cancel)
    hits = result.hits
    if result.status != 'complete':
        hits.append(diagnostic(task, result.status, 'Lookup '+result.status+'. Any returned partial results are retained.'))
    elif not hits:
        hits.append(diagnostic(task, 'not_found', 'The source returned no matching public records.'))
    return hits


def clean_hit(hit):
    """Keep result payloads bounded and never return server file paths or page bodies."""
    allowed = {'kind','source','source_url','endpoint','checked_at','content_sha256','bytes',
               'fields','profile','input_fields','context_fields','matched_inputs','identity_verified',
               'engine','requested_engine','fallback_from','http_status','relationship',
               'entity_type','entity_value','subject_url','task_id','coverage_plan'}
    def bounded(value, depth=0):
        if depth>4: return str(value)[:200]
        if isinstance(value,dict):return {str(k)[:100]:bounded(v,depth+1) for k,v in list(value.items())[:40]}
        if isinstance(value,(list,tuple)):return [bounded(v,depth+1) for v in value[:40]]
        if isinstance(value,str):return value[:4000]
        if value is None or isinstance(value,(bool,int,float)):return value
        return str(value)[:4000]
    raw = bounded({k:v for k,v in hit.raw.items() if k in allowed})
    if len(json.dumps(raw))>24000:
        for key in ('fields','profile'):
            if key in raw:raw[key]={'note':'Large structured details omitted. Review the original source.'}
    return OSINTHit(str(hit.site)[:100], str(hit.title)[:600], str(hit.snippet)[:4000], str(hit.url)[:4000],raw)


@dataclass
class Job:
    id: str
    owner: str
    query: OSINTQuery
    sources: list
    settings: dict
    tasks: list
    plan: dict
    created_at: str = field(default_factory=utc_now)
    finished_at: str = ''
    expires: float = 0
    state: str = 'running'
    completed: int = 0
    hits: list = field(default_factory=list)
    cancel: threading.Event = field(default_factory=threading.Event)
    lock: threading.RLock = field(default_factory=threading.RLock)
    truncated: bool = False
    task_states: dict = field(default_factory=dict)

    def snapshot(self):
        with self.lock:
            hits = list(self.hits)
            return {'id':self.id, 'state':self.state, 'created_at':self.created_at, 'finished_at':self.finished_at,
                    'settings':dict(self.settings), 'sources':list(self.sources), 'inputs':asdict(self.query),
                    'progress':{'completed':self.completed, 'total':len(self.tasks)},
                    'coverage':coverage(hits,self.plan,self.state in FINISHED), 'truncated':self.truncated,
                    'tasks':[{'id':t.task_id,'source':t.site,'fields':list(t.fields),'mode':CATALOG[t.site]['mode'],
                              'state':self.task_states.get(t.task_id,'queued')} for t in self.tasks],
                    'hits':[asdict(h) for h in balanced_findings(hits)]}


class CapacityError(RuntimeError): pass


class JobStore:
    def __init__(self, collector=collect, ttl=1800, max_active=2, max_jobs=32, max_seconds=900):
        self.collector, self.ttl = collector, ttl
        self.max_active, self.max_jobs, self.max_seconds = max_active, max_jobs, max_seconds
        self.jobs = {}
        self.active = 0
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=max_active, thread_name_prefix='search')
        self.limits = {}
        self.secret = secrets.token_bytes(32)
        self.closed = False
        self.directory_lock = threading.Lock()
        self.directory_next = 0

    def prune(self):
        now = time.monotonic()
        with self.lock:
            for key, job in list(self.jobs.items()):
                if job.expires and job.expires<=now:
                    del self.jobs[key]
            self.limits = {k:[t for t in v if now-t<SEARCH_WINDOW_SECONDS] for k,v in self.limits.items() if v and now-v[-1]<SEARCH_WINDOW_SECONDS}

    def create(self, owner, peer, payload):
        q, sources, settings = validate_request(payload)
        tasks = plan_lookups(sources, q, CATS)
        settings['run_budget_seconds'] = run_budget(tasks,settings['lookup_budget_seconds'],self.max_seconds)
        key = hmac.new(self.secret, peer.encode(), hashlib.sha256).hexdigest()
        with self.lock:
            self.prune()
            if self.closed or self.active >= self.max_active or len(self.jobs)>=self.max_jobs:
                raise CapacityError('All search slots are busy. Please try again shortly.')
            if any(j.owner==owner and j.state not in FINISHED for j in self.jobs.values()):
                raise CapacityError('A search is already running in this session.')
            attempts = self.limits.get(key, [])
            if len(attempts)>=SEARCHES_PER_WINDOW or (key not in self.limits and len(self.limits)>=4096):
                raise CapacityError('The free limit is five searches per ten minutes. Please try later.')
            for previous in list(self.jobs.values()):
                if previous.owner==owner and previous.state in FINISHED:
                    del self.jobs[previous.id]
            job = Job(secrets.token_urlsafe(24), owner, q, sources, settings, tasks, coverage_plan(q,tasks))
            self.jobs[job.id] = job
            self.limits[key] = attempts+[time.monotonic()]
            self.active += 1
            self.pool.submit(self._run, job)
            return job

    def get(self, job_id, owner):
        with self.lock:
            self.prune()
            job = self.jobs.get(job_id)
            return job if job and secrets.compare_digest(job.owner,owner) else None

    def forget(self, job_id, owner):
        with self.lock:
            job = self.get(job_id,owner)
            if job:
                job.cancel.set()
                del self.jobs[job_id]
            return bool(job)

    def _run(self, job):
        expired = threading.Event()
        def deadline():
            expired.set()
            job.cancel.set()
        timer = threading.Timer(job.settings['run_budget_seconds'], deadline)
        timer.daemon = True
        timer.start()
        paused = set()
        def one(task):
            if task.site in ENGINE_SOURCES: task.query.search_skip_engines=tuple(paused)
            with job.lock:job.task_states[task.task_id]='running'
            if job.cancel.is_set(): return [diagnostic(task,'cancelled','Lookup cancelled before collection.')]
            try:
                if task.site=='US Assessor & Tax Directory':
                    # NETR requests are serialized across all jobs, with its published
                    # ten-second crawl delay after each completed directory collector.
                    with self.directory_lock:
                        if job.cancel.wait(max(0,self.directory_next-time.monotonic())):
                            return [diagnostic(task,'cancelled','Directory lookup cancelled.')]
                        hits=self.collector(task,job.settings['lookup_budget_seconds'],job.cancel)
                        self.directory_next=time.monotonic()+10.1
                else: hits=self.collector(task,job.settings['lookup_budget_seconds'],job.cancel)
            except Exception: hits=[diagnostic(task,'error','The collector could not complete this lookup.')]
            if task.site in ENGINE_SOURCES:
                paused.update(h.raw['engine'] for h in hits if h.raw.get('engine') and h.raw.get('http_status') in (202,403,429))
            return hits
        try:
            # One web search at a time per run; other sources have two worker slots.
            with ThreadPoolExecutor(max_workers=2) as normal, ThreadPoolExecutor(max_workers=1) as web:
                # Resolve zero-network portals immediately, then run actual data
                # collectors before less reliable legacy page checks.
                ordered=ordered_tasks(job.tasks)
                futures = {(web if task.site in ENGINE_SOURCES else normal).submit(one,task):task for task in ordered}
                for future in as_completed(futures):
                    task = futures[future]
                    hits = future.result()
                    with job.lock:
                        kinds={h.raw.get('kind') for h in hits}
                        job.task_states[task.task_id]=next((k for k in ('cancelled','timeout','error') if k in kinds),'complete')
                        for hit in hits:
                            hit.raw.setdefault('source', task.site)
                            hit.raw.setdefault('checked_at', utc_now())
                            hit.raw.setdefault('input_fields', list(task.fields))
                            hit.raw['task_id'] = task.task_id
                            hit.raw['coverage_plan'] = job.plan
                            annotate_hit(hit,job.query)
                            if len(job.hits)<500:job.hits.append(clean_hit(hit))
                            else:job.truncated=True
                        job.completed += 1
            with job.lock:
                job.state = 'timed_out' if expired.is_set() else 'cancelled' if job.cancel.is_set() else 'complete'
        except Exception:
            with job.lock: job.state='failed'
        finally:
            timer.cancel()
            with job.lock:
                job.finished_at = utc_now()
                job.expires = time.monotonic()+self.ttl
            with self.lock: self.active -= 1

    def close(self):
        with self.lock:
            self.closed = True
            for job in self.jobs.values(): job.cancel.set()
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.jobs.clear()
        self.limits.clear()
