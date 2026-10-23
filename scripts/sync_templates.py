# -*- coding: utf-8 -*-
"""Sync Template: and Module: pages from doorsgame.wiki to zh.doorsgame.wiki.

Pipeline: enumerate + classify models -> Special:Export (curonly XML) ->
API import (action=import) into zh.doorsgame.wiki -> verify models & text.

Only the current revision is imported (fast, clean sync); the import log
records the origin. Honors HTTPS_PROXY / HTTP_PROXY env vars (requests).

Usage:
    python sync_templates.py            # dry-run: plan only, no writes
    python sync_templates.py --apply    # perform the sync + verify
"""
import collections
import sys
import time

import requests
import pywikibot
from pywikibot import comms

DST_API = 'https://zh.doorsgame.wiki/w/api.php'
SUMMARY = '从 doorsgame.wiki 同步当前修订（CC BY-SA 4.0）'
NS_TEMPLATE = 10
NS_MODULE = 828
CHUNK = 50
APPLY = '--apply' in sys.argv
CHECK_ONLY = '--check-only' in sys.argv

UA = ('doors-wiki-sync/1.0 (https://zh.doorsgame.wiki; '
      'sync between doorsgame.wiki and zh.doorsgame.wiki)')
HEADERS = {'User-Agent': UA}

# dedicated requests session; cookies are copied from pywikibot after login
SESSION = requests.Session()


def prepare_session():
    """Log in via pywikibot, then copy its cookies into the requests session."""
    DST.login()
    SRC.login()
    SESSION.headers.update(HEADERS)
    for cookie in comms.http.session.cookies:
        if 'doorsgame.wiki' in cookie.domain:
            SESSION.cookies.set_cookie(cookie)


def log(*a):
    print(*a, flush=True)


def chunked(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def fetch_infos(site, titles):
    """Batch query page info (canonical title, contentmodel, missing)."""
    out = {}
    for chunk in chunked(titles, CHUNK):
        res = site.simple_request(action='query', prop='info',
                                  formatversion='2',
                                  titles='|'.join(chunk)).submit()
        pages = res['query']['pages']
        if isinstance(pages, dict):
            pages = list(pages.values())
        for page in pages:
            out[page['title']] = page
    return out


def fetch_texts(site, titles):
    """Batch fetch current wikitext for titles."""
    out = {}
    for chunk in chunked(titles, CHUNK):
        res = site.simple_request(action='query', prop='revisions',
                                  rvprop='content', rvslots='main',
                                  formatversion='2',
                                  titles='|'.join(chunk)).submit()
        pages = res['query']['pages']
        if isinstance(pages, dict):
            pages = list(pages.values())
        for page in pages:
            revs = page.get('revisions') or []
            out[page['title']] = (revs[0]['slots']['main']['content']
                                  if revs else None)
    return out


def export_pages(titles):
    """GET Special:Export (current revisions only) -> XML bytes.

    Note: this wiki's Special:Export expects the 'pages' parameter to be
    newline-separated (one page per line), not pipe-separated.
    """
    r = SESSION.get('https://doorsgame.wiki/wiki/Special:Export',
                    params={'pages': '\n'.join(titles), 'curonly': '1',
                            'limit': '50', 'action': 'submit'},
                    timeout=180)
    data = r.content
    if r.status_code != 200 or b'<mediawiki' not in data[:2000]:
        raise RuntimeError('export failed http=%s body=%r'
                           % (r.status_code, data[:200]))
    return data


def import_pages(xml):
    """POST the exported XML to the target wiki via action=import."""
    tok = SESSION.get(DST_API,
                      params={'action': 'query', 'meta': 'tokens',
                              'type': 'csrf', 'format': 'json'},
                      timeout=60).json()['query']['tokens']['csrftoken']
    r = SESSION.post(DST_API, timeout=600,
                     data={'action': 'import', 'format': 'json', 'token': tok,
                           'interwikiprefix': 'doorsgame',
                           'summary': SUMMARY},
                     files={'xml': ('doors-sync.xml', xml,
                                    'application/xml')})
    r.raise_for_status()
    body = r.json()
    if 'error' in body:
        raise RuntimeError('import API error: %s' % body['error'])
    result = body.get('import')
    if isinstance(result, dict):
        return result
    # this MW returns the imported pages as a plain list
    return {'pages': result if result is not None else []}


def fix_content_model(title, model):
    """Change a page's content model (safety net for CSS/Scribunto pages)."""
    tok = SESSION.get(DST_API,
                      params={'action': 'query', 'meta': 'tokens',
                              'type': 'csrf', 'format': 'json'},
                      timeout=60).json()['query']['tokens']['csrftoken']
    r = SESSION.post(DST_API,
                     data={'action': 'editcontentmodel', 'format': 'json',
                           'title': title, 'model': model,
                           'token': tok}, timeout=60)
    body = r.json()
    ok = body.get('editcontentmodel', {}).get('result') == 'Success'
    log('    [model] %s -> %s : %s' % (title, model,
                                       'OK' if ok else body.get('error')))
    return ok


def main():
    global DST, SRC
    SRC = pywikibot.Site('doorsgame', 'doorsgame')
    DST = pywikibot.Site('zhdoors', 'zhdoors')

    # 1) enumerate source pages
    titles = []
    for ns in (NS_TEMPLATE, NS_MODULE):
        for p in SRC.allpages(namespace=ns):
            titles.append(p.title(with_ns=True))
    log('[plan] source pages: %d (Template %d + Module %d)' % (
        len(titles), sum(1 for t in titles if t.startswith('Template:')),
        sum(1 for t in titles if t.startswith('Module:'))))

    # 2) content model distribution
    models = {t: i.get('contentmodel')
              for t, i in fetch_infos(SRC, titles).items()}
    dist = collections.Counter(models.values())
    log('[plan] content models: %s' % dict(dist))

    # 3) already present on target?
    exists = fetch_infos(DST, titles)
    missing = [t for t in titles if 'missing' in exists.get(t, {'missing': 1})]
    log('[plan] target already has: %d ; to import: %d'
        % (len(titles) - len(missing), len(missing)))

    if CHECK_ONLY:
        src_texts = fetch_texts(SRC, titles)
        dst_texts = fetch_texts(DST, titles)
        mismatched = []
        for title in titles:
            source_text = src_texts.get(title) or ''
            target_text = dst_texts.get(title) or ''
            if source_text == target_text:
                continue
            mismatched.append((title, len(source_text), len(target_text)))
        log('[check] content mismatches: %d' % len(mismatched))
        for title, source_len, target_len in mismatched:
            state = 'missing' if title in missing else 'diff'
            log('  %-5s %-48s en=%-6d zh=%d'
                % (state, title, source_len, target_len))
        return

    if not APPLY:
        log('[plan] DRY-RUN mode: no writes. Re-run with --apply to sync.')
        return

    prepare_session()

    # 4) export + import in chunks
    t0 = time.time()
    imported = {}
    for n, chunk in enumerate(chunked(missing, CHUNK), 1):
        try:
            xml = export_pages(chunk)
        except Exception as e:
            log('[export] chunk %d FAILED: %s' % (n, e))
            continue
        try:
            result = import_pages(xml)
        except Exception as e:
            log('[import] chunk %d FAILED: %s' % (n, e))
            continue
        pages = result.get('pages', [])
        imported.update({p['title']: p.get('revisions') for p in pages})
        log('[sync] chunk %d/%d: +%d pages (%.1fs)'
            % (n, (len(missing) + CHUNK - 1) // CHUNK, len(pages),
               time.time() - t0))

    # 5) verify: content models
    log('[verify] checking content models on target ...')
    dst_models = {t: i.get('contentmodel')
                  for t, i in fetch_infos(DST, list(models)).items()}
    for title, m in models.items():
        dm = dst_models.get(title)
        if dm is None:
            log('[verify] MISSING on target: %s' % title)
        elif dm != m:
            log('[verify] model differs on %s: src=%r dst=%r -> fixing'
                % (title, m, dm))
            fix_content_model(title, m)

    # 6) verify: current wikitext equality
    log('[verify] comparing wikitext of %d pages ...' % len(models))
    src_texts = fetch_texts(SRC, list(models))
    dst_texts = fetch_texts(DST, list(models))
    ok = sum(1 for t in models if src_texts.get(t) == dst_texts.get(t))
    bad = [t for t in models if src_texts.get(t) != dst_texts.get(t)]
    log('[verify] identical: %d/%d' % (ok, len(models)))
    if bad:
        log('[verify] MISMATCH (%d): %r' % (len(bad), bad[:20]))
    log('[done] imported=%d  elapsed=%.1fs' % (len(imported),
                                               time.time() - t0))


if __name__ == '__main__':
    main()
