"""Read-only public jurisdiction index, safe to import in the web parent."""
import json
import re
from functools import lru_cache
from pathlib import Path

@lru_cache(maxsize=1)
def directory():
    return json.loads((Path(__file__).resolve().parent/'data/us_property_directory.json').read_text())


def state_entry(value):
    value = value.strip().casefold()
    return next((s for s in directory()['states'] if value in (s['code'].casefold(), s['name'].casefold())), None)


def jurisdiction_key(value):
    value = re.sub(r'\b(county|parish|borough|census area|municipality)\b', '', value.casefold())
    return re.sub(r'[^a-z0-9]', '', value)


def jurisdiction_entry(state, county, city=''):
    # A county and its independent city must never be silently merged.
    choices = state.get('jurisdictions', [])
    order = (city,county) if state.get('code') in ('CT','MA','ME','NH','RI','VT') else (county,city)
    for wanted in order:
        if not wanted: continue
        exact = [c for c in choices if jurisdiction_key(c['name']) == jurisdiction_key(wanted)]
        if len(exact) == 1: return exact[0]
    return None
