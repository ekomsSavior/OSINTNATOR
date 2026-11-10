"""Free structured public sources; never imply comprehensive people coverage."""
from urllib.parse import quote, urlencode
from bs4 import BeautifulSoup
import requests
from scrapers import register, OSINTHit, StreamingHits
from api_sources import get_json, result, normalize_domain
from query_inputs import github_handle

@register('GitHub Public Discovery')
def github_discovery(session, q):
    site='GitHub Public Discovery'
    # Each populated identity field is a separate query, not a guessed identity merge.
    terms=[]
    for value,field in ((q.full_name,'fullname'),(q.username,'login'),(q.email,'email')):
        if value:
            if field=='login':
                try: value,_=github_handle(value)
                except ValueError: continue
            literal=value.replace('"',' ').replace('\\',' ').strip()[:160]
            terms.append((f'"{literal}" in:{field}',field))
    hits=StreamingHits(session)
    enrich=[]
    for query,field in terms:
        endpoint='https://api.github.com/search/users'
        page='https://github.com/search?'+urlencode({'q':query,'type':'users'})
        data,failure=get_json(session,site,endpoint,page,params={'q':query,'per_page':10})
        if failure:
            for h in failure: hits.append(h)
            continue
        items=data.get('items')
        if not isinstance(items,list):
            for h in result(site,'Unexpected API response','No usable search results were returned.',page,'error'): hits.append(h)
            continue
        if field=='login':
            # GitHub's quoted login search can still return prefix/substring
            # matches. A supplied handle is not a request for similar accounts.
            expected,_=github_handle(q.username)
            items=[item for item in items if isinstance(item,dict) and str(item.get('login','')).casefold()==expected.casefold()]
        if not items:
            for h in result(site,'No public GitHub match',f'No results in the public {field} index. This says nothing about other websites or private profile fields.',page,'not_found'): hits.append(h)
        field_hits=[]
        for item in items:
            if not isinstance(item,dict) or not isinstance(item.get('id'),int) or not item.get('login'): continue
            url='https://github.com/'+quote(item['login'],safe='')
            hit=OSINTHit(site,item['login'],f"Public GitHub {field} search candidate. Account ID: {item['id']}. Review the profile; this does not establish a real-world identity.",url,
                {'kind':'candidate','account_id':item['id'],'matched_field':field,'endpoint':endpoint,'query':query,'profile':{},'identity_verified':False,'incomplete_results':bool(data.get('incomplete_results'))})
            hits.append(hit)
            field_hits.append(hit)
        if field_hits:
            enrich.append(field_hits[0])
    # Emit every search match before optional profile calls. A source timeout
    # must preserve already retrieved candidates, even if enrichment is slow.
    for hit in enrich:
        detail,_=get_json(session,site,'https://api.github.com/users/'+quote(hit.title,safe=''),hit.url)
        if detail and detail.get('id')==hit.raw['account_id']:
            profile={key:detail.get(key) for key in ('login','name','bio','email','company','location','blog','twitter_username','created_at','public_repos') if detail.get(key) is not None}
            hit.raw['profile']=profile
            if profile:
                hit.snippet+=' Public profile: '+' | '.join(f'{key}: {value}' for key,value in profile.items())
    return hits

@register('Hacker News Profile API')
def hackernews(session,q):
    site='Hacker News Profile API'
    user=q.username.strip()
    if not user:
        return result(site,'Username needed','Enter a Hacker News username.','https://news.ycombinator.com/','needs_input')
    page='https://news.ycombinator.com/user?id='+quote(user,safe='')
    endpoint='https://hacker-news.firebaseio.com/v0/user/'+quote(user,safe='')+'.json'
    try:
        response=session.get(endpoint,timeout=(4,8))
        response.raise_for_status()
        data=response.json()
        if data is None:
            return result(site,'No public account returned','The API returned no profile for this username.',page,'not_found')
        if not isinstance(data,dict) or data.get('id') != user: raise ValueError('Unexpected record')
        about=BeautifulSoup(data.get('about',''),'html.parser').get_text(' ',strip=True)
        return result(site,'Public account: '+user,f"Karma: {data.get('karma','')} | Created (Unix time): {data.get('created','')} | {about}",page,'record',endpoint=endpoint,identity_verified=False)
    except (requests.RequestException,ValueError):
        return result(site,'Profile request failed','No conclusion can be drawn; the API was unavailable.',page,'error',endpoint=endpoint)


def dns_lookup(session,domain,types,site,kind='record'):
    hits=StreamingHits(session)
    for record_type in types:
        endpoint='https://dns.google/resolve'
        page=endpoint+'?'+urlencode({'name':domain,'type':record_type})
        data,failure=get_json(session,site,endpoint,page,params={'name':domain,'type':record_type})
        if failure:
            for hit in failure: hits.append(hit)
            continue
        status=data.get('Status')
        if status != 0:
            hits.append(OSINTHit(site,f'{record_type}: DNS status {status}', 'NXDOMAIN means this DNS name does not exist; other error codes are lookup failures. No mailbox test was performed.',page,{'kind':'not_found' if status==3 else 'error','dns_status':status}))
            continue
        answers=data.get('Answer',[])
        if not answers:
            hits.append(OSINTHit(site,f'No {record_type} answer',f'No {record_type} answer returned for {domain}. This does not verify or disprove an individual mailbox.',page,{'kind':'not_found'}))
        for answer in answers:
            if not isinstance(answer,dict): continue
            hits.append(OSINTHit(site,f"{domain} | {record_type}",f"{answer.get('name','')}: {answer.get('data','')} (TTL {answer.get('TTL','')}). Public DNS observation; not a mailbox or ownership confirmation.",page,{'kind':kind,'domain':domain,'record_type':answer.get('type'),'value':answer.get('data'),'endpoint':endpoint,'subject_url':'https://'+domain+'/', 'entity_type':'dns_record','entity_value':str(answer.get('data','')),'relationship':'dns_'+record_type,'source_url':page}))
    return hits

@register('Domain DNS Records')
def domain_dns(session,q):
    try: domain=normalize_domain(q.domain)
    except ValueError as exc: return result('Domain DNS Records','Domain needed',str(exc),'https://dns.google/','needs_input')
    return dns_lookup(session,domain,('A','AAAA','MX','NS','TXT'),'Domain DNS Records')

@register('Email Domain Records')
def email_domain(session,q):
    email=q.email.strip()
    if email.count('@') != 1 or not email.split('@')[0]:
        return result('Email Domain Records','Email needed','Enter an email address. Only its domain is sent to the DNS service.','https://dns.google/','needs_input')
    try: domain=normalize_domain(email.rsplit('@',1)[1])
    except ValueError as exc: return result('Email Domain Records','Invalid email domain',str(exc),'https://dns.google/','needs_input')
    if domain in {'gmail.com','googlemail.com','yahoo.com','outlook.com','hotmail.com','live.com','icloud.com','aol.com','proton.me','protonmail.com'}:
        return result('Email Domain Records','Shared email-provider domain: '+domain,
                      'Provider infrastructure would not identify this mailbox owner. No provider DNS rows were added as findings.',
                      'https://'+domain+'/', 'context',domain=domain)
    return dns_lookup(session,domain,('MX','TXT'),'Email Domain Records',kind='context')
