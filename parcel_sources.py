"""Bounded parcel queries against public government GIS services.

Known statewide services are preferred. Other jurisdictions discover government-
hosted or Esri-verified public-authoritative services at the geocoded location.
Returned addresses must match independently; a nearby polygon is not a match.
"""
import re
from urllib.parse import urlencode, urlsplit
from datetime import datetime, timezone

from api_sources import result
from identity_sources import read_json
from query_inputs import normalized_street
from scrapers import StreamingHits
from web_fetch import FetchError

SITE = 'Official Property Records'
SEARCH = 'https://www.arcgis.com/sharing/rest/search'
STATE_SERVICES = {
    'WA': ('Washington statewide parcels', 'https://services.arcgis.com/jsIt88o09Q0r1j8h/arcgis/rest/services/Current_Parcels/FeatureServer/0', 'https://www.arcgis.com/home/item.html?id=2b603a599a0842a3b2284c04c8927f35'),
    'MA': ('MassGIS property tax parcels', 'https://services1.arcgis.com/hGdibHYSPO59RG1h/arcgis/rest/services/Massachusetts_Property_Tax_Parcels/FeatureServer/0', 'https://www.mass.gov/info-details/massgis-data-property-tax-parcels'),
    'NC': ('NC OneMap statewide parcels', 'https://services.gis.nc.gov/secure/rest/services/NC1Map_Parcels/FeatureServer/1', 'https://www.nconemap.gov/pages/parcels'),
}
ADDRESS_FIELDS = ('situs_address', 'site_addr', 'siteadd', 'site_address', 'situsaddr', 'situsfulladdress', 'situs_full_address', 'situs', 'fulladdr', 'full_address', 'fulladdress', 'propertyaddress', 'property_address', 'prop_address', 'loc_addr', 'address', 'address1')
ID_FIELDS = ('parcel_id_nr', 'orig_parcel_id', 'parno', 'nparno', 'prop_id', 'parcelid', 'parcel_id', 'apn', 'pin', 'account', 'map_par_id', 'objectid')


def extent_contains(extent, x, y):
    try: return len(extent) == 2 and extent[0][0] <= x <= extent[1][0] and extent[0][1] <= y <= extent[1][1]
    except (TypeError, IndexError): return False


def discover_services(session, match):
    from property_directory import state_entry
    coords = match.get('coordinates', {})
    x, y = coords.get('x'), coords.get('y')
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)): return []
    counties = match.get('geographies', {}).get('Counties', [])
    county = re.sub(r'[^\w ]', ' ', counties[0].get('NAME', '')) if counties else ''
    state=state_entry(match.get('addressComponents',{}).get('state',''))
    # Spatial extent excludes same-name counties in other states. Status is also
    # checked on returned objects rather than trusting the search filter alone.
    expression = '(parcel OR parcels OR taxlot OR property) AND (type:"Feature Service" OR type:"Map Service")'
    jurisdictions=[term for term in (county,state['name'] if state else '') if term]
    if jurisdictions:expression+=' AND ('+' OR '.join('"'+term.replace('"',' ')+'"' for term in jurisdictions)+')'
    url = SEARCH + '?' + urlencode({'f':'json', 'q':expression, 'bbox':f'{x-.01},{y-.01},{x+.01},{y+.01}', 'num':40})
    data, _ = read_json(session, url)
    items = []
    for item in data.get('results', []):
        endpoint = str(item.get('url', '')).rstrip('/')
        government = (urlsplit(endpoint).hostname or '').endswith('.gov')
        if (item.get('contentStatus') != 'public_authoritative' and not government) or not extent_contains(item.get('extent'), x, y): continue
        if not re.search(r'/(?:FeatureServer|MapServer)(?:/\d+)?$', endpoint) or urlsplit(endpoint).scheme != 'https': continue
        title = item.get('title', '')
        if re.search(r'vacant|flood|selected|subset|buffer|proposed|right.of.way', title, re.I): continue
        items.append((title, endpoint, 'https://www.arcgis.com/home/item.html?id='+item['id']))
    key = lambda item: (bool(re.search(r'historic|archive',item[0],re.I)), 0 if county and county.lower().replace(' county','') in item[0].lower() else 1, len(item[0]))
    return sorted(items, key=key)[:3]


def address_matches(returned, requested):
    actual, wanted = normalized_street(str(returned)), normalized_street(requested)
    # Require the complete street, including direction/suffix and unit when supplied.
    return bool(wanted) and re.search(r'(?<!\w)' + re.escape(wanted) + r'(?!\w)', actual) is not None


def query_layer(session, q, match, title, endpoint, source):
    schema, _ = read_json(session, endpoint+'?f=json')
    if 'fields' not in schema:
        layers = [l for l in schema.get('layers', []) if re.search(r'parcel|taxlot|assess|property', l.get('name',''), re.I) and l.get('subLayerIds') in (None, [])]
        if not layers: raise FetchError('No queryable parcel layer was advertised by this service.')
        endpoint += '/' + str(int(layers[0]['id']))
        schema, _ = read_json(session, endpoint+'?f=json')
    fields = {f['name'].lower():f for f in schema.get('fields', []) if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', f.get('name',''))}
    address = next((fields[key]['name'] for key in ADDRESS_FIELDS if key in fields and fields[key]['type']=='esriFieldTypeString'), None)
    if not address:
        address=next((f['name'] for f in fields.values() if f['type']=='esriFieldTypeString' and re.search(r'(site|situs|property|physical|full)\s*address',f.get('alias',''),re.I) and not re.search(r'mail|owner',f.get('alias',''),re.I)),None)
    if not address: raise FetchError('This parcel layer does not expose a supported property site-address field.')
    street = normalized_street(q.address1)
    number = re.match(r'^(\d+[a-z]?)\s+', street)
    if not number: raise FetchError('A street number and street name are needed for parcel retrieval.')
    # Query the spatial index first. UPPER/LIKE on multi-million-row statewide
    # address columns can trigger a full table scan even with a spatial filter.
    # Matching is done below, so no user-controlled SQL reaches the source.
    params = {'f':'json', 'where':'1=1', 'outFields':'*', 'returnGeometry':'false', 'resultRecordCount':100}
    coords = match.get('coordinates', {})
    if isinstance(coords.get('x'), (int,float)) and isinstance(coords.get('y'), (int,float)):
        x, y = coords['x'], coords['y']
        params.update(geometry=f'{x-.0015},{y-.0015},{x+.0015},{y+.0015}', geometryType='esriGeometryEnvelope', inSR=4326, spatialRel='esriSpatialRelIntersects')
    else: raise FetchError('No unambiguous geocoded location was returned; parcel retrieval was not attempted.')
    url = endpoint+'/query?'+urlencode(params)
    data, metadata = read_json(session, url)
    if not isinstance(data.get('features'), list): raise FetchError('The parcel service did not return a feature list.')
    hits = []
    for feature in data['features'][:100]:
        attrs = feature.get('attributes', {})
        if not address_matches(attrs.get(address, ''), q.address1): continue
        lower = {key.lower():value for key,value in attrs.items()}
        pid = next((lower[key] for key in ID_FIELDS if lower.get(key) is not None), None)
        if pid is None: continue
        values = {'site_address':attrs[address], 'parcel_id':str(pid), 'dataset':title, 'dataset_page':source,
                  'matched_geography':match.get('matchedAddress','')}
        for key, value in attrs.items():
            if value is None or key.lower() == address.lower(): continue
            label = fields.get(key.lower(), {}).get('alias', key).strip()
            if re.search(r'owner.?name|owner1|ownname|value|_val|val$|year|^fy$|acre|lot.?size|sale|use.?desc|zoning|parcel|tax|data.?link|^city$|situs.?city|^szip$|^zip$|county', key+' '+label, re.I) and not re.search(r'mail|own_addr|own_city|own_zip|own_state', key, re.I):
                if fields.get(key.lower(),{}).get('type')=='esriFieldTypeDate' and isinstance(value,(int,float)):
                    try:value=datetime.fromtimestamp(value/1000,timezone.utc).date().isoformat()
                    except (ValueError,OverflowError,OSError):pass
                values[label] = str(value)[:500]
            if len(values)>=32: break
        last = schema.get('editingInfo', {}).get('lastEditDate')
        if isinstance(last, (int,float)):
            try: values['service_last_edit'] = datetime.fromtimestamp(last/1000, timezone.utc).date().isoformat()
            except (ValueError,OverflowError,OSError): pass
        values['currency_note'] = 'Assessment year and update date vary by locality; verify current taxes and title with the office.'
        record_page = url
        for key in ('data_link','parcel_url','property_url'):
            candidate=str(lower.get(key,''))
            try:
                parsed=urlsplit(candidate)
                valid=parsed.scheme in ('https','http') and parsed.hostname and not parsed.username and parsed.port in (None,80,443)
            except ValueError:valid=False
            if valid:record_page=candidate;break
        summary = {key:value for key,value in values.items() if key in ('site_address','parcel_id') or re.search(r'value|_val|fiscal|^fy$|year.built|acre',key,re.I)}
        hits.extend(result(SITE, title+': parcel '+str(pid), ' | '.join(f'{key}: {value}' for key,value in list(summary.items())[:8])+'. Verify the assessment year and current tax/title status with the local office.', record_page,
                           'record', **metadata, fields=values, entity_type='parcel', entity_value=endpoint+':'+str(pid),
                           relationship='site_address_matches_parcel', identity_verified=False))
        if len(hits)>=12: break
    if not hits and data.get('exceededTransferLimit'):
        raise FetchError('The local parcel response was truncated before a site-address match was found. Use the assessor portal for a complete search.')
    return hits


def nationwide_property(session, q):
    from property_sources import address_geography, el_paso_property
    from property_directory import state_entry
    hits = StreamingHits(session)
    try:
        matches, _ = address_geography(session, q)
        if len(matches) != 1:
            return result(SITE, 'Property location needs clarification', 'The address geocoder did not return one unambiguous location. Use the nationwide assessor directory to search the jurisdiction directly.', 'https://publicrecords.netronline.com/', 'unavailable')
        match = matches[0]
        state = state_entry(match.get('addressComponents', {}).get('state', q.state))
        code = state['code'] if state else q.state.upper()
        if any(c.get('GEOID')=='48141' for c in match.get('geographies',{}).get('Counties',[])):
            return el_paso_property(session, q)
        services = [STATE_SERVICES[code]] if code in STATE_SERVICES else discover_services(session, match)
        seen = set()
        for title, endpoint, source in services:
            if endpoint in seen: continue
            seen.add(endpoint)
            try:
                records = query_layer(session, q, match, title, endpoint, source)
                hits.extend(records)
                if records: return hits
                hits.extend(result(SITE, title+': no matching site address', 'No parcel near the geocoded location had the complete supplied site address. A parcel may use another entrance/address, or the geocoder may be approximate. Use the assessor directory to resolve it; nearby parcels are not treated as matches.', source, 'not_found'))
            except FetchError as exc:
                hits.extend(result(SITE, title+': parcel lookup unavailable', str(exc), source, 'unavailable'))
        if not services:
            hits.extend(result(SITE, 'No supported public parcel service found', 'Automatic discovery found no verified, queryable parcel service here. Select US Assessor & Tax Directory for the local assessor, tax collector and recorder.', 'https://publicrecords.netronline.com/', 'unavailable'))
    except (FetchError,ValueError) as exc:
        hits.extend(result(SITE, 'Parcel lookup unavailable', str(exc), 'https://publicrecords.netronline.com/', 'unavailable'))
    return hits
