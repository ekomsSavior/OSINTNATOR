"""Bounded public HTTP collection with evidence copies and explicit failures."""
import hashlib
import ipaddress
import json
import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urljoin
import requests

EVIDENCE_DIR=Path(__file__).resolve().parent/'reports'/'evidence'
AGENT='OSINTNATOR/3 public-source-research'
MAX_BYTES=1_500_000


class FetchError(RuntimeError): pass


def public_url(url):
    parsed=urlsplit(url)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
        raise FetchError('Unsupported public URL')
    if parsed.port not in (None,80,443): raise FetchError('Only standard public web ports are supported')
    try:
        addresses=socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme=='https' else 80), type=socket.SOCK_STREAM)
    except OSError as exc: raise FetchError('The hostname could not be resolved') from exc
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise FetchError('The URL does not resolve to a public address')
    return url


def fetch_page(session,url,save=True,limit=MAX_BYTES,accept='text/html,application/xhtml+xml,text/plain'):
    requested=url
    for _ in range(4):
        public_url(url)
        # Clear cookies between pages; no browser account or saved login is used.
        session.cookies.clear()
        last=getattr(session,'_osint_last_request',0)
        time.sleep(max(0,.4-(time.monotonic()-last)))
        session._osint_last_request=time.monotonic()
        try:
            with session.get(url,timeout=(4,8),stream=True,allow_redirects=False,
                             headers={'User-Agent':AGENT,'Accept':accept}) as response:
                if response.status_code in (301,302,303,307,308):
                    location=response.headers.get('Location')
                    if not location: raise FetchError('Redirect has no destination')
                    url=urljoin(url,location);continue
                if response.status_code!=200: raise FetchError(f'HTTP {response.status_code} from {url}')
                content_type=response.headers.get('Content-Type','').lower()
                if content_type and not any(t in content_type for t in ('text/','application/xhtml+xml','application/json')):
                    raise FetchError('The URL returned a non-text document')
                chunks=[];size=0
                for chunk in response.iter_content(65536):
                    size+=len(chunk)
                    if size>limit: raise FetchError('Page exceeds the collection size limit')
                    chunks.append(chunk)
                body=b''.join(chunks)
                encoding=response.encoding if 'charset=' in content_type else 'utf-8'
        except requests.RequestException as exc: raise FetchError(f'Network request failed: {type(exc).__name__}') from exc
        text=body.decode(encoding or 'utf-8',errors='replace')
        digest=hashlib.sha256(body).hexdigest()
        metadata={'source_url':url,'requested_url':requested,'checked_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
                  'content_sha256':digest,'bytes':len(body),'content_type':content_type}
        if save and os.environ.get('OSINTNATOR_WEB_WORKER') != '1':
            EVIDENCE_DIR.mkdir(parents=True,exist_ok=True)
            filename=datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')+'_'+digest[:12]
            path=EVIDENCE_DIR/(filename+'.html')
            path.write_bytes(body)
            metadata['evidence_file']=str(path)
            (EVIDENCE_DIR/(filename+'.json')).write_text(json.dumps(metadata,indent=2))
        return text,metadata
    raise FetchError('Too many redirects')
