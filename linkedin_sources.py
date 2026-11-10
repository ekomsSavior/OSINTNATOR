"""Find indexed public LinkedIn profiles by name, without guessing profile URLs."""
import re
import unicodedata
from urllib.parse import quote, quote_plus, unquote, urlencode, urlsplit

from api_sources import result
from query_inputs import ENGINES
from scrapers import StreamingHits, register
from web_fetch import FetchError, fetch_page
from web_search import parse_results

SITE = 'LinkedIn Name Search'


def name_tokens(value):
    value = unicodedata.normalize('NFKD', value.casefold())
    value = ''.join(c for c in value if not unicodedata.combining(c))
    return re.findall(r'[^\W_]+', value)


def name_matches(text, first, last):
    """Allow middle names/initials and surname-first titles, not substring matches."""
    words, given, family = name_tokens(text), name_tokens(first), name_tokens(last)
    if not given or not family:
        return False
    for left, right in ((given, family), (family, given)):
        for start in range(len(words)):
            if words[start:start+len(left)] != left:
                continue
            end = start + len(left)
            for gap in range(4):
                if words[end+gap:end+gap+len(right)] == right:
                    return True
    return False


def profile_url(value):
    """Accept observed person-profile paths only; strip tracking and deduplicate regions."""
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or '').lower()
        if (parsed.scheme not in ('http', 'https') or parsed.username or parsed.password
                or parsed.port not in (None, 80, 443)
                or not re.fullmatch(r'(?:[a-z0-9-]+\.)*linkedin\.com', host)):
            return ''
        parts = parsed.path.strip('/').split('/')
        if not ((len(parts) == 2 and parts[0] == 'in') or
                (len(parts) == 5 and parts[0] == 'pub' and parts[1] != 'dir')):
            return ''
        decoded = [unquote(part) for part in parts]
        if any(not part or re.search(r'[\s/\\?#\x00-\x1f%]', part) or part in ('.', '..') for part in decoded):
            return ''
        return 'https://www.linkedin.com/' + '/'.join(quote(part, safe='-._~') for part in decoded) + '/'
    except ValueError:
        return ''


def search_expression(q, alternative=False):
    # Separate quoted names still find profiles containing a middle name or initial.
    quoted = lambda value: '"' + ' '.join(value.replace('"', ' ').split()) + '"'
    expression = (quoted(q.full_name) + ' site:linkedin.com' if alternative else
                  ' '.join((quoted(q.first), quoted(q.last), 'site:linkedin.com/in/')))
    context = []
    if getattr(q, 'search_context', 'identifier_only') != 'identifier_only':
        for key in ('city', 'state'):
            value = getattr(q, key).strip()
            if value:
                expression += ' ' + quoted(value)
                context.append(key)
    return expression, context


def profile_candidates(body, metadata, q, engine):
    rows = parse_results(body, metadata, q.full_name, engine, field='name',
                         include_unmatched=True, limit=30)
    seen, candidates = set(), []
    for row in rows:
        url = profile_url(row.url)
        # Names must occur in returned title/snippet text, never just in the query or URL.
        title_match = name_matches(row.title, q.first, q.last)
        snippet_match = name_matches(row.snippet, q.first, q.last)
        if not url or url in seen or not (title_match or snippet_match):
            continue
        seen.add(url)
        evidence = row.title + ' ' + row.snippet
        row.site, row.url = SITE, url
        fields = {'profile_url': url, 'indexed_title': row.title,
                  'indexed_snippet': row.snippet, 'name_match_in': 'title' if title_match else 'snippet',
                  'evidence_type': 'Search-engine index; profile page not retrieved'}
        row.raw.update(kind='candidate', fields=fields, evidence_text=evidence,
                       entity_value=url, input_fields=['name'], identity_verified=False,
                       relationship='name_matches_indexed_linkedin_profile')
        row.snippet += ' Public LinkedIn profile candidate from the search index; verify the person and current details on LinkedIn.'
        candidates.append(row)
        if len(candidates) >= 10:
            break
    return candidates


@register(SITE)
def linkedin_name_search(session, q):
    if not name_tokens(q.first) or not name_tokens(q.last):
        return result(SITE, 'First and last name needed',
                      'Enter first and last name for LinkedIn profile discovery.',
                      'https://www.linkedin.com/', 'needs_input')
    requested = getattr(q, 'search_engine', 'Bing')
    if requested not in ENGINES:
        requested = 'Bing'
    engines = [requested]
    if getattr(q, 'search_fallback', True):
        engines += [e for e in ('Bing', 'Yahoo', 'DuckDuckGo') if e != requested][:2]
    expression, context = search_expression(q)
    hits = StreamingHits(session)
    for engine in engines:
        expression, context = search_expression(q)
        prefix = 'https://html.duckduckgo.com/html/?q=' if engine == 'DuckDuckGo' else ENGINES[engine]
        url = prefix + quote_plus(expression)
        common = {'input_fields': ['name'], 'context_fields': context, 'requested_engine': requested,
                  'engine': engine, 'query': q.full_name, 'search_expression': expression}
        if engine != requested:
            common['fallback_from'] = requested
        if engine in getattr(q, 'search_skip_engines', ()):
            hits.extend(result(SITE, engine + ': paused for this run',
                               'An earlier request was challenged or rate limited; no repeat request was sent.',
                               url, 'blocked', **common))
            continue
        # Some indexes handle a full-name/domain query better than a profile-path
        # restriction. Try that once after an empty response, never after a block.
        for alternative in ([False, True] if engine == requested else [False]):
            expression, context = search_expression(q, alternative)
            url = prefix + quote_plus(expression)
            common.update(search_expression=expression, context_fields=context)
            try:
                body, metadata = fetch_page(session, url)
                rows = profile_candidates(body, metadata, q, engine)
                for row in rows:
                    row.raw.update(common)
                    hits.append(row)
                if rows:
                    return hits
                hits.extend(result(SITE, engine + ': no matching LinkedIn profiles extracted',
                                   'No supported profile results matched both names. Profiles may be unindexed, private, or absent from these results.',
                                   url, 'unavailable', **metadata, **common))
            except (FetchError, ValueError) as exc:
                status = re.match(r'HTTP (\d+)', str(exc))
                code = int(status.group(1)) if status else None
                hits.extend(result(SITE, engine + ': LinkedIn name search unavailable', str(exc), url,
                                   'blocked' if code in (202, 401, 403, 429) or 'challenge' in str(exc).lower() else 'unavailable',
                                   http_status=code, **common))
                break
    hits.extend(result(SITE, 'Continue in LinkedIn people search',
                       'No public profile candidate was retrieved. LinkedIn may show additional results when you sign in; no signed-in search was performed here.',
                       'https://www.linkedin.com/search/results/people/?' + urlencode({'keywords': q.full_name}),
                       'manual', input_fields=['name']))
    return hits
