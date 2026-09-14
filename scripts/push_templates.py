# -*- coding: utf-8 -*-
"""推送模板文件到 zh 维基（编辑摘要为单个空格）。用法：python push_templates.py manifest.json"""
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import pywikibot
from pathlib import Path
zh = pywikibot.Site("zhdoors", "zhdoors")
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
for title, path in manifest:
    if isinstance(path, list):
        text = "\n".join(Path(part).read_text(encoding="utf-8") for part in path)
    else:
        text = Path(path).read_text(encoding="utf-8")
    page = pywikibot.Page(zh, title)
    page.put(text, summary=" ")
    print("PUSHED %-46s len=%-6d revid=%s" % (title, len(text), page.latest_revision_id))
