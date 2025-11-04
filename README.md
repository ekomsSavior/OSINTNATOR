# OSINTNATOR
open source osint framework

# Quick smoke tests

* **Run app**

  ```bash
  python osintnator.py
  ```

  Expect the GUI, banner, tabs, and default engine = DuckDuckGo.
* **Dry-run username pack**

  * Put a test username (e.g., `me0w.me0w`) → select “Specialized / Extra → Username Pack (direct)” → Run.
  * Expect several “found / not found” rows plus links.
* **Report files created**

  * After a run, confirm new files:

    ```
    reports/osint_YYYY-MM-DD_HHMMSS.csv
    reports/osint_YYYY-MM-DD_HHMMSS.json
    reports/cache/<sha256>.json
    ```
  * CSV has 4 cols: site, title, snippet, url.

# Debug & logs

* **Verbose logging**

  ```bash
  export OSINTNATOR_DEBUG=1
  python osintnator.py
  ```

  * Console should show `[DEBUG] scrapers: registered scraper: …`
  * Rolling log: `logs/scrapers.log`
* **Understand common HTTPs**

  * `404` not found = likely no profile.
  * `403` forbidden / CF shield = try `cloudscraper` or remote render (below).
  * `405` method not allowed = HEAD blocked; code falls back to GET.
  * `406` not acceptable = some sites (e.g., GitHub) will still return a body on GET—UI shows the URL regardless.

# Options (env vars)

* **Cloudflare-aware client** (auto if lib present):

  * `pip install cloudscraper` (optional). The app will use it if available.
* **Remote render for heavy JS**

  ```bash
  export OSINTNATOR_REMOTE_RENDER=1
  ```

  Uses a simple remote renderer to fetch HTML for pages that block JS-less clients.
* **HIBP API key** (email/username breach checks):

  ```bash
  export HIBP_API_KEY="your_real_key"
  ```

  Put an email or username, select **HaveIBeenPwned**, run. No key → scraper returns empty quietly.

# GUI sanity checks

* **Theme & readability**

  * Toggle “Dark” checkbox in header; confirm inputs/combos readable.
* **Search engine**

  * Change dropdown; run “search dork” fallbacks; links should open with that engine’s query.
* **Resizable output area**

  * Resize the window—the results Text area expands with the window.
  * If you still want more vertical room by default: in `App._result_area()` change `height=16` → `height=24` (or higher).

# Performance tuning

* **Threads**

  * Header “Threads” spinner controls the thread pool (`2–40`).
    Large values = faster but more likely to trip anti-bot. Try **8–16**.
* **Timeout**

  * Header “Timeouts” (sec) per site. **8–15s** is a good range.
* **Priorities**

  * `PRIORITY_SITES` in `osintnator.py` run first; keep fast/high-value entries there.

# Caching & re-runs

* **Per-query cache**

  * Cache key = sha256 of query fields.
  * Delete a single cache file to force a fresh run:

    ```
    rm reports/cache/<hash>.json
    ```
* **Disable cache for a one-off**

  * Temporarily comment the early `load_cache(q)` block in `_background_run` (or delete the cache file above).

# Scraper health checks

* **Registry sanity**

  ```bash
  python - <<'PY'
  ```

import importlib, scrapers
importlib.reload(scrapers)
print("REGISTERED:", ", ".join(sorted(scrapers.SCRAPERS.keys())))
PY

````
Ensure all the sites you expect appear in the list.
- **Network probe**
```bash
python - <<'PY'
import scrapers
s = scrapers.get_session_for_tests()
r = s.get("https://example.com", timeout=8)
print(r.status_code, len(r.text))
PY
````

Confirms outbound HTTP works and tool chain is intact.

* **Remote render quick check**

  ```bash
  OSINTNATOR_REMOTE_RENDER=1 python - <<'PY'
  ```

import scrapers
s = scrapers.get_session_for_tests()
print("Render enabled:", bool(scrapers._maybe_rendered_copy("[https://httpbin.org/html](https://httpbin.org/html)")))
PY

````

# Interpreting zero-hit runs
- Sites change HTML/routes often. “0 hits” can be legit (no profile) *or* a subtle layout change.
- Use the UI’s **(open site)** and **(search dork)** links the app adds automatically for manual confirmation.
- For JS-heavy or CF-guarded sites, try:
1) `pip install cloudscraper`
2) `export OSINTNATOR_REMOTE_RENDER=1`
3) Increase Timeout to ~15s.
4) Reduce Threads to avoid bursts.

# Output & exports
- **CSV/JSON**: click “Save CSV+JSON” or rely on auto-save after run.
- **What’s inside**
- `OSINTHit`: `site`, `title`, `snippet` (first ~200–300 chars of page), `url`, and a `raw` dict with flags like `exists`, `code`, `fallback`, `probed`.

# Search-dork logic (fallbacks)
- If a scraper times out/errors or isn’t registered, the app inserts:
- **Open site** (homepage or base path)
- **Search dork** (engine + `site:domain` + your tokens)
- Configure engine via the header dropdown. It’s guarded (bad key → DuckDuckGo).

# Adding a new scraper (recipe)
1. Open `scrapers.py`.
2. Add:
 ```python
 @register("MySite")
 def scrape_mysite(sess, q):
     if not q.username and not q.full_name and not q.email:
         return []
     probes = [
         f"https://mysite.tld/search?q={quote_plus(q.username or q.full_name or q.email)}"
     ]
     return probe_site_for_terms(sess, "MySite", q, probes, max_hits=2)
````

3. Save, restart app. It will appear under its tab (if listed in `CATS` in `osintnator.py`).

# Troubleshooting quickies

* **Nothing registers** → You have a duplicate filename/module shadowing `scrapers.py`. Ensure only one `scrapers.py` in your working dir.
* **SSL errors** → Update certs (`sudo apt install ca-certificates`), or try `cloudscraper`.
* **403/Just a moment…** → CF page; use `cloudscraper` and/or `OSINTNATOR_REMOTE_RENDER=1`.
* **GUI text unreadable** → Toggle Dark; if you themed locally, confirm `TCombobox`/`TEntry` foreground & fieldbackground are set (we set them for both themes).

# Etiquette & legal

* Respect each site’s **ToS/robots**; throttle via Threads/Timeout.
* Don’t store or republish sensitive data beyond permissible use.
* HIBP is rate-limited and requires an API key tied to an account.

