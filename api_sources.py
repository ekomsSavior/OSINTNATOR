"""Small documented API adapters; account records are not identity matches."""
import re
from urllib.parse import quote
from datetime import datetime, timezone
import requests
from scrapers import register, OSINTHit
from query_inputs import normalize_domain, github_handle


def result(site, title, snippet, url, kind, **raw):
    return [OSINTHit(site, title, snippet, url, {"kind": kind,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **raw})]


def get_json(session, site, endpoint, page, **kwargs):
    try:
        response = session.get(endpoint, timeout=(4, 8), headers={"Accept": "application/json", "User-Agent": "OSINTNATOR/2"}, **kwargs)
        code = response.status_code
        if code == 404:
            return None, result(site, "Record not returned", "The API returned HTTP 404. This does not establish a person's identity or absence elsewhere.", page, "not_found", code=code, endpoint=endpoint)
        if code != 200:
            reason = "Rate limited; retry later." if code == 429 or (code == 403 and response.headers.get('X-RateLimit-Remaining') == '0') else "API lookup unavailable; open the source manually."
            return None, result(site, "API unavailable", reason, page, "manual", code=code, endpoint=endpoint)
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Expected an object")
        return data, None
    except (requests.RequestException, ValueError):
        return None, result(site, "API request failed", "No conclusion can be drawn. Retry or open the source manually.", page, "manual", endpoint=endpoint)


@register("GitHub Profile API")
def github_profile(session, q):
    site = "GitHub Profile API"
    try:
        user, derived = github_handle(q.username)
    except ValueError as exc:
        return result(site, 'GitHub handle needed', str(exc), 'https://github.com/', 'needs_input')
    page = "https://github.com/" + quote(user, safe="")
    endpoint = "https://api.github.com/users/" + quote(user, safe="")
    data, failure = get_json(session, site, endpoint, page)
    if failure: return failure
    if str(data.get('login', '')).casefold() != user.casefold() or not isinstance(data.get('id'), int):
        return result(site, "Unexpected API record", "The returned login did not match the requested username; review manually.", page, "manual", endpoint=endpoint)
    fields = {key:data.get(key) for key in ('login','id','name','bio','email','location','blog','company','twitter_username','public_repos','created_at','updated_at') if data.get(key) is not None}
    snippet = ' | '.join(f'{key}: {value}' for key,value in fields.items())
    if derived: snippet='Candidate handle formed by removing spaces from the input. '+snippet
    hits = result(site, 'GitHub: '+data['login'], snippet, page, 'candidate' if derived else 'record',
                  endpoint=endpoint, account_id=data['id'], identity_verified=False, fields=fields,
                  input_username=q.username, matched_handle=user, derived_handle=derived,
                  subject_url=endpoint, entity_type='url', entity_value=page, relationship='returned_profile')
    blog=data.get('blog') or ''
    if blog:
        try:
            domain=normalize_domain(blog)
            link=blog if blog.startswith(('http://','https://')) else 'https://'+domain
            hits.extend(result(site,'Website published by '+data['login'],link,link,'record',
                               subject_url=page,source_url=page,entity_type='url',entity_value=link,
                               relationship='profile_links_to',identity_verified=False))
        except ValueError: pass
    return hits


@register("Bluesky Profile API")
def bluesky_profile(session, q):
    site = "Bluesky Profile API"
    handle = q.username.strip().lstrip('@').lower()
    page = "https://bsky.app/profile/" + quote(handle, safe="")
    if not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", handle):
        return result(site, "Enter a full Bluesky handle", "For example bsky.app or example.bsky.social. A bare username is ambiguous.", "https://bsky.app/", "needs_input")
    endpoint = "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile"
    data, failure = get_json(session, site, endpoint, page, params={"actor": handle})
    if failure: return failure
    if data.get('handle', '').lower() != handle or not str(data.get('did', '')).startswith('did:'):
        return result(site, "Unexpected API record", "The response does not match this handle; review manually.", page, "manual", endpoint=endpoint)
    return result(site, "Public profile record returned", f"Handle: {handle} | DID: {data['did']} | Name: {data.get('displayName', '')} | {data.get('description', '')}", page, "record", endpoint=endpoint, did=data['did'], identity_verified=False)


@register("Domain RDAP")
def domain_rdap(session, q):
    site = "Domain RDAP"
    try:
        domain = normalize_domain(q.domain)
    except ValueError as exc:
        return result(site, "Domain needed", str(exc), "https://lookup.icann.org/", "needs_input")
    endpoint = "https://rdap.org/domain/" + domain
    data, failure = get_json(session, site, endpoint, "https://lookup.icann.org/")
    if failure: return failure
    if data.get('objectClassName') != 'domain' or data.get('ldhName', '').lower() != domain:
        return result(site, "Unexpected RDAP record", "No matching domain object was returned.", endpoint, "manual")
    events = '; '.join(f"{e.get('eventAction')}: {e.get('eventDate')}" for e in data.get('events', []) if isinstance(e, dict))
    nameservers = ', '.join(n.get('ldhName', '') for n in data.get('nameservers', []) if isinstance(n, dict))
    return result(site, f"Registration record: {domain}", f"{events} | Nameservers: {nameservers}. Registration fields may be redacted.", endpoint, "record", endpoint=endpoint, identity_verified=False)


@register("VirusTotal Domain (opt-in)")
def virustotal_domain(session, q):
    import os
    site = "VirusTotal Domain (opt-in)"
    try:
        domain = normalize_domain(q.domain)
    except ValueError as exc:
        return result(site, "Domain needed", str(exc), "https://www.virustotal.com/", "needs_input")
    page = "https://www.virustotal.com/gui/domain/" + domain
    key = os.environ.get('VIRUSTOTAL_API_KEY', '').strip()
    if not key or os.environ.get('OSINTNATOR_VT_ENABLE') != '1':
        return result(site, "Optional integration is disabled",
                      "VirusTotal says queried indicators can be scanned and added to its community dataset. For public domains only: review provider terms, then set VIRUSTOTAL_API_KEY and OSINTNATOR_VT_ENABLE=1 to opt in. Keys are not saved in UI settings.",
                      "https://docs.virustotal.com/reference/domain-info", "needs_input")
    endpoint = "https://www.virustotal.com/api/v3/domains/" + domain
    try:
        response = session.get(endpoint, timeout=(4,8), headers={'x-apikey':key, 'Accept':'application/json'})
        if response.status_code != 200:
            return result(site, "Report unavailable", f"HTTP {response.status_code}. Check access and provider quota; this is not a clean verdict.", page, "manual", code=response.status_code)
        data = response.json().get('data', {})
        if data.get('type') != 'domain' or data.get('id', '').lower() != domain:
            raise ValueError('Unexpected domain response')
        attrs = data.get('attributes', {})
        stats = attrs.get('last_analysis_stats', {})
        timestamp = attrs.get('last_analysis_date')
        observed = datetime.fromtimestamp(timestamp,timezone.utc).isoformat() if isinstance(timestamp,(int,float)) else 'not supplied'
        counts = ', '.join(f'{key}: {value}' for key,value in stats.items())
        return result(site, f"Domain reputation report: {domain}",
                      f"Provider analysis time: {observed}. {counts}. Detection counts are provider observations, not a definitive safety verdict.",
                      page, "record", endpoint=endpoint, provider_analysis_at=observed)
    except (requests.RequestException, ValueError, TypeError, AttributeError, OverflowError):
        return result(site, "Report request failed", "Retry later or review the report manually; no safety conclusion can be drawn.", page, "manual")
