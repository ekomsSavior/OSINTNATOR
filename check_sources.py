#!/usr/bin/env python3
"""Check public entry pages without submitting personal search terms.
HTTP reachability is not proof that a lookup works or returns records.
"""
import argparse
import concurrent.futures
import json
from datetime import datetime, timezone
from pathlib import Path
import requests
from osintnator import CATS, SITE_DOMAIN, SITE_URL, OSINTQuery
from lookup_paths import manual_path


def check(item):
    site, url = item
    checked_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    try:
        response = requests.get(url, timeout=(4, 7), stream=True,
                                headers={'User-Agent':'OSINTNATOR source availability check'})
        try:
            code = response.status_code
            state = 'reachable' if 200 <= code < 300 else 'blocked' if code in (401,403,429) else 'http_error'
            return dict(site=site, url=url, status=state, code=code, final_url=response.url, checked_at=checked_at)
        finally:
            response.close()
    except requests.RequestException as exc:
        return dict(site=site, url=url, status='unavailable', error=type(exc).__name__, checked_at=checked_at)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='reports/source-health.json')
    args = parser.parse_args()
    # Blank query checks entry pages only, never individual records.
    query = OSINTQuery()
    items = [(site,manual_path(site, query, SITE_DOMAIN, SITE_URL, CATS).url)
             for group in CATS.values() for site in group]
    output=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        for row in executor.map(check, items):
            output.append(row)
            print(f"{row['site']}: {row['status']} {row.get('code', '')}",flush=True)
    path=Path(args.output)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(output,indent=2))
    print(f"Saved {len(output)} source checks to {path}")

if __name__ == '__main__':
    main()
