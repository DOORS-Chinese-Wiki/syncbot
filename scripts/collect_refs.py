# -*- coding: utf-8 -*-
"""Collect referenced pages on zh wiki; cross-check with EN wiki (read-only)."""
import json
import time
from collections import Counter, defaultdict
from datetime import datetime

import pywikibot

zh = pywikibot.Site("zhdoors", "zhdoors")
en = pywikibot.Site("doorsgame", "doorsgame")


def enum_full(site, module, params, tag):
    items = []
    cont = {}
    n = 0
    while True:
        req = site.simple_request(action="query", list=module, formatversion=2, **params, **cont)
        data = req.submit()
        items.extend(data.get("query", {}).get(module, []))
        n += 1
        if n % 10 == 0:
            print("  [%s] batches=%d items=%d" % (tag, n, len(items)), flush=True)
        if "continue" in data:
            cont = data["continue"]
        else:
            break
    return items


def batch_info(site, titles, chunk=50, tag=""):
    out = {}
    titles = sorted(titles)
    total = (len(titles) + chunk - 1) // chunk
    done = 0
    for i in range(0, len(titles), chunk):
        ct = titles[i:i + chunk]
        req = site.simple_request(
            action="query", prop="info|revisions", rvprop="timestamp",
            titles="|".join(ct), formatversion=2)
        data = req.submit()
        q = data.get("query", {})
        norm = {x["from"]: x["to"] for x in q.get("normalized", [])}
        pages = {p["title"]: p for p in q.get("pages", [])}
        for t in ct:
            key = norm.get(t, t)
            p = pages.get(key)
            if p is None:
                out[t] = {"missing": True, "redirect": False, "touch": None, "ns": None}
            else:
                revs = p.get("revisions") or []
                out[t] = {
                    "missing": p.get("missing", False),
                    "redirect": p.get("redirect", False),
                    "touch": revs[0].get("timestamp") if revs else None,
                    "ns": p.get("ns"),
                }
        done += 1
        if done % 5 == 0 or done == total:
            print("  [%s] %d/%d batches" % (tag, done, total), flush=True)
        time.sleep(0.1)
    return out


def parse_ts(s):
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# 1. namespaces + stats
req = zh.simple_request(action="query", meta="siteinfo", siprop="namespaces|statistics", formatversion=2)
data = req.submit()
stats = data["query"]["statistics"]
ns_ids = [int(k) for k in data["query"]["namespaces"] if int(k) >= 0]
print("zh stats:", json.dumps(stats), flush=True)
print("namespaces:", ns_ids, flush=True)

# 2. full enumeration of references (with duplicates => counts)
link_count = Counter()
tr_count = Counter()
fu_count = Counter()
for ns in ns_ids:
    items = enum_full(zh, "alllinks", {"allimit": "max", "alnamespace": ns}, "alllinks ns%d" % ns)
    link_count.update((it["ns"], it["title"]) for it in items)
for ns in ns_ids:
    items = enum_full(zh, "alltransclusions", {"atlimit": "max", "atnamespace": ns}, "transcl ns%d" % ns)
    tr_count.update((it["ns"], it["title"]) for it in items)
items = enum_full(zh, "allfileusages", {"aflimit": "max"}, "fileusages")  # MW 1.45 renamed au* -> af*
fu_count.update((it["ns"], it["title"]) for it in items)

print("unique linked:", len(link_count), "| unique transcluded:", len(tr_count),
      "| unique files used:", len(fu_count), flush=True)

all_refs = set(link_count) | set(tr_count) | set(fu_count)
print("total unique referenced titles:", len(all_refs), flush=True)

# 3. existence + last edit on zh and en
ref_titles = sorted(t for (_ns, t) in all_refs)
print("querying zh info for %d titles..." % len(ref_titles), flush=True)
zh_info = batch_info(zh, ref_titles, tag="zh")
print("querying en info for %d titles (read-only)..." % len(ref_titles), flush=True)
en_info = batch_info(en, ref_titles, tag="en")

# 4. compose records
records = []
for (ns, title) in sorted(all_refs):
    zi = zh_info.get(title, {"missing": True, "redirect": False, "touch": None, "ns": ns})
    ei = en_info.get(title, {"missing": True, "redirect": False, "touch": None, "ns": ns})
    zh_exists = not zi.get("missing", True)
    en_exists = not ei.get("missing", True)
    zt, et = parse_ts(zi.get("touch")), parse_ts(ei.get("touch"))
    if zh_exists and en_exists:
        if zt and et:
            diff = (zt - et).total_seconds() / 86400.0
            if abs(diff) <= 1.5:
                status = "同步"
            elif diff > 0:
                status = "zh较新(EN之后有本地改动)"
            else:
                status = "落后EN %.0f天" % (-diff)
        else:
            status = "时间未知"
    elif zh_exists and not en_exists:
        status = "zh原创页(EN无对应)"
    elif (not zh_exists) and en_exists:
        status = "待翻译"
    else:
        status = "失效引用(两站均不存在)"
    records.append({
        "ns": ns, "title": title,
        "links": link_count.get((ns, title), 0),
        "transclusions": tr_count.get((ns, title), 0),
        "fileuses": fu_count.get((ns, title), 0),
        "zh_exists": zh_exists, "zh_redirect": zi.get("redirect", False), "zh_touch": zi.get("touch"),
        "en_exists": en_exists, "en_redirect": ei.get("redirect", False), "en_touch": ei.get("touch"),
        "status": status,
    })

with open("refs_data.json", "w", encoding="utf-8") as f:
    json.dump({"stats": stats, "records": records}, f, ensure_ascii=False, indent=1)
print("saved refs_data.json (%d records)" % len(records), flush=True)

# 5. summary
summ = defaultdict(Counter)
for r in records:
    if r["ns"] == 6:
        cat = "文件"
    elif r["ns"] == 10:
        cat = "模板"
    elif r["ns"] == 828:
        cat = "模块"
    elif r["ns"] == 0:
        cat = "内容页"
    else:
        cat = "其他(ns%d)" % r["ns"]
    summ[cat][r["status"]] += 1
print("", flush=True)
print("===== SUMMARY =====", flush=True)
for cat in sorted(summ):
    print("-- %s --" % cat, flush=True)
    for st, c in summ[cat].most_common():
        print("   %-40s %d" % (st, c), flush=True)
