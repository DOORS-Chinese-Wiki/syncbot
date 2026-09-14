# -*- coding: utf-8 -*-
"""Run a literal replacement through Special:MassEditRegex using pywikibot's
authenticated HTTP session.

Usage:
    python scripts/massedit_regex.py preview "钉上十字架" "封印" "统一译名"
    python scripts/massedit_regex.py execute "钉上十字架" "封印" "统一译名"
"""
from __future__ import annotations

import argparse
import html
import re
import sys
import time
from urllib.parse import quote

import pywikibot
import pywikibot.comms.http as http


USER_AGENT = "Yatmt/DOORS-Wiki-maintenance (contact: Yatmt; pywikibot)"


def find_matching_pages(site: pywikibot.Site, needle: str) -> list[str]:
    """Scan content namespaces for pages containing a literal string."""
    namespaces = [0, 4, 8, 10, 12, 14, 828]
    titles: list[str] = []
    for namespace in namespaces:
        titles.extend(page.title() for page in site.allpages(namespace=namespace))
    titles = list(dict.fromkeys(titles))

    matches: list[str] = []
    for offset in range(0, len(titles), 40):
        batch = titles[offset : offset + 40]
        last_error: Exception | None = None
        for _ in range(3):
            try:
                data = site.simple_request(
                    action="query",
                    titles="|".join(batch),
                    prop="revisions",
                    rvprop="content",
                    rvslots="main",
                ).submit()
                break
            except Exception as exc:  # pragma: no cover - depends on remote API
                last_error = exc
                time.sleep(2)
        else:
            raise RuntimeError(f"Failed to scan titles at offset {offset}") from last_error

        for page in data.get("query", {}).get("pages", {}).values():
            revisions = page.get("revisions") or [{}]
            slots = revisions[0].get("slots") or {}
            text = (slots.get("main") or {}).get("*", "")
            if needle in text:
                matches.append(page["title"])
    return matches


def submit_massedit(
    site: pywikibot.Site,
    pages: list[str],
    match: str,
    replace: str,
    summary: str,
    execute: bool,
) -> str:
    """Submit the MassEditRegex form using pywikibot's authenticated session."""
    headers = {"User-Agent": USER_AGENT}
    special_url = f"{site.protocol()}://{site.hostname()}/wiki/Special:MassEditRegex"
    response = http.session.get(special_url, headers=headers)
    response.raise_for_status()

    token_tag = re.search(
        r"<input[^>]+name=\"wpEditToken\"[^>]*>",
        response.text,
        re.IGNORECASE,
    )
    token_match = (
        re.search(r'value="([^"]+)"', token_tag.group(0), re.IGNORECASE)
        if token_tag
        else None
    )
    if not token_match:
        raise RuntimeError("Could not find MassEditRegex edit token")

    data = {
        "wpPageList": "\n".join(pages),
        "wpPageListType": "pagenames",
        "wpMatch": match,
        "wpReplace": replace,
        "wpSummary": summary,
        "wpEditToken": html.unescape(token_match.group(1)),
    }
    data["wpSave" if execute else "wpPreview"] = "执行" if execute else "显示预览"

    response = http.session.post(
        special_url + "?action=submit",
        data=data,
        headers=headers,
    )
    response.raise_for_status()
    return response.text


def summarize_response(document: str) -> str:
    """Return compact, human-readable lines instead of the full HTML page."""
    plain = re.sub(r"<script\b.*?</script>", " ", document, flags=re.S | re.I)
    plain = re.sub(r"<style\b.*?</style>", " ", plain, flags=re.S | re.I)
    plain = re.sub(r"<[^>]+>", "\n", plain)
    plain = html.unescape(plain)
    lines = []
    for line in plain.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        if any(
            key in line
            for key in (
                "页面",
                "预览",
                "替换",
                "编辑",
                "错误",
                "找不到",
                "没有任何",
                "已保存",
            )
        ):
            lines.append(line)
    return "\n".join(dict.fromkeys(lines))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("preview", "execute"))
    parser.add_argument("match")
    parser.add_argument("replace")
    parser.add_argument("summary")
    args = parser.parse_args()

    site = pywikibot.Site("zhdoors", "zhdoors")
    pages = find_matching_pages(site, args.match)
    print(f"Matched pages: {len(pages)}", flush=True)
    for title in pages:
        print(title)

    result = submit_massedit(
        site,
        pages,
        args.match,
        args.replace,
        args.summary,
        execute=args.mode == "execute",
    )
    summary = summarize_response(result)
    if summary:
        print(summary)
    print(f"MassEditRegex {args.mode} request completed for {len(pages)} pages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
