"""GraphML of observed entities and sourced relationships, excluding navigation noise."""
import hashlib
import re
import json
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode
from research_plan import coverage

NS='http://graphml.graphdrawing.org/xmlns'
ET.register_namespace('',NS)

def clean(value):
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]','',str(value))

def canonical_url(value):
    parsed=urlsplit(value)
    query=urlencode([(k,v) for k,v in parse_qsl(parsed.query,keep_blank_values=True) if not k.lower().startswith('utm_') and k.lower() not in ('msockid','msclkid','gclid','fbclid')])
    return urlunsplit((parsed.scheme.lower(),parsed.netloc.lower(),parsed.path or '/',query,parsed.fragment))

def export_graphml(hits,path,include_diagnostics=False,run_metadata=None):
    def element(parent,name,**attrs): return ET.SubElement(parent,'{'+NS+'}'+name,attrs)
    root=ET.Element('{'+NS+'}graphml')
    keys=('label','kind','url','checked_at','snippet','relationship','source_url','content_sha256','evidence_file','fields','input_fields','context_fields','matched_inputs','coverage','run_metadata')
    for name in keys: element(root,'key',id=name,**{'for':'all','attr.name':name,'attr.type':'string'})
    graph=element(root,'graph',id='evidence',edgedefault='directed')
    nodes={}
    def data(parent,**values):
        for key,value in values.items():
            if value is not None: element(parent,'data',key=key).text=clean(value)
    plan=next((hit.raw['coverage_plan'] for hit in hits if 'coverage_plan' in hit.raw),None)
    data(graph,coverage=json.dumps(coverage(hits,plan),ensure_ascii=False))
    if run_metadata:data(graph,run_metadata=json.dumps(run_metadata,ensure_ascii=False))
    def node(kind,value,label=None,**values):
        canonical=canonical_url(value) if kind=='url' else value
        key=(kind,canonical)
        if key not in nodes:
            identifier='n'+hashlib.sha256(repr(key).encode()).hexdigest()[:24]
            nodes[key]=identifier
            data(element(graph,'node',id=identifier),label=label or canonical,kind=kind,
                 url=canonical if kind=='url' else '',**values)
        return nodes[key]
    for i,hit in enumerate(hits):
        status=hit.raw.get('kind','candidate')
        if not include_diagnostics and status not in ('record','candidate'): continue
        raw=hit.raw
        subject=raw.get('subject_url') or raw.get('source_url') or raw.get('endpoint')
        source=node('url',subject) if subject else node('source',raw.get('source',hit.site))
        entity_type=raw.get('entity_type')
        entity_value=raw.get('entity_value')
        if entity_type and entity_value:
            target=node(entity_type,str(entity_value),snippet=hit.snippet,fields=json.dumps(raw.get('fields',{}),ensure_ascii=False))
        else:
            target=node(status,hit.site+'|'+hit.title+'|'+hit.url,label=hit.title,
                        snippet=hit.snippet,checked_at=raw.get('checked_at',''))
        edge=element(graph,'edge',id='e'+str(i),source=source,target=target)
        data(edge,kind=status,label=hit.title,snippet=hit.snippet,
             relationship=raw.get('relationship','returned candidate' if status=='candidate' else 'returned record' if status=='record' else 'diagnostic; not evidence'),
             source_url=raw.get('source_url') or raw.get('endpoint') or hit.url,
             checked_at=raw.get('checked_at',''),content_sha256=raw.get('content_sha256',''),
             evidence_file=raw.get('evidence_file',''),fields=json.dumps(raw.get('fields',{}),ensure_ascii=False),
             input_fields=json.dumps(raw.get('input_fields',[])),context_fields=json.dumps(raw.get('context_fields',[])),matched_inputs=json.dumps(raw.get('matched_inputs',[])))
    ET.ElementTree(root).write(path,encoding='utf-8',xml_declaration=True)
    return str(path)
