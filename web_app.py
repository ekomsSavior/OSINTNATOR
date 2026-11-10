"""Same-origin web UI and ephemeral search API. Run as one Uvicorn worker."""
import asyncio
import io
import json
import os
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.middleware.trustedhost import TrustedHostMiddleware

from graph_export import export_graphml
from models import OSINTHit
from query_inputs import ENGINES
from report_html import render_html
from web_catalog import public_catalog
from jurisdiction_catalog import directory
from web_service import JobStore, CapacityError, VERSION, SEARCHES_PER_WINDOW, SEARCH_WINDOW_SECONDS

WEB = Path(__file__).resolve().parent/'web'
COOKIE = 'osintnator_session'


def create_app(store=None, origin=None):
    origin = (origin or os.environ.get('OSINTNATOR_ORIGIN','http://127.0.0.1:8766')).rstrip('/')
    parsed = urlsplit(origin)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.path or parsed.username:
        raise ValueError('OSINTNATOR_ORIGIN must be the public origin, without a path.')
    store = store or JobStore()
    cookie_name = '__Host-osintnator_session' if parsed.scheme=='https' else COOKIE

    @asynccontextmanager
    async def lifespan(app):
        async def reap():
            while True:
                await asyncio.sleep(30)
                store.prune()
        reaper = asyncio.create_task(reap())
        yield
        reaper.cancel()
        try: await reaper
        except asyncio.CancelledError: pass
        await asyncio.to_thread(store.close)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.jobs = store

    @app.middleware('http')
    async def privacy(request, call_next):
        owner = request.cookies.get(cookie_name,'')
        new_cookie = not bool(re.fullmatch(r'[A-Za-z0-9_-]{43}',owner))
        if new_cookie: owner=secrets.token_urlsafe(32)
        request.state.owner = owner
        if request.method in ('POST','DELETE') and (request.headers.get('origin')!=origin or request.headers.get('x-osintnator')!='1'):
            response = JSONResponse({'detail':'This action must come from the OSINTNATOR page.'},403)
        else:
            response = await call_next(request)
        response.headers.update({'Cache-Control':'no-store', 'Pragma':'no-cache',
            'X-Content-Type-Options':'nosniff', 'Referrer-Policy':'no-referrer',
            'X-Frame-Options':'DENY', 'X-Robots-Tag':'noindex, nofollow',
            'Permissions-Policy':'camera=(), microphone=(), geolocation=()',
            'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"})
        if new_cookie:
            response.set_cookie(cookie_name,owner,httponly=True,secure=parsed.scheme=='https',samesite='strict',path='/')
        return response

    app.add_middleware(TrustedHostMiddleware,allowed_hosts=[parsed.hostname])

    def owned(request, job_id):
        return store.get(job_id,request.state.owner)

    def missing():
        return JSONResponse({'detail':'This search is unavailable or has expired.'},404)

    @app.get('/')
    def index(): return FileResponse(WEB/'index.html')

    @app.get('/app.js')
    def script(): return FileResponse(WEB/'app.js',media_type='text/javascript')

    @app.get('/style.css')
    def styles(): return FileResponse(WEB/'style.css',media_type='text/css')

    @app.get('/healthz')
    def health(): return {'status':'ok'}

    @app.get('/api/config')
    def config():
        return {'sources':public_catalog(), 'engines':list(ENGINES), 'retention_minutes':store.ttl//60,
                'max_run_seconds':store.max_seconds, 'version':VERSION,
                'search_limit':{'searches':SEARCHES_PER_WINDOW,'window_seconds':SEARCH_WINDOW_SECONDS}}

    @app.get('/api/property-directory')
    def property_index():
        return directory()

    @app.post('/api/jobs')
    async def start(request: Request):
        if request.headers.get('content-type','').split(';')[0]!='application/json':
            return JSONResponse({'detail':'Send a JSON search request.'},415)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>8192:return JSONResponse({'detail':'Search request is too large.'},413)
        try:
            payload = json.loads(body)
            job = store.create(request.state.owner,request.client.host if request.client else 'unknown',payload)
        except (json.JSONDecodeError,UnicodeDecodeError,RecursionError):
            return JSONResponse({'detail':'Invalid JSON request.'},422)
        except ValueError as exc:
            return JSONResponse({'detail':str(exc)},422)
        except CapacityError as exc:
            return JSONResponse({'detail':str(exc)},429,headers={'Retry-After':'60'})
        return JSONResponse(job.snapshot(),202)

    @app.get('/api/jobs/{job_id}')
    def status(job_id: str, request: Request):
        job = owned(request,job_id)
        return job.snapshot() if job else missing()

    @app.post('/api/jobs/{job_id}/cancel')
    def cancel(job_id: str, request: Request):
        job = owned(request,job_id)
        if not job:return missing()
        job.cancel.set()
        return {'state':'cancelling'}

    @app.delete('/api/jobs/{job_id}')
    def forget(job_id: str, request: Request):
        return Response(status_code=204) if store.forget(job_id,request.state.owner) else missing()

    @app.get('/api/jobs/{job_id}/report/{format}')
    def download(job_id: str, format: str, request: Request):
        job = owned(request,job_id)
        if not job:return missing()
        if format not in ('json','html','graphml'):return missing()
        snapshot = job.snapshot()
        meta = {k:v for k,v in snapshot.items() if k not in ('hits','id')}
        hits = [OSINTHit(**h) for h in snapshot['hits']]
        if format=='json':
            content=json.dumps(snapshot,ensure_ascii=False,indent=2)
            mime='application/json'
        elif format=='html':
            content=render_html(hits,run_metadata=meta)
            mime='text/html'
        else:
            buffer=io.BytesIO()
            export_graphml(hits,buffer,run_metadata=meta)
            content=buffer.getvalue()
            mime='application/graphml+xml'
        return Response(content,media_type=mime,headers={'Content-Disposition':f'attachment; filename="osintnator-report.{format}"'})

    return app
