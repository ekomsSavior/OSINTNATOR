"""Nationwide jurisdiction routing and published assessor/tax office links."""
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from api_sources import result
from scrapers import register, StreamingHits
from web_fetch import fetch_page, FetchError

SITE = 'US Assessor & Tax Directory'
BASE = 'https://publicrecords.netronline.com/'


from jurisdiction_catalog import directory, state_entry, jurisdiction_entry


def office_links(body, metadata):
    soup = BeautifulSoup(body, 'html.parser')
    rows = []
    for row in soup.select('#county-list .div-table-row'):
        label = row.select_one('[col-name="Name"]')
        online = row.select_one('[col-name="Online"] a[href]')
        if not label: continue
        name = label.get_text(' ', strip=True)
        if not re.search(r'assess|apprais|tax|treasur|record|clerk|auditor|mapping|gis|equaliz', name, re.I): continue
        if 'NETR' in name: continue
        phone = row.select_one('[col-name="Phone"]')
        url = urljoin(metadata['source_url'], online['href']) if online else metadata['source_url']
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username: continue
        fields = {'office': name, 'directory_source': metadata['source_url'],
                  'office_phone': phone.get_text(' ', strip=True) if phone else '',
                  'online_access': online.get_text(' ', strip=True) if online else 'No online lookup listed'}
        rows.extend(result(SITE, name, 'Published office/portal entry. Open the source and search by street, parcel or owner name. '
                           'This is a research path, not a returned property record.', url, 'manual', **metadata, fields=fields))
    return rows


@register(SITE)
def assessor_directory(session, q):
    from property_sources import address_ready, address_geography
    hits = StreamingHits(session)
    state = state_entry(q.state)
    county = ''
    city = q.city
    if address_ready(q):
        try:
            matches, _ = address_geography(session, q)
            if len(matches) == 1:
                match = matches[0]
                state = state_entry(match.get('addressComponents', {}).get('state', q.state)) or state
                city = q.city or match.get('addressComponents',{}).get('city','')
                counties = match.get('geographies', {}).get('Counties', [])
                if len(counties) == 1: county = counties[0].get('NAME', '')
        except FetchError as exc:
            hits.extend(result(SITE, 'Address jurisdiction could not be resolved', str(exc), BASE, 'unavailable'))
    if not state:
        hits.extend(result(SITE, 'Choose a US state and jurisdiction', 'Use the US property directory below the results to browse all 50 states and DC.', BASE, 'manual'))
        return hits
    selected = jurisdiction_entry(state, county, city)
    url = selected['url'] if selected else state['url']
    name = (selected['name'] + ', ' if selected else '') + state['name']
    hits.extend(result(SITE, name + ': assessor, tax and recorder directory',
                       'Jurisdiction directory; follow the listed assessor/appraiser, tax collector/treasurer or recorder. '
                       'Directory coverage is not a claim that every office offers downloadable records.', url, 'manual',
                       fields={'state': state['code'], 'county_from_geocoder': county, 'directory_checked_at': directory()['checked_at']}))
    if not selected:
        divisions=[entry for entry in state['jurisdictions'] if county and jurisdiction_key(entry['name'].split(' (')[0])==jurisdiction_key(county)]
        for entry in divisions[:8]:
            hits.extend(result(SITE,entry['name']+': choose the appropriate district',
                               'This county has separate directory entries. Confirm which office serves the property before searching its records.',entry['url'],'manual'))
        return hits
    try:
        body, metadata = fetch_page(session, url)
        links = office_links(body, metadata)
        hits.extend(links or result(SITE, 'Office links were not extractable', 'Open the jurisdiction directory to use its office listings.', url, 'unavailable', **metadata))
    except FetchError as exc:
        hits.extend(result(SITE, 'Office directory unavailable', str(exc), url, 'unavailable'))
    return hits
