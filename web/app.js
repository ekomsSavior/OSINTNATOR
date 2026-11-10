'use strict';
const $ = id => document.getElementById(id);
const labels = {name:'Name',username:'Username',email:'Email',phone:'Phone',address:'Address',domain:'Website',location:'Location'};
let catalog = [], autoSources = true, jobId = null, current = null, timer = null, signature = '';
let busy = false;
const emptyState = $('cards').cloneNode(true);
const done = state => ['complete','cancelled','timed_out','failed'].includes(state);
function node(tag, text, className) { const el=document.createElement(tag); if(text!==undefined)el.textContent=text; if(className)el.className=className; return el; }
function showError(text='') { $('error').textContent=text; $('error').hidden=!text; }
function inputs() { return Object.fromEntries([...$('inputs').querySelectorAll('input')].map(i=>[i.name,i.value.trim()])); }
function populated() {
  const q=inputs(), fields=[];
  if(q.first||q.last)fields.push('name');
  for(const f of ['username','email','phone','domain'])if(q[f])fields.push(f);
  if(q.address1)fields.push('address');
  if((q.city||q.state||q.zip)&&!q.address1&&!q.first&&!q.last)fields.push('location');
  return fields;
}
function selected() { return [...$('sources').querySelectorAll('input:checked')].map(el=>el.value); }
function sourceCount() { $('source-count').textContent=`${selected().length} / ${catalog.length} selected`; }
function relevant() {
  const fields=populated();
  for(const box of $('sources').querySelectorAll('input')){const source=catalog.find(s=>s.id===box.value);box.checked=source.mode!=='portal'&&source.fields.some(f=>fields.includes(f));}
  sourceCount();
}
function renderSources() {
  const counts={collector:0,page_check:0,portal:0}, groups=new Map();
  for(const source of catalog) {
    counts[source.mode]=(counts[source.mode]||0)+1;
    if(!groups.has(source.category)){
      const group=node('section',undefined,'source-group'), heading=node('h3',source.category), toggle=node('button','Select category');toggle.type='button';toggle.className='category-select';
      toggle.addEventListener('click',()=>{autoSources=false;const boxes=[...group.querySelectorAll('input')];const select=boxes.some(box=>!box.checked);for(const box of boxes)box.checked=select;sourceCount();});
      group.append(heading,toggle);groups.set(source.category,group);$('sources').append(group);
    }
    const row=node('label',undefined,'source'), box=node('input'); box.type='checkbox'; box.value=source.id;
    box.addEventListener('change',()=>{autoSources=false;sourceCount();});
    row.dataset.search=`${source.id} ${source.category} ${source.fields.join(' ')}`.toLowerCase();
    const mode={collector:'COLLECTOR',page_check:'PUBLIC-PAGE CHECK',portal:'INTERACTIVE PORTAL'}[source.mode];
    const text=node('span');text.append(node('strong',source.id),node('small',mode,'source-mode'),node('small',source.description));row.append(box,text);groups.get(source.category).append(row);
  }
  $('catalog-summary').textContent=`${catalog.length} sources: ${counts.collector} collectors, ${counts.page_check} public-page checks, ${counts.portal} interactive portals. Portals are never counted as findings.`;
  relevant();
}
$('source-filter').addEventListener('input',()=>{const text=$('source-filter').value.trim().toLowerCase();for(const row of $('sources').querySelectorAll('.source'))row.hidden=!row.dataset.search.includes(text);for(const group of $('sources').querySelectorAll('.source-group'))group.hidden=![...group.querySelectorAll('.source')].some(row=>!row.hidden);});
async function api(url, options={}) {
  const response=await fetch(url,{credentials:'same-origin',...options,headers:{'Content-Type':'application/json','X-OSINTNATOR':'1',...options.headers}});
  if(!response.ok) {let body;try{body=await response.json();}catch{body={};} const error=new Error(body.detail||`Request failed (${response.status}).`);error.status=response.status;throw error;}
  return response.status===204 ? null : response.json();
}
function setBusy(value) {
  busy=value; $('run').disabled=value; $('run').replaceChildren(node('span',value?'Searching…':'Run all selected'),node('span',value?'':'→'));
  for(const el of $('search-form').querySelectorAll('input,select,button'))if(el.id!=='run')el.disabled=value;
  $('cancel').hidden=!value; $('cancel').disabled=false;
}
function safeLink(url, text) {
  try { const u=new URL(url);if(!['http:','https:'].includes(u.protocol)||u.username||u.password)return null;
    const a=node('a',text);a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';return a;
  } catch {return null;}
}
function renderCoverage() {
  $('coverage').replaceChildren();
  $('field-status').replaceChildren();
  for(const [field,entry] of Object.entries(current.coverage)) {
    const tasks=(current.tasks||[]).filter(task=>task.fields.includes(field)&&task.mode!=='portal');
    const running=tasks.filter(task=>task.state==='running').length, queued=tasks.filter(task=>task.state==='queued').length;
    const button=node('button',undefined,$('field').value===field?'active':'');button.type='button';
    button.append(node('span',labels[field]||entry.label),node('strong',`${entry.findings} ${entry.findings===1?'finding':'findings'}`),node('small',entry.findings ? (entry.checks<entry.planned_checks&&!done(current.state)?'More sources running':'Returned public results') : entry.status),node('small',`${entry.checks}/${entry.planned_checks} lookups reported`));
    button.addEventListener('click',()=>{$('field').value=$('field').value===field?'all':field;if(!entry.findings)$('view').value='all';renderCoverage();renderCards();});$('coverage').append(button);
    if(!entry.findings) {
      const section=node('div',undefined,'field-status'), title=node('strong',labels[field]||entry.label);
      const state=!done(current.state)&&(running||queued)?`${running} running, ${queued} queued. No findings returned yet.`:entry.status;
      const issues=current.hits.filter(hit=>(hit.raw.input_fields||[]).includes(field)&&['blocked','unavailable','timeout','error','not_found','needs_input','cancelled'].includes(hit.raw.kind));
      section.append(title,node('span',state));
      if(issues.length)section.append(node('small',issues.slice(-2).map(hit=>`${hit.site}: ${hit.title}`).join(' · ')));
      const inspect=node('button','Review '+(labels[field]||entry.label).toLowerCase()+' sources');inspect.type='button';inspect.addEventListener('click',()=>{$('field').value=field;$('view').value='all';$('filter').value='';renderCoverage();renderCards();});section.append(inspect);$('field-status').append(section);
    }
  }
  $('lookup-progress').hidden=false;$('lookup-tasks').replaceChildren();
  const tasks=current.tasks||[], running=tasks.filter(task=>task.state==='running').length, queued=tasks.filter(task=>task.state==='queued').length;
  $('lookup-progress').querySelector('summary').textContent=`Lookup progress: ${current.progress.completed}/${current.progress.total} reported · ${running} running · ${queued} queued`;
  for(const task of tasks)if($('field').value==='all'||task.fields.includes($('field').value)) {
    const row=node('div',undefined,'lookup-task');row.append(node('span',task.source+(task.id.endsWith('_location')?' (with location)':'')+' · '+task.fields.map(f=>labels[f]||f).join(', ')),node('span',task.state==='complete'?(task.mode==='portal'?'Portal ready':'Reported'):task.state));$('lookup-tasks').append(row);
  }
}
function card(hit) {
  const raw=hit.raw, article=node('article',undefined,'result-card'), top=node('div',undefined,'card-top');
  top.append(node('span',raw.kind==='manual'?'SOURCE PORTAL':(raw.kind||'candidate').replaceAll('_',' ').toUpperCase(),'kind'),node('span',hit.site));
  const fields=(raw.input_fields||[]).map(f=>labels[f]||f).join(' / ');if(fields)top.append(node('span',fields));
  if(raw.engine)top.append(node('span',raw.engine+(raw.fallback_from?' (fallback)':'')));
  article.append(top,node('h3',hit.title),node('p',hit.snippet));
  if((raw.matched_inputs||[]).length>1)article.append(node('p','Found together: '+raw.matched_inputs.map(f=>labels[f]||f).join(', ')+'. Review the relationship in the source.','shared'));
  const bottom=node('div',undefined,'card-bottom'), result=safeLink(hit.url,'Open result'), source=safeLink(raw.source_url||raw.endpoint,'Source page');
  if(result)bottom.append(result);if(source&&source.href!==result?.href)bottom.append(source);
  if(raw.checked_at)bottom.append(node('span',new Date(raw.checked_at).toLocaleString(),'timestamp'));article.append(bottom);
  const evidence=node('details',undefined,'evidence');evidence.append(node('summary','Evidence details'));
  const list=node('dl'), data={...(raw.fields||raw.profile||{}),Source:raw.source_url||raw.endpoint||hit.url,'Collected at':raw.checked_at,'Response SHA-256':raw.content_sha256};
  for(const [key,value] of Object.entries(data))if(value!==undefined&&value!==null&&value!=='')list.append(node('dt',key.replaceAll('_',' ')),node('dd',typeof value==='object'?JSON.stringify(value,null,2):String(value)));
  evidence.append(list,node('p',raw.kind==='record'?'A returned public record does not by itself establish identity or ownership.':'Candidates need corroboration. Unavailable sources do not mean the identifier has no public records.'));
  article.append(evidence);return article;
}
function renderCards() {
  if(!current)return;
  const field=$('field').value, view=$('view').value, text=$('filter').value.toLowerCase();
  const hits=current.hits.filter(hit=>{
    const finding=['record','candidate'].includes(hit.raw.kind), group=new Set([...(hit.raw.input_fields||[]),...(hit.raw.matched_inputs||[])]);
    return (field==='all'||group.has(field))&&(view==='all'||view==='findings'&&finding||view==='portals'&&hit.raw.kind==='manual'||view==='issues'&&!finding&&hit.raw.kind!=='manual'||view==='shared'&&finding&&(hit.raw.matched_inputs||[]).length>1)&&`${hit.title} ${hit.site} ${hit.snippet} ${hit.url}`.toLowerCase().includes(text);
  });
  $('result-count').textContent=`${hits.length} shown · ${current.hits.filter(h=>['record','candidate'].includes(h.raw.kind)).length} findings · ${current.hits.filter(h=>h.raw.kind==='manual').length} source portals${current.truncated?' · Result limit reached':''}`;
  $('cards').replaceChildren(...hits.map(card));
  if(!hits.length){const empty=node('div',undefined,'no-results');empty.append(node('p',!done(current.state)?'Collection is running. Results will appear as each lookup finishes.':'No results match this view. Inspect source status to see completed checks, access failures and missing inputs.'));const button=node('button','Show source status');button.addEventListener('click',()=>{$('view').value='issues';$('filter').value='';renderCards();});empty.append(button);$('cards').append(empty);}
}
function render(snapshot) {
  current=snapshot;
  const sig=`${snapshot.id}:${snapshot.state}:${snapshot.progress.completed}:${snapshot.hits.length}:${(snapshot.tasks||[]).map(t=>t.state).join(',')}`;
  if(sig===signature)return;signature=sig;
  const finished=done(snapshot.state);setBusy(!finished);
  $('forget').hidden=false;$('result-tools').hidden=false;$('progress').hidden=false;
  $('progress').max=snapshot.progress.total||1;$('progress').value=snapshot.progress.completed;
  $('progress-text').textContent=`${snapshot.progress.completed} / ${snapshot.progress.total} lookups`;
  const phrases={running:'Searching public sources',complete:'Search complete',cancelled:'Search stopped — partial results retained',timed_out:'Run budget reached — partial results retained',failed:'Search failed — any partial results are retained'};
  $('status').textContent=`${phrases[snapshot.state]||snapshot.state} · ${snapshot.settings.engine}${snapshot.settings.fallback?' + fallback':''} · ${snapshot.settings.lookup_budget_seconds}s per lookup`;
  const old=$('field').value;$('field').replaceChildren(new Option('All inputs','all'));
  for(const [field,entry] of Object.entries(snapshot.coverage))$('field').append(new Option(labels[field]||entry.label,field));
  $('field').value=[...$('field').options].some(o=>o.value===old)?old:'all';
  for(const format of ['json','html','graphml']){const link=$(format+'-download');link.href=`/api/jobs/${encodeURIComponent(jobId)}/report/${format}`;link.download=`osintnator-report.${format}`;}
  renderCoverage();renderCards();
}
async function poll(id) {
  if(id!==jobId)return;
  try {const snapshot=await api('/api/jobs/'+encodeURIComponent(id));if(id!==jobId)return;render(snapshot);if(!done(snapshot.state))timer=setTimeout(()=>poll(id),1200);}
  catch(error){if(id!==jobId)return;if(error.status===404){sessionStorage.removeItem('osintnator-job');jobId=null;setBusy(false);$('cancel').hidden=true;showError(error.message);}else{$('status').textContent='Connection interrupted. Retrying…';timer=setTimeout(()=>poll(id),3000);}}
}
$('search-form').addEventListener('submit',async event=>{
  event.preventDefault();if(busy)return;showError();if(!Object.values(inputs()).some(Boolean)){showError('Enter at least one search detail.');return;}if(!selected().length){showError('Select at least one source.');$('sources-box').open=true;return;}
  setBusy(true);clearTimeout(timer);
  try {const snapshot=await api('/api/jobs',{method:'POST',body:JSON.stringify({inputs:inputs(),sources:selected(),engine:$('engine').value,fallback:$('fallback').checked,budget:Number($('budget').value)})});jobId=snapshot.id;sessionStorage.setItem('osintnator-job',jobId);signature='';$('filter').value='';$('view').value='findings';$('field').value='all';render(snapshot);poll(jobId);if(matchMedia('(max-width:720px)').matches)$('results').scrollIntoView({behavior:'auto'});}
  catch(error){setBusy(false);showError(error.message);}
});
$('inputs').addEventListener('input',()=>{if(autoSources)relevant();});
$('relevant').addEventListener('click',()=>{autoSources=true;relevant();});
for(const id of ['all-sources','no-sources'])$(id).addEventListener('click',()=>{autoSources=false;for(const box of $('sources').querySelectorAll('input'))box.checked=id==='all-sources';sourceCount();});
for(const id of ['view','field'])$(id).addEventListener('change',()=>{renderCoverage();renderCards();});
$('filter').addEventListener('input',renderCards);
$('cancel').addEventListener('click',async()=>{if(!jobId)return;$('cancel').disabled=true;try{await api(`/api/jobs/${jobId}/cancel`,{method:'POST'});$('status').textContent='Stopping search and keeping returned results…';}catch(error){showError(error.message);$('cancel').disabled=false;}});
$('forget').addEventListener('click',async()=>{if(!jobId)return;try{await api('/api/jobs/'+jobId,{method:'DELETE'});clearTimeout(timer);jobId=null;current=null;signature='';sessionStorage.removeItem('osintnator-job');setBusy(false);$('search-form').reset();$('engine').value='Bing';autoSources=true;relevant();$('forget').hidden=true;$('result-tools').hidden=true;$('progress').hidden=true;$('progress-text').textContent='';$('coverage').replaceChildren();$('field-status').replaceChildren();$('lookup-progress').hidden=true;$('lookup-tasks').replaceChildren();$('cards').replaceChildren(...[...emptyState.childNodes].map(n=>n.cloneNode(true)));$('status').textContent='Session results deleted. Ready for a new search.';showError();}catch(error){showError(error.message);}});
(async()=>{try{const config=await api('/api/config');catalog=config.sources;for(const name of config.engines)$('engine').append(new Option(name,name));$('engine').value='Bing';$('retention').textContent=config.retention_minutes;renderSources();$('run').disabled=false;const stored=sessionStorage.getItem('osintnator-job');if(stored){jobId=stored;const snapshot=await api('/api/jobs/'+encodeURIComponent(stored));for(const [key,value] of Object.entries(snapshot.inputs))if($('inputs').querySelector(`[name="${key}"]`))$('inputs').querySelector(`[name="${key}"]`).value=value;autoSources=false;for(const box of $('sources').querySelectorAll('input'))box.checked=snapshot.sources.includes(box.value);sourceCount();$('engine').value=snapshot.settings.engine;$('fallback').checked=snapshot.settings.fallback;$('budget').value=snapshot.settings.lookup_budget_seconds;render(snapshot);if(!done(snapshot.state))poll(jobId);}}catch(error){if(error.status===404){sessionStorage.removeItem('osintnator-job');jobId=null;}showError(error.message);}})();

(async()=>{
  try {
    const index=await api('/api/property-directory');
    for(const state of index.states)$('property-state').append(new Option(state.name,state.code));
    const total=index.states.reduce((sum,state)=>sum+state.jurisdictions.length,0);
    $('property-directory-note').textContent=`${total.toLocaleString()} county and municipal directory entries across 50 states + DC. Directory checked ${new Date(index.checked_at).toLocaleDateString()}. Source: NETR public records directory.`;
    const updateLinks=()=>{
      $('property-links').replaceChildren();const state=index.states.find(s=>s.code===$('property-state').value);if(!state)return;
      const county=state.jurisdictions.find(c=>c.url===$('property-county').value);
      const link=safeLink(county?.url||state.url,county?`Open ${county.name} assessor / tax / recorder directory`:`Browse ${state.name} offices`);
      if(link)$('property-links').append(link);
    };
    $('property-state').addEventListener('change',()=>{
      const state=index.states.find(s=>s.code===$('property-state').value);$('property-county').replaceChildren(new Option('Choose a jurisdiction',''));$('property-county').disabled=!state;
      if(state)for(const county of state.jurisdictions)$('property-county').append(new Option(county.name,county.url));updateLinks();
    });
    $('property-county').addEventListener('change',updateLinks);
  } catch {$('property-directory-note').textContent='Directory temporarily unavailable. Try reloading the page.';}
})();
