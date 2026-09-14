# -*- coding: utf-8 -*-
"""Generate 被引用页面与翻译情况.md from refs_data.json."""
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

data = json.load(open("refs_data.json", encoding="utf-8"))
recs = data["records"]
stats = data["stats"]

CAT_ORDER = ["内容页", "模板", "模块", "文件", "其他"]
NS_LABEL = {0: "(主)", 2: "用户", 4: "项目", 6: "文件", 8: "MediaWiki", 10: "模板",
            12: "帮助", 14: "分类", 828: "模块", 829: "模块讨论", 1502: "博客", 502: "用户博客"}

def cat_of(r):
    if r["ns"] == 0: return "内容页"
    if r["ns"] == 10: return "模板"
    if r["ns"] == 828: return "模块"
    if r["ns"] == 6: return "文件"
    return "其他"

def title_disp(r):
    t = r["title"]
    ns = r["ns"]
    if ns in (10, 828):
        return t.split(":", 1)[1] if ":" in t else t
    return t

def d8(s):
    return (s or "")[:10] or "-"

CAT_OF_ROW = {}
for r in recs:
    CAT_OF_ROW[(r["ns"], r["title"])] = cat_of(r)

gen_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")

cats = defaultdict(list)
for r in recs:
    cats[cat_of(r)].append(r)

STATUS_REWRITE = {
    "同步": "已翻译 · 与EN同步",
    "zh较新(EN之后有本地改动)": "已翻译 · zh较新",
}

def status_cell(r):
    st = r["status"]
    if r["ns"] == 6 and st == "待翻译":
        return "EN 文件库共享（无需处理）"
    if st in STATUS_REWRITE:
        return STATUS_REWRITE[st]
    if st == "zh原创页(EN无对应)":
        return "zh 原创（EN 无对应页）"
    if st == "失效引用(两站均不存在)":
        return "**失效引用**（两站均不存在）"
    if st == "时间未知":
        return "已翻译 · 时间未知"
    if st.startswith("落后EN"):
        return "已翻译 · " + st
    if st == "待翻译":
        return "**待翻译**"
    return st

def zh_cell(r):
    if r["zh_exists"]: return "✅" + ("（重定向）" if r["zh_redirect"] else "")
    return "❌"

def en_cell(r):
    if r["en_exists"]: return "✅" + ("（重定向）" if r["en_redirect"] else "")
    return "❌"

def ref_cell(r):
    parts = []
    if r["links"]: parts.append("链接%d" % r["links"])
    if r["transclusions"]: parts.append("嵌入%d" % r["transclusions"])
    if r["fileuses"]: parts.append("使用%d" % r["fileuses"])
    return " / ".join(parts)

out = []
out.append("# DOORS 中文维基 · 被引用页面与翻译情况")
out.append("")
out.append("- 生成时间：%s（UTC+8）" % gen_time)
out.append("- 中文站：[zh.doorsgame.wiki](https://zh.doorsgame.wiki)（%s 篇内容页 / %s 页面 / %s 文件）" % (
    stats.get("articles"), stats.get("pages"), stats.get("images")))
out.append("- 英文站：[doorsgame.wiki](https://doorsgame.wiki)（只读查询，未做任何编辑）")
out.append("- 统计口径：zh 站现有页面发出的全部 [[链接]]、{{模板嵌入}} 与文件使用；共 **%d** 个被引用的不同页面标题。" % len(recs))
out.append("- 翻译判断：同名对照（zh 标题 = EN 标题）；“同步/落后”比较两侧最后编辑时间（容差 1.5 天）。")
out.append("- 文件说明：中文站的文件资源直接使用英文维基的文件数据库（共享库），zh 本地未上传属正常现象，无需处理；zh ✅ 表示已额外上传到本地。")
out.append("")

# overview
out.append("## 总览")
out.append("")
out.append("| 分类 | 页面数 | 待翻译 | 已翻译·同步 | 已翻译·zh较新 | 已翻译·落后EN | zh原创 | 失效引用 | EN文件库共享 |")
out.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
def bucket(r):
    st = r["status"]
    if r["ns"] == 6 and st == "待翻译": return "enlib"
    if st == "待翻译": return "tbt"
    if st == "同步": return "sync"
    if st.startswith("zh较新"): return "newer"
    if st.startswith("落后EN"): return "behind"
    if st.startswith("zh原创"): return "orig"
    if st.startswith("失效引用"): return "dead"
    return "other"

ov = defaultdict(Counter)
for r in recs:
    ov[cat_of(r)][bucket(r)] += 1
tot = Counter()
for c in CAT_ORDER:
    cc = ov.get(c, Counter())
    for k in cc: tot[k] += cc[k]
    out.append("| **%s** | %d | %d | %d | %d | %d | %d | %d | %d |" % (c,
        sum(cc.values()), cc["tbt"], cc["sync"], cc["newer"], cc["behind"], cc["orig"], cc["dead"], cc["enlib"]))
out.append("| **合计** | %d | %d | %d | %d | %d | %d | %d | %d |" % (
    sum(tot.values()), tot["tbt"], tot["sync"], tot["newer"], tot["behind"], tot["orig"], tot["dead"], tot["enlib"]))
out.append("")

# focus paragraphs
out.append("## 翻译优先级建议（内容页 · 待翻译，按被引用次数排序）")
out.append("")
miss0 = sorted([r for r in cats["内容页"] if bucket(r) == "tbt"],
               key=lambda r: -(r["links"] + r["transclusions"]))
out.append("以下 **%d** 个内容页在 zh 站被大量引用但尚未创建，全部在英文站存在、可直接作为翻译源：" % len(miss0))
out.append("")
out.append("| # | 页面 | 被引用 | EN 最后编辑 |")
out.append("|--:|---|---|---|")
for i, r in enumerate(miss0[:30], 1):
    out.append("| %d | %s | %d | %s |" % (i, r["title"], r["links"] + r["transclusions"], d8(r["en_touch"])))
if len(miss0) > 30:
    out.append("")
    out.append("（其余 %d 个见下方完整表格）" % (len(miss0) - 30))
out.append("")

def md_table(rows, opts):
    buf = []
    buf.append("| 页面 | 被引用 | zh | EN | 翻译情况 | zh 最后编辑 | EN 最后编辑 |")
    buf.append("|---|---|---|---|---|---|---|")
    for r in rows:
        buf.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            title_disp(r), ref_cell(r), zh_cell(r), en_cell(r), status_cell(r),
            d8(r["zh_touch"]), d8(r["en_touch"])))
    return buf

opts = {
    "内容页": ("-r.links -r.transclusions"),
    "模板": ("-r.transclusions -r.links"),
    "模块": ("-r.transclusions -r.links"),
    "文件": ("-r.fileuses -r.title.lower()"),
    "其他": ("-r.title"),
}
INTRO = {
    "内容页": "主命名空间被引用页面（实体、地点、机制、活动等）。",
    "模板": "Template: 命名空间被嵌入模板。zh 较新 = 团队已翻译并推送。",
    "模块": "Module: 命名空间（Lua）。",
    "文件": "被使用的 File: 文件。中文站共享使用英文维基文件数据库，本地未上传属正常（EN 文件库共享）；zh ✅ = 已上传本地。",
    "其他": "其余命名空间（用户、项目、分类、MediaWiki 等）。",
}
SORT_KEY = {
    "内容页": lambda r: (-(r["links"] + r["transclusions"]), r["title"].lower()),
    "模板": lambda r: (-r["transclusions"], -r["links"], r["title"].lower()),
    "模块": lambda r: (-r["transclusions"], -r["links"], r["title"].lower()),
    "文件": lambda r: (-r["fileuses"], r["title"].lower()),
    "其他": lambda r: r["title"].lower(),
}

for c in CAT_ORDER:
    rows = cats.get(c, [])
    if not rows:
        continue
    out.append("")
    out.append("## %s（%d）" % (c, len(rows)))
    out.append("")
    out.append(INTRO[c])
    out.append("")
    rows = sorted(rows, key=SORT_KEY[c])
    out.extend(md_table(rows, opts))

md = "\n".join(out) + "\n"
with open("被引用页面与翻译情况.md", "w", encoding="utf-8") as f:
    f.write(md)
print("written 被引用页面与翻译情况.md:", len(md.encode("utf-8")), "bytes,", md.count(chr(10)), "lines")
