"""Readable offline report with findings and source diagnostics kept distinct."""
from collections import Counter
from html import escape
from pathlib import Path
from urllib.parse import urlsplit
from research_plan import coverage,balanced_findings
from query_inputs import FIELD_LABELS

def link(url,label=None):
    value=str(url or '')
    if urlsplit(value).scheme not in ('http','https'): return escape(label or value)
    return '<a rel="noreferrer" href="'+escape(value,quote=True)+'">'+escape(label or value)+'</a>'

def render_html(hits,run_metadata=None):
    counts=Counter(h.raw.get('kind','candidate') for h in hits)
    def card(hit):
        raw=hit.raw;kind=raw.get('kind','candidate')
        fields=raw.get('fields') or raw.get('profile') or {}
        detail=''.join('<dt>'+escape(str(k))+'</dt><dd>'+escape(str(v))+'</dd>' for k,v in fields.items()) if isinstance(fields,dict) else ''
        source=raw.get('source_url') or raw.get('endpoint') or hit.url
        proof=''
        if raw.get('content_sha256'): proof='<p class="muted">Response SHA-256: <code>'+escape(raw['content_sha256'])+'</code></p>'
        if len(raw.get('matched_inputs',[]))>=2:
            proof='<p>Supplied details found together: '+escape(', '.join(FIELD_LABELS.get(f,f) for f in raw['matched_inputs']))+'. Review the source relationship.</p>'+proof
        input_label=', '.join(FIELD_LABELS.get(field,field) for field in raw.get('input_fields',()))
        engine=raw.get('engine','')+(' (fallback from '+raw['fallback_from']+')' if raw.get('fallback_from') else '')
        label=' · '.join(value for value in (kind.upper(),hit.site,input_label,engine) if value)
        return '<article><p class="muted">'+escape(label)+'</p><h3>'+link(hit.url,hit.title)+'</h3><p>'+escape(hit.snippet)+'</p>'+('<dl>'+detail+'</dl>' if detail else '')+'<p>Source: '+link(source)+'</p><p class="muted">Collected: '+escape(raw.get('checked_at','not recorded'))+'</p>'+proof+'</article>'
    findings=[h for h in balanced_findings(hits) if h.raw.get('kind','candidate') in ('record','candidate')]
    other=[h for h in hits if h.raw.get('kind','candidate') not in ('record','candidate')]
    html='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OSINTNATOR research report</title>
<style>body{background:#0b0b0b;color:#eee;font:16px/1.55 system-ui,sans-serif;max-width:1000px;margin:40px auto;padding:0 24px}h1,h2,h3{line-height:1.25}a{color:#fff;text-decoration:underline;overflow-wrap:anywhere}article{border:1px solid #444;background:#161616;padding:20px;margin:16px 0}article p{margin:8px 0}.muted{color:#aaa;font-size:14px}dl{display:grid;grid-template-columns:160px 1fr;gap:6px}dt{color:#aaa}dd{margin:0;overflow-wrap:anywhere}code{overflow-wrap:anywhere}summary{cursor:pointer;padding:16px;background:#222}@media(max-width:600px){dl{grid-template-columns:1fr}}</style>
<h1>OSINTNATOR research report</h1>'''
    html+='<p>'+str(counts['record'])+' source records · '+str(counts['candidate'])+' candidates · '+str(len(other))+' context or source-status rows</p>'
    html+='<p>Records describe what a source returned or published. Candidate matches require review. Published links show a relationship between pages; they do not by themselves prove who owns an account.</p>'
    plan=next((hit.raw['coverage_plan'] for hit in hits if 'coverage_plan' in hit.raw),None)
    if any('input_fields' in hit.raw for hit in hits):
        html+='<h2>Input coverage</h2><dl>'
        for row in coverage(hits,plan).values():
            html+='<dt>'+escape(row['label'])+'</dt><dd>'+escape(row['status'])+' ('+str(row['checks'])+'/'+str(row['planned_checks'])+' source tasks reported; manual paths are not retrieved records)</dd>'
        html+='</dl>'
    html+='<h2>Retrieved findings</h2>'
    html+=''.join(card(h) for h in findings) or '<p>No records or candidates were retrieved. Inspect the source details below.</p>'
    html+='<details><summary>Context, unavailable sources and manual paths ('+str(len(other))+')</summary>'+''.join(card(h) for h in other)+'</details></html>'
    if run_metadata:
        import json
        html=html.replace('</html>','<details><summary>Run settings and input details</summary><pre>'+escape(json.dumps(run_metadata,ensure_ascii=False,indent=2))+'</pre></details></html>')
    return html

def export_html(hits,path):
    Path(path).write_text(render_html(hits),encoding='utf-8')
    return str(path)
