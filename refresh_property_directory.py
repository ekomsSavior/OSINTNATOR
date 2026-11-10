"""Refresh public jurisdiction links, respecting NETR's ten-second crawl delay.

Maintenance only; never run in a visitor request. No property/person data is saved.
"""
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = 'https://publicrecords.netronline.com'


def refresh(destination):
    session = requests.Session()
    session.headers['User-Agent'] = 'OSINTNATOR/3 public-jurisdiction-directory'
    last = 0

    def page(url):
        nonlocal last
        time.sleep(max(0, 10.1 - (time.monotonic() - last)))
        last = time.monotonic()
        response = session.get(url, timeout=(5, 20))
        response.raise_for_status()
        return BeautifulSoup(response.text, 'html.parser')

    home = page(BASE + '/')
    states = {}
    for anchor in home.select('a[href]'):
        match = re.fullmatch(r'/state/([A-Z]{2})/?', anchor['href'])
        if match:
            states[match[1]] = anchor.get_text(' ', strip=True)
    if len(states) != 51:
        raise RuntimeError(f'Expected 50 states and DC, found {len(states)}; existing index preserved.')
    rows = []
    for code, name in sorted(states.items()):
        url = BASE + '/state/' + code
        soup = page(url)
        counties = {}
        for anchor in soup.select('a[href]'):
            match = re.fullmatch(r'/state/' + code + r'/county/([a-z0-9_-]+)/?', anchor['href'])
            if match:
                counties[match[1]] = {'name': anchor.get_text(' ', strip=True), 'url': urljoin(BASE, anchor['href'])}
        if not counties:
            raise RuntimeError('No jurisdictions parsed for ' + code + '; existing index preserved.')
        rows.append({'code': code, 'name': name, 'url': url, 'jurisdictions': sorted(counties.values(), key=lambda c: c['name'])})
        print(code, len(counties), flush=True)
    payload = {'source': BASE + '/', 'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
               'scope': '50 US states and District of Columbia; county and municipal directory entries, not property records',
               'states': rows}
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(target)
    print('Saved', len(rows), 'states/DC and', sum(len(s['jurisdictions']) for s in rows), 'jurisdictions', flush=True)


if __name__ == '__main__':
    refresh(Path(__file__).resolve().parent / 'data' / 'us_property_directory.json')
