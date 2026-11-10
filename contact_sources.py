"""Retrieve matching public contact statements from original pages."""
import json
import re
from urllib.parse import urlsplit,unquote
from urllib.robotparser import RobotFileParser
from bs4 import BeautifulSoup
from scrapers import register,OSINTHit
from api_sources import result
from web_fetch import fetch_page,FetchError,AGENT
from evidence_matching import matched_inputs,matches

def public_page(session,url):
    parsed=urlsplit(url);root=parsed.scheme+'://'+parsed.netloc
    try:
        body,_=fetch_page(session,root+'/robots.txt',save=False,limit=100_000)
        policy=RobotFileParser();policy.parse(body.splitlines())
        if not policy.can_fetch(AGENT,url):raise FetchError('Collection disallowed by robots.txt')
    except FetchError as exc:
        if not str(exc).startswith('HTTP 404 '):raise
    return fetch_page(session,url)

def extract_contacts(body,meta,q,site='Retrieved Public Page',required_field=None,allow_plain=True):
    soup=BeautifulSoup(body,'html.parser')
    title=soup.title.get_text(' ',strip=True) if soup.title else 'Public page'
    if re.search(r'just a moment|access denied|verify you are human|checking your browser',title+' '+soup.get_text(' ',strip=True)[:1000],re.I):raise FetchError('The source returned an access challenge')
    hits=[]
    def objects(value):
        if isinstance(value,list):
            for item in value:yield from objects(item)
        elif isinstance(value,dict):
            yield value
            for key in ('@graph','mainEntity','itemListElement','item'):
                if key in value:yield from objects(value[key])
    for script in soup.select('script[type="application/ld+json"]'):
        try:data=json.loads(script.string or script.get_text())
        except ValueError:continue
        for item in objects(data):
            types=item.get('@type',[]);types=[types] if isinstance(types,str) else types
            if not isinstance(types,list):continue
            types=[value for value in types if isinstance(value,str)]
            if not set(types).intersection({'Person','Organization','LocalBusiness','RealEstateListing','Place','Residence','House'}):continue
            fields={key:item[key] for key in ('name','telephone','email','address','contactPoint','description','url','sameAs') if item.get(key)}
            text=json.dumps(fields,ensure_ascii=False)
            matched=matched_inputs(text,q)
            if not matched or (required_field and required_field not in matched):continue
            hits.append(OSINTHit(site,title,' | '.join(f'{k}: {v}' for k,v in fields.items()),meta['source_url'],
                        {**meta,'kind':'candidate','fields':fields,'evidence_text':text,'matched_inputs':matched,
                         'entity_type':'url','entity_value':meta['source_url'],'relationship':'publishes_matching_contact','identity_verified':False}))
    # Exact contact links are stronger evidence than a query in a page title.
    contacts={}
    for anchor in soup.select('a[href]'):
        href=anchor['href']
        if href.lower().startswith(('tel:','mailto:')):
            field='phone' if href.lower().startswith('tel:') else 'email'
            value=unquote(href.split(':',1)[1].split('?')[0])
            if matches(value,field,getattr(q,field,'')):contacts[field]=value
    if contacts and (not required_field or required_field in contacts):
        text=json.dumps(contacts)
        hits.append(OSINTHit(site,'Published contact on '+title,' | '.join(f'{k}: {v}' for k,v in contacts.items()),meta['source_url'],
                    {**meta,'kind':'record','fields':contacts,'evidence_text':text,'matched_inputs':list(contacts),
                     'entity_type':'url','entity_value':meta['source_url'],'relationship':'publishes_matching_contact','identity_verified':False}))
    # Plain published contact mentions often have no schema or clickable link.
    # Limit extraction to content blocks, excluding search forms and query headings.
    if not allow_plain:return hits
    seen=set()
    for block in soup.select('p,li,address,td,dd'):
        if block.find_parent(['form','nav','script','style']):continue
        text=block.get_text(' ',strip=True)
        if not text or len(text)>1600 or re.search(r'no (?:results|records|matches)|search (?:for|results)',text,re.I):continue
        values={'name':q.full_name,'email':q.email,'phone':q.phone,'address':q.address1}
        fields=[f for f,value in values.items() if matches(text,f,value)]
        if not fields or (required_field and required_field not in fields):continue
        if text in seen:continue
        seen.add(text)
        hits.append(OSINTHit(site,'Published '+', '.join(fields)+' mention',text[:1600],meta['source_url'],
                    {**meta,'kind':'record' if set(fields)&{'email','phone'} else 'candidate','evidence_text':text,'matched_inputs':matched_inputs(text,q),
                     'entity_type':'url','entity_value':meta['source_url'],'relationship':'publishes_contact_mention','identity_verified':False}))
        if len(seen)>=5:break
    return hits

def phone_source(session,q,site,url):
    if not q.phone.strip():return result(site,'Phone number needed','Enter a phone number.',url,'needs_input')
    try:
        body,meta=public_page(session,url)
        rows=extract_contacts(body,meta,q,site,required_field='phone',allow_plain=False)
        return rows or result(site,'No structured matching phone record returned','The page did not expose a matching contact record. A number echoed in a heading is not a person match.',url,'not_found',**meta)
    except FetchError as exc:return result(site,'Phone source unavailable',str(exc),url,'unavailable')

@register('USPhoneBook')
def usphonebook(session,q):
    digits=re.sub(r'\D','',q.phone)
    if len(digits)==11 and digits.startswith('1'):digits=digits[1:]
    if len(digits)!=10:return result('USPhoneBook','US phone number needed','Enter a ten-digit US number or +1 and ten digits.','https://www.usphonebook.com/','needs_input')
    return phone_source(session,q,'USPhoneBook','https://www.usphonebook.com/'+digits)
