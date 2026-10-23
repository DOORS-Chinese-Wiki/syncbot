# -*- coding: utf-8 -*-
"""Synchronize ModifierData between the English wiki, Grist and Chinese wiki.

English Module:ModifierData is the structural source of truth. Grist owns the
Chinese description field; the rendered Chinese module falls back to the
English description until a translation is entered.

Usage:
    python scripts/modifiers_sync.py sync
    python scripts/modifiers_sync.py sync --apply
    python scripts/modifiers_sync.py dump
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import time
from typing import Any

import pywikibot
import requests

import achievements_sync as A

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / "data" / "modifiers_sync_state.json"
BACKUP_DIR = ROOT / "scripts" / "_wiki_facts" / "modifiers" / "backup"

SOURCE_SITE = pywikibot.Site("doorsgame", "doorsgame")
TARGET_SITE = pywikibot.Site("zhdoors", "zhdoors")
SOURCE_PAGE = "Module:ModifierData"
TARGET_PAGE = "Module:ModifierData"

CATEGORY_ORDER = [
    "Challenge",
    "Highlight",
    "Random",
    "Normal",
    "Player",
    "Entity",
    "Testing",
    "Removed",
    "Upcoming",
    "Scrapped",
]

TABLE_FIELDS = [
    "key",
    "category",
    "title",
    "description",
    "description_en",
    "requirements",
    "exclusive",
    "knobs",
    "rift",
    "progress",
    "group",
    "reason",
    "wiki_rev",
    "row_hash",
    "sync_status",
]

GRIST_TABLE = "Modifiers"
GRIST_ID_FIELD = "_id"


def field_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def parse_requirements(raw: str) -> list[str]:
    raw = raw.strip()
    if raw in {"", "nil"}:
        return []
    values = re.findall(r"'((?:\\.|[^'])*)'|\"((?:\\.|[^\"])*)\"", raw)
    return [
        A.parse_lua_string(
            "'" + (single or double) + "'"
        )
        for single, double in values
    ]


def requirements_text(raw: str) -> str:
    return "\n".join(parse_requirements(raw))


def render_requirements(raw: str) -> str:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return "nil"
    if len(lines) == 1:
        return "{ " + A.lua_quote(lines[0]) + " }"
    return "{ " + ", ".join(A.lua_quote(line) for line in lines) + " }"


def parse_modifier_module(text: str, revision: int) -> list[dict[str, Any]]:
    root_start = text.index("{", text.index("return"))
    root_end = A.matching_brace(text, root_start)
    root = text[root_start + 1:root_end]
    rows: list[dict[str, Any]] = []

    for match in re.finditer(
        r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\{",
        root,
    ):
        category = match.group(1)
        if category not in CATEGORY_ORDER:
            continue
        start = match.end() - 1
        end = A.matching_brace(root, start)
        body = root[start + 1:end]
        for entry_body in A.top_level_objects(body):
            fields = A.top_level_fields(entry_body)
            title = A.string_field(fields, "title")
            if not title:
                continue
            description = A.string_field(fields, "description")
            requirements = requirements_text(fields.get("requirements", "nil"))
            row = {
                "key": f"{category}|{title}",
                "category": category,
                "title": title,
                "description": description,
                "description_en": description,
                "requirements": requirements,
                "exclusive": A.string_field(fields, "exclusive"),
                "knobs": fields.get("knobs", "nil").strip(),
                "rift": A.bool_value(fields.get("rift"), False),
                "progress": A.bool_value(fields.get("progress"), False),
                "group": A.string_field(fields, "group"),
                "reason": A.string_field(fields, "reason"),
                "wiki_rev": revision,
                "sync_status": "已同步",
            }
            row["row_hash"] = modifier_hash(row)
            rows.append(row)
    return rows


def modifier_hash(row: dict[str, Any]) -> str:
    payload = {
        field: field_text(row.get(field, ""))
        for field in (
            "category",
            "title",
            "description",
            "description_en",
            "requirements",
            "exclusive",
            "knobs",
            "rift",
            "progress",
            "group",
            "reason",
        )
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha1(encoded).hexdigest()


def render_modifier_module(rows: list[dict[str, Any]]) -> str:
    grouped = {name: [] for name in CATEGORY_ORDER}
    for row in rows:
        if row.get("category") in grouped:
            grouped[row["category"]].append(row)

    out = ["return {"]
    for category in CATEGORY_ORDER:
        entries = grouped[category]
        if not entries:
            continue
        out.append(f"\n{category} = {{")
        for row in entries:
            description = row.get("description") or row.get("description_en", "")
            out.extend([
                "{",
                f"\ttitle = {A.lua_quote(row.get('title', ''))},",
                f"\tdescription = {A.lua_quote(description)},",
                f"\trequirements = {render_requirements(field_text(row.get('requirements', '')))},",
                f"\texclusive = {A.lua_quote(row.get('exclusive')) if row.get('exclusive') else 'nil'},",
                f"\tknobs = {render_knobs(row.get('knobs'))},",
                f"\trift = {'true' if row.get('rift') else 'false'},",
                f"\tprogress = {'true' if row.get('progress') else 'false'},",
                f"\tgroup = {A.lua_quote(row.get('group')) if row.get('group') else 'nil'},",
            ])
            if row.get("reason"):
                out.append(f"\treason = {A.lua_quote(row['reason'])},")
            out.append("},")
        out.append("},")
    out.append("}")
    return "\n".join(out) + "\n"


def render_knobs(value: Any) -> str:
    value = field_text(value).strip().lower()
    if value in {"", "nil"}:
        return "nil"
    if value == "false":
        return "false"
    return value


class GristModifiers:
    def __init__(self) -> None:
        self.server = os.environ.get(
            "GRIST_SERVER", "https://sheet.189-24-78-35.sslip.io"
        )
        self.doc_id = os.environ.get(
            "GRIST_DOC_ID", "1JRoy2vJar2kh945PXUbFP"
        )
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {A.load_grist_key()}",
            "Content-Type": "application/json",
        })
        self.base = f"{self.server}/api/docs/{self.doc_id}"
        self.records_url = f"{self.base}/tables/{GRIST_TABLE}/records"

    def ensure_table(self, apply: bool) -> None:
        tables = self.session.get(
            f"{self.base}/tables", timeout=60
        ).json().get("tables", [])
        if any(table.get("id") == GRIST_TABLE for table in tables):
            return
        print(f"Grist 表 {GRIST_TABLE} 不存在")
        if not apply:
            return
        columns = [
            {"id": field, "label": field, "type": "Text"}
            for field in TABLE_FIELDS
        ]
        response = self.session.post(
            f"{self.base}/apply",
            json=[["AddTable", GRIST_TABLE, columns]],
            timeout=120,
        )
        if response.status_code >= 400:
            raise RuntimeError(response.text[:500])
        print(f"已创建 Grist 表 {GRIST_TABLE}")

    def fetch(self) -> list[dict[str, Any]]:
        response = self.session.get(
            self.records_url,
            params={"limit": 2000},
            timeout=120,
        )
        if response.status_code >= 400:
            return []
        rows = []
        for record in response.json().get("records", []):
            fields = record.get("fields") or {}
            row = {field: field_text(fields.get(field)) for field in TABLE_FIELDS}
            row[GRIST_ID_FIELD] = record.get("id")
            rows.append(row)
        return rows

    def patch(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        payload = [
            {
                "id": row[GRIST_ID_FIELD],
                "fields": {field: field_text(row.get(field, ""))
                           for field in TABLE_FIELDS},
            }
            for row in rows if row.get(GRIST_ID_FIELD)
        ]
        if not payload:
            return 0
        response = self.session.patch(
            self.records_url,
            json={"records": payload},
            timeout=300,
        )
        if response.status_code >= 400:
            raise RuntimeError(response.text[:500])
        return len(payload)

    def add(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        payload = {
            "records": [
                {
                    "fields": {
                        field: field_text(row.get(field, ""))
                        for field in TABLE_FIELDS
                    }
                }
                for row in rows
            ]
        }
        response = self.session.post(
            self.records_url,
            json=payload,
            timeout=300,
        )
        if response.status_code >= 400:
            raise RuntimeError(response.text[:500])
        return len(rows)


def merge_rows(
    source_rows: list[dict[str, Any]],
    target_rows: list[dict[str, Any]],
    table_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    target_by_key = {row["key"]: row for row in target_rows}
    table_by_key = {row["key"]: row for row in table_rows}
    merged = []
    for source in source_rows:
        key = source["key"]
        target = target_by_key.get(key, {})
        table = table_by_key.get(key, {})
        description = (
            table.get("description")
            or target.get("description")
            or source.get("description")
            or source.get("description_en")
            or ""
        )
        row = dict(source)
        row["description"] = description
        for field in (
            "requirements",
            "exclusive",
            "knobs",
            "group",
            "reason",
        ):
            value = table.get(field, "")
            if field_text(value).strip():
                row[field] = value
        for field in ("rift", "progress"):
            value = field_text(table.get(field, "")).strip().lower()
            if value:
                row[field] = value in {"1", "true", "yes", "是", "on"}
        row["wiki_rev"] = source.get("wiki_rev", "")
        row["sync_status"] = "已同步"
        row["row_hash"] = modifier_hash(row)
        merged.append(row)
    return merged


def command_dump(args: argparse.Namespace) -> int:
    try:
        SOURCE_SITE.login()
    except Exception as exc:
        print(f"英文站登录跳过（只读）：{exc}")
    TARGET_SITE.login()
    src = pywikibot.Page(SOURCE_SITE, SOURCE_PAGE)
    dst = pywikibot.Page(TARGET_SITE, TARGET_PAGE)
    print("英文:", src.latest_revision_id, len(src.text))
    print("中文:", dst.latest_revision_id, len(dst.text))
    print("英文条目:", len(parse_modifier_module(src.text, src.latest_revision_id)))
    print("中文条目:", len(parse_modifier_module(dst.text, dst.latest_revision_id)))
    return 0


def command_sync(args: argparse.Namespace) -> int:
    try:
        SOURCE_SITE.login()
    except Exception as exc:
        print(f"英文站登录跳过（只读）：{exc}")
    TARGET_SITE.login()
    source_page = pywikibot.Page(SOURCE_SITE, SOURCE_PAGE)
    target_page = pywikibot.Page(TARGET_SITE, TARGET_PAGE)
    source_rows = parse_modifier_module(
        source_page.text, source_page.latest_revision_id
    )
    target_rows = parse_modifier_module(
        target_page.text, target_page.latest_revision_id
    )
    grist = GristModifiers()
    grist.ensure_table(args.apply)
    table_rows = grist.fetch() if args.apply or GRIST_TABLE else []
    merged = merge_rows(source_rows, target_rows, table_rows)

    table_by_key = {row["key"]: row for row in table_rows}
    to_add: list[dict[str, Any]] = []
    to_patch: list[dict[str, Any]] = []
    for row in merged:
        old = table_by_key.get(row["key"])
        if not old:
            to_add.append(row)
            continue
        changed = any(
            field_text(old.get(field)) != field_text(row.get(field))
            for field in TABLE_FIELDS
            if field not in {"wiki_rev", "row_hash", "sync_status"}
        )
        if changed:
            row[GRIST_ID_FIELD] = old.get(GRIST_ID_FIELD)
            to_patch.append(row)

    print(
        f"英文={len(source_rows)} 中文={len(target_rows)} "
        f"Grist={len(table_rows)} 合并={len(merged)} "
        f"表格新增={len(to_add)} 表格更新={len(to_patch)}"
    )
    if not args.apply:
        print("演练模式；加 --apply 才写入 Grist 和中文 Module:ModifierData")
        return 0

    if to_add:
        print("Grist 新增:", grist.add(to_add))
    if to_patch:
        print("Grist 更新:", grist.patch(to_patch))

    new_text = render_modifier_module(merged)
    if new_text.rstrip("\n") != target_page.text.rstrip("\n"):
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        (BACKUP_DIR / "Module_ModifierData.before").write_text(
            target_page.text, encoding="utf-8"
        )
        target_page.put(
            new_text,
            summary="从英文站同步 ModifierData 并应用机器人表格描述",
        )
        print("已写入中文 Module:ModifierData")
    else:
        print("中文 Module:ModifierData 无变化")
    STATE_FILE.write_text(
        json.dumps(
            {
                "source_revision": source_page.latest_revision_id,
                "target_revision": target_page.latest_revision_id,
                "rows": {row["key"]: row["row_hash"] for row in merged},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


def command_watch(args: argparse.Namespace) -> int:
    while True:
        try:
            command_sync(args)
        except Exception as exc:
            print(f"同步失败：{type(exc).__name__}: {exc}", flush=True)
        time.sleep(args.interval)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sync = sub.add_parser("sync")
    sync.add_argument("--apply", action="store_true")
    sync.set_defaults(func=command_sync)
    watch = sub.add_parser("watch")
    watch.add_argument("--apply", action="store_true")
    watch.add_argument("--interval", type=int, default=30)
    watch.set_defaults(func=command_watch)
    dump = sub.add_parser("dump")
    dump.set_defaults(func=command_dump)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
