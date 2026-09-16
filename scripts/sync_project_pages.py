# -*- coding: utf-8 -*-
"""同步 DOORS Wiki 项目命名空间页面（沿用仓库既有同步流程）。

约定与 sync_templates.py / push_templates.py 一致：
  1. 英文站源码 -> pages_src/project/<名称>.en.mw
  2. 中文译文   -> pages_zh/project/<名称>.zh.mw
  3. 推送清单   -> push_project_<日期>.json  （[["标题", "路径"], ...]）
  4. 推送       -> pywikibot page.put(text, summary=" ")

用法：
    python scripts/sync_project_pages.py --fetch      # 抓英文站 DOORS Wiki 命名空间
    python scripts/sync_project_pages.py --pull-zh    # 抓中文站当前正文
    python scripts/sync_project_pages.py --manifest   # 生成推送清单
    python scripts/sync_project_pages.py --push       # 执行推送
    （不带参数 = 全部 dry-run，只报告差异）
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import pywikibot

sys.stdout.reconfigure(encoding="utf-8")

EN_NS = 4            # 英文站 DOORS Wiki 命名空间
ZH_PREFIX = "DOORS Wiki:"   # 中文站对应的标题前缀（主命名空间伪命名空间）
SRC_DIR = Path("pages_src/project")
ZH_DIR = Path("pages_zh/project")


def fname(title: str) -> str:
    name = title.split(":", 1)[1] if ":" in title else title
    return name.replace("/", "__")


def en_pages(site) -> list[str]:
    return [p.title() for p in site.allpages(namespace=EN_NS)]


def zh_pages(site) -> list[str]:
    return [p.title() for p in site.allpages(namespace=0, prefix=ZH_PREFIX)]


def fetch_en(execute: bool) -> int:
    en = pywikibot.Site("doorsgame", "doorsgame")
    titles = en_pages(en)
    print("英文站 ns4 页面: %d" % len(titles))
    if not execute:
        for t in titles:
            print("   ", t)
        return 0
    SRC_DIR.mkdir(parents=True, exist_ok=True)
    for t in titles:
        page = pywikibot.Page(en, t)
        path = SRC_DIR / (fname(t) + ".en.mw")
        path.write_text(page.text, encoding="utf-8")
        print("FETCH-EN %-44s -> %s (%d)" % (t, path.name, len(page.text)))
    return 0


def pull_zh(execute: bool) -> int:
    zh = pywikibot.Site("zhdoors", "zhdoors")
    titles = zh_pages(zh)
    print("中文站 %s 页面: %d" % (ZH_PREFIX, len(titles)))
    if not execute:
        for t in titles:
            print("   ", t)
        return 0
    ZH_DIR.mkdir(parents=True, exist_ok=True)
    for t in titles:
        page = pywikibot.Page(zh, t)
        path = ZH_DIR / (fname(t) + ".zh.mw")
        path.write_text(page.text, encoding="utf-8")
        print("PULL-ZH  %-44s -> %s (%d)" % (t, path.name, len(page.text)))
    return 0


def zh_titles_from_disk() -> list[str]:
    return sorted(p.stem[:-3] for p in ZH_DIR.glob("*.zh.mw"))


def manifest_path() -> Path:
    """项目命名空间清单固定为 manifests/project.json（见 manifests/README.md）。"""
    return Path("manifests/project.json")


def build_manifest(execute: bool) -> int:
    entries = []
    for stem in zh_titles_from_disk():
        name = stem.replace("__", "/")
        entries.append([ZH_PREFIX + name,
                        (ZH_DIR / (stem + ".zh.mw")).as_posix()])
    print("清单条目: %d" % len(entries))
    path = manifest_path()
    if execute:
        path.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
        print("已写入", path)
    return 0


def report() -> int:
    """列出英文站有、中文站还没译的页面，以及中文站独有的页面。"""
    en = pywikibot.Site("doorsgame", "doorsgame")
    en_names = {fname(t) for t in en_pages(en)}
    zh_names = set(zh_titles_from_disk())
    pending = sorted(en_names - zh_names)
    extra = sorted(zh_names - en_names)
    print("英文站 ns4 页面 %d，中文站 %s 页面 %d" % (len(en_names), ZH_PREFIX, len(zh_names)))
    print("待翻译（英文站有、中文站缺）: %d" % len(pending))
    for name in pending:
        print("   ", name.replace("__", "/"))
    print("中文站独有: %d" % len(extra))
    for name in extra:
        print("   ", name.replace("__", "/"))
    return 0


def push(execute: bool, force: bool = False, only: str | None = None) -> int:
    path = manifest_path()
    if not path.exists():
        print("清单不存在，先跑 --manifest:", path)
        return 1
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if only:
        manifest = [item for item in manifest if item[0] == only]
    zh = pywikibot.Site("zhdoors", "zhdoors")
    zh.login()
    changed = same = failed = 0
    for title, rel in manifest:
        text = Path(rel).read_text(encoding="utf-8")
        page = pywikibot.Page(zh, title)
        current = page.text if page.exists() else None
        if current == text and not force:
            same += 1
            print("SAME     %-44s" % title)
            continue
        if not execute:
            changed += 1
            print("WOULD PUSH %-42s (%d -> %d)" % (title, len(current or ""), len(text)))
            continue
        try:
            page.put(text, summary=" ")
            changed += 1
            print("PUSHED   %-44s revid=%s" % (title, page.latest_revision_id))
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print("FAILED   %-44s %s" % (title, repr(exc)[:160]))
    print("--- 需推送 %d，已一致 %d，失败 %d" % (changed, same, failed))
    return 0


# 旧 Project: 命名空间 / 中文别名 -> 新页面的重定向。
# MediaWiki 的 aboutpage / disclaimerpage / copyrightpage 等界面消息默认指向
# {{ns:project}}:X；英文站的 {{ns:project}} 就是 DOORS Wiki，中文站叫 Project，
# 因此这些链接会落到空页面，需要在这里补重定向。
LEGACY_REDIRECTS = {
    "Project:关于": "DOORS Wiki:About",
    "Project:免责声明": "DOORS Wiki:General disclaimer",
    "Project:著作权": "DOORS Wiki:Copyrights",
    "Project:Contributors": "DOORS Wiki:Wiki Contributors",
    "Project:方针": "DOORS Wiki:Policies",
    "Project:规则": "DOORS Wiki:Rules",
    "Project:格式手册": "DOORS Wiki:Manual of Style",
    "Project:工作人员": "DOORS Wiki:Staff",
    "Project:用户权限": "DOORS Wiki:User rights",
    "Project:图片方针": "DOORS Wiki:Image policy",
    "Project:版权方针": "DOORS Wiki:Copyright",
    "Project:渲染图方针": "DOORS Wiki:Render policy",
    "Project:AI 方针": "DOORS Wiki:AI policy",
    "Project:收录标准": "DOORS Wiki:Notability",
    "Project:贡献者": "DOORS Wiki:Wiki Contributors",
    "Project:条目视频化": "DOORS Wiki:计划/条目视频化",
}

# 已存在但目标写错的重定向（改名过程中产生）
REDIRECT_REPAIRS = {
    "Rules": "DOORS Wiki:Rules",   # 目标误写成小写的 Doors Wiki:Rules
}

# 页脚链接的界面消息改指新页面（需要 interface-admin）
MESSAGE_OVERRIDES = {
    "MediaWiki:Aboutpage": "DOORS Wiki:About",
    "MediaWiki:Disclaimerpage": "DOORS Wiki:General disclaimer",
    "MediaWiki:Copyrightpage": "DOORS Wiki:Copyrights",
}


def sync_redirects(execute: bool) -> int:
    zh = pywikibot.Site("zhdoors", "zhdoors")
    created = existing = repaired = failed = 0
    for source, target in sorted(LEGACY_REDIRECTS.items()):
        page = pywikibot.Page(zh, source)
        if page.exists():
            existing += 1
            print("已存在  %-24s -> %s" % (source, page.getRedirectTarget().title()))
            continue
        if not execute:
            print("将创建  %-24s -> %s" % (source, target))
            continue
        try:
            page.text = "#REDIRECT [[%s]]" % target
            page.save(summary=" ", createonly=True)
            created += 1
            print("已创建  %-24s -> %s" % (source, target))
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print("失败    %-24s %s" % (source, repr(exc)[:140]))
    for source, target in sorted(REDIRECT_REPAIRS.items()):
        page = pywikibot.Page(zh, source)
        want = "#REDIRECT [[%s]]" % target
        if not page.exists():
            print("缺失    %-24s（应重定向到 %s）" % (source, target))
            continue
        if page.text.strip() == want:
            print("无需修  %-24s -> %s" % (source, target))
            continue
        if not execute:
            print("将修正  %-24s -> %s（当前 %r）" % (source, target, page.text.strip()[:60]))
            continue
        page.text = want
        page.save(summary=" ")
        repaired += 1
        print("已修正  %-24s -> %s" % (source, target))
    print("--- 新建 %d，已存在 %d，修正 %d，失败 %d" % (created, existing, repaired, failed))
    return 0


def override_messages(execute: bool) -> int:
    zh = pywikibot.Site("zhdoors", "zhdoors")
    for title, value in sorted(MESSAGE_OVERRIDES.items()):
        page = pywikibot.Page(zh, title)
        current = page.text if page.exists() else None
        if current == value:
            print("已一致  %-28s = %s" % (title, value))
            continue
        if not execute:
            print("将覆盖  %-28s %r -> %r" % (title, current, value))
            continue
        page.text = value
        page.save(summary="页脚链接改指 DOORS Wiki: 命名空间页面")
        print("已覆盖  %-28s = %s" % (title, value))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch", action="store_true", help="抓取英文站源码")
    parser.add_argument("--pull-zh", action="store_true", help="抓取中文站正文")
    parser.add_argument("--manifest", action="store_true", help="生成推送清单")
    parser.add_argument("--push", action="store_true", help="执行推送")
    parser.add_argument("--report", action="store_true", help="列出待翻译与中文站独有页面")
    parser.add_argument("--redirects", action="store_true", help="补齐旧 Project:/中文别名重定向并修正错误重定向")
    parser.add_argument("--messages", action="store_true", help="把页脚界面消息改指新页面")
    parser.add_argument("--apply", action="store_true", help="实际写入（默认 dry-run）")
    parser.add_argument("--force", action="store_true", help="内容一致时也推送（校验推送链路）")
    parser.add_argument("--only", help="只处理指定标题")
    args = parser.parse_args()
    if args.fetch:
        return fetch_en(args.apply)
    if args.pull_zh:
        return pull_zh(args.apply)
    if args.manifest:
        return build_manifest(args.apply)
    if args.report:
        return report()
    if args.redirects:
        return sync_redirects(args.apply)
    if args.messages:
        return override_messages(args.apply)
    if args.push:
        return push(args.apply, args.force, args.only)
    # 无参数：全流程 dry-run
    fetch_en(False)
    pull_zh(False)
    build_manifest(False)
    return push(False)


if __name__ == "__main__":
    raise SystemExit(main())
