# datasets.py
# Simple "free public datasets" helpers for Osintnator
# - Wayback CDX (snapshots)
# - crt.sh (cert transparency lookup)
# - construct helper search links (GitHub, search engine dorks)
# Returns results as lightweight dicts compatible with OSINTHit

import requests
import time
from typing import List, Dict, Any, Optional
from urllib.parse import quote_plus

# small polite default timeout & UA
REQUEST_TIMEOUT = 12
HEADERS = {"User-Agent": "osintnator-dataset-client/1.0 (+https://github.com/ekomsSavior)"}

# Limit how many snapshots / certs we return per site
MAX_WAYBACK = 6
MAX_CRT = 6

def _safe_get(url: str, params: dict = None, timeout: int = REQUEST_TIMEOUT) -> Optional[requests.Response]:
    try:
        return requests.get(url, params=params, headers=HEADERS, timeout=timeout)
    except Exception:
        return None

def find_wayback_snapshots(domain_or_url: str, limit: int = MAX_WAYBACK) -> List[Dict[str, Any]]:
    """
    Query Wayback CDX for recent snapshots for domain_or_url.
    Returns list of dicts: {"title": "...", "snippet": "...", "url": snapshot_url, "raw": {...}}
    """
    out = []
    if not domain_or_url:
        return out
    # make a domain-based pattern if only domain given
    query_url = "http://web.archive.org/cdx/search/cdx"
    params = {
        "url": f"{domain_or_url}/*",
        "output": "json",
        "filter": "statuscode:200",
        "limit": str(limit),
        "from": "1996",
        "collapse": "digest"  # try to reduce duplicates
    }
    r = _safe_get(query_url, params=params)
    if not r or r.status_code != 200:
        return out
    try:
        arr = r.json()  # CDX JSON returns array: first row is field names
        if not isinstance(arr, list) or len(arr) < 2:
            return out
        fields = arr[0]  # e.g. ["urlkey","timestamp","original","mimetype","statuscode","digest","length"]
        for row in arr[1:]:
            rec = dict(zip(fields, row))
            ts = rec.get("timestamp")
            orig = rec.get("original")
            snap_url = f"https://web.archive.org/web/{ts}/{orig}"
            title = f"Wayback snapshot — {ts}"
            snippet = orig
            out.append({"site": "Wayback", "title": title, "snippet": snippet, "url": snap_url, "raw": rec})
    except Exception:
        # fallback: try to parse lines if it wasn't JSON
        text = r.text or ""
        for line in text.strip().splitlines()[:limit]:
            parts = line.split()
            if len(parts) >= 3:
                ts = parts[1]
                orig = parts[2]
                snap_url = f"https://web.archive.org/web/{ts}/{orig}"
                out.append({"site": "Wayback", "title": f"Wayback snapshot — {ts}", "snippet": orig, "url": snap_url, "raw": {"line": line}})
    return out[:limit]


def find_crtsh_certificates(domain: str, limit: int = MAX_CRT) -> List[Dict[str, Any]]:
    """
    Query crt.sh JSON API for certificates relating to domain.
    Returns dicts: {"site": "crt.sh", "title": "...", "snippet": "...", "url": crtsh_entry_url, "raw": {...}}
    """
    out = []
    if not domain:
        return out
    q = f"%.{domain}" if "." in domain else domain
    url = "https://crt.sh/"
    params = {"q": q, "output": "json"}
    r = _safe_get(url, params=params)
    if not r or r.status_code != 200:
        return out
    try:
        arr = r.json()
    except Exception:
        return out
    seen_ids = set()
    for rec in arr:
        # some recs have 'min_cert_id'
        cert_id = rec.get("min_cert_id") or rec.get("id") or rec.get("cert_id")
        if not cert_id or cert_id in seen_ids:
            continue
        seen_ids.add(cert_id)
        name = rec.get("common_name") or rec.get("name_value") or rec.get("entry")
        issued = rec.get("not_before") or rec.get("logged_at") or ""
        url_entry = f"https://crt.sh/?id={cert_id}"
        title = f"Certificate: {name} — {issued}"
        snippet = f"cert id={cert_id} name_value={rec.get('name_value')}"
        out.append({"site": "crt.sh", "title": title, "snippet": snippet, "url": url_entry, "raw": rec})
        if len(out) >= limit:
            break
    return out


def construct_search_links_for_site(site_label: str, site_domain: str, q: dict) -> List[Dict[str, Any]]:
    """
    Build handy search links you can present in the UI as 'quick lookups'.
    q is the query dict: {first,last,username,email,phone,address1,city,state,zip}
    """
    out = []
    # construct a full-name token if present
    fullname = " ".join([q.get("first","").strip(), q.get("last","").strip()]).strip()
    tokens = []
    if fullname: tokens.append(f"\"{fullname}\"")
    if q.get("username"): tokens.append(q.get("username"))
    if q.get("email"): tokens.append(q.get("email"))
    if q.get("phone"): tokens.append("".join([c for c in q.get("phone","") if c.isdigit()]))
    # 1) search engine site:dork
    if site_domain:
        dork = " ".join([f"site:{site_domain}"] + tokens) if tokens else f"site:{site_domain}"
    else:
        dork = " ".join(tokens) if tokens else site_label
    # engine links
    engines = {
        "DuckDuckGo": "https://duckduckgo.com/?q=",
        "Google": "https://www.google.com/search?q=",
        "Bing": "https://www.bing.com/search?q=",
        "GitHub code": "https://github.com/search?q="
    }
    for name, base in engines.items():
        qstr = quote_plus(dork) if name != "GitHub code" else quote_plus(" ".join(tokens))
        out.append({"site": "Search Link", "title": f"{name} search", "snippet": dork, "url": base + qstr, "raw": {"engine": name}})
    # Common Crawl / BigQuery hint (not auto-run)
    out.append({"site": "Hint", "title": "Common Crawl (index) / BigQuery hint", "snippet": "Use Common Crawl index or BigQuery to fetch page text; BigQuery can be queried from console", "url": "https://commoncrawl.org/"})
    return out


def search_for_site(site_label: str, site_domain: str, qdict: dict) -> List[Dict[str, Any]]:
    """
    High-level convenience function: run dataset lookups relevant to the site and return OSINTHit-like dicts.
    - site_domain is from SITE_DOMAIN map, may be None
    - qdict is query dict (first,last,username,email,phone,...)
    """
    results = []
    # 1) Wayback for domain
    if site_domain:
        wb = find_wayback_snapshots(site_domain, limit=4)
        for r in wb:
            # mark site as dataset-originated
            r["site"] = f"{site_label} (Wayback)"
            results.append(r)
    else:
        # fallback: try wayback for site_label directly (some entries in SITE_URL)
        pass

    # 2) Certificates (crt.sh) — discover subdomains
    if site_domain and "." in site_domain:
        certs = find_crtsh_certificates(site_domain, limit=4)
        for c in certs:
            c["site"] = f"{site_label} (crt.sh)"
            results.append(c)

    # 3) helpful search links (GitHub, engine dorks)
    links = construct_search_links_for_site(site_label, site_domain, qdict)
    for l in links:
        l["site"] = f"{site_label} (Search link)"
        results.append(l)

    return results


def search_sites_for_query(sites: List[Dict[str, str]], qdict: dict) -> List[Dict[str, Any]]:
    """
    sites: list of dicts {"label": "...", "domain": "..."}
    qdict: query dict
    Returns aggregated results.
    """
    out = []
    for s in sites:
        label = s.get("label")
        dom = s.get("domain")
        try:
            hits = search_for_site(label, dom, qdict)
            if hits:
                out.extend(hits)
            # polite pause to avoid hammering crt.sh / Wayback
            time.sleep(0.5)
        except Exception:
            continue
    return out
