"""The full desktop catalog, with explicit hosted capabilities for every entry."""
from source_catalog import CATS
SOURCES = [
    ('Public Web Search', ['name','username','email','phone','address','domain','location'], 'Search each supplied identifier separately, then inspect matching public pages.'),
    ('LinkedIn Name Search', ['name'], 'Find indexed public LinkedIn profiles by first and last name, with a separate city/state refinement when supplied. Returns profile links and indexed descriptions as candidates; no LinkedIn login required.'),
    ('GitHub Public Discovery', ['name','username','email'], 'Search public GitHub profiles. Similar names remain candidates.'),
    ('GitHub Profile API', ['username'], 'Retrieve a public profile and its published links.'),
    ('Username Pack (direct)', ['username'], 'Check public profiles across supported platforms; access failures stay visible.'),
    ('Bluesky Profile API', ['username'], 'Look up a full Bluesky handle, such as name.bsky.social.'),
    ('Hacker News Profile API', ['username'], 'Retrieve a public Hacker News account.'),
    ('Gravatar Email Profile', ['email'], 'Look up an email-linked public Gravatar profile.'),
    ('GitHub Email Commits', ['email'], 'Find public commits with this author email. Commit authorship is self-declared.'),
    ('Email Domain Records', ['email'], 'Check the mail domain. This does not identify a mailbox owner.'),
    ('USPhoneBook', ['phone'], 'Check published US phone details. The provider may block automated access.'),
    ('US Address Geography', ['address'], 'Standardize a US street address and retrieve county geography.'),
    ('Official Property Records', ['address'], 'Retrieve matching parcel fields from public statewide services and discover verified local GIS services. Dates and available fields vary.'),
    ('US Assessor & Tax Directory', ['address','location'], 'Find the jurisdiction and retrieve assessor, appraiser, tax collector, treasurer and recorder links across all 50 states and DC.'),
    ('Obituary Web Search', ['name'], 'Search obituary, funeral-home and newspaper mentions using the selected engine. Name matches remain candidates.'),
    ('Legacy Obituaries', ['name'], 'Read matching names from the public obituary index when accessible; also provides the name-specific search page.'),
    ('Dignity Memorial Obituaries', ['name'], 'Search indexed Dignity Memorial notices using the selected engine; verify dates and location in the original notice.'),
    ('Tribute Archive Obituaries', ['name'], 'Search indexed Tribute Archive notices using the selected engine; name matches do not establish identity.'),
    ('Website & Linked Profiles', ['domain'], 'Collect a public website, published contacts and linked profiles.'),
    ('Domain DNS Records', ['domain'], 'Retrieve public DNS records.'),
    ('Domain RDAP', ['domain'], 'Retrieve public registration data; some fields may be redacted.'),
]
AUTO = {name:{'id':name, 'fields':fields, 'description':description, 'mode':'collector'} for name,fields,description in SOURCES}
PAGE_CHECKS = {'FastPeopleSearch','TruePeopleSearch','TruePeopleSearch.io','FastBackgroundCheck','That’sThem',
               'FamilyTreeNow','ZabaSearch','Radaris','WhoCallsMe','PeekYou','Social Searcher','Username Search','IDcrawl','BlackBookOnline'}
ACCESS_REQUIRED = {'Pipl (preview)','DataAxle Reference','Hunter.io','EmailHippo','HaveIBeenPwned','VirusTotal Domain (opt-in)','Sportradar','PACER (federal index)'}


def fields_for(name, category):
    if name in ('HaveIBeenPwned','EmailHippo','Hunter.io'):return ['email']
    if name=='VirusTotal Domain (opt-in)':return ['domain']
    if name in ('Username Search','instant username search','IDcrawl'):return ['username']
    if name in ('PeekYou','Social Searcher'):return ['name','username']
    if name=='That’sThem':return ['email','phone','address']
    if name in ('FastPeopleSearch','TruePeopleSearch'):return ['name','phone','address']
    if name in ('TruePeopleSearch.io','ZabaSearch'):return ['name','phone']
    if name=='Radaris':return ['name','username']
    if category=='Reverse Phone / Address':return ['phone','address']
    if category=='Property Records & Assessor':return ['address','name','location']
    if category=='Obituaries & Memorials':return ['name']
    if category in ('People Search','Court/Criminal/Gov'):return ['name']
    return ['name','username','location']


def public_catalog():
    rows = []
    for category, names in CATS.items():
        for name in names:
            if name in AUTO:
                row = dict(AUTO[name])
            else:
                mode = 'page_check' if name in PAGE_CHECKS else 'portal'
                description = 'Try the public lookup page and inspect returned mentions. Access blocks and unconfirmed results remain visible.' if mode=='page_check' else 'Interactive source portal. Open its search form; this entry does not automatically retrieve records.'
                if name in ACCESS_REQUIRED: description+=' Provider account, credentials, institutional access or fees may be required; none are supplied by this service.'
                row = {'id':name,'fields':fields_for(name,category),'description':description,'mode':mode}
            rows.append({**row,'category':category})
    return rows


CATALOG = {row['id']:row for row in public_catalog()}
SOURCE_NAMES = set(CATALOG)
