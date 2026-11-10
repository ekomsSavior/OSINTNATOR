"""Save UI preferences only. Never query values, credentials, or API keys."""
import json
from pathlib import Path


def save_settings(path, workers, timeout, dark, selected, engine="DuckDuckGo", search_fallback=True):
    data={'version':1, 'workers':max(2,min(12,int(workers))),
          'timeout':max(3,min(60,int(timeout))), 'dark':bool(dark),
          'selected':list(dict.fromkeys(selected)), 'engine':engine, 'search_fallback':bool(search_fallback)}
    path=Path(path)
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data,indent=2))
    temporary.replace(path)


def load_settings(path, known_sources):
    data=json.loads(Path(path).read_text())
    if not isinstance(data,dict) or data.get('version') != 1:
        raise ValueError('Unsupported settings format')
    if not isinstance(data.get('dark'),bool) or not isinstance(data.get('selected'),list):
        raise ValueError('Invalid settings values')
    if not isinstance(data.get('search_fallback',True),bool):raise ValueError('Invalid fallback setting')
    return {'workers':max(2,min(12,int(data['workers']))),
            'timeout':max(3,min(60,int(data['timeout']))),
            'dark':data['dark'], 'engine':data.get('engine','DuckDuckGo'),
            'search_fallback':data.get('search_fallback',True),
            'selected':[s for s in data['selected'] if isinstance(s,str) and s in known_sources]}
