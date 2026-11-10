import json
import threading
import unittest
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from models import OSINTQuery
from source_catalog import CATS
from web_catalog import CATALOG
from web_service import collect, validate_request
from research_plan import LookupTask, plan_lookups
import property_directory as directory
import parcel_sources as parcels
import obituary_sources as obits

META={'source_url':'https://example.org/query','checked_at':'2026-11-07','content_sha256':'fixture'}
MATCH={'coordinates':{'x':-71.08,'y':42.35},'matchedAddress':'123 EXAMPLE ST, BOSTON, MA','addressComponents':{'state':'MA'}}
SCHEMA={'fields':[{'name':'SITE_ADDR','alias':'Site address','type':'esriFieldTypeString'},
                  {'name':'PROP_ID','alias':'Parcel','type':'esriFieldTypeString'},
                  {'name':'TOTAL_VAL','alias':'Assessed value','type':'esriFieldTypeDouble'},
                  {'name':'FY','alias':'Fiscal year','type':'esriFieldTypeInteger'}]}


class PropertyExpansionTests(unittest.TestCase):
    def test_directory_has_all_states_and_valid_provenance(self):
        index=directory.directory()
        self.assertEqual(len(index['states']),51)
        self.assertGreater(sum(len(s['jurisdictions']) for s in index['states']),3100)
        self.assertIn('checked_at',index)
        for state in index['states']:
            self.assertTrue(state['jurisdictions'])
            for county in state['jurisdictions']:
                self.assertTrue(county['url'].startswith('https://publicrecords.netronline.com/state/'+state['code']+'/county/'))

    def test_same_named_city_and_county_not_conflated(self):
        state={'jurisdictions':[{'name':'Richmond','url':'county'},{'name':'Richmond City','url':'city'}]}
        self.assertEqual(directory.jurisdiction_entry(state,'Richmond city')['url'],'city')
        self.assertEqual(directory.jurisdiction_entry(state,'Richmond County')['url'],'county')

    def test_office_links_are_paths_not_property_findings(self):
        html='''<div id="county-list"><div class="div-table-row"><div col-name="Name">Example Assessor</div><div col-name="Phone">555-0100</div><div col-name="Online"><a href="https://assessor.example.gov/">Go to Data Online</a></div></div><div class="div-table-row"><div col-name="Name">NETR Mapping</div><div col-name="Online"><a href="https://map.example/">Map</a></div></div></div>'''
        rows=directory.office_links(html,META)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0].raw['kind'],'manual')
        self.assertEqual(rows[0].url,'https://assessor.example.gov/')
        self.assertEqual(rows[0].raw['fields']['office_phone'],'555-0100')

    def test_exact_site_address_required_and_dates_preserved(self):
        data={'features':[{'attributes':{'SITE_ADDR':'123 EXAMPLE STREET','PROP_ID':'p1','TOTAL_VAL':1234,'FY':2025}},
                          {'attributes':{'SITE_ADDR':'124 EXAMPLE ST','PROP_ID':'wrong'}}]}
        q=OSINTQuery(address1='123 Example St',city='Boston',state='MA')
        with patch.object(parcels,'read_json',side_effect=[(SCHEMA,META),(data,META)]) as read:
            rows=parcels.query_layer(None,q,MATCH,'Fixture parcels','https://example.gov/FeatureServer/0','https://example.gov/')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0].raw['fields']['Fiscal year'],'2025')
        self.assertEqual(rows[0].raw['fields']['parcel_id'],'p1')
        params=parse_qs(urlsplit(read.call_args.args[1]).query)
        self.assertEqual(params['resultRecordCount'],['100'])
        self.assertEqual(params['where'],['1=1'])
        self.assertEqual(params['returnGeometry'],['false'])
        self.assertIn('geometry',params)

    def test_neighbor_direction_and_unit_do_not_become_matches(self):
        for returned,requested in [('123 N Main St','123 S Main St'),('123 Example St','123 Example St Apt 2'),('1123 Example St','123 Example St')]:
            self.assertFalse(parcels.address_matches(returned,requested))
        self.assertTrue(parcels.address_matches('123 S MAIN STREET, CITY','123 S Main St'))

    def test_discovery_rejects_unverified_wrong_extent_and_wrong_urls(self):
        good={'id':'abc','title':'Local parcels','url':'https://example.gov/FeatureServer','contentStatus':'public_authoritative','extent':[[-72,42],[-70,43]]}
        items=[good,{**good,'id':'unverified','contentStatus':None,'url':'https://unverified.example/FeatureServer'},{**good,'id':'elsewhere','extent':[[0,0],[1,1]]},{**good,'id':'badurl','url':'file:///etc/passwd'},{**good,'id':'subset','title':'Selected parcels'}]
        with patch.object(parcels,'read_json',return_value=({'results':items},META)):
            rows=parcels.discover_services(None,MATCH)
        self.assertEqual(len(rows),1)
        self.assertTrue(rows[0][2].endswith('abc'))

    def test_no_address_or_ambiguous_location_does_not_query_parcels(self):
        q=OSINTQuery(address1='123 Example St',state='MA')
        with patch('property_sources.address_geography',return_value=([MATCH,MATCH],META)),patch.object(parcels,'query_layer') as query:
            rows=parcels.nationwide_property(None,q)
        query.assert_not_called()
        self.assertEqual(rows[0].raw['kind'],'unavailable')

    def test_entire_desktop_catalog_is_present_and_portals_never_execute(self):
        self.assertEqual(set(CATALOG),{name for names in CATS.values() for name in names})
        q=OSINTQuery(email='test@example.org',domain='example.org')
        with patch('web_service.run_bounded') as run:
            for site in ('HaveIBeenPwned','VirusTotal Domain (opt-in)','PACER (federal index)'):
                rows=collect(LookupTask(site,q,('email',),site),10,threading.Event())
                self.assertEqual(rows[0].raw['kind'],'manual')
        run.assert_not_called()

    def test_obituary_and_property_tasks_route_separately(self):
        q=OSINTQuery(first='Example',last='Person',address1='123 Example St',city='Boston',state='MA')
        tasks=plan_lookups(['Obituary Web Search','Official Property Records','US Assessor & Tax Directory'],q,CATS)
        self.assertEqual([t.fields for t in tasks],[('name',),('address',),('address',)])

    def test_obituary_index_rejects_echo_and_wrong_name(self):
        q=OSINTQuery(first='Example',last='Person')
        html='''<input value="Example Person"><a href="/obituaries/name/person/example">Search Example Person</a><a href="/us/obituaries/name/example-person-obituary?id=1">Example Person</a><a href="/person/another-person-2">Another Person</a><a href="javascript:alert(1)">Example Person</a>'''
        rows=obits.obituary_links(html,{**META,'source_url':'https://www.legacy.com/obituaries/name/person/example'},q)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0].raw['kind'],'candidate')
        self.assertFalse(rows[0].raw['identity_verified'])

    def test_obituary_search_honors_engine_and_domain(self):
        q=OSINTQuery(first='Example',last='Person');q.search_engine='Google';q.search_fallback=False
        html='<h2><a href="https://www.dignitymemorial.com/obituaries/city/example-person-123">Example Person Obituary</a></h2><h2><a href="https://wrong.example/obituary">Example Person Obituary</a></h2>'
        with patch.object(obits,'fetch_page',return_value=(html,{**META,'source_url':'https://www.google.com/search?q=x'})) as fetch,patch.object(obits,'public_page',return_value=('<title>Fixture</title>',META)):
            rows=obits.dignity_obituaries(SimpleNamespace(),q)
        self.assertTrue(fetch.call_args.args[1].startswith('https://www.google.com/search?'))
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0].raw['kind'],'candidate')
        self.assertEqual(rows[0].site,'Dignity Memorial Obituaries')

    def test_obituary_metadata_does_not_label_publication_as_death_or_copy_body(self):
        html='<title>Example Person obituary</title><script type="application/ld+json">{"@type":"NewsArticle","datePublished":"2024-01-02","articleBody":"private fixture body","publisher":{"name":"Example News"},"about":{"@type":"Person","name":"Example Person","deathDate":"2024-01-01"}}</script>'
        fields=obits.notice_metadata(html,META,OSINTQuery(first='Example',last='Person'))
        self.assertEqual(fields['notice_published_at'],'2024-01-02')
        self.assertEqual(fields['publisher_stated_deathDate'],'2024-01-01')
        self.assertNotIn('private fixture body',json.dumps(fields))

    def test_obituary_requires_both_names(self):
        with patch.object(obits,'fetch_page') as fetch:
            rows=obits.all_obituaries(None,OSINTQuery(last='Person'))
        fetch.assert_not_called();self.assertEqual(rows[0].raw['kind'],'needs_input')


if __name__=='__main__':unittest.main()
