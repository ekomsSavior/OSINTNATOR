"""Plan independent input lookups and explain coverage without treating failures as findings."""
from collections import Counter,defaultdict
from dataclasses import dataclass,replace
from query_inputs import FIELD_LABELS,search_inputs

FINDINGS={'record','candidate'}
ISSUES={'blocked','unavailable','error','timeout'}

@dataclass
class LookupTask:
    site:str
    query:object
    fields:tuple
    task_id:str

def source_fields(site,q,categories):
    if site=='LinkedIn Name Search':return ('name',)
    if site in ('Website & Linked Profiles','Domain DNS Records','Domain RDAP','VirusTotal Domain (opt-in)'):return ('domain',)
    if site in ('Email Domain Records','HaveIBeenPwned','EmailHippo','Hunter.io','Gravatar Email Profile','GitHub Email Commits'):return ('email',)
    if site in ('US Address Geography','Official Property Records','US Assessor & Tax Directory'):return ('address',) if q.address1 else ('location',)
    if site in categories.get('Obituaries & Memorials',[]):return ('name',)
    if site in ('GitHub Profile API','Bluesky Profile API','Hacker News Profile API','Username Pack (direct)','IDcrawl','Username Search','instant username search'):return ('username',)
    if site in categories.get('Reverse Phone / Address',[]) or site=='USPhoneBook':return ('phone',) if q.phone else ('address',)
    if site in categories.get('Property Records & Assessor',[]):return ('address',) if q.address1 else ('name',)
    if site in categories.get('People Search',[]) or site in categories.get('Court/Criminal/Gov',[]):return ('name',)
    if site in ('PeekYou','Social Searcher'):return ('username',) if q.username else ('name',)
    return ('other',)

def plan_lookups(sites,q,categories):
    tasks=[]
    for site in sites:
        if site=='Public Web Search':
            inputs=search_inputs(q)
            for item in inputs:
                scoped=replace(q)
                scoped.search_field=item['field']
                scoped.search_engine=getattr(q,'search_engine','DuckDuckGo')
                scoped.search_fallback=getattr(q,'search_fallback',True)
                scoped.fetch_result_pages=True
                if item['field']=='name' and item['context_fields']:
                    broad=replace(scoped)
                    broad.search_field='name'
                    broad.search_engine=scoped.search_engine
                    broad.search_fallback=scoped.search_fallback
                    broad.fetch_result_pages=True
                    broad.search_context='identifier_only'
                    tasks.append(LookupTask(site,broad,('name',),site+':name'))
                    tasks.append(LookupTask(site,scoped,('name',),site+':name_location'))
                    continue
                tasks.append(LookupTask(site,scoped,(item['field'],),site+':'+item['field']))
            if inputs: continue
        elif site=='LinkedIn Name Search' and q.first.strip() and q.last.strip():
            for context in (['identifier_only','location'] if q.city.strip() or q.state.strip() else ['identifier_only']):
                scoped=replace(q)
                scoped.search_engine=getattr(q,'search_engine','DuckDuckGo')
                scoped.search_fallback=getattr(q,'search_fallback',True)
                scoped.search_context=context
                tasks.append(LookupTask(site,scoped,('name',),site+(':name' if context=='identifier_only' else ':name_location')))
            continue
        elif site in ('GitHub Public Discovery','FastPeopleSearch','TruePeopleSearch','TruePeopleSearch.io','That’sThem','ZabaSearch','Radaris'):
            supported={'GitHub Public Discovery':('name','username','email'),'FastPeopleSearch':('name','phone','address'),
                       'TruePeopleSearch':('name','phone','address'),'TruePeopleSearch.io':('name','phone'),
                       'That’sThem':('email','phone','address'),'ZabaSearch':('name','phone'),'Radaris':('name','username')}
            mapping={'name':('first','last'),'username':('username',),'email':('email',),'phone':('phone',),'address':('address1',)}
            groups=[(label,mapping[label]) for label in supported[site]]
            for label,fields in groups:
                if not any(getattr(q,key).strip() for key in fields):continue
                location=('city','state','zip') if site!='GitHub Public Discovery' and label in ('name','address') else ()
                scoped=type(q)(**{key:getattr(q,key) for key in fields+location})
                scoped.search_engine=getattr(q,'search_engine','Bing')
                scoped.search_fallback=getattr(q,'search_fallback',True)
                tasks.append(LookupTask(site,scoped,(label,),site+':'+label))
            if any(task.site==site for task in tasks):continue
        fields=source_fields(site,q,categories)
        scoped=replace(q)
        scoped.search_engine=getattr(q,'search_engine','DuckDuckGo')
        scoped.search_fallback=getattr(q,'search_fallback',True)
        tasks.append(LookupTask(site,scoped,fields,site+':'+','.join(fields)))
    return tasks

def coverage_plan(q,tasks):
    # Values are deliberately omitted: coverage metadata need not duplicate private inputs.
    fields=[item['field'] for item in search_inputs(q)]
    if q.domain.strip() and 'domain' not in fields:fields.append('domain')
    return {field:sum(field in task.fields for task in tasks) for field in fields}

def coverage(hits,plan=None,finished=True):
    groups=defaultdict(list)
    for hit in hits:
        fields=set(hit.raw.get('input_fields',('other',)))
        if hit.raw.get('kind') in FINDINGS:fields.update(hit.raw.get('matched_inputs',()))
        for field in fields:groups[field].append(hit)
    fields=list(plan) if plan is not None else [key for key in FIELD_LABELS if key in groups]
    output={}
    for field in fields:
        rows=groups[field];counts=Counter(h.raw.get('kind','candidate') for h in rows)
        completed=len({h.raw.get('task_id',h.raw.get('source',h.site)) for h in rows if plan is None or field in h.raw.get('input_fields',())})
        total=plan.get(field,0) if plan is not None else completed
        found=sum(counts[kind] for kind in FINDINGS)
        issues=sum(counts[kind] for kind in ISSUES)
        if found:status=f'{found} finding'+('s' if found!=1 else '')
        elif not total:status='no selected collector'
        elif completed<total and not finished:status='pending'
        elif counts['cancelled']:status='cancelled'
        elif issues:status='no findings; source unavailable'
        elif counts['needs_input']:status='input/configuration needed'
        elif counts['manual']:status='manual paths only'
        elif counts['not_found']:status='no matches returned'
        elif counts['context']:status='context only'
        else:status='not completed' if finished else 'pending'
        if completed<total and not finished and found:status+='; searching'
        output[field]={'label':FIELD_LABELS.get(field,field),'status':status,'findings':found,
                       'checks':completed,'planned_checks':total,'counts':dict(counts)}
    return output

def balanced_findings(hits):
    """Round-robin input groups so a domain's many links do not bury other identifiers."""
    buckets=defaultdict(list)
    shared=[hit for hit in hits if hit.raw.get('kind') in FINDINGS and len(hit.raw.get('matched_inputs',()))>=2]
    for hit in hits:
        if hit not in shared:buckets[next(iter(hit.raw.get('input_fields',('other',))),'other')].append(hit)
    keys=[key for key in FIELD_LABELS if key in buckets]
    ordered=list(shared)
    for index in range(max((len(rows) for rows in buckets.values()),default=0)):
        for key in keys:
            if index<len(buckets[key]):ordered.append(buckets[key][index])
    return ordered
