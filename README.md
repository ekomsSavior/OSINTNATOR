# OSINTNATOR

Public-source research dashboard by DA3 and ek0ms savi0r. Python 3.10+ and Tkinter.

## Free web edition

Use **https://osint.churchofmalware.org/**. The browser interface runs the existing collectors with independent field coverage, live progress, source evidence, cancellation, and JSON/HTML/GraphML exports. It uses ephemeral private sessions, bounded jobs and no paid data accounts. The public service is isolated behind the church's existing Cloudflare and Nginx infrastructure.

For a local browser version, run `bash run_web.sh`; see [WEB-DEPLOYMENT.md](WEB-DEPLOYMENT.md) for installation, hosting and coverage limits. The desktop interface below remains available. GitHub username discovery now excludes merely similar handles, and GraphML URL nodes ignore common tracking parameters while preserving original evidence URLs.

## Run

```bash
git clone https://github.com/ekomsSavior/OSINTNATOR.git
cd OSINTNATOR
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python osintnator.py
```

Install your operating system's `python3-tk` package before launching the desktop interface. `cloudscraper` remains optional. Reports and logs are stored next to the application, regardless of the current working directory, and are excluded from Git.

## Using the dashboard

1. Enter the details you already have. Use **Username** for GitHub names or full Bluesky handles; use **Domain / website URL** for `example.org` or `https://example.org/`. GitHub accepts handles, profile URLs, and a clearly labeled candidate formed by removing spaces.
2. Check the sources you want in any tab, then click **Run all selected** to run those checked sources across every tab. **Select all sources** checks every tab; each tab's **Select all** checks only that tab. The Free Research tab is selected initially. **Run selected (category)** runs only the checked sources in that category. No sources are run when nothing is selected.
3. Review the result status. `record` means the provider returned a structured record. It does not prove that an account belongs to a particular person. `candidate` means a page needs review. `manual` provides a navigation path. `needs_input`, `timeout`, `error`, and `not_found` are distinct outcomes.
4. Open the source links. A manual path is not evidence that data exists there. Blocked requests and failed lookups are never proof of absence.
5. The default **Findings** filter shows records and candidates. Choose **All** to see context, blocked sources and manual paths. The **All inputs** dropdown can show only name, username, email, phone, address, or website findings. The coverage summary stays visible when errors are filtered out. CSV/JSON/text/HTML reports preserve all rows; GraphML exports findings and their observed relationships, plus input coverage as graph metadata.

The interface defaults to black, white, and grayscale, without emojis. The pane divider and Max results button resize the result area. Settings save worker count, lookup budget, theme, search engine, fallback preference, and selected sources only; query details and API keys are excluded.

## Retrieval by input

Every filled identifier is routed to its relevant selected collectors. Multi-input sources are split into separate tasks so earlier name/username lookups do not consume the budget for phone, address or email. Location fields narrow the address/name query rather than becoming unrelated person identifiers.

| Input | Automatic collectors and extracted data |
|---|---|
| Name | Separate public-web search, LinkedIn indexed-profile name search and GitHub public-name discovery; original-page structured contacts when available. Same-name results remain candidates. |
| Username | Public profiles, username pack, GitHub discovery and web mentions; GitHub now retains public email, location and linked social handle when present. |
| Email | Gravatar public-profile lookup by SHA-256 email hash; GitHub public commit author-email search; GitHub public-profile email index; web mentions and matching contacts on collected pages. |
| Phone | Plain-number public-web search with formatting-aware result checks; USPhoneBook structured contact extraction; matching telephone links/plain mentions on collected pages. A search heading echo is not a returned owner record. |
| Address | US Census address/county lookup, official parcel adapter where supported, and separate public-web/property-page searches. |
| Domain | Website pages/published contacts and links, DNS, RDAP and independent web search. |

**Property research now routes nationwide.** The web directory contains 4,498 county and municipal entries across all 50 states and DC, sourced from NETR's public directory. **US Assessor & Tax Directory** resolves a supplied address and retrieves published assessor/appraiser, tax collector/treasurer and recorder links. **Official Property Records** queries Washington, Massachusetts and North Carolina statewide services, preserves the El Paso historical adapter, and discovers other public-authoritative ArcGIS parcel services by location. Returned parcels must match the supplied site address; nearby parcels, alternate entrance addresses and source failures are not silently treated as matches. Some jurisdictions still require their interactive portal; the directory is not universal automatic record coverage.

**Obituaries & Memorials** adds an obituary web collector, Legacy name-index lookup, Dignity Memorial and Tribute Archive indexed searches, and a Find a Grave portal. The selected engine and fallback settings apply. Matching names remain candidates, and original notice metadata is retrieved where accessible. Publication dates are kept distinct from dates of death.

The website now exposes the complete **84-source catalog**: 21 collectors, 14 legacy public-page checks and 49 interactive portals. Categories, source filtering, per-category selection and a separate Source portals result view make the distinction visible. No paid credentials are supplied, and portal entries do not count as findings.

**Gravatar Email Profile** and **GitHub Email Commits** are in **Free Research**. They use public endpoints without paid credentials. An absent Gravatar profile or public commit is not evidence that a mailbox does not exist. Commit author names/emails can be self-declared. No password-reset, sign-up or private-account enumeration is performed.

Aggregation compares supplied inputs against **returned source fields/text**, excluding request URLs and query metadata. Evidence containing multiple supplied identifiers is highlighted and available under **Shared evidence**. For example, an email published on the supplied website contributes to email coverage even though it came from the website collector. Co-occurrence is not an automatic identity merge. CSV/JSON/HTML/GraphML retain the matched input labels and provenance.

The source checklist scrolls, and the divider cannot collapse it out of view. Old saved settings may not select newly added collectors; use **Select all sources**, or check the additions individually, before **Run all selected**.

Technical sources: [Gravatar REST API](https://docs.gravatar.com/rest-api/), [Gravatar hash format](https://docs.gravatar.com/rest/hash/), [GitHub commit search](https://docs.github.com/en/rest/search/search#search-commits), [Census Geocoder](https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.html), [El Paso city parcel dataset](https://services1.arcgis.com/hyTVSIhR7dHyDsJF/arcgis/rest/services/Parcels_2023/FeatureServer/0), and [published organization/contact fields](https://developers.google.com/search/docs/appearance/structured-data/organization).

## LinkedIn name discovery

**LinkedIn Name Search** is available in **Free Research** on the desktop and website. Enter first and last names; the website selects it automatically while source selection is still automatic, or click **Select relevant** / select it explicitly. Click **Run all selected**. A city/state adds a separate refinement with its own lookup budget; it never replaces the name-only search. All other selected input searches still run independently.

The collector queries the chosen search engine for indexed LinkedIn person profiles, using the existing fallback, cancellation, rate-limit and network controls. It returns observed profile URLs, indexed titles/descriptions, retrieval timestamps and search-source links. It recognizes middle names/initials, surname-first titles and common accent/punctuation variants. Region-specific and tracking URLs are normalized; company, directory, login and non-LinkedIn links are excluded. Names must appear in returned text, not merely in an input echo or a guessed URL.

These are **candidates**, not verified identity or a fresh copy of the LinkedIn profile. Private or unindexed profiles can be absent, and engine blocks remain visible. When collection yields no candidate, a LinkedIn people-search link is provided separately for the user's own review. The service never signs into LinkedIn or uses its private APIs.

Reference: [LinkedIn public-profile visibility](https://www.linkedin.com/help/linkedin/answer/a528138/control-your-public-linkedin-profile).

## Reliability changes

- Source lookups run directly; generated search links no longer skip actual work.
- Each automated source runs in a separate killable process, with a wall-clock budget. Stop search terminates active work and preserves partial results. Worker concurrency defaults to 6 and is capped at 12.
- The username pack no longer stops after eight candidates. Unvisited platform URLs remain manual paths when its budget expires. Numeric-ID routes are used only for numeric input.
- Every catalog entry has a navigation path or explicit alternative, including entries with no scraper. Missing inputs produce guidance instead of unrelated requests.
- Source-specific manual instructions replace several obsolete, moved, or unavailable routes. The original provider is not represented as the alternative provider.
- Cache keys include query and source selection, expire after 24 hours, and exclude cancelled/failed-budget runs. Runs containing only manual paths are not cached. Clear cache removes all current-query variants.
- Reports use unique filenames and include result status and collection timestamp. GraphML exports observed relationships such as a website publishing an account link. It excludes navigation paths, errors and context rows by default.

## API sources

- **GitHub Profile API:** public account lookup, including login and stable numeric account ID. No key required; unauthenticated quotas apply.
- **Bluesky Profile API:** public handle lookup with stable DID. Enter a full handle such as `bsky.app`, not a bare username.
- **Domain RDAP:** structured domain registration data via the RDAP.org bootstrap service. Some fields are redacted; an unsupported registry is not evidence that a domain is available.
- **VirusTotal Domain (opt-in):** disabled by default. Requires both `VIRUSTOTAL_API_KEY` and `OSINTNATOR_VT_ENABLE=1`. VirusTotal documents that queried indicators can be scanned and added to its community dataset. Use only public indicators you intend to share, and review your provider plan and terms before enabling. The Public API has usage and workflow restrictions. API keys are read from the environment, never saved by the settings controls. The displayed provider analysis time may be older than collection time. This adapter was fixture-tested, not tested against a live paid/keyed account.
- **HaveIBeenPwned:** requires `HIBP_API_KEY` and an email address; missing configuration is now visible.

`OSINTNATOR_REMOTE_RENDER=1` still enables the legacy optional third-party rendering helper. It is off by default and sends requested URLs to that service. It does not guarantee access through challenges. `OSINTNATOR_DEBUG=1` enables diagnostic logs; those can contain search URLs.

## Reports and checks

Readable HTML, CSV, JSON, and text reports are written to `reports/`. GraphML can be opened in compatible graph tools such as Gephi. Graph edges carry the observed relationship, source URL, collection time, and evidence hash when available. They do not assert that two people or accounts are the same identity.

```bash
python3 -m unittest discover -s tests -v
python3 check_sources.py --output reports/source-health.json
```

GUI tests run when an accessible display is available; otherwise they skip. The source checker requests entry pages with no personal search terms. A reachable page is not a validated search form, and HTTP 200 can still be a login or challenge page. Check JSON `final_url` and status rather than assuming every source works automatically.

The November 6, 2026 check of 66 entry paths found 50 reachable, 15 blocked, and one unavailable. Public API smoke checks returned GitHub's documented `octocat` example, the `bsky.app` service profile, and `example.org` registration data. A fabricated GitHub username correctly returned 404. These checks do not validate every site's live search results.

## Research behind the update

- [GitHub public-user REST API](https://docs.github.com/en/rest/users/users#get-a-user): structured account fields and stable IDs instead of HTML status-code guessing. Implemented.
- [Bluesky API reference](https://endpoints.bsky.app/): public profile data and DIDs. Implemented and live-checked against the public service profile.
- [ICANN RDAP overview](https://www.icann.org/rdap) and [RDAP.org](https://about.rdap.org/): RDAP replaces WHOIS with structured data and authoritative-server discovery. Implemented for domains.
- [Maigret contribution guidance](https://github.com/soxoj/maigret/blob/main/CONTRIBUTING.md): validate known-positive and nonexistent identifiers and disable unreliable checks. Applied to testing strategy; Maigret is not installed or integrated. A maintained optional adapter is a sensible next step, with output kept as candidates until reviewed.
- [USAGov court directory](https://www.usa.gov/courts) and [NETR public-record directory](https://publicrecords.netronline.com/): useful routes to jurisdiction-specific records. Added manual guidance rather than guessing undocumented forms.
- [VirusTotal domain-report documentation](https://docs.virustotal.com/reference/domain-info) and [API plan restrictions](https://docs.virustotal.com/reference/public-vs-premium-api): reviewed before implementing the explicitly opt-in adapter. Automatic domain-to-IP-to-reputation chaining is not enabled.

The most useful remaining work is source-specific parsers with positive/negative fixtures, a maintained optional username-tool adapter, and source health history. Proxies, image/face identification, recovery-endpoint account enumeration, and location tracking were not added. Map output is deferred until a source provides coordinates with explicit provenance; addresses are not automatically treated as a person's location.

## Limits

Many legacy sources still use generic text matching or manual forms. Login requirements, CAPTCHAs, subscriptions, regional coverage, and site changes remain outside the dashboard's control. This update makes failures explicit and retains research paths; it cannot guarantee data for every query. Use lawful public-source research and verify material findings at their original source.

## Free public sources

No paid account is required for the additions below. Select the sources you want in **Free Research** or **Public APIs**, then click **Run all selected**. Only checked sources run.

| Input | Implemented retrieval | Coverage limit |
|---|---|---|
| Name | Public Web Search returns relevant result snippets; GitHub Public Discovery queries its public full-name index | Search candidates require review; names are not unique |
| Username | GitHub and Hacker News public profiles; Bluesky for full handles | Platform-specific; matching handles do not prove a shared identity |
| Domain / website URL | Website & Linked Profiles collects page metadata, explicit contact links and outbound links, followed by up to three relevant pages and two linked GitHub profiles; RDAP and DNS remain available | Bounded public collection; a published link does not prove common ownership |
| Email | Separate exact-address public-web query and GitHub public-email search; domain DNS is context only | Does not verify mailbox existence or its owner; shared providers such as Gmail are not expanded into misleading findings |
| Phone | Public Web Search queries the number independently and accepts formatted-number matches in returned results | A matching public mention does not establish current ownership; no recovery endpoints or private account checks |
| Address | Public Web Search queries the street with city, state and ZIP context and recognizes common street/direction abbreviations | A matching property or page is a candidate, not proof that a person lives there |

GitHub's unauthenticated search and REST quotas still apply. Discovery retrieves candidates before enriching at most one candidate per populated identifier to limit requests. If enrichment exceeds the source budget, already retrieved candidates retain their public account ID and link. A no-match result in these sources is not a no-match result across the internet.

### Search-engine selector restored

The dropdown offers DuckDuckGo, Google, Brave, Bing, Yahoo, Yandex, Baidu, ZoomEye, and DogPile. It controls **Public Web Search** and optional web-search fallback links. It does not change which provider a direct API queries. The engine preference is included in saved settings.

**Try other engines if unavailable**, in Free Research, is enabled by default. The chosen engine is tried first. If it fails or returns no extractable matching results, the collector uses DuckDuckGo, Bing and Yahoo as available fallbacks, up to three distinct engines total within the lookup budget. The original failure remains in the report and findings name the engine actually used. HTTP 202/403/429 pauses that engine for the rest of the run; later fields can still use another engine. Turn fallback off to use only the selected engine. No challenges are solved or bypassed.

### Independent input coverage

Public Web Search creates separate lookups for name, username, email, phone, street address and domain. Names are searched independently and again with city/state when supplied; city, state and ZIP narrow an address query. Location-only input also has its own search. GitHub Public Discovery and supported multi-input legacy collectors separately schedule their accepted identifiers. Each task gets the configured **Lookup budget (s)**; a slow name query cannot consume the phone/address budget. Web searches run one at a time to reduce throttling while other sources run concurrently. Matching search candidates are preserved before fetching up to two original pages for contact extraction.

Only checked collectors run. Coverage distinguishes findings, unavailable sources, manual paths, and inputs with no selected collector. Each finding carries its input group. On completion, the dashboard and HTML report alternate between input groups so a website's many outbound links do not bury other results. CSV/JSON preserve the input and engine attribution; HTML shows coverage, and GraphML stores coverage metadata without turning errors into evidence nodes.

The initial November 7 report exposed omitted phone/address searches and hidden Yandex failures. The later report showed DuckDuckGo returning HTTP 202 and most legacy entries remaining manual. The next revision added the direct collectors above, fallback from DuckDuckGo itself, and a plain-number phone query after a combined Boolean phone query failed a known-positive check. Live checks retrieved an official parcel and Census address record for the supplied address, public name/username candidates, ten public commit candidates for a test email, and seven web candidates for a published business number. The supplied email and phone did not produce usable matches in the targeted live run. This is not a claim of complete coverage, verified identity, or automatic retrieval from every legacy provider.

### Verification

- Live free sources: an earlier GitHub name search returned candidates, but later attempts timed out or returned API unavailable. Hacker News returned a public profile; DNS examples returned 26 domain rows and 14 email-domain rows. Counts are observations and can change. Free provider access is not guaranteed.
- Automated checks cover source routing, timeouts and cancellation, reports, GraphML, filtering, API failures, streaming before enrichment, and domain-only email DNS requests.

### Paid-product research: what is and is not reproducible for free

| Company | Relevant commercial capability | Reference |
|---|---|---|
| Pipl | Licensed identity index connecting identifiers | [Pipl integration documentation](https://support.maltego.com/en/support/solutions/articles/15000036593-pipl) |
| People Data Labs | Professional profiles, employment/contact and company enrichment | [Provider website](https://www.peopledatalabs.com/) |
| DomainTools | Historical registration, DNS and infrastructure context | [Platform documentation](https://www.domaintools.com/platform) |
| ShadowDragon | Commercial collection/analysis of public social data | [SocialNet](https://shadowdragon.io/products/socialnet/) |
| OSINT Industries | Commercial lookups across multiple identifier types | [Provider website](https://www.osint.industries/) |

These are commercial indexes or collection services, not necessarily datasets composed entirely of nonpublic information. They are research comparisons, not purchases or configured integrations. Vendor claims about perfect accuracy have not been independently validated here.

[Maltego](https://www.maltego.com/maltego-data/) is a useful model for source-specific queries, pivots, and data provenance. [Hunchly](https://hunch.ly/) is a useful model for capture and evidence organization. OSINTNATOR uses source-specific queries, result statuses, source links, and exports. Full browser evidence capture is not implemented.

Free-source technical references: [GitHub search API](https://docs.github.com/en/rest/search/search#search-users), [official Hacker News API](https://github.com/HackerNews/API), and [Google DNS JSON API](https://developers.google.com/speed/public-dns/docs/doh/json).


## Retrieval rebuild after the failed report

The supplied report contained 139 manual paths, 17 missing-input rows, seven no-match rows, two timeouts, and ten Gmail infrastructure records. It contained no candidate matches. Passing the earlier tests had not demonstrated useful investigative retrieval.

The corrected workflow is:

1. Check **Website & Linked Profiles**, **Public Web Search**, and the relevant public API sources. These are ordinary source checkboxes; **Run all selected** remains the only global run button.
2. Supply a website, handle, name, or email. Web search queries identifiers separately, instead of combining unrelated fields into one over-constrained query. URL input is accepted for domain lookups.
3. Review retrieved fields, snippets and published links in **Findings**. Each new web observation retains its collection URL/time and a SHA-256 hash of the saved response under `reports/evidence/`. These are HTTP response copies, not full rendered browser archives.
4. Use **Save reports** for a readable HTML report and machine-readable files. The HTML report shows findings first and source diagnostics in an expandable section. GraphML links observed entities with labels such as `links_to`, `profile_links_to`, and `dns_A`.

The crawler checks robots.txt, delays requests, limits itself to four pages and two directly linked GitHub profiles, and refuses nonpublic network destinations and oversized/non-text responses. It does not execute page JavaScript. A login screen or access challenge is not a finding. The source budget defaults to 30 seconds and preserves collected rows if the budget expires.

The username pack now requires a profile-specific marker or a declared canonical profile. A username echoed in generic page HTML is insufficient. Coverage remains narrower than a maintained specialist username database; unsupported pages remain explicit diagnostics.

### What the research changed

| Primary source reviewed | Applied method |
|---|---|
| [SpiderFoot web-spider implementation](https://github.com/smicallef/spiderfoot/blob/master/modules/sfp_spider.py) | Bound the crawl and extract identifiers from fetched pages so observations can lead to further queries. |
| [Maigret development guidance](https://github.com/soxoj/maigret/blob/main/docs/source/development.rst) | Require positive source-specific evidence, test nonexistent/challenge cases, and keep uncertain matches as candidates. |
| [Sherlock site definitions](https://github.com/sherlock-project/sherlock/blob/master/sherlock_project/sites.py) | Treat profile detection as a per-site problem, not a universal HTTP-200 check. |
| [Scrapy AutoThrottle](https://docs.scrapy.org/en/latest/topics/autothrottle.html) and [robots middleware](https://docs.scrapy.org/en/latest/topics/downloader-middleware.html#robotstxtmiddleware) | Add request spacing, crawl bounds and robots handling. OSINTNATOR uses a small requests-based collector rather than adding Scrapy as a dependency. |
| [DDGS search adapters](https://github.com/deedy5/ddgs/tree/main/ddgs/engines) | Inspect current result structures and tracking-link formats. Direct selected-engine collection is implemented; DDGS was tested separately and is not a runtime dependency. |
| [Bellingcat investigation toolkit](https://www.bellingcat.com/resources/2024/09/24/bellingcat-online-investigations-toolkit/) | Keep tools tied to a specific investigative task, with visible access and coverage limits. |

The [Verification Handbook for Investigative Reporting](https://verificationhandbook.com/downloads/verification.handbook.2.pdf) and [Berkeley Protocol, investigation and collection sections](https://humanrights.berkeley.edu/wp-content/uploads/archive/2024/02/Berkeley-Protocol.pdf) provide broader methodological references. The collection guidance informed source URLs, timestamps, saved response copies, and integrity hashes. Full-text copies were located after initial publisher requests failed; relevant sections were reviewed. OSINTNATOR does not claim full forensic compliance, and this is not a claim that every OSINT book was read.

### Live verification of this rebuild

- Website collection returned 21 published observations from the supplied public church website.
- The supplied spaced handle produced the GitHub candidate `ekomsSavior`, with returned profile fields and a published link back to the supplied website.
- Domain DNS accepted the full website URL and returned ten infrastructure records for that domain.
- A separate DuckDuckGo query for the organization returned nine relevant search candidates. Bing returned unrelated results that were rejected; Brave returned an unavailable response. Search-engine availability varies between runs.
- The actual desktop GUI completed the website/profile/domain run with 32 records and one candidate and exported the relationship graph. These counts describe observations, not 33 identified people or verified account owners.

Legacy directory entries still need individual parsers or manual forms. They are labeled **manual guide** where no automatic collector is configured. This rebuild delivers specific working public collection paths; it does not make every legacy source automatic.

### Hosted field retrieval update

The hosted service accepts five searches per visitor IP per ten minutes. Every selected automated task keeps its chosen lookup budget. The run deadline is calculated from the queue (at most 15 minutes), with two simultaneous searches and three source workers per search. Primary searches for all entered identifiers run before location refinements and obituary searches. Search-engine requests are serialized within each run and honor engine access failures.

The results panel exposes queued/running/reported task states and missing-field diagnostics even when another field has findings. Yahoo snippets are parsed from current result blocks. When an indexed result omits an email or phone from its preview, up to two original pages are checked for the exact identifier before any finding is reported. Numeric URL IDs alone cannot qualify as phone evidence. Website collection prioritizes published contact pages. No feature guarantees a public record or bypasses an access challenge.
