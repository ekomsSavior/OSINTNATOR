"""Public US address geography and a registry of official parcel data adapters."""
import re
from urllib.parse import urlencode
from scrapers import register,OSINTHit
from api_sources import result
from identity_sources import read_json
from web_fetch import FetchError
from query_inputs import normalized_street

SITE='Official Property Records'
CENSUS='https://geocoding.geo.census.gov/geocoder/geographies/address'
EL_PASO='https://services1.arcgis.com/hyTVSIhR7dHyDsJF/arcgis/rest/services/Parcels_2023/FeatureServer/0'

def address_ready(q):
    return bool(q.address1.strip() and (q.zip.strip() or (q.city.strip() and q.state.strip())))

def address_geography(session,q):
    params={'street':q.address1,'city':q.city,'state':q.state,'zip':q.zip,
            'benchmark':'Public_AR_Current','vintage':'Current_Current','format':'json'}
    data,meta=read_json(session,CENSUS+'?'+urlencode(params))
    matches=data.get('result',{}).get('addressMatches')
    if not isinstance(matches,list):raise FetchError('The geocoder did not return an address match list.')
    return matches,meta

@register('US Address Geography')
def census_address(session,q):
    site='US Address Geography'
    if not address_ready(q):return result(site,'Address and location needed','Enter a street with ZIP or city and state.',CENSUS,'needs_input')
    try:matches,meta=address_geography(session,q)
    except FetchError as exc:return result(site,'Address source unavailable',str(exc),CENSUS,'unavailable')
    hits=[]
    for match in matches[:5]:
        geographies=match.get('geographies',{});counties=geographies.get('Counties',[])
        fields={'matched_address':match.get('matchedAddress'),'county':', '.join(c.get('NAME','') for c in counties),
                'county_fips':', '.join(c.get('GEOID','') for c in counties),
                'address_components':match.get('addressComponents',{})}
        hits.extend(result(site,'US Census address match',
                    ' | '.join(f'{key}: {value}' for key,value in fields.items())+'. Address-range geography; not a building, owner or resident record.',
                    meta['source_url'],'record',**meta,fields=fields,entity_type='address',entity_value=match.get('matchedAddress',''),
                    relationship='geocoder_address_match',identity_verified=False))
    return hits or result(site,'No address match returned','The geocoder did not match this address. This does not establish that the property is absent.',CENSUS,'not_found',**meta)

def street_tokens(street):
    value=normalized_street(street)
    number=re.match(r'^(\d+[a-z]?)\s+(.+)$',value)
    if not number:raise ValueError('Enter a street number and street name.')
    parts=number.group(2).split()
    stop={'north','south','east','west','northeast','northwest','southeast','southwest','street','road','avenue','lane','drive','boulevard','court','place','way','circle','unit','apt'}
    words=[p for p in parts if p not in stop]
    if not words:raise ValueError('Enter a street name as well as its number.')
    return number.group(1),words[:4]

def el_paso_property(session,q):
    number,words=street_tokens(q.address1)
    literal=lambda value:value.upper().replace("'","''")
    # Only fixed field names and escaped literal values enter ArcGIS SQL.
    where="SITUS_NUM = '"+literal(number)+"'"+''.join(" AND UPPER(SITUS_STRE) LIKE '%"+literal(word)+"%'" for word in words)
    if q.zip:where+=" AND SITUS_ZIP LIKE '"+literal(q.zip[:5])+"%'"
    fields=['PROP_ID','PROP_VAL_Y','LEGAL_DESC','LAND_ACRES','ZONING','SITUS_NUM','SITUS_DIR','SITUS_STRE','SITUS_UNIT','SITUS_CITY','SITUS_STAT','SITUS_ZIP','TOTAL_ASSE','TOTAL_APPR','TOTAL_IMP_','TOTAL_LAND','YR_BLT']
    url=EL_PASO+'/query?'+urlencode({'f':'json','where':where,'outFields':','.join(fields),'returnGeometry':'false','resultRecordCount':10})
    data,meta=read_json(session,url)
    if not isinstance(data.get('features'),list):raise FetchError('The parcel source did not return a feature list.')
    labels={'PROP_ID':'property_id','PROP_VAL_Y':'valuation_year','LEGAL_DESC':'legal_description','LAND_ACRES':'land_acres','ZONING':'zoning',
            'TOTAL_ASSE':'assessed_value','TOTAL_APPR':'appraised_value','TOTAL_IMP_':'improvement_value','TOTAL_LAND':'land_value','YR_BLT':'year_built'}
    hits=[]
    for feature in data.get('features',[]):
        attrs=feature.get('attributes',{})
        if not attrs.get('PROP_ID'):continue
        address=' '.join(str(attrs[key]).strip() for key in ('SITUS_NUM','SITUS_DIR','SITUS_STRE','SITUS_UNIT','SITUS_CITY','SITUS_STAT','SITUS_ZIP') if attrs.get(key))
        if str(attrs.get('SITUS_NUM','')).strip().casefold()!=number.casefold():continue
        returned_words=set(normalized_street(str(attrs.get('SITUS_STRE',''))).split())
        if not all(word in returned_words for word in words):continue
        values={label:attrs[key] for key,label in labels.items() if attrs.get(key) is not None}
        values={'site_address':address,'dataset_year':2023,**values}
        pid=str(attrs['PROP_ID']);page=url
        hits.extend(result(SITE,'El Paso property '+pid+' (2023 dataset)',
                    ' | '.join(f'{key}: {value}' for key,value in values.items())+'. Historical city-published parcel record; not proof of current ownership or residence.',
                    page,'record',**meta,fields=values,entity_type='parcel',entity_value='TX-ElPaso:'+pid,
                    relationship='address_matches_parcel',dataset_year=2023,identity_verified=False))
    return hits or result(SITE,'No parcel matched the supplied address','No matching parcel in the city-published 2023 dataset. Check spelling, unit and ZIP; current records may differ.',url,'not_found',**meta)

@register(SITE)
def official_property(session,q):
    if not address_ready(q):return result(SITE,'Street and location needed','Enter a street with ZIP or city and state. This collector searches properties by site address.', 'https://publicrecords.netronline.com/','needs_input')
    from parcel_sources import nationwide_property
    return nationwide_property(session,q)
