"""Normalize identifiers without merging them into an assumed identity."""
import re
from urllib.parse import urlsplit, unquote

ENGINES={
    'DuckDuckGo':'https://duckduckgo.com/?q=',
    'Google':'https://www.google.com/search?q=',
    'Brave':'https://search.brave.com/search?q=',
    'Bing':'https://www.bing.com/search?q=',
    'Yahoo':'https://search.yahoo.com/search?p=',
    'Yandex':'https://yandex.com/search/?text=',
    'Baidu':'https://www.baidu.com/s?wd=',
    'ZoomEye':'https://www.zoomeye.ai/search?q=',
    'DogPile':'https://www.dogpile.com/serp?q=',
}


def normalize_domain(value):
    value = value.strip()
    parsed = urlsplit(value if '://' in value else '//'+value)
    if parsed.scheme not in ('', 'http', 'https') or parsed.username or parsed.password:
        raise ValueError('Enter a public domain or an http/https website URL.')
    domain = (parsed.hostname or '').rstrip('.').lower()
    try:
        domain = domain.encode('idna').decode('ascii')
    except UnicodeError:
        raise ValueError('Invalid domain')
    if len(domain) > 253 or not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})', domain):
        raise ValueError('Enter a public domain or website URL, such as example.org or https://example.org/.')
    return domain


def github_handle(value):
    """Return a handle and whether it is only a whitespace-derived hypothesis."""
    value = value.strip()
    if '://' in value or value.lower().startswith(('github.com/', 'www.github.com/')):
        parsed = urlsplit(value if '://' in value else 'https://'+value)
        parts = [unquote(p) for p in parsed.path.split('/') if p]
        if parsed.scheme not in ('http', 'https') or parsed.hostname not in ('github.com','www.github.com') or parsed.username or not parts:
            raise ValueError('Enter a GitHub handle or github.com profile URL.')
        value = parts[0]
    value = value.lstrip('@')
    derived = bool(re.search(r'\s', value))
    value = re.sub(r'\s+', '', value)
    if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?', value):
        raise ValueError('Enter a GitHub handle or github.com profile URL.')
    if value.lower() in ('login','signup','search','settings','features','marketplace','topics','orgs','users'):
        raise ValueError('This is a GitHub navigation page, not a profile.')
    return value, derived


def search_terms(q):
    return [item['term'] for item in search_inputs(q)]


FIELD_LABELS={'name':'Name','username':'Username','email':'Email','phone':'Phone',
              'address':'Address','domain':'Website/domain','location':'Location','other':'Other'}

def normalized_street(value):
    value=re.sub(r'[\W_]+',' ',value.casefold()).strip()
    words={'st':'street','rd':'road','ln':'lane','dr':'drive','ave':'avenue','blvd':'boulevard',
           'n':'north','s':'south','e':'east','w':'west','ne':'northeast','nw':'northwest','se':'southeast','sw':'southwest'}
    return ' '.join(words.get(word,word) for word in value.split())


def search_inputs(q):
    """Each identifier has its own query; location narrows names and addresses."""
    location=' '.join(v.strip() for v in (q.city,q.state,q.zip) if v.strip())
    def quoted(value): return '"'+value.replace('"',' ').strip()+'"'
    items=[]
    for field,value in (('name',q.full_name),('username',q.username),('email',q.email),
                        ('phone',q.phone),('address',q.address1),('domain',q.domain)):
        value=value.strip()
        if not value: continue
        context=[]
        if field=='domain':
            try: value=normalize_domain(value)
            except ValueError: continue
        query=quoted(value)
        if field=='name' and (q.city.strip() or q.state.strip()) and getattr(q,'search_context','')!='identifier_only':
            query+=' '+' '.join(quoted(v) for v in (q.city,q.state) if v.strip())
            context=['city','state']
        elif field=='address' and location:
            expanded=normalized_street(value)
            if expanded!=value.casefold():query='('+quoted(value)+' OR '+quoted(expanded)+')'
            query+=' '+' '.join(quoted(v) for v in (q.city,q.state,q.zip) if v.strip())
            context=['city','state','zip']
        elif field=='phone':
            digits=re.sub(r'\D','',value)
            if len(digits)==10:
                query=digits
        items.append({'field':field,'term':value,'query':query,
                      'context_fields':[key for key in context if getattr(q,key).strip()]})
    if location and not (q.full_name or q.address1):
        items.append({'field':'location','term':location,'query':' '.join(quoted(v) for v in (q.city,q.state,q.zip) if v.strip()),'context_fields':[]})
    selected=getattr(q,'search_field',None)
    return [item for item in items if not selected or item['field']==selected]
