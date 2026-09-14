# -*- coding: utf-8 -*-
"""Show what changed on the English wiki since a timestamp, per page.

Usage: python diff_en_window.py 2026-09-13T17:50:00Z < titles.txt
"""
import difflib
import sys

import pywikibot

EN = pywikibot.Site('doorsgame', 'doorsgame')


def revision_before(title, start):
    """Content of the newest English revision at or before `start`."""
    res = EN.simple_request(action='query', prop='revisions',
                            titles=title, rvprop='ids|timestamp|content',
                            rvslots='main', rvlimit=1, rvstart=start,
                            rvdir='older', formatversion=2).submit()
    pages = res['query']['pages']
    if isinstance(pages, dict):
        pages = list(pages.values())
    page = pages[0]
    if 'missing' in page:
        return None, None
    revs = page.get('revisions') or []
    if not revs:
        return '', None
    return revs[0]['slots']['main']['content'], revs[0].get('timestamp')


def main():
    start = sys.argv[1]
    EN.login()
    titles = [ln.strip() for ln in sys.stdin.read().splitlines() if ln.strip()]
    for t in titles:
        p = pywikibot.Page(EN, t)
        if not p.exists():
            print('### MISSING', t)
            continue
        base, ts = revision_before(t, start)
        if base is None:
            print('### MISSING', t)
            continue
        d = list(difflib.unified_diff(base.splitlines(), p.text.splitlines(),
                                      'old@%s' % ts, 'new ' + t, lineterm=''))
        if not d:
            print('### %s — no change in window' % t)
            continue
        print('#' * 70)
        print('# %s  (%d changed diff lines)' % (t, len(d)))
        print('#' * 70)
        for line in d:
            print(line)


if __name__ == '__main__':
    main()
