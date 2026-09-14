# -*- coding: utf-8 -*-
"""Synchronize redirects from the English wiki's main namespace."""
from __future__ import annotations

import argparse
import threading
import time
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import pywikibot


_thread_state = threading.local()


def get_thread_client() -> tuple[pywikibot.Site, str]:
    if not hasattr(_thread_state, "site"):
        _thread_state.site = pywikibot.Site("zhdoors", "zhdoors")
        _thread_state.token = _thread_state.site.tokens["csrf"]
    return _thread_state.site, _thread_state.token


def normalize(title: str) -> str:
    return unicodedata.normalize("NFKC", title.replace("_", " ")).strip().casefold()


def target_text(target: str, fragment: str | None) -> str:
    if fragment:
        target = f"{target}#{fragment}"
    return f"#REDIRECT [[{target}]]"


def create_redirect(item: tuple[str, str, str | None]) -> tuple[str, str]:
    source, target, fragment = item
    site, token = get_thread_client()
    for attempt in range(4):
        try:
            site.simple_request(
                action="edit",
                title=source,
                text=target_text(target, fragment),
                summary=" ",
                token=token,
                createonly=1,
                watchlist="nochange",
            ).submit()
            return "created", source
        except pywikibot.exceptions.APIError as exc:
            if exc.code == "articleexists":
                return "exists", source
            if attempt == 3:
                return "failed", f"{source}\t{type(exc).__name__}: {exc}"
        except Exception as exc:  # pragma: no cover - remote API behavior
            if attempt == 3:
                return "failed", f"{source}\t{type(exc).__name__}: {exc}"
        time.sleep(0.5 * (attempt + 1))
    return "failed", source


def run(execute: bool, workers: int) -> int:
    en_site = pywikibot.Site("doorsgame", "doorsgame")
    zh_site = pywikibot.Site("zhdoors", "zhdoors")

    zh_titles = set()
    for namespace in (0, 2, 4, 6, 8, 10, 12, 14, 828):
        zh_titles.update(normalize(page.title()) for page in zh_site.allpages(namespace=namespace))

    redirect_titles = [
        page.title() for page in en_site.allpages(namespace=0, filterredir=True)
    ]
    candidates: list[tuple[str, str, str | None]] = []

    for offset in range(0, len(redirect_titles), 50):
        batch = redirect_titles[offset : offset + 50]
        data = en_site.simple_request(
            action="query",
            titles="|".join(batch),
            redirects=1,
            prop="info",
        ).submit()
        for redirect in data.get("query", {}).get("redirects", []):
            source = redirect.get("from", "")
            target = redirect.get("to", "")
            fragment = redirect.get("tofragment")
            if not source or not target:
                continue
            if normalize(source) in zh_titles:
                continue
            if normalize(target) not in zh_titles:
                continue

            target_page = pywikibot.Page(zh_site, target)
            if target_page.namespace().id in (-1, 6, 8):
                continue

            candidates.append((source, target, fragment))

    counts = Counter(target.split(":", 1)[0] if ":" in target else "(main)" for _, target, _ in candidates)
    print(f"Redirect pages on English wiki: {len(redirect_titles)}")
    print(f"Missing and safely syncable: {len(candidates)}")
    print("By target namespace:", dict(sorted(counts.items())))

    if not execute:
        return 0

    created = 0
    skipped = 0
    failed: list[str] = []
    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(create_redirect, item) for item in candidates]
        for future in as_completed(futures):
            status, detail = future.result()
            completed += 1
            if status == "created":
                created += 1
            elif status == "exists":
                skipped += 1
            else:
                failed.append(detail)
            if completed % 25 == 0 or completed == len(candidates):
                print(f"Progress: {completed}/{len(candidates)}", flush=True)

    print(f"Created: {created}")
    print(f"Already existed: {skipped}")
    print(f"Failed: {len(failed)}")
    for error in failed:
        print(f"FAILED\t{error}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    return run(args.execute, args.workers)


if __name__ == "__main__":
    raise SystemExit(main())
