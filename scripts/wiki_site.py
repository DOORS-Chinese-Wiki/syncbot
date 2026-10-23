# -*- coding: utf-8 -*-
"""统一的中文站 Site 入口。

账号策略（2026-10-09 起）：
  * 默认 DesignBot（bot 用户组）—— 所有常规内容/模板/模块编辑都用它，
    编辑不占最近更改。
  * 以下三类 DesignBot 改不了，必须用 Yatmt（sysop + interface-admin）：
      1. MediaWiki: 等界面命名空间（需要 editinterface）
      2. 受保护的页面（需要 editprotected）—— 例如首页 DOORS Wiki
      3. 删除/移动等管理操作

用法：
    from wiki_site import site_zh, login_zh, page_zh, page_zh_auto
    site = site_zh()                    # DesignBot
    site = site_zh(for_interface=True)  # Yatmt（界面页）
    p = page_zh_auto("DOORS Wiki")      # 自动判断：受保护 -> Yatmt
"""
import pywikibot

ZH_FAMILY = "zhdoors"
ZH_LANG = "zhdoors"

# MediaWiki: 命名空间需要 editinterface；DesignBot 没有该权限
INTERFACE_PREFIXES = ("MediaWiki:", "MediaWiki talk:", "Gadget definition:",
                      "Gadget:", "User:Gadget")


def is_interface_title(title: str) -> bool:
    """判断标题是否落在 DesignBot 无法编辑的界面命名空间。"""
    t = title.strip()
    return any(t.startswith(p) for p in INTERFACE_PREFIXES)


def is_protected(title: str) -> bool:
    """页面是否被保护到 DesignBot 无法编辑（需要 editprotected）。

    只读查询，失败时返回 False（宁可让保存时报错，也不要误用高权限账号）。
    """
    try:
        site = pywikibot.Site(ZH_FAMILY, ZH_LANG)
        prot = pywikibot.Page(site, title).protection()
    except Exception:
        return False
    edit = prot.get("edit")
    if not edit:
        return False
    levels = edit[0] if isinstance(edit, (tuple, list)) else edit
    if isinstance(levels, str):
        levels = [levels]
    # DesignBot 只有 bot/user/autoconfirmed，任何 sysop/autoconfirmed 以上限制都要换号
    return any(lv in ("sysop", "interface-admin", "editinterface", "editprotected",
                      "templateeditor", "accountcreator") for lv in (levels or []))


def needs_yatmt(title: str | None) -> bool:
    """综合判断某标题是否需要 Yatmt。"""
    if title is None:
        return False
    return is_interface_title(title) or is_protected(title)


def site_zh(for_interface: bool = False, title: str | None = None) -> "pywikibot.Site":
    """返回中文站 Site。

    for_interface=True，或 title 属于界面命名空间/受保护页面时，使用 Yatmt。
    """
    use_yatmt = for_interface or needs_yatmt(title)
    if use_yatmt:
        return pywikibot.Site(ZH_FAMILY, ZH_LANG, user="Yatmt")
    return pywikibot.Site(ZH_FAMILY, ZH_LANG)


def login_zh(for_interface: bool = False, title: str | None = None) -> "pywikibot.Site":
    """返回并登录中文站 Site。"""
    s = site_zh(for_interface=for_interface, title=title)
    s.login()
    return s


def page_zh(title: str) -> "pywikibot.Page":
    """按标题自动挑选账号的 Page 对象（含受保护页判断）。"""
    return pywikibot.Page(site_zh(title=title), title)


# 便于其他脚本沿用旧名
page_zh_auto = page_zh

# ---------------------------------------------------------------------------
# 保存：一律不写编辑摘要（2026-10-10 起）
# ---------------------------------------------------------------------------
# 用法：
#     import wiki_site
#     wiki_site.save_zh("某页面", 新文本)          # 自动选账号 + 不写摘要
#
# pywikibot 传 summary="" 即可留空摘要，不会弹交互提示。
# pywikibot 在 summary="" 时会填 config.default_edit_summary（默认 "Pywikibot x.y.z"），
# 必须显式清空，摘要才是真的空。
pywikibot.config.default_edit_summary = ""


def save_zh(title, text, minor=False):
    site = login_zh(title=title)
    page = pywikibot.Page(site, title)
    page.text = text
    page.save(summary="", minor=minor)
    return page
