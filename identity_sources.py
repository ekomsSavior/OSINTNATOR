"""Public email profiles and commit metadata. No account recovery or private databases."""
import hashlib
import json
import re
from urllib.parse import quote,urlencode
from scrapers import register,OSINTHit,StreamingHits
from api_sources import result
from web_fetch import fetch_page,FetchError

def email_value(q):
    value=q.email.strip().lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value):raise ValueError('Enter a complete email address.')
    return value

def read_json(session,url):
    body,meta=fetch_page(session,url,accept='application/vnd.github+json' if url.startswith('https://api.github.com/') else 'application/json')
    try:data=json.loads(body)
    except ValueError as exc:raise FetchError('The source returned non-JSON data.') from exc
    if not isinstance(data,dict):raise FetchError('The source returned an unexpected record.')
    if data.get('error'):raise FetchError('The source returned an API error: '+str(data['error'])[:180])
    return data,meta

@register('Gravatar Email Profile')
def gravatar_email(session,q):
    site='Gravatar Email Profile'
    try:email=email_value(q)
    except ValueError as exc:return result(site,'Email needed',str(exc),'https://gravatar.com/','needs_input')
    digest=hashlib.sha256(email.encode()).hexdigest()
    endpoint='https://api.gravatar.com/v3/profiles/'+digest
    try:data,meta=read_json(session,endpoint)
    except FetchError as exc:
        return result(site,'No public profile returned' if str(exc).startswith('HTTP 404 ') else 'Profile source unavailable',
                      str(exc),endpoint,'not_found' if str(exc).startswith('HTTP 404 ') else 'unavailable')
    fields={key:data[key] for key in ('display_name','description','location','profile_url','pronunciation','job_title','company') if data.get(key)}
    if not fields:return result(site,'No usable public profile fields','No profile fields were returned.',endpoint,'unavailable')
    page=data.get('profile_url') or 'https://gravatar.com/'+digest
    hits=result(site,'Gravatar public profile: '+str(data.get('display_name') or 'profile'),
                ' | '.join(f'{key}: {value}' for key,value in fields.items()),page,'record',
                **meta,fields=fields,entity_type='url',entity_value=page,relationship='email_hash_profile',
                email_hash=digest,identity_verified=False)
    for account in data.get('verified_accounts',[])[:8]:
        if not isinstance(account,dict) or account.get('is_hidden') or not str(account.get('url','')).startswith('https://'):continue
        hits.extend(result(site,'Profile publishes account: '+str(account.get('service_label') or account.get('service_type') or 'account'),
                           str(account.get('url')),account['url'],'record',**meta,subject_url=page,
                           entity_type='url',entity_value=account['url'],relationship='profile_links_to',identity_verified=False))
    return hits

@register('GitHub Email Commits')
def email_commits(session,q):
    site='GitHub Email Commits'
    try:email=email_value(q)
    except ValueError as exc:return result(site,'Email needed',str(exc),'https://github.com/','needs_input')
    endpoint='https://api.github.com/search/commits?'+urlencode({'q':'author-email:'+email,'per_page':10})
    try:data,meta=read_json(session,endpoint)
    except FetchError as exc:return result(site,'Public commit search unavailable',str(exc),endpoint,'unavailable')
    if not isinstance(data.get('items'),list):return result(site,'Unexpected commit response','The source did not return a results list.',endpoint,'unavailable',**meta)
    hits=StreamingHits(session)
    for item in data.get('items',[]):
        if not isinstance(item,dict):continue
        commit=item.get('commit') or {};author=commit.get('author') or {}
        if str(author.get('email','')).lower()!=email:continue
        page=item.get('html_url','')
        if not page.startswith('https://github.com/'):continue
        fields={'published_author_name':author.get('name'),'published_author_email':author.get('email'),
                'commit_date':author.get('date'),'repository':(item.get('repository') or {}).get('full_name'),
                'linked_account':(item.get('author') or {}).get('login'),'commit_sha':item.get('sha')}
        fields={key:value for key,value in fields.items() if value is not None}
        hits.append(OSINTHit(site,'Public commit: '+str(fields.get('repository','repository')),
                    ' | '.join(f'{key}: {value}' for key,value in fields.items())+'. Git author metadata can be self-declared; this does not prove mailbox ownership.',page,
                    {**meta,'kind':'candidate','fields':fields,'entity_type':'url','entity_value':page,
                     'relationship':'commit_publishes_email','identity_verified':False,'incomplete_results':bool(data.get('incomplete_results'))}))
    if not hits:hits.extend(result(site,'No matching public commits returned','The public commit index returned no exact author-email match. This does not test mailbox existence.',endpoint,'not_found',**meta))
    return hits
