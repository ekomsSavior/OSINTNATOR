# scrapers.py — lightweight, robust, no-Playwright required
from typing import List, Dict, Any, Callable
from dataclasses import dataclass
from urllib.parse import quote_plus
import random
import time
import re
import os
import logging
import pathlib

import requests
from bs4 import BeautifulSoup  # kept for future selectors

# Optional Cloudflare helper (auto if available)
try:
    import cloudscraper
    HAVE_CLOUD = True
except Exception:
    HAVE_CLOUD = False

# requests retry helpers
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ======================= Config & Logging =======================
DEFAULT_TIMEOUT = 12
# Trim retries to avoid duplicate log noise; never retry on 4xx
DEFAULT_RETRIES = 1
MIN_JITTER = 0.15       # polite tiny delay before each request
MAX_JITTER = 0.45

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.6533.88 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.6478.127 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.6478.127 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.6478.122 Mobile Safari/537.36",
]

LOG_DIR = pathlib.Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "scrapers.log"

# Basic logging; optionally mirror to console when debug env var set
logging.basicConfig(
    filename=str(LOG_PATH),
    filemode="a",
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("scrapers")

if os.environ.get("OSINTNATOR_DEBUG", "0") == "1":
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    ch.setLevel(logging.DEBUG)
    log.addHandler(ch)
    log.setLevel(logging.DEBUG)

# ======================= Types & Registry =======================
@dataclass
class OSINTQuery:
    first: str = ""; last: str = ""; username: str = ""; email: str = ""; phone: str = ""
    address1: str = ""; city: str = ""; state: str = ""; zip: str = ""
    @property
    def full_name(self) -> str:
        parts = [self.first.strip(), self.last.strip()]
        return " ".join([p for p in parts if p])

@dataclass
class OSINTHit:
    site: str
    title: str
    snippet: str
    url: str
    raw: Dict[str, Any]

Scraper = Callable[[requests.Session, OSINTQuery], List[OSINTHit]]
SCRAPERS: Dict[str, Scraper] = {}

def register(site: str):
    def deco(fn: Scraper):
        SCRAPERS[site] = fn
        log.debug(f"registered scraper: {site}")
        return fn
    return deco

# ======================= Session & Fetch Helpers =======================
def _build_retry_adapter(total=DEFAULT_RETRIES):
    # Don’t retry on 4xx; do backoff for 429/5xx only
    retry = Retry(
        total=total,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
    )
    return HTTPAdapter(max_retries=retry)

def get_session() -> requests.Session:
    """Return a configured Session (or cloudscraper) with retries."""
    if HAVE_CLOUD:
        s = cloudscraper.create_scraper()
    else:
        s = requests.Session()

    s.headers.update({
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Connection": "keep-alive",
    })

    adapter = _build_retry_adapter()
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s

def _maybe_rendered_copy(url: str) -> str:
    """
    Optional remote rendering to bypass heavy JS:
    export OSINTNATOR_REMOTE_RENDER=1
    """
    if os.environ.get("OSINTNATOR_REMOTE_RENDER", "0") != "1":
        return ""
    # r.jina.ai serves a prerendered copy; good for CF/js heavy pages
    render_url = f"https://r.jina.ai/http://{url.replace('https://','').replace('http://','')}"
    try:
        r = requests.get(render_url, timeout=DEFAULT_TIMEOUT, headers={"User-Agent": random.choice(UA_POOL)})
        if r.status_code < 400 and len(r.text) > 80:
            return r.text
    except Exception as e:
        log.debug(f"remote-render failed for {url}: {e}")
    return ""

def _looks_js_blocked(html: str) -> bool:
    s = (html or "").lower()
    return any(k in s for k in [
        "enable javascript", "requires javascript", "please enable js",
        "captcha", "cf-chl", "cloudflare", "challenge-form"
    ])

def _http_error_snippet(resp: requests.Response) -> str:
    try:
        body = re.sub(r"\s+", " ", resp.text)[:200] if getattr(resp, "text", None) else ""
        return f"{resp.status_code} :: {body}"
    except Exception:
        return f"{resp.status_code} :: <no body>"

def _log_http(resp: requests.Response, url: str, context: str):
    code = getattr(resp, "status_code", 0)
    snippet = _http_error_snippet(resp)
    # Demote 4xx (esp. 404) to DEBUG to avoid noise
    if 400 <= code < 500:
        log.debug(f"HTTP {snippet} for {url} {context}")
    else:
        log.info(f"HTTP {snippet} for {url} {context}")

def _fetch(sess: requests.Session, url: str, method: str = "GET", **kwargs) -> requests.Response:
    time.sleep(random.uniform(MIN_JITTER, MAX_JITTER))
    headers = kwargs.pop("headers", {})
    headers = {**headers, "User-Agent": random.choice(UA_POOL)}
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)

    try:
        if method.upper() == "GET":
            r = sess.get(url, headers=headers, **kwargs)
        else:
            r = sess.post(url, headers=headers, **kwargs)
        if r.status_code >= 400:
            _log_http(r, url, "(GET/POST)")
        if _looks_js_blocked(getattr(r, "text", "")):
            rendered = _maybe_rendered_copy(url)
            if rendered:
                r._content = rendered.encode("utf-8", errors="ignore")
        return r
    except Exception as e:
        log.warning(f"Request failed for {url}: {e}")
        raise

def _head_or_get(sess: requests.Session, url: str, **kwargs) -> requests.Response:
    time.sleep(random.uniform(MIN_JITTER, MAX_JITTER))
    headers = kwargs.pop("headers", {})
    headers = {**headers, "User-Agent": random.choice(UA_POOL)}
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    try:
        r = sess.head(url, headers=headers, allow_redirects=True, **kwargs)
        if r.status_code in (405, 403) or not getattr(r, "text", ""):
            r = sess.get(url, headers=headers, allow_redirects=True, **kwargs)
        if r.status_code >= 400:
            _log_http(r, url, "(HEAD/GET)")
        if _looks_js_blocked(getattr(r, "text", "")):
            rendered = _maybe_rendered_copy(url)
            if rendered:
                r._content = rendered.encode("utf-8", errors="ignore")
        return r
    except Exception as e:
        log.warning(f"HEAD/GET failed for {url}: {e}")
        raise

def probe_site_for_terms(sess: requests.Session, base_site: str, q: OSINTQuery,
                         probes: List[str], max_hits: int = 2) -> List[OSINTHit]:
    """
    GET a set of probe URLs; mark a hit if any of the query tokens appear in HTML <title> or body.
    """
    tokens = []
    if q.username: tokens.append(q.username.lower())
    if q.full_name: tokens.extend([p.lower() for p in q.full_name.split() if p])
    if q.email: tokens.append(q.email.lower())
    if q.phone:
        d = "".join(c for c in q.phone if c.isdigit())
        if d: tokens.append(d)

    if not tokens:
        return []

    hits: List[OSINTHit] = []
    for tmpl in probes:
        url = tmpl.format(
            username=quote_plus(q.username or ""),
            first=quote_plus(q.first or ""),
            last=quote_plus(q.last or ""),
            email=quote_plus(q.email or ""),
            phone=quote_plus("".join(c for c in q.phone if c.isdigit()))
        )
        try:
            r = _fetch(sess, url)
            if r.status_code >= 400 or not getattr(r, "text", ""):
                continue
            body = (r.text or "")
            body_lower = body.lower()
            found = any(tok in body_lower for tok in tokens if tok)
            title = ""
            try:
                m = re.search(r"<title[^>]*>([^<]+)</title>", body, flags=re.I | re.S)
                if m: title = m.group(1).strip().lower()
            except Exception:
                pass
            if found or (q.username and q.username.lower() in (title or "")):
                snippet = re.sub(r"\s+", " ", body)[:300]
                hits.append(OSINTHit(base_site, f"probe → {url}", snippet, url, {"probed": True}))
                if len(hits) >= max_hits:
                    break
        except Exception as e:
            log.debug(f"probe failed {url}: {e}")
            continue
    return hits

def _mk_negative(site: str, url: str, reason: str, code: int | None = None) -> OSINTHit:
    snip = f"{reason}" + (f" (HTTP {code})" if code else "")
    return OSINTHit(site, f"{site}: not found", snip, url, {"exists": False, "reason": reason, "code": code})

# ---------- Username normalization helpers ----------
def _norm_user_for(service: str, u: str) -> str:
    """
    Some sites are case-sensitive in path routing; normalize where appropriate.
    """
    if not u:
        return u
    lower_sites = {
        "SoundCloud", "Dev.to", "ProductHunt", "Behance", "Flickr",
        "Kaggle", "Keybase", "GitLab", "Medium", "Pinterest",
        "Twitch", "Instagram", "Twitter/X",
    }
    if service in lower_sites:
        return u.lower()
    # YouTube handles are case-insensitive; keep as-is (but lower doesn’t hurt)
    if service == "YouTube":
        return u.lower()
    return u

# ======================= Site-Specific Scrapers =======================
@register("Username Pack (direct)")
def scrape_username_pack(sess: requests.Session, q: OSINTQuery) -> List[OSINTHit]:
    if not q.username:
        return []
    u_input = q.username
    services = [
        ("GitHub",        lambda u: f"https://github.com/{u}",                     r'<title>[^<]*?github[^<]*', True),
        ("Reddit",        lambda u: f"https://www.reddit.com/user/{u}",            r'/user/[^/]+', True),
        ("TikTok",        lambda u: f"https://www.tiktok.com/@{u}",                r'@'+re.escape(u_input.lower()), True),
        ("Twitch",        lambda u: f"https://www.twitch.tv/{u}",                  r'twitch', False),
        ("Pinterest",     lambda u: f"https://www.pinterest.com/{u}/",             r'pinterest', False),
        ("Steam",         lambda u: f"https://steamcommunity.com/id/{u}",          r'steam', False),
        ("Steam (prof)",  lambda u: f"https://steamcommunity.com/profiles/{u}",    r'steam', False),
        ("SoundCloud",    lambda u: f"https://soundcloud.com/{u}",                 r'soundcloud', False),
        ("Medium",        lambda u: f"https://medium.com/@{u}",                    r'medium', False),
        ("Dev.to",        lambda u: f"https://dev.to/{u}",                         r'dev\.to', False),
        ("Keybase",       lambda u: f"https://keybase.io/{u}",                     r'keybase', False),
        ("GitLab",        lambda u: f"https://gitlab.com/{u}",                     r'gitlab', False),
        ("Kaggle",        lambda u: f"https://www.kaggle.com/{u}",                 r'kaggle', False),
        ("Flickr",        lambda u: f"https://www.flickr.com/people/{u}/",         r'flickr', False),
        ("Gravatar",      lambda u: f"https://en.gravatar.com/{u}",                r'gravatar', False),
        ("YouTube",       lambda u: f"https://www.youtube.com/@{u}",               r'youtube', False),
        ("Behance",       lambda u: f"https://www.behance.net/{u}",                r'behance', False),
        ("ProductHunt",   lambda u: f"https://www.producthunt.com/@{u}",           r'product hunt|producthunt', False),
        ("HackerNews",    lambda u: f"https://news.ycombinator.com/user?id={u}",   r'created|about:', False),
        ("StackOverflow", lambda u: f"https://stackoverflow.com/users/{u}",        r'profile|Stack Overflow', False),
        ("Instagram",     lambda u: f"https://www.instagram.com/{u}/",             r'instagram', False),
        ("Twitter/X",     lambda u: f"https://x.com/{u}",                          r'x\.com|twitter', False),
        ("Facebook",      lambda u: f"https://www.facebook.com/{u}",               r'facebook', False),
        ("LinkedIn",      lambda u: f"https://www.linkedin.com/in/{u}/",           r'linkedin', False),
    ]

    hits: List[OSINTHit] = []
    positives = 0

    for name, url_fn, verify_re, must_contain in services:
        try:
            norm_u = _norm_user_for(name, u_input)
            url = url_fn(norm_u)
            r = _head_or_get(sess, url)
            code = getattr(r, "status_code", 0)
            if code == 200:
                body = (r.text or "").lower()
                ok = True
                if must_contain:
                    ok = bool(re.search(verify_re, body, flags=re.I))
                if ok:
                    snip = re.sub(r"\s+", " ", body)[:220] if body else ""
                    hits.append(OSINTHit(f"{name}", f"{name}: found", snip, url, {"exists": True, "code": code}))
                    positives += 1
                else:
                    hits.append(_mk_negative(name, url, "page loaded but pattern not found", code))
            elif code in (301, 302, 303, 307, 308):
                # follow redirect with GET
                r2 = _fetch(sess, url)
                body = (r2.text or "").lower()
                ok = r2.status_code < 400 and (not must_contain or re.search(verify_re, body, flags=re.I))
                if ok:
                    hits.append(OSINTHit(f"{name}", f"{name}: found", re.sub(r"\s+"," ",body)[:220], url, {"exists": True, "code": r2.status_code}))
                    positives += 1
                else:
                    hits.append(_mk_negative(name, url, "redirect but no profile", r2.status_code))
            elif code == 404:
                hits.append(_mk_negative(name, url, "not found", 404))
            else:
                # e.g., 403, 429, 5xx
                hits.append(_mk_negative(name, url, "request failed", code))
        except Exception as e:
            log.debug(f"Username pack fail {name} {url_fn(u_input)}: {e}")
            hits.append(_mk_negative(name, url_fn(u_input), "error", None))

        # keep it snappy; stop after a handful of positives
        if positives >= 8:
            break

    if positives:
        summary = f"{positives} service(s) matched for @{u_input}"
        hits.insert(0, OSINTHit("Username Pack (direct)", summary, "; ".join(h.site for h in hits if h.raw.get("exists"))[:300], "#", {"exists": True, "count": positives}))
    else:
        hits.insert(0, OSINTHit("Username Pack (direct)", f"No matches for @{u_input}", "Checked major platforms", "#", {"exists": False}))
    return hits

# ---------- OSINT sites from your tabs ----------
@register("HaveIBeenPwned")
def scrape_hibp(sess: requests.Session, q: OSINTQuery) -> List[OSINTHit]:
    """
    Requires HIBP_API_KEY env for real data. Uses email OR username (account).
    HIBP enforces rate limits; we sleep a bit to be polite.
    """
    api = os.environ.get("HIBP_API_KEY", "").strip()
    acct = (q.email or q.username or "").strip()
    if not api or not acct:
        return []
    time.sleep(1.7)
    url = f"https://haveibeenpwned.com/api/v3/breachedaccount/{quote_plus(acct)}?truncateResponse=true"
    try:
        r = sess.get(url, headers={
            "hibp-api-key": api,
            "User-Agent": random.choice(UA_POOL),
            "Accept": "application/json"
        }, timeout=DEFAULT_TIMEOUT)
        if r.status_code == 404:
            log.debug("HaveIBeenPwned: 0 hits (404)")
            return []
        if r.status_code >= 400:
            log.debug(f"HaveIBeenPwned error {r.status_code}")
            return []
        breaches = r.json() if r.text.strip() else []
        hits = []
        for b in breaches[:10]:
            name = b.get("Name") or "Breach"
            dom = b.get("Domain") or "haveibeenpwned.com"
            url_b = f"https://haveibeenpwned.com/account/{quote_plus(acct)}"
            hits.append(OSINTHit("HaveIBeenPwned", f"HIBP: {name}", f"Domain: {dom}", url_b, {"exists": True}))
        return hits
    except Exception as e:
        log.debug(f"HIBP failed: {e}")
        return []

@register("IDcrawl")
def scrape_idcrawl(sess: requests.Session, q: OSINTQuery) -> List[OSINTHit]:
    if not q.username:
        return []
    base = "IDcrawl"
    probes = [
        f"https://idcrawl.com/username-search/{quote_plus(q.username)}",
        f"https://idcrawl.com/username-search?username={quote_plus(q.username)}",
        f"https://idcrawl.com/search/?q={quote_plus(q.username)}",
    ]
    return probe_site_for_terms(sess, base, q, probes, max_hits=3)

@register("Username Search")
def scrape_usersearch_org(sess: requests.Session, q: OSINTQuery) -> List[OSINTHit]:
    if not q.username:
        return []
    base = "Username Search"
    probes = [
        f"https://usersearch.org/results/?username={quote_plus(q.username)}",
        f"https://usersearch.org/search/{quote_plus(q.username)}",
    ]
    return probe_site_for_terms(sess, base, q, probes, max_hits=2)

@register("Social Searcher")
def scrape_social_searcher(sess: requests.Session, q: OSINTQuery) -> List[OSINTHit]:
    term = (q.username or q.full_name or q.email or "").strip()
    if not term:
        return []
    base = "Social Searcher"
    probes = [
        f"https://social-searcher.com/social-search/?q={quote_plus(term)}",
        f"https://social-searcher.com/reports?query={quote_plus(term)}",
    ]
    return probe_site_for_terms(sess, base, q, probes, max_hits=2)

@register("PeekYou")
def scrape_peekyou(sess: requests.Session, q: OSINTQuery) -> List[OSINTHit]:
    base = "PeekYou"
    probes = []
    if q.username:
        probes.append(f"https://www.peekyou.com/{quote_plus(q.username)}")
    if q.full_name:
        nm = quote_plus(q.full_name)
        probes.append(f"https://www.peekyou.com/usa/{nm}")
    return probe_site_for_terms(sess, base, q, probes or [], max_hits=2)

@register("instant username search")
def scrape_instantusername(sess: requests.Session, q: OSINTQuery) -> List[OSINTHit]:
    if not q.username:
        return []
    base = "instant username search"
    probes = [f"https://instantusername.com/#/{quote_plus(q.username)}"]
    return probe_site_for_terms(sess, base, q, probes, max_hits=1)

@register("USPhoneBook")
def scrape_usphonebook(sess: requests.Session, q: OSINTQuery) -> List[OSINTHit]:
    if not q.phone:
        return []
    d = "".join(c for c in q.phone if c.isdigit())
    if not d:
        return []
    base = "USPhoneBook"
    probes = [
        f"https://www.usphonebook.com/{d}",
        f"https://www.usphonebook.com/search?number={d}",
    ]
    return probe_site_for_terms(sess, base, q, probes, max_hits=2)

@register("WhoCallsMe")
def scrape_whocallsme(sess: requests.Session, q: OSINTQuery) -> List[OSINTHit]:
    if not q.phone:
        return []
    d = "".join(c for c in q.phone if c.isdigit())
    if not d:
        return []
    base = "WhoCallsMe"
    probes = [f"https://whocallsme.com/Phone-Number.aspx/{d}"]
    return probe_site_for_terms(sess, base, q, probes, max_hits=1)

@register("FamilyTreeNow")
def scrape_familytreenow(sess: requests.Session, q: OSINTQuery) -> List[OSINTHit]:
    if not (q.first or q.last):
        return []
    base = "FamilyTreeNow"
    probes = [(
        "https://www.familytreenow.com/search/genealogy/results?"
        f"first={quote_plus(q.first)}&last={quote_plus(q.last)}"
        f"&city={quote_plus(q.city)}&state={quote_plus(q.state)}"
    )]
    return probe_site_for_terms(sess, base, q, probes, max_hits=1)

@register("FastPeopleSearch")
def scrape_fastpeoplesearch(sess: requests.Session, q: OSINTQuery) -> List[OSINTHit]:
    base = "FastPeopleSearch"
    probes = []
    if q.first or q.last or q.city or q.state:
        name_slug = quote_plus((q.first + " " + q.last).strip()).replace("%20", "-")
        area = quote_plus((q.city or q.state or "").strip())
        probes.append(f"https://www.fastpeoplesearch.com/name/{name_slug}/{area}")
    if q.address1:
        probes.append(f"https://www.fastpeoplesearch.com/address/{quote_plus(q.address1)}")
    if q.phone:
        d = "".join(c for c in q.phone if c.isdigit())
        if d:
            probes.append(f"https://www.fastpeoplesearch.com/phone/{d}")
    return probe_site_for_terms(sess, base, q, probes or [], max_hits=2)

@register("TruePeopleSearch")
def scrape_truepeoplesearch(sess: requests.Session, q: OSINTQuery) -> List[OSINTHit]:
    base = "TruePeopleSearch"
    probes = []
    if q.first or q.last:
        probes.append(
            "https://www.truepeoplesearch.com/results?"
            f"name={quote_plus((q.first + ' ' + q.last).strip())}"
            f"&citystatezip={quote_plus((q.city or q.state or q.zip or '').strip())}"
        )
    if q.phone:
        d = "".join(c for c in q.phone if c.isdigit())
        if d:
            probes.append(f"https://www.truepeoplesearch.com/results?phoneno={d}")
    if q.address1:
        probes.append(
            "https://www.truepeoplesearch.com/results?"
            f"streetaddress={quote_plus(q.address1)}&citystatezip={quote_plus(q.city or q.state or q.zip)}"
        )
    return probe_site_for_terms(sess, base, q, probes or [], max_hits=2)

@register("TruePeopleSearch.io")
def scrape_truepeoplesearch_io(sess: requests.Session, q: OSINTQuery) -> List[OSINTHit]:
    base = "TruePeopleSearch.io"
    probes = []
    if q.first or q.last:
        probes.append(
            "https://truepeoplesearch.io/search?"
            f"name={quote_plus((q.first + ' ' + q.last).strip())}&state={quote_plus(q.state)}"
        )
    if q.phone:
        d = "".join(c for c in q.phone if c.isdigit())
        if d:
            probes.append(f"https://truepeoplesearch.io/phone/{d}")
    return probe_site_for_terms(sess, base, q, probes or [], max_hits=2)

@register("FastBackgroundCheck")
def scrape_fastbackgroundcheck(sess: requests.Session, q: OSINTQuery) -> List[OSINTHit]:
    base = "FastBackgroundCheck"
    probes = []
    if q.first or q.last:
        probes.append(
            "https://www.fastbackgroundcheck.com/people/"
            f"{quote_plus((q.first + '-' + q.last).strip())}/"
            f"{quote_plus((q.state or '').lower())}"
        )
    return probe_site_for_terms(sess, base, q, probes or [], max_hits=1)

@register("ZabaSearch")
def scrape_zabasearch(sess: requests.Session, q: OSINTQuery) -> List[OSINTHit]:
    base = "ZabaSearch"
    probes = []
    if q.first or q.last:
        probes.append(
            "https://www.zabasearch.com/people/"
            f"{quote_plus((q.first + ' ' + q.last).strip())}/{quote_plus(q.state or '')}/"
        )
    if q.phone:
        d = "".join(c for c in q.phone if c.isdigit())
        if d:
            probes.append(f"https://www.zabasearch.com/phone/{d}/")
    return probe_site_for_terms(sess, base, q, probes or [], max_hits=2)

@register("Radaris")
def scrape_radaris(sess: requests.Session, q: OSINTQuery) -> List[OSINTHit]:
    base = "Radaris"
    probes = []
    if q.first or q.last:
        probes.append("https://radaris.com/p/%s/%s" % (quote_plus(q.first), quote_plus(q.last)))
    if q.username:
        probes.append(f"https://radaris.com/p/{quote_plus(q.username)}")
    return probe_site_for_terms(sess, base, q, probes or [], max_hits=1)

@register("That’sThem")
def scrape_thatsthem(sess: requests.Session, q: OSINTQuery) -> List[OSINTHit]:
    base = "That’sThem"
    probes = []
    if q.email:
        probes.append(f"https://thatsthem.com/email/{quote_plus(q.email)}")
    if q.phone:
        d = "".join(c for c in q.phone if c.isdigit())
        if d:
            probes.append(f"https://thatsthem.com/phone/{d}")
    if q.address1:
        probes.append(f"https://thatsthem.com/address/{quote_plus(q.address1)}-{quote_plus(q.city)}-{quote_plus(q.state)}")
    return probe_site_for_terms(sess, base, q, probes or [], max_hits=2)

@register("EmailHippo")
def scrape_emailhippo(sess: requests.Session, q: OSINTQuery) -> List[OSINTHit]:
    if not q.email:
        return []
    base = "EmailHippo"
    probes = [f"https://tools.emailhippo.com/EmailHippo/verify?email={quote_plus(q.email)}"]
    return probe_site_for_terms(sess, base, q, probes, max_hits=1)

@register("Hunter.io")
def scrape_hunter(sess: requests.Session, q: OSINTQuery) -> List[OSINTHit]:
    base = "Hunter.io"
    probes = []
    if q.email:
        probes.append(f"https://hunter.io/verify/{quote_plus(q.email)}")
    domain = q.email.split("@")[1] if q.email and "@" in q.email else ""
    if domain:
        probes.append(f"https://hunter.io/try/{quote_plus(domain)}")
    return probe_site_for_terms(sess, base, q, probes or [], max_hits=1)

@register("BlackBookOnline")
def scrape_blackbookonline(sess: requests.Session, q: OSINTQuery) -> List[OSINTHit]:
    base = "BlackBookOnline"
    term = q.username or q.full_name or q.email or q.phone or q.address1
    if not term:
        return []
    probes = [f"https://www.blackbookonline.info/Search.aspx?kw={quote_plus(term)}"]
    return probe_site_for_terms(sess, base, q, probes, max_hits=1)

@register("DataAxle Reference")
def scrape_dataaxle(sess: requests.Session, q: OSINTQuery) -> List[OSINTHit]:
    base = "DataAxle Reference"
    term = q.username or q.full_name or q.email
    if not term:
        return []
    probes = [f"https://www.referenceusa.com/Search/QuickSearch?search={quote_plus(term)}"]
    return probe_site_for_terms(sess, base, q, probes, max_hits=1)

# ======================= Runner =======================
def run_scraper(sess: requests.Session, site: str, q: OSINTQuery) -> List[OSINTHit]:
    """
    Execute the registered scraper function for `site`.
    If not implemented, return [] so the GUI can fall back to links/dorks.
    """
    log.debug(f"run_scraper called for site={site} (username={q.username}, email={q.email})")
    fn = SCRAPERS.get(site)
    if not fn:
        log.debug(f"No scraper registered for {site}. Registered keys: {list(SCRAPERS.keys())}")
        return []
    try:
        hits = fn(sess, q) or []
        log.debug(f"scraper {site} returned {len(hits)} hit(s)")
        if not hits:
            log.debug(f"{site}: 0 hits")
        return hits
    except NotImplementedError:
        log.debug(f"{site}: scraper not implemented")
        return []
    except Exception as e:
        # Don’t explode the UI; log context so we can tune selectors later
        log.exception(f"{site}: unexpected error — {e}")
        return []

def get_session_for_tests() -> requests.Session:
    """Tiny helper for quick REPL tests."""
    return get_session()
