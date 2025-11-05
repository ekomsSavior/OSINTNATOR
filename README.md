# OSINTNATOR

## Open-source OSINT framework 
⌕ ⋆.˚ by: DA3 & ek0ms savi0r ⌕ ⋆.˚

![Screenshot_2025-11-04_17_36_53](https://github.com/user-attachments/assets/a1cc0952-5173-497a-81e5-95ec53de9c8b)
---

## Install

```bash
git clone https://github.com/ekomsSavior/OSINTNATOR.git

cd OSINTNATOR

sudo apt update && sudo apt install python3-tk

pip3 install requests beautifulsoup4 cloudscraper urllib3
```

`cloudscraper` is used automatically by the scraper session if available. See the optional Cloudflare note below. 

---

## Usage


* Verbose Mode (Best):

```bash
# recommended run (my default)
export OSINTNATOR_REMOTE_RENDER=1
export OSINTNATOR_DEBUG=1
python3 osintnator.py
``` 
The GUI will launch. Default engine shown in the header is DuckDuckGo.
 
Osintnator is most easily viewed in fullscreen mode.

* Standard run:

  ```bash
  python3 osintnator.py
  ```

---

## Important environment variables

* `OSINTNATOR_REMOTE_RENDER=1`
  Enables optional remote prerendering for JS-heavy / Cloudflare pages. The scrapers module will call a prerender service (r.jina.ai) to fetch a rendered HTML snapshot when JS-block messages are detected. Use this for pages where normal requests return JS-only content or a Cloudflare challenge. 

* `OSINTNATOR_DEBUG=1`
  Enables console log output (debug) and sets the logger to DEBUG for scrapers. Also helps when troubleshooting HTTP failures. 

* `HIBP_API_KEY="..."`
  If you want to use the HaveIBeenPwned lookup, set `HIBP_API_KEY` in your environment. The HIBP scraper will return nothing if the key is missing, so add it only if you have a valid key and accept the HIBP rate limits / ToS. 

---

## What engines are available (try different ones!)

The UI exposes multiple search engines for fallback “dork” lookups. Experiment — different engines will return different results:

* DuckDuckGo (default), Google, Brave, Bing, Yandex, Baidu, ZoomEye, DogPile. 

Switch from the GUI dropdown to see how results differ. The fallback dork format uses `site:domain + tokens` and will open with the selected engine. 

---

![Screenshot_2025-11-04_17_14_10](https://github.com/user-attachments/assets/226f9afa-33d3-40a2-b2a3-0ffe9bb1e4d7)


## GUI controls & quick actions

* **Engine** — choose search engine for dork fallbacks. 
* **Threads** — controls concurrent scraper threads (2–40). Higher = faster but increases chance of anti-bot triggers. Default in UI is `16` Try **8–16**. 
* **Timeouts** — per-site timeout (seconds). Default UI value is `12`. Increase to ~15–20 for JS/heavy sites. 
* **Quick Username Pack** — special one-click check for usernames (`Username Pack (direct)`) that always bypasses cache and forces a fresh run for immediate feedback. Use it when you want instant username lookups. 
* The GUI includes a “Bypass cache” checkbox and a “Clear Cache (this query)” button for convenience.

---

## Reports & caching

* After any run the app auto-saves reports under `reports/`:

  ```
  reports/osint_YYYY-MM-DD_HHMMSS.csv
  reports/osint_YYYY-MM-DD_HHMMSS.json
  reports/osint_YYYY-MM-DD_HHMMSS.txt
  reports/cache/<sha256>.json
  ```

  CSV columns: `site, title, snippet, url`. Save behavior and the report paths are controlled by the `save_reports()` helpers. 

* Per-query cache is a SHA256 of the query fields. Cache files live in `reports/cache/` and are returned automatically unless you bypass the cache. You can clear the cache for the current GUI query or delete the file manually:

  ```bash
  rm reports/cache/<sha256>.json
  ```
  ---

## Scrapers / datasets behavior (how results are produced)

* The tool first tries **datasets** (Wayback, crt.sh, helpful engine search links) for each site; if datasets return results the live scrapers for those sites are skipped. This helps surface subdomains, snapshots, and certificates quickly. The datasets helpers are in `datasets.py`.

* When scrapers run, the `scrapers` module prepares a session (optionally `cloudscraper`), uses polite jitter before requests, and will attempt a remote-render if the page looks like it’s JS-protected. All network helpers live in `scrapers.py`.

---

## Useful tweak points (where to edit)

If you want to tune behavior directly in code:

* `DEFAULT_TIMEOUT` in `scrapers.py` — change the default HTTP timeout for scrapers. 
* `DEFAULT_RETRIES` in `scrapers.py` — control retry strategy for transient errors. 
* `UA_POOL` in `scrapers.py` — expand or customize the user-agent pool used for fetches. 
* `PRIORITY_SITES` in `osintnator.py` — keep high-value stacks here so the GUI runs these first. 

---

## Troubleshooting checklist

* **0 hits everywhere** → try a different engine, increase `Timeouts`, reduce `Threads`, and/or enable `OSINTNATOR_REMOTE_RENDER`. The app adds “(open site)” and “(search dork)” fallback links automatically if scrapers fail.

* **403 / Cloudflare / challenge pages** → install `cloudscraper` and/or set `OSINTNATOR_REMOTE_RENDER=1`. The scrapers module will auto-use `cloudscraper` when installed.

* **HIBP returns nothing** → ensure `HIBP_API_KEY` is set and that you’re using a valid key. The HIBP scraper will return empty if the key is missing. 

* **SSL / certificate errors** → on Debian/Ubuntu: `sudo apt install ca-certificates` and ensure Python uses a current `certifi`. Alternatively try `cloudscraper` if the issue is Cloudflare-related.

* **No GUI / tkinter errors** → install system `python3-tk` package for your distribution.

---

## Extending the project

* **Add a new scraper**: open `scrapers.py`, add a new `@register("MySite")` scraper function that returns `List[OSINTHit]`. Follow the existing `probe_site_for_terms` helpers as examples. The registration decorator exposes the site in the notebook tabs automatically. 

* **Datasets**: add or refine dataset helpers in `datasets.py` — already includes Wayback and crt.sh helpers plus a utility to produce dork links. 

---

## Legal

This tool is for lawful research and defensive use only.

Respect site ToS and robots. 

Throttle with Threads/Timeouts and avoid aggressive scans against 3rd-party infrastructure. 


---
```
          .:'
      __ :'__
   .'`__`-'__``.
  :__________.-'
  :_________:
   :_________`-;
    `.__.-.__.'

  ___  ___(_)_ __ | |_ _ __   __ _| |_ ___  _ __ 
 / _ \/ __| | '_ \| __| '_ \ / _` | __/ _ \| '__|
| (_) \__ \ | | | | |_| | | | (_| | || (_) | |   
 \___/|___/_|_| |_|\__|_| |_|\__,_|\__\___/|_|    
```
---

