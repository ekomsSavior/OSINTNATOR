"""Compare returned evidence with supplied inputs without asserting shared identity."""
import json
import re
from query_inputs import normalized_street,normalize_domain

def normalized(value):
    return re.sub(r'[^\w]+',' ',str(value).casefold()).strip()

def matches(value,field,term):
    if not term.strip():return False
    if field=='phone':
        value=re.sub('[‐‑‒–—−]','-',value)
        digits=re.sub(r'\D','',term)
        if len(digits)==11 and digits.startswith('1'):digits=digits[1:]
        prefix=r'(?:\+?1[\s()./-]*)?' if len(digits)==10 else ''
        return len(digits)>=7 and bool(re.search(r'(?<!\d)'+prefix+r'[\s().+/-]*'.join(digits)+r'(?!\d)',value))
    if field=='email':
        return bool(re.search(r'(?<![\w.+-])'+re.escape(term.strip())+r'(?![\w.-])',value,re.I))
    normalizer=normalized_street if field=='address' else normalized
    wanted=normalizer(term)
    return bool(wanted) and bool(re.search(r'(?<!\w)'+re.escape(wanted)+r'(?!\w)',normalizer(value)))

def matched_inputs(text,q):
    fields={'name':q.full_name,'username':q.username,'email':q.email,'phone':q.phone,'address':q.address1}
    try:fields['domain']=normalize_domain(q.domain)
    except ValueError:pass
    return [field for field,value in fields.items() if value and matches(text,field,value)]

def annotate_hit(hit,q):
    if hit.raw.get('kind') not in ('record','candidate'):return
    # Do not examine request URLs, query parameters or the input echoed in metadata.
    evidence=hit.raw.get('evidence_text')
    if evidence is None:
        evidence=json.dumps(hit.raw.get('fields') or hit.raw.get('profile') or {},ensure_ascii=False)
        if evidence=='{}':evidence=hit.snippet
    hit.raw['matched_inputs']=matched_inputs(evidence,q)
    hit.raw['identity_verified']=False
