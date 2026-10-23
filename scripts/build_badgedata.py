# -*- coding: utf-8 -*-
"""Rebuild Module:BadgeData zh from the new EN source, reusing live zh translations."""
import io
import json
import re
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from new_trans_part1 import TEXT_NEW, DIR_NEW
from new_trans_part2 import TUT_NEW
from new_trans_part3 import DIR_NEW2, TUT_NEW2
from new_trans_part4 import OVERRIDE
from new_trans_part5 import POLISH
from new_trans_part6 import DIR6, TUT6

DIR_NEW = dict(DIR_NEW); DIR_NEW.update(DIR_NEW2); DIR_NEW.update(DIR6)
TUT_NEW = dict(TUT_NEW); TUT_NEW.update(TUT_NEW2); TUT_NEW.update(TUT6)

FIELDS = ("text", "directions", "tutorial")
NEW_MAP = {"text": TEXT_NEW, "directions": DIR_NEW, "tutorial": TUT_NEW}

def unq(v):
    if v is None:
        return None
    v = v.strip()
    if v.endswith(","):
        v = v[:-1].strip()
    if v in ("nil",):
        return None
    if len(v) >= 2 and v.startswith("'") and v.endswith("'"):
        return v[1:-1].replace("\\'", "'").replace("\\\\", "\\")
    return None

def escape(v):
    return v.replace("\\", "\\\\").replace("'", "\\'")

FIELD_RE = re.compile(r"^(\t+)(text|directions|tutorial) = ('.*'|nil)\s*,?\s*$")
TITLE_RE = re.compile(r"^(\t+)title = ('.*?')\s*,?\s*$")

def parse_entries(path):
    """Return list of dicts: title + fields, in file order, tracking nearest title."""
    text = Path(path).read_text(encoding="utf-8")
    out = []
    cur = None
    for line in text.split("\n"):
        mt = TITLE_RE.match(line)
        if mt:
            cur = {"title": unq(mt.group(2))}
            out.append(cur)
            continue
        mf = FIELD_RE.match(line)
        if mf and cur is not None:
            cur[mf.group(2)] = unq(mf.group(3))
    return out

SOURCE_OLD = ROOT / "BadgeData_src.mw"
SOURCE_NEW = ROOT / "pages_src/badgedata/BadgeData_en.mw"
ZH_LIVE = ROOT / "pages_src/badgedata/BadgeData_zh.mw"
OUTPUT_MODULE = ROOT / "BadgeData_new_zh.mw"
OUTPUT_MISSING = ROOT / "badge_miss2.json"

en_old = parse_entries(SOURCE_OLD)
zh_live = parse_entries(ZH_LIVE)
en_new = parse_entries(SOURCE_NEW)
print("titles: old EN %d, live zh %d, new EN %d" % (len(en_old), len(zh_live), len(en_new)))

def group(lst):
    d = {}
    for e in lst:
        d.setdefault(e["title"], []).append(e)
    return d

zmap, omap = group(zh_live), group(en_old)
vmap = {"text": {}, "directions": {}, "tutorial": {}}
for t, olist in omap.items():
    zlist = zmap.get(t)
    if not zlist:
        continue
    for o, z in zip(olist, zlist):
        for f in FIELDS:
            ov, zv = o.get(f), z.get(f)
            if ov and zv and ov not in vmap[f]:
                vmap[f][ov] = zv
print("reuse map sizes:", {f: len(vmap[f]) for f in FIELDS})

for f in FIELDS:
    vmap[f].update(OVERRIDE[f])
    vmap[f].update(NEW_MAP[f])
    vmap[f].update(POLISH[f])

CJK = re.compile(r"[\u4e00-\u9fff]")

def norm(s):
    if not CJK.search(s):
        return s
    s = re.sub(r"\.{3,}", "……", s)
    s = re.sub(r"\.{2}", "……", s)
    s = re.sub(r"(?<=[\u4e00-\u9fff])\!+", "！", s)
    s = re.sub(r"(?<=[\u4e00-\u9fff])\?+", "？", s)
    s = re.sub(r"(?<=[\u4e00-\u9fff])\.", "。", s)
    s = re.sub(r"(?<=[\u4e00-\u9fff]),(?=[\u4e00-\u9fff])", "，", s)
    s = re.sub(r"(?<=[\u4e00-\u9fff]);", "；", s)
    s = re.sub(r"\((?=[\u4e00-\u9fff])", "（", s)
    s = re.sub(r"(?<=[\u4e00-\u9fff])\)", "）", s)
    s = re.sub(r"^在 (\[\[[^\]]+\]\]) 手下存活。$", r"躲过 \1。", s)
    s = re.sub(r"^在 (\[\[[^\]]+\]\]) 的虫群里存活。$", r"躲过一群 \1。", s)
    s = re.sub(r"^在 (\[\[[^\]]+\]\]) 的踩踏潮中存活。$", r"躲过 \1 的踩踏潮。", s)
    s = re.sub(r"^在 (\[\[[^\]]+\]\]) 危险物中存活。$", r"躲过 \1 危险物。", s)
    s = re.sub(r"^在 (\[\[[^\]]+\]\]) 面前存活。$", r"躲过 \1。", s)
    s = re.sub(r"^在 (\[\[[^\]]+\]\]) 泄漏中存活。$", r"躲过 \1 泄漏。", s)
    return s
print("combined map sizes:", {f: len(vmap[f]) for f in FIELDS})

lines = SOURCE_NEW.read_text(encoding="utf-8").split("\n")
cur_title = None
miss = {"text": [], "directions": [], "tutorial": []}
done = {"text": 0, "directions": 0, "tutorial": 0}
for i, line in enumerate(lines):
    mt = TITLE_RE.match(line)
    if mt:
        cur_title = unq(mt.group(2))
        continue
    mf = FIELD_RE.match(line)
    if not mf:
        continue
    field, raw = mf.group(2), mf.group(3)
    val = unq(raw)
    if val is None:
        continue
    zh = vmap[field].get(val)
    if zh is None:
        miss[field].append((cur_title, val))
        continue
    lines[i] = mf.group(1) + field + " = '" + escape(norm(zh)) + "',"
    done[field] += 1
print("applied:", done)
for f in FIELDS:
    print("missing %s: %d" % (f, len(miss[f])))
    for t, v in miss[f][:8]:
        print("   [%s] %s" % (t, v[:130]))
OUTPUT_MODULE.write_text("\n".join(lines), encoding="utf-8", newline="")
OUTPUT_MISSING.write_text(
    json.dumps(
        {f: [[t, v] for t, v in miss[f]] for f in FIELDS},
        ensure_ascii=False,
        indent=1,
    ) + "\n",
    encoding="utf-8",
)
print(f"written {OUTPUT_MODULE.name}", len(lines), "lines")
