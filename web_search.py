"""Collect public search-result snippets using the explicitly selected engine."""
import base64
import re
from urllib.parse import urljoin,urlsplit,parse_qs,quote_plus,unquote
from bs4 import BeautifulSoup
from scrapers import OSINTHit,StreamingHits,register
from query_inputs import ENGINES,search_inputs,normalized_street
from web_fetch import fetch_page,FetchError
from evidence_matching import matched_inputs,matches

SITE='Public Web Search'


def normalized(text):
    return re.sub(r'[\W_]+',' ',text.casefold()).strip()


def parse_results(body,metadata,term,engine,field=None,include_unmatched=False,limit=10):
    soup=BeautifulSoup(body,'html.parser')
    text=soup.get_text(' ',strip=True)
    if re.search(r'verify you are human|unusual traffic|complete the captcha|checking your browser|enable javascript to continue',text[:3000],re.I):
        raise FetchError('Search engine returned an access challenge')
    hits=[];seen=set();source=metadata['source_url']
    for anchor in soup.select('a[href]'):
        if not (anchor.find(['h2','h3']) or anchor.find_parent(['h2','h3']) or 'result__a' in anchor.get('class',[])
                or (anchor.select_one('.title') and anchor.find_parent(attrs={'data-type':'web'}))): continue
        target=urljoin(source,anchor['href'])
        parsed=urlsplit(target);params=parse_qs(parsed.query)
        if parsed.path=='/url': target=params.get('q',params.get('url',[target]))[0]
        if parsed.path=='/l/' and 'uddg' in params: target=params['uddg'][0]
        if parsed.hostname=='r.search.yahoo.com':
            redirect=re.search(r'/RU=([^/]+)',parsed.path)
            if redirect:target=unquote(redirect.group(1))
        if parsed.hostname in ('bing.com','www.bing.com') and parsed.path=='/ck/a':
            encoded=params.get('u',[''])[0]
            if encoded.startswith('a1'):
                try: target=base64.urlsafe_b64decode(encoded[2:]+'='*(-len(encoded[2:])%4)).decode()
                except (ValueError,UnicodeError): continue
        parsed=urlsplit(target)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or target in seen: continue
        if parsed.hostname==urlsplit(source).hostname and not (engine=='Baidu' and parsed.path=='/link'): continue
        heading=anchor.find(['h2','h3'])
        title=(heading or anchor).get_text(' ',strip=True)
        snippet='';parent=anchor.parent
        for _ in range(5):
            if parent is None or parent.name in ('body','html','[document]'): break
            if len(parent.find_all(['h2','h3']))>1: break
            description=parent.select_one('.b_caption p, .result__snippet, .compText p, .VwiC3b, .content, .OrganicTextContentSpan')
            if description:
                snippet=description.get_text(' ',strip=True)[:700];break
            parent=parent.parent
        # Query echo elsewhere on the page does not make a result relevant.
        wanted=normalized(term)
        values=(title,snippet,target)
        if field in ('phone','email'):
            # A numeric URL ID or an echoed query parameter is not contact evidence.
            matched=any(matches(value,field,term) for value in (title,snippet))
        elif field=='address':
            matched=any(re.search(r'(?<!\w)'+re.escape(normalized_street(term))+r'(?!\w)',normalized_street(value)) for value in values)
        else:
            matched=bool(wanted) and any(re.search(r'(?<!\w)'+re.escape(wanted)+r'(?!\w)',normalized(v)) for v in values)
        if not matched and not include_unmatched: continue
        seen.add(target)
        hits.append(OSINTHit(SITE,title,snippet or 'Search result mentioning this identifier; review the original page.',target,
                    {**metadata,'kind':'candidate' if matched else 'unverified','query':term,'engine':engine,'identity_verified':False,
                     'subject_url':source,'entity_type':'url','entity_value':target,'relationship':'search_mentions'}))
        if len(hits)>=max(1,min(limit,30)): break
    return hits


@register(SITE)
def web_search(session,q):
    requested=getattr(q,'search_engine','DuckDuckGo')
    if requested not in ENGINES: requested='DuckDuckGo'
    inputs=search_inputs(q)
    if not inputs:
        return [OSINTHit(SITE,'Search identifier needed','Enter a name, username, email, phone, address, or domain.','',{'kind':'needs_input'})]
    hits=StreamingHits(session)
    for item in inputs:
        leads=[]
        found=False
        engines=[requested]
        if getattr(q,'search_fallback',True):
            engines+= [engine for engine in ('DuckDuckGo','Bing','Yahoo') if engine!=requested]
        engines=engines[:3]
        for engine in engines:
            prefix='https://html.duckduckgo.com/html/?q=' if engine=='DuckDuckGo' else ENGINES[engine]
            url=prefix+quote_plus(item['query'])
            common={'query':item['term'],'search_expression':item['query'],'input_fields':[item['field']],
                    'context_fields':item['context_fields'],'requested_engine':requested,'engine':engine}
            if engine!=requested:common['fallback_from']=requested
            if engine in getattr(q,'search_skip_engines',()):
                hits.append(OSINTHit(SITE,engine+': paused for this run','An earlier request in this run was challenged or rate limited; no repeat request was sent to this engine.',url,{'kind':'blocked',**common}))
                continue
            try:
                body,metadata=fetch_page(session,url)
                parsed=parse_results(body,metadata,item['term'],engine,field=item['field'],include_unmatched=True)
                rows=[row for row in parsed if row.raw['kind']=='candidate']
                leads=[(row,dict(common)) for row in parsed if row.raw['kind']=='unverified']+leads
                found=bool(rows)
                if not rows:
                    rows=[OSINTHit(SITE,engine+': no extractable relevant results',
                                  'No supported result blocks matched this identifier. This is a source limitation, not evidence that the information does not exist.',url,
                                  {**metadata,'kind':'unavailable'})]
                for row in rows:
                    row.raw.update(common)
                    if found:
                        row.raw['evidence_text']=row.title+' '+row.snippet
                        row.raw['matched_inputs']=matched_inputs(row.raw['evidence_text'],q)
                    hits.append(row)
                if found:
                    # Preserve search candidates before optional original-page retrieval.
                    # The worker budget bounds these reads and retains streamed candidates.
                    if getattr(q,'fetch_result_pages',False) and item['field'] in ('name','email','phone','address'):
                        from contact_sources import public_page,extract_contacts
                        for candidate in rows[:2]:
                            try:
                                page,proof=public_page(session,candidate.url)
                                for hit in extract_contacts(page,proof,q,required_field=item['field']):
                                    hit.raw.update(common);hits.append(hit)
                            except FetchError as exc:
                                hits.append(OSINTHit(SITE,'Original page unavailable',str(exc),candidate.url,{'kind':'unavailable',**common}))
                    break
            except (FetchError,ValueError) as exc:
                code=re.match(r'HTTP (\d+)',str(exc))
                hits.append(OSINTHit(SITE,engine+': search unavailable',str(exc),url,
                            {'kind':'blocked','http_status':int(code.group(1)) if code else None,**common}))
        if not found and getattr(q,'fetch_result_pages',False) and item['field'] in ('name','email','phone','address'):
            # Search snippets can omit the identifier. Inspect at most two returned
            # pages, but promote nothing unless the original content matches.
            from contact_sources import public_page,extract_contacts
            seen=set()
            if item['field']=='email':
                mail_domain=item['term'].rsplit('@',1)[-1].lower()
                leads.sort(key=lambda pair:(urlsplit(pair[0].url).hostname or '').removeprefix('www.')!=mail_domain)
            for lead,common in leads:
                if lead.url in seen:continue
                seen.add(lead.url)
                try:
                    page,proof=public_page(session,lead.url)
                    for hit in extract_contacts(page,proof,q,required_field=item['field']):
                        hit.raw.update(common);hits.append(hit)
                except FetchError as exc:
                    hits.append(OSINTHit(SITE,'Original page unavailable',str(exc),lead.url,{'kind':'unavailable',**common}))
                if len(seen)>=2:break
    return hits
