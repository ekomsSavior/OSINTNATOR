"""Read a website, extract published identifiers, and check linked public profiles."""
import json
import re
from types import SimpleNamespace
from urllib.parse import urlsplit,urljoin,unquote
from urllib.robotparser import RobotFileParser
from bs4 import BeautifulSoup
from scrapers import OSINTHit,StreamingHits,register
from api_sources import github_profile,result
from query_inputs import normalize_domain,github_handle
from web_fetch import fetch_page,FetchError,AGENT

SITE='Website & Linked Profiles'
SOCIAL_HOSTS={'github.com','gitlab.com','linkedin.com','youtube.com','youtu.be','x.com','twitter.com','facebook.com','instagram.com','bsky.app','discord.gg','discord.com','matrix.to','keybase.io','t.me'}
SKIP_PATH=re.compile(r'/(?:login|logout|signin|signup|register|checkout|cart|admin)(?:/|$)',re.I)


def parse_page(body,metadata,domain):
    soup=BeautifulSoup(body,'html.parser')
    title=soup.title.get_text(' ',strip=True) if soup.title else domain
    visible=BeautifulSoup(body,'html.parser')
    for element in visible(['script','style','noscript','input','textarea']): element.decompose()
    text=visible.get_text(' ',strip=True)
    if re.search(r'^(?:just a moment|attention required|access denied)|verify you are human|checking your browser|unusual traffic',title+' '+text[:1500],re.I):
        raise FetchError('The site returned an access challenge')
    description=soup.find('meta',attrs={'name':re.compile('^description$',re.I)}) or soup.find('meta',attrs={'property':'og:description'})
    description=description.get('content','') if description else ''
    heading=soup.find('h1')
    fields={'title':title,'description':description,'heading':heading.get_text(' ',strip=True) if heading else ''}
    url=metadata['source_url']
    common={**metadata,'identity_verified':False,'subject_url':url}
    hits=[OSINTHit(SITE,title,' | '.join(f'{k}: {v}' for k,v in fields.items() if v),url,
                   {**common,'kind':'record','fields':fields,'entity_type':'url','entity_value':url,'relationship':'page_metadata'})]
    links=[];seen=set();follow=[]
    for anchor in soup.select('a[href]'):
        href=anchor['href'].strip()
        label=anchor.get_text(' ',strip=True)[:160]
        if href.lower().startswith('mailto:'):
            email=unquote(href[7:].split('?')[0]).strip()
            if re.fullmatch(r'[^\s@,;]+@[^\s@,;]+\.[^\s@,;]+',email) and email not in seen:
                seen.add(email)
                hits.append(OSINTHit(SITE,'Published contact: '+email,'Email address explicitly published as a contact link on '+url,url,
                            {**common,'kind':'record','entity_type':'email','entity_value':email,'relationship':'publishes_contact'}))
            continue
        target=urljoin(url,href)
        parsed=urlsplit(target)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or SKIP_PATH.search(parsed.path): continue
        host=parsed.hostname.lower().removeprefix('www.')
        root=domain.removeprefix('www.')
        same_host=host==urlsplit(url).hostname.removeprefix('www.')
        if same_host:
            if not parsed.query and not parsed.fragment and re.search(r'about|contact|community|team',parsed.path+' '+label,re.I):
                follow.append(target)
        elif target not in seen:
            seen.add(target)
            links.append((target,label,host in SOCIAL_HOSTS or host.endswith('.'+root)))
    # JSON-LD sameAs is a published association, not a verified shared identity.
    for script in soup.find_all('script',attrs={'type':'application/ld+json'}):
        try: data=json.loads(script.string or '')
        except (ValueError,TypeError): continue
        objects=data if isinstance(data,list) else [data]
        for obj in objects:
            if not isinstance(obj,dict): continue
            values=obj.get('sameAs',[])
            for target in ([values] if isinstance(values,str) else values if isinstance(values,list) else []):
                if isinstance(target,str) and target.startswith(('https://','http://')) and target not in seen:
                    seen.add(target);links.append((target,'Structured sameAs link',True))
    links.sort(key=lambda item:not item[2])
    for target,label,priority in links[:40]:
        hits.append(OSINTHit(SITE,label or urlsplit(target).hostname,
                    'Published link on '+url+'. Link text: '+(label or '(none)')+'. Destination ownership has not been inferred.',target,
                    {**common,'kind':'record','entity_type':'url','entity_value':target,'relationship':'links_to','linked_url':target}))
    # A contact page should precede generic community/about navigation.
    follow.sort(key=lambda link:('contact' not in urlsplit(link).path.lower(),len(urlsplit(link).path)))
    return hits,list(dict.fromkeys(follow))[:3]


@register(SITE)
def website_collection(session,q):
    try: domain=normalize_domain(q.domain)
    except ValueError as exc: return result(SITE,'Website needed',str(exc),'','needs_input')
    url='https://'+domain+'/'
    hits=StreamingHits(session)
    try:
        robots,robot_meta=fetch_page(session,url+'robots.txt',save=False,limit=100_000)
        policy=RobotFileParser();policy.parse(robots.splitlines())
        if not policy.can_fetch(AGENT,url):
            return result(SITE,'Collection disallowed by robots.txt','The site disallows automated collection for this path.',url,'blocked')
    except FetchError as exc:
        if 'HTTP 404 ' not in str(exc):
            return result(SITE,'Could not establish crawl access',str(exc),url,'blocked')
        policy=None
    pending=[url];seen_pages=set();seen_rows=set();profiles=[]
    for page in pending:
        if len(seen_pages)>=4: break
        if page in seen_pages: continue
        seen_pages.add(page)
        if policy and not policy.can_fetch(AGENT,page): continue
        try:
            body,metadata=fetch_page(session,page)
            rows,more=parse_page(body,metadata,domain)
            from contact_sources import extract_contacts
            rows.extend(extract_contacts(body,metadata,q,site=SITE))
            if page==url:
                pending.extend(link for link in more if link not in pending)
            for hit in rows:
                key=(hit.raw['entity_type'],hit.raw['entity_value'],hit.raw['relationship'],hit.raw.get('evidence_text',''))
                if key in seen_rows: continue
                seen_rows.add(key);hits.append(hit)
                target=hit.raw.get('linked_url','')
                parsed=urlsplit(target)
                if parsed.hostname=='github.com' and len([p for p in parsed.path.split('/') if p])==1:
                    try: handle,_=github_handle(target)
                    except ValueError: continue
                    if handle not in profiles: profiles.append(handle)
        except (FetchError,ValueError) as exc:
            hits.append(OSINTHit(SITE,'Page could not be collected',str(exc),page,{'kind':'error','source_url':page}))
    for handle in profiles[:2]:
        for hit in github_profile(session,SimpleNamespace(username=handle)):
            hit.raw['discovered_from']=url
            hits.append(hit)
    return hits
