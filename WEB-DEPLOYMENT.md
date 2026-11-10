# OSINTNATOR web edition

This is a working Python service with a responsive grayscale browser interface, prepared for Church of Malware. It is not a static landing page. The original desktop application remains available. The public web edition is live at https://osint.churchofmalware.org/. The church homepage and its existing services were not replaced.

## Run locally

```bash
git clone https://github.com/ekomsSavior/OSINTNATOR.git
cd OSINTNATOR
python3 -m venv .venv-web
.venv-web/bin/pip install -r requirements-web.txt
bash run_web.sh
```

Open http://127.0.0.1:8766. Stop with Ctrl-C. The web server does not require Tkinter, a display, a paid provider account, or a JavaScript build step. For an existing checkout, start with the `cd` step.

## What users can do

- Enter any combination of name, username, email, phone, address and domain. City/state/ZIP narrow relevant queries. Each identifier gets separate public-web tasks.
- Select from the full 84-source catalog (21 collectors, 14 public-page checks and 49 interactive portals), choose any of the desktop's nine search engines, enable fallback, and set a 10/20/30-second budget per lookup.
- Watch progress and field coverage, filter findings or source failures, inspect returned fields and provenance, stop a search, or delete its results.
- Download JSON, HTML and GraphML reports. Reports preserve engine, fallback, budgets, source selections, original inputs, timestamps and partial-run state.

The browser selects relevant sources as inputs are entered. Relevant selection includes collectors and public-page checks, not interactive portals. Manually changing the source choices preserves that selection until **Select relevant** is clicked. Only selected collectors run. A populated input with no selected matching collector is reported explicitly.

## Hosting on churchofmalware.org

The live destination is **https://osint.churchofmalware.org/**. The main church homepage is a Cloudflare Worker; the research backend runs on the existing Netherlands VPS through Nginx. `deploy/church-tool-link.html` is a prepared directory card; the homepage navigation was not changed in this release.

This backend runs Python processes and makes outbound HTTP requests. It needs a server/container host; uploading these files to static hosting alone will not run the collectors. Users need no paid data accounts. An existing church server could host it without an additional provider subscription, subject to its capacity and network limits. No free hosting quota or zero hosting cost is promised.

### Current church installation

The `osintnator` systemd service runs as a separate dynamic non-root user from `/opt/osintnator/current`, with its own virtual environment. Nginx connects through `/run/osintnator/api.sock`; the backend has no TCP listener. Only the service owner, root and Nginx can traverse the socket directory. The service is enabled at boot.

The deployed unit in `deploy/osintnator.service` masks other application trees, uses a read-only filesystem, drops capabilities and sets CPU, memory, process and file-descriptor limits. Kernel IP filters deny local/private/metadata networks and protected church origin addresses. The collector's connection-time IP checks provide an additional boundary, including DNS-rebinding and redirect destinations. Protected addresses are held in a host-only configuration and unit drop-in, excluded from the source package.

`deploy/nginx-osint.conf` uses the existing origin certificate and trusted Cloudflare IP list. It rejects non-Cloudflare origin traffic, overwrites forwarded IP headers, disables access logs/caching, limits requests per IP and globally, bounds connections and request sizes, and sets short body/header timeouts. DNS is Cloudflare-proxied. The existing network firewall and other virtual hosts were preserved.

The HTTPS session cookie has the `__Host-` prefix, Secure, HttpOnly and SameSite Strict attributes. There is no public job listing, report directory, debug endpoint or cross-user report access.

Use `systemctl status osintnator`, `journalctl -u osintnator`, and `nginx -t` for maintenance. Stop this service and disable only its Nginx site to roll back; the new DNS record can be removed separately. Do not alter shared proxy/firewall configuration or other services. A restart clears in-memory results, so announce planned maintenance if users are active.

The generic installation alternatives below are for another host; they are not additional services to start on the church server.

### Existing reverse proxy/server

Install the Python dependencies in a virtual environment and run the following through the server's service manager:

```bash
OSINTNATOR_ORIGIN=https://osint.churchofmalware.org \
  .venv-web/bin/python -m uvicorn web_app:create_app --factory \
  --host 127.0.0.1 --port 8766 --workers 1 --no-access-log \
  --proxy-headers --forwarded-allow-ips 127.0.0.1
```

Point the subdomain to that server, add HTTPS to the existing proxy, preserve the public Host header and forward requests to port 8766. Only the trusted local proxy should set forwarded client-IP headers. The service must not be exposed directly on its internal port. A non-local proxy needs its exact address in `--forwarded-allow-ips`; do not use `*` on a publicly reachable backend. If a CDN sits in front, configure the existing proxy to recover the visitor IP from that trusted CDN. Otherwise all users can share one rate-limit bucket.

For a host running Caddy already, the route is:

```caddyfile
osint.churchofmalware.org {
    request_body {
        max_size 8KB
    }
    reverse_proxy 127.0.0.1:8766
}
```

Keep access logging disabled for this route, or explicitly redact request identifiers and result links. Do not replace the church's existing web-server configuration with the standalone example below.

### Standalone Docker installation

`Dockerfile.web` copies only application modules and browser assets. It excludes previous investigations, reports, logs, caches, attachments, virtual environments and work files. The example uses a dedicated non-root app, a read-only filesystem, limited memory/processes, and Caddy for HTTPS.

```bash
docker compose -f deploy/compose.yaml up -d --build
```

This example owns ports 80 and 443. Use it only on a host where those ports are available and where the proposed subdomain points. Its fixed private network must not conflict with an existing network. It trusts only the included proxy's address for visitor IPs. DNS/CDN/proxy integration must be checked on the actual host before public launch. The container recipe has not been built in this workspace because the installed Docker snap cannot access its runtime directories here; the Python service itself has been run and tested directly.

Once the service passes an HTTPS browser search, add the small link/card in `deploy/church-tool-link.html` to the church's tools directory. No iframe is needed.

## Operational behavior

- Run **one Uvicorn worker and one service instance**. Jobs and session ownership live in process memory; multi-worker routing requires an external job store and global scheduler first.
- At most two simultaneous searches, three source workers per search, a run deadline calculated from the selected tasks (at most 15 minutes), 500 result rows per run, 32 retained jobs, and five new searches per visitor IP per ten minutes. Capacity pressure returns an explicit retry message instead of silently dropping fields.
- Only the browser session that started a job can retrieve, cancel, delete or export it. The session cookie is HttpOnly, SameSite Strict, and Secure with a `__Host-` prefix when the configured origin uses HTTPS. Writes require the configured origin and a custom same-origin header. There is no wildcard CORS.
- A new run replaces the previous finished run in that session. Finished results expire after 30 minutes and are pruned periodically. Restarting the server clears all jobs. Downloads saved by users are outside this retention policy.
- Hosted collectors disable saved page bodies, report/cache files, collector logging, ambient proxy/netrc credentials, remote rendering and paid-provider keys. Search engines and source sites still receive the relevant query inputs.
- Hosted child processes restrict actual socket connections to public IPs on ports 80/443, including after redirects and DNS resolution. Requests have source and overall deadlines. Deploy with ordinary host/network isolation as well; this is not a substitute for hosting hardening or load testing.
- Responses are private/no-store; untrusted source text is rendered as text, not HTML. Downloads are attachment responses. No `/reports` directory, filesystem browser, job listing or public search history is served.

## Coverage limits

Public sources can be blocked, unavailable, incomplete or out of date. A returned mention or public record does not establish that two accounts belong to the same person. An email/phone search may legitimately return no useful record.

The property directory covers 4,498 county and municipal directory entries across all 50 states and DC. It is a jurisdiction/office directory, not a nationwide database of returned property/tax records. Automatic parcel collection uses known statewide services in Washington, Massachusetts and North Carolina, the historical El Paso adapter, and spatial discovery of government-hosted or public-authoritative ArcGIS services elsewhere. Site addresses must match the input. Some localities have no supported public GIS layer or require interactive forms. A street entrance and recorded parcel address may differ. Dataset years, unavailable services and unmatched addresses remain explicit.

The index is stored in `data/us_property_directory.json`; `python3 refresh_property_directory.py` refreshes it using public state directory pages, respecting NETR's ten-second crawl delay. This maintenance command takes about nine minutes and is never exposed as an API operation. It replaces the index only after all 51 state/DC pages parse successfully. Restart the application after an index update. Hosted office-directory collectors are serialized across searches with ten seconds between completed requests. The browser's read-only directory endpoint serves this public index without making upstream requests.

Obituary searches require first and last names, preserve the selected engine/fallback, and treat matching notices as candidates. Original-page publication metadata is collected where accessible without copying obituary bodies. Access challenges remain visible. A name match does not establish identity or death.

All previous network, session, proxy and resource controls remain in place. Restored access-dependent desktop entries are interactive portals in the hosted service; selecting one never executes a paid API or exposes server credentials.

## Verification

```bash
.venv-web/bin/pip install httpx networkx
.venv-web/bin/python -m unittest discover -s tests -v
node --check web/app.js
```

GUI tests need a display; headless environments skip those tests. API tests cover all-field scheduling, session separation for reads/exports/cancellation/deletion, expiry, rate and concurrency limits, deadlines, request validation, output escaping and report metadata. Deterministic fixture results test routing; live public/example controls separately test real collectors. These are functional checks, not an independent security audit or production load test.

Implementation references: [FastAPI container deployment](https://fastapi.tiangolo.com/deployment/docker/), [Uvicorn settings](https://www.uvicorn.org/settings/), [Caddy reverse proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy).

## November 9 update: LinkedIn name search

Web version `web-0.4.1` adds LinkedIn Name Search in Free Research, selected for name inputs by Select relevant. First and last names are required. Name-only and optional city/state queries run as separate serialized engine tasks with their own lookup budgets. Results retain indexed titles/descriptions, source links and candidate status; LinkedIn account access is not used. The five-search limit, field scheduling, process isolation and protected network settings are unchanged.
