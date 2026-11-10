"""Manual research paths. These are navigation aids, not discovered records."""

GUIDES = {
    "PACER (federal index)": ("https://pacer.uscourts.gov/find-case", "Search federal court records", "Register or sign in to PACER, then use the Case Locator with a party name or case number. Access may incur fees."),
    "BOP Inmate Locator": ("https://www.bop.gov/inmateloc/", "Open the federal inmate locator", "Choose Find by Name or Find by Number. This covers federal custody; use the state corrections directory for state records."),
    "State Prison Inmate Locators": ("https://www.usa.gov/prisoner-records", "Find the correct prison records source", "Choose federal or state records, then follow the relevant corrections agency's lookup instructions."),
}


def guide_for(site):
    return GUIDES.get(site)

# Source-specific instructions take precedence over generic site homepages.
GUIDES.update({
    "State/County Court Directory": ("https://www.usa.gov/courts", "Find the state court system", "Choose the state, then the court or county records portal. Use a party name or case number; availability varies by court."),
    "NeighborReport": ("https://publicrecords.netronline.com/", "Alternative: county property records", "The legacy entry has no configured source. Choose state and county, then assessor or recorder; search the address or parcel."),
    "CallerName": ("https://www.numlookup.com/", "Alternative: reverse phone lookup", "The legacy entry has no configured source. Enter a full phone number in the provider's lookup form; verify any returned association."),
    "Netronline Public Records": ("https://publicrecords.netronline.com/", "Find official county property records", "Select state and county, then assessor, recorder, or tax office. Search by address, owner name, or parcel number."),
    "PublicRecords360": ("https://publicrecords.netronline.com/", "Alternative: public property records", "The old PublicRecords360 URL redirects to a commercial service. For property records, choose the state and county here."),
    "BustedMugshots": ("https://www.usa.gov/courts", "Alternative: state court records", "The legacy source failed the connection check. Use the official state court directory and locate the relevant county or case."),
    "PeopleSearch AU": ("https://www.whitepages.com.au/", "Alternative: Australian directory", "The legacy source failed the connection check. Use the directory's person or business search with a name and location."),
    "QKenteken": ("https://ovi.rdw.nl/", "Alternative: official RDW vehicle lookup", "Use the official Dutch registration lookup. Enter the vehicle registration plate in its form; this dashboard has no plate field."),
    "DataAxle Reference": ("https://www.data-axle.com/platforms-products/reference-solutions/", "Reference Solutions access", "ReferenceUSA moved to Reference Solutions. Check access through your library or institution before searching its databases."),
    "Pipl (preview)": ("https://pipl.com/", "Pipl access information", "This service requires provider access. Open the service to review its access options; no public preview is claimed here."),
    "RDW-OVI": ("https://ovi.rdw.nl/", "Official vehicle lookup", "Enter the Dutch registration plate on the source site. Vehicle details are not an owner identity match."),
    "GestolenObjectenRegister": ("https://gestolenobjectenregister.nl/", "Object register", "Use the site's object or serial-number fields. The dashboard's person fields do not identify an object."),
    "Sportradar": ("https://sportradar.com/", "Sports data service", "This is a sports data provider, not a person-search source. Review product access on the source site."),
    "HKU DataHub": ("https://datahub.hku.hk/", "Research data repository", "Search the repository by dataset title, subject, or researcher. This is not a general people lookup."),
    "Hunter.io": ("https://hunter.io/", "Email and domain tools", "Choose Email Verifier or Domain Search. Provider access and credits may be required; no result was retrieved automatically."),
    "EmailHippo": ("https://www.emailhippo.com/", "Email validation tools", "Use the provider's email verification product and review its access requirements. Validation does not establish identity."),
    "instant username search": ("https://instantusername.com/", "Interactive username search", "Enter the username in the site's interactive form. Its browser-only results are not fetched by this dashboard."),
})


def input_hint(site, q, categories):
    """Return required-input guidance instead of performing unrelated requests."""
    if site=='LinkedIn Name Search':
        return 'Enter first and last name for LinkedIn profile discovery.' if not (q.first.strip() and q.last.strip()) else ''
    if site in categories.get('Obituaries & Memorials',[]):
        return 'Enter first and last name for obituary searches.' if not (q.first.strip() and q.last.strip()) else ''
    if site=='US Assessor & Tax Directory':
        return 'Enter a US state or an address with ZIP to find the local assessor and tax offices.' if not (q.state or (q.address1 and q.zip)) else ''
    if site in ("Website & Linked Profiles", "Domain RDAP", "Domain DNS Records", "VirusTotal Domain (opt-in)"):
        return "Enter a domain such as example.org." if not q.domain else ""
    if site in ("GitHub Profile API", "Hacker News Profile API", "Bluesky Profile API", "Username Pack (direct)", "IDcrawl", "Username Search", "instant username search"):
        return "Enter a username (a full handle for Bluesky)." if not q.username else ""
    if site in ("HaveIBeenPwned", "EmailHippo", "Hunter.io", "Email Domain Records", "Gravatar Email Profile", "GitHub Email Commits"):
        return "Enter an email address." if not q.email else ""
    if site in ('US Address Geography','Official Property Records'):
        return 'Enter a street with ZIP or city and state.' if not (q.address1 and (q.zip or (q.city and q.state))) else ''
    if site in categories.get("Reverse Phone / Address", []) or site == "USPhoneBook":
        return "Enter a phone number or street address." if not (q.phone or q.address1) else ""
    if site in categories.get("Property Records & Assessor", []):
        return "Enter a street address or owner name; include location to narrow the source search." if not (q.address1 or q.full_name) else ""
    if site in categories.get("People Search", []) or site in categories.get("Court/Criminal/Gov", []):
        return "Enter a name or other identifier accepted by the source." if not (q.full_name or q.phone or q.address1 or q.email) else ""
    return ""


def manual_path(site, q, domains, urls, categories, status="manual", detail=""):
    from urllib.parse import quote
    from models import OSINTHit
    guide = guide_for(site)
    if guide:
        url, title, instruction = guide
    else:
        domain = domains.get(site)
        url = urls.get(site) or ("https://" + domain if domain else "")
        title = "Open source lookup"
        instruction = "Use the source's search form with the supplied details. Access or payment may be required; no record has been confirmed."
        if site in categories.get("People Search", []):
            instruction = "Search by name and city/state. Compare the source record with known details before treating it as a match."
        elif site in categories.get("Reverse Phone / Address", []) or site == "USPhoneBook":
            instruction = "Choose reverse phone or address lookup and enter the full number or street address. Review the returned record on the source."
        elif site in categories.get("Property Records & Assessor", []):
            instruction = "Search by street address and city/state, or owner name. For authoritative records use the county assessor/recorder."
        if site == "Username Pack (direct)":
            url = "https://github.com/" + quote(q.username, safe="") if q.username else "https://github.com/"
            instruction = "Review the individual platform paths. A timeout leaves unvisited platforms marked manual."
        elif site == "GitHub Profile API":
            url = "https://github.com/" + quote(q.username, safe="")
        elif site == "Bluesky Profile API":
            url = "https://bsky.app/profile/" + quote(q.username, safe="") if q.username else "https://bsky.app/"
        elif site == "Domain RDAP":
            url = "https://lookup.icann.org/"
            instruction = "Enter the domain in ICANN Lookup. Some registration fields are redacted."
    if site == "Website & Linked Profiles":
        from query_inputs import normalize_domain
        try: url="https://"+normalize_domain(q.domain)+"/"
        except ValueError: url="https://example.org/"
        instruction="Collect the supplied public website and its published links. Enter a domain or website URL."
    elif site == "Public Web Search":
        url="https://duckduckgo.com/"
        instruction="Collect result snippets for separate identifiers using the selected search engine. Access challenges remain visible."
    elif site == "GitHub Public Discovery":
        url = "https://github.com/search?type=users"
        instruction = "Search GitHub's public profile index; coverage is limited to GitHub and public fields."
    elif site == "Hacker News Profile API":
        url = "https://news.ycombinator.com/"
        instruction = "Enter a Hacker News username; a missing account says nothing about other platforms."
    elif site in ("Domain DNS Records", "Email Domain Records"):
        url = "https://dns.google/"
        instruction = "Public DNS records describe a domain, not the identity or existence of an individual mailbox."
    elif site=='Gravatar Email Profile':
        url='https://gravatar.com/'
        instruction='Retrieve a public profile by the SHA-256 hash of the supplied email. No account recovery is performed.'
    elif site=='GitHub Email Commits':
        url='https://github.com/search?type=commits'
        instruction='Search public commit author-email metadata. Published authorship does not prove mailbox ownership.'
    elif site=='US Address Geography':
        url='https://geocoding.geo.census.gov/geocoder/'
        instruction='Retrieve the standardized address and county from the US Census geocoder. This is not a property ownership record.'
    elif site=='Official Property Records':
        url='https://publicrecords.netronline.com/'
        instruction='Retrieve official parcel fields where a county adapter is available. Dataset dates and unsupported coverage are explicit.'
    if site == "VirusTotal Domain (opt-in)":
        url = "https://docs.virustotal.com/reference/domain-info"
        instruction = "Optional integration; queried domains may be scanned and added to the provider dataset. Review terms and configure explicit opt-in before use."
    if site == "OpenStreetMap" and q.address1:
        url = "https://www.openstreetmap.org/search?query=" + quote(" ".join(filter(None, (q.address1, q.city, q.state, q.zip))))
        instruction = "Review the mapped address. Map features do not establish who lives there."
    if status != "manual":
        title = f"{status.replace('_', ' ').capitalize()}: {title}"
    return OSINTHit(site, title, (detail + " " + instruction).strip(), url,
                    {"kind": status, "fallback": "guide", "source": site})
