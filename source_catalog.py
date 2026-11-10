"""Source catalog shared by desktop and headless clients."""
ENGINE_SOURCES = {'Public Web Search','LinkedIn Name Search','Obituary Web Search','Dignity Memorial Obituaries','Tribute Archive Obituaries'}
# === Catalog ===
CATS = {
    "Free Research": ["Public Web Search", "LinkedIn Name Search", "GitHub Public Discovery", "Gravatar Email Profile", "GitHub Email Commits", "Website & Linked Profiles", "Hacker News Profile API", "Domain DNS Records", "Email Domain Records"],
    "People Search": [
        "FastPeopleSearch","TruePeopleSearch","TruePeopleSearch.io","FastBackgroundCheck","That’sThem",
        "FamilyTreeNow","ZabaSearch","Radaris","NeighborReport","Nuwber",
    ],
    "Reverse Phone / Address": [
        "Whitepages (Free Search)","411.com","AnyWho","WhoCallsMe","SpyDialer",
        "CallerName","OKCaller","Sync.me","NumLookup","ReversePhoneLookup",
    ],
    "Property Records & Assessor": [
        "Official Property Records","US Assessor & Tax Directory","US Address Geography","Zillow","Rehold","NeighborWho","HomeFacts","Melissa Address Lookup",
        "PropertyShark","Netronline Public Records","PublicRecords360","AddressSearch.com","HOMES.com",
    ],
    "Obituaries & Memorials": ["Obituary Web Search", "Legacy Obituaries", "Dignity Memorial Obituaries", "Tribute Archive Obituaries", "Find a Grave"],
    "Court/Criminal/Gov": [
        "PACER (federal index)","VINELink","BOP Inmate Locator","State/County Court Directory","InmateAid",
        "State Prison Inmate Locators","Offender Search","Arrests.org","Mugshots.com","BustedMugshots",
    ],
    "Specialized / Extra": [
        "PeekYou","Pipl (preview)","Social Searcher","Username Search","instant username search","IDcrawl","Username Pack (direct)","Hunter.io",
        "EmailHippo","HaveIBeenPwned","BlackBookOnline","DataAxle Reference","USPhoneBook",
    ],
    "Public APIs": ["GitHub Profile API", "Bluesky Profile API", "Domain RDAP", "VirusTotal Domain (opt-in)"],
    "Worldwide": [
        "SearchSystems", "GestolenObjectenRegister", "RDW-OVI", "PeopleSearch AU",
        "QKenteken", "KVK Zoeken", "Sportradar", "Weibo", "HKU DataHub", "OpenStreetMap",
    ],
}

# Primary domain roots (used for dork queries)
SITE_DOMAIN = {
    "FastPeopleSearch":"fastpeoplesearch.com","TruePeopleSearch":"truepeoplesearch.com","TruePeopleSearch.io":"truepeoplesearch.io",
    "FastBackgroundCheck":"fastbackgroundcheck.com","That’sThem":"thatsthem.com","FamilyTreeNow":"familytreenow.com","ZabaSearch":"zabasearch.com",
    "Radaris":"radaris.com","NeighborReport":None,"Nuwber":"nuwber.com",
    "Whitepages (Free Search)":"whitepages.com","411.com":"411.com","AnyWho":"anywho.com","WhoCallsMe":"whocallsme.com",
    "SpyDialer":"spydialer.com","CallerName":None,"OKCaller":"okcaller.com","Sync.me":"sync.me","NumLookup":"numlookup.com","ReversePhoneLookup":"reversephonelookup.com",
    "Zillow":"zillow.com","Rehold":"rehold.com","NeighborWho":"neighborwho.com","HomeFacts":"homefacts.com","Melissa Address Lookup":"melissa.com",
    "PropertyShark":"propertyshark.com","Netronline Public Records":"netronline.com","PublicRecords360":"publicrecords360.com","AddressSearch.com":"addresssearch.com","HOMES.com":"homes.com",
    "PACER (federal index)":"pacer.uscourts.gov","VINELink":"vinelink.vineapps.com","BOP Inmate Locator":"bop.gov","State/County Court Directory":None,
    "InmateAid":"inmateaid.com","State Prison Inmate Locators":None,"Offender Search":"nsopw.gov","Arrests.org":"arrests.org","Mugshots.com":"mugshots.com","BustedMugshots":"bustedmugshots.com",
    "PeekYou":"peekyou.com","Pipl (preview)":"pipl.com","Social Searcher":"social-searcher.com","Username Search":"usersearch.org","instant username search":"instantusername.com",
    "IDcrawl":"idcrawl.com/username-search","Username Pack (direct)": None,"Hunter.io":"hunter.io",
    "EmailHippo":"emailhippo.com","HaveIBeenPwned":"haveibeenpwned.com","BlackBookOnline":"blackbookonline.info","DataAxle Reference":"referenceusa.com","USPhoneBook":"usphonebook.com",
    "SearchSystems":"searchsystems.net","GestolenObjectenRegister":"gestolenobjectenregister.nl","RDW-OVI":"ovi.rdw.nl","PeopleSearch AU":"peoplesearch.com.au",
    "QKenteken":"qenteken.nl","KVK Zoeken":"kvk.nl","Sportradar":"sportradar.com","Weibo":"weibo.com","HKU DataHub":"datahub.hku.hk","OpenStreetMap":"openstreetmap.org",
}

SITE_URL = {
    "LinkedIn Name Search": "https://www.linkedin.com/search/results/people/",
    "US Assessor & Tax Directory": "https://publicrecords.netronline.com/",
    "Obituary Web Search": "https://www.legacy.com/obituaries/",
    "Legacy Obituaries": "https://www.legacy.com/obituaries/",
    "Dignity Memorial Obituaries": "https://www.dignitymemorial.com/obituaries",
    "Tribute Archive Obituaries": "https://www.tributearchive.com/obituaries",
    "Find a Grave": "https://www.findagrave.com/memorial/search",
    "SearchSystems": "https://publicrecords.searchsystems.net/",
    "GestolenObjectenRegister": "https://gestolenobjectenregister.nl/",
    "RDW-OVI": "https://ovi.rdw.nl/",
    "PeopleSearch AU": "https://peoplesearch.com.au/",
    "QKenteken": "https://www.qenteken.nl/",
    "KVK Zoeken": "https://www.kvk.nl/zoeken/",
    "Sportradar": "https://sportradar.com/",
    "Weibo": "https://s.weibo.com/",
    "HKU DataHub": "https://datahub.hku.hk/",
    "OpenStreetMap": "https://www.openstreetmap.org/",
}

PRIORITY_SITES = ["Username Pack (direct)", "FamilyTreeNow", "WhoCallsMe", "HaveIBeenPwned"]
