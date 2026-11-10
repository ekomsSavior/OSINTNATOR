"""Name-based obituary discovery, with candidates kept separate from identity claims."""
import re
import json
from urllib.parse import quote, quote_plus, urljoin, urlsplit

from bs4 import BeautifulSoup
from api_sources import result
from scrapers import register, StreamingHits
from query_inputs import ENGINES
from web_fetch import fetch_page, FetchError
from web_search import parse_results
from contact_sources import public_page


def full_name_matches(text, q):
    words = re.findall(r'\w+', text.casefold())
    first = re.findall(r'\w+', q.first.casefold())
    last = re.findall(r'\w+', q.last.casefold())
    return bool(first and last) and all(w in words for w in first+last)


def obituary_links(body, metadata, q):
    soup = BeautifulSoup(body, 'html.parser')
    hits, seen = [], set()
    for anchor in soup.select('a[href]'):
        url = urljoin(metadata['source_url'], anchor['href'])
        parsed = urlsplit(url)
        if parsed.scheme!='https' or parsed.hostname not in ('legacy.com','www.legacy.com') or parsed.username: continue
        if not re.search(r'^/(?:us/obituaries/.+/.*obituary|person/)', parsed.path): continue
        title = anchor.get_text(' ', strip=True)
        if not full_name_matches(title, q) or url in seen: continue
        seen.add(url)
        hits.extend(result('Legacy Obituaries', title[:300],
                    'An obituary index entry matches the supplied name. Compare dates, location and the publisher before linking it to a person; name matches do not establish death or identity.',
                    url, 'candidate', **metadata, fields={'index_name':title[:300]}, entity_type='url', entity_value=url,
                    relationship='name_matches_obituary_index', identity_verified=False))
        if len(hits)>=10: break
    return hits


def notice_metadata(body, metadata, q):
    """Extract limited factual metadata, never copy an entire obituary."""
    soup=BeautifulSoup(body,'html.parser')
    title=soup.title.get_text(' ',strip=True) if soup.title else ''
    if not full_name_matches(title,q) or not re.search(r'obituar|memorial|funeral|death|tribute',title+' '+metadata['source_url'],re.I): return {}
    fields={'page_title':title[:400]}
    for key,label in [('article:published_time','notice_published_at'),('article:modified_time','notice_updated_at'),('og:site_name','publisher')]:
        tag=soup.find('meta',attrs={'property':key})
        if tag and tag.get('content'):fields[label]=tag['content'][:200]
    def objects(value, depth=0):
        if depth>5:return
        if isinstance(value,list):
            for item in value[:30]:yield from objects(item,depth+1)
        elif isinstance(value,dict):
            yield value
            for key in ('@graph','mainEntity','about'):
                if key in value:yield from objects(value[key],depth+1)
    for script in soup.select('script[type="application/ld+json"]')[:8]:
        try:data=json.loads(script.string or script.get_text())
        except (ValueError,RecursionError):continue
        for item in objects(data):
            if item.get('datePublished'):fields['notice_published_at']=str(item['datePublished'])[:200]
            publisher=item.get('publisher')
            if isinstance(publisher,dict) and publisher.get('name'):fields['publisher']=str(publisher['name'])[:200]
            if full_name_matches(str(item.get('name','')),q):
                for key in ('birthDate','deathDate'):
                    if item.get(key):fields['publisher_stated_'+key]=str(item[key])[:100]
    return fields


@register('Legacy Obituaries')
def legacy_obituaries(session, q):
    site = 'Legacy Obituaries'
    if not q.first.strip() or not q.last.strip():
        return result(site, 'First and last name needed', 'Enter both names to avoid surname-only obituary matches.', 'https://www.legacy.com/obituaries/', 'needs_input')
    slug = lambda value: quote(re.sub(r'\s+', '-', value.strip().lower()), safe='')
    url = 'https://www.legacy.com/obituaries/name/'+slug(q.last)+'/'+slug(q.first)
    hits = StreamingHits(session)
    try:
        body, metadata = fetch_page(session, url)
        rows = obituary_links(body, metadata, q)
        hits.extend(rows or result(site, 'No extractable matching obituary entries', 'The index returned no supported matching entries. This is not evidence that a person is living or deceased.', url, 'not_found', **metadata))
    except FetchError as exc:
        hits.extend(result(site, 'Legacy automatic lookup unavailable', str(exc), url, 'unavailable'))
    hits.extend(result(site, 'Review Legacy name results', 'Open the matching-name index and refine by location or date. Access challenges are not bypassed.', url, 'manual'))
    return hits


def obituary_search(session, q, site, domain=''):
    if not q.first.strip() or not q.last.strip():
        return result(site, 'First and last name needed', 'Enter both names for obituary discovery.', '', 'needs_input')
    requested = getattr(q, 'search_engine', 'Bing')
    if requested not in ENGINES: requested='Bing'
    expression = '"'+q.full_name.replace('"',' ')+'" obituary'
    if q.city: expression+=' "'+q.city.replace('"',' ')+'"'
    if q.state: expression+=' "'+q.state.replace('"',' ')+'"'
    if domain: expression+=' site:'+domain
    engines = [requested]
    if getattr(q, 'search_fallback', True): engines += [e for e in ('Bing','Yahoo','DuckDuckGo') if e!=requested][:2]
    hits = StreamingHits(session)
    for engine in engines:
        url = ('https://html.duckduckgo.com/html/?q=' if engine=='DuckDuckGo' else ENGINES[engine])+quote_plus(expression)
        if engine in getattr(q,'search_skip_engines',()):
            hits.extend(result(site,engine+': paused for this run','An earlier search was challenged or rate limited.',url,'blocked',engine=engine))
            continue
        try:
            body, metadata = fetch_page(session, url)
            rows = parse_results(body, metadata, q.full_name, engine, field='name')
            rows = [row for row in rows if (not domain or (urlsplit(row.url).hostname or '').removeprefix('www.')==domain)
                    and re.search(r'obituar|memorial|funeral|death.notice|tribute', row.title+' '+row.snippet+' '+row.url, re.I)]
            for row in rows:
                row.site = site
                row.raw.update(requested_engine=requested, input_fields=['name'], relationship='search_mentions_obituary', identity_verified=False)
                if engine!=requested: row.raw['fallback_from']=requested
                # The result is a candidate even if the publisher is authoritative.
                row.snippet += ' Name match only; verify dates, location and identity in the original notice.'
                hits.append(row)
            if rows:
                for row in rows[:2]:
                    try:
                        page,proof=public_page(session,row.url)
                        details=notice_metadata(page,proof,q)
                        if details:
                            row.raw.update(proof,fields=details)
                            row.snippet=' | '.join(f'{key}: {value}' for key,value in details.items())+'. Name match only; publication date is not the date of death. Verify identity in the source.'
                    except FetchError as exc:
                        hits.extend(result(site,'Original obituary page unavailable',str(exc),row.url,'unavailable',engine=engine))
                return hits
            hits.extend(result(site, engine+': no matching obituary results extracted', 'No supported result blocks matched the name and obituary topic. This does not establish whether a person is living or deceased.', url, 'unavailable', **metadata, engine=engine, requested_engine=requested))
        except (FetchError,ValueError) as exc:
            code=re.match(r'HTTP (\d+)',str(exc))
            hits.extend(result(site, engine+': obituary search unavailable', str(exc), url, 'unavailable', engine=engine, requested_engine=requested,http_status=int(code.group(1)) if code else None))
    return hits


@register('Obituary Web Search')
def all_obituaries(session, q): return obituary_search(session,q,'Obituary Web Search')


@register('Dignity Memorial Obituaries')
def dignity_obituaries(session, q): return obituary_search(session,q,'Dignity Memorial Obituaries','dignitymemorial.com')


@register('Tribute Archive Obituaries')
def tribute_obituaries(session, q): return obituary_search(session,q,'Tribute Archive Obituaries','tributearchive.com')
