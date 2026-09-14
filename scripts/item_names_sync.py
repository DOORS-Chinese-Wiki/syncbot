# -*- coding: utf-8 -*-
"""物品译名 ↔ 腾讯文档「物品翻译确认表」同步。

Wiki 侧：
  Module:ItemNames          纯数据（本脚本维护）
  Module:ItemNames/render   渲染器，只创建一次，之后不再改动
  Help:物品译名对照表         {{#invoke:ItemNames/render|table}}

表格侧（docs.qq.com/sheet/DUkhWU3VFU3NNTFNR，工作表「物品翻译」）：
  第 4 行是表头，A 列是脏数据，从 B 列（英文名）开始读。

方向：
  表格 → Wiki：除 final / note 之外的字段都照搬（建议译名、备选、分类、状态…）。
  Wiki → 表格：只允许改 final（最终译名）和 note（备注），避免误改征集字段。

用法：
  python scripts/item_names_sync.py sync            # 干跑
  python scripts/item_names_sync.py sync --apply    # 执行
  python scripts/item_names_sync.py fetch           # 抓取表格到本地 JSON
  python scripts/item_names_sync.py mapping         # 输出已确认译名对照
"""
import argparse
import base64
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import pywikibot
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import achievements_sync as A  # noqa: E402

ITEM_URL_ID = "DUkhWU3VFU3NNTFNR"
ITEM_SHEET_ID = "000001"
ITEM_FILE_ID = "300000000$" + base64.b64decode(
    ITEM_URL_ID[1:] + "=" * ((4 - len(ITEM_URL_ID[1:]) % 4) % 4)
).decode("utf-8")

MODULE = "Module:ItemNames"
RENDER_MODULE = "Module:ItemNames/render"
GLOSSARY = "Help:物品译名对照表"
SUMMARY = "同步物品译名"
STATE_FILE = Path("data/item_names_sync_state.json")
JSON_FILE = Path("data/item_names_tencent.json")

# --- Grist 后端（自建，辅） ---
GRIST_SERVER = os.environ.get(
    "GRIST_SERVER", "https://sheet.189-24-78-35.sslip.io"
)
GRIST_DOC_ID = os.environ.get("GRIST_DOC_ID", "1JRoy2vJar2kh945PXUbFP")
GRIST_TABLE = "ItemNames"
ALT_COLUMNS = ("alt1", "alt2", "alt3", "alt4")

HEADER_ROW = 4  # 1-based
COLUMNS = {
    "key": 1,
    "suggested": 2,
    "alternatives": (3, 4, 5, 6),
    "final": 7,
    "reason": 8,
    "category": 9,
    "page": 10,
    "source": 11,
    "status": 12,
    "priority": 13,
    "owner": 14,
    "confirmed": 15,
    "note": 16,
}
MIRROR_FIELDS = (
    "final", "suggested", "alternatives", "reason", "category", "page",
    "source", "status", "priority", "owner", "confirmed", "note",
)
# 允许在 Wiki 侧修改并回写到表格的字段
EDITABLE_FIELDS = ("final", "note")
FIELD_ORDER = MIRROR_FIELDS

RENDER_LUA = """-- 由 scripts/item_names_sync.py 创建，请勿手工改动。
local data = mw.loadData('Module:ItemNames')

local p = {}

local HEADERS = {
    '英文名', '最终译名', '建议中文译名', '备选译名', '分类',
    '页面状态', '处理状态', '备注',
}

local function sorted_keys()
    local keys = {}
    for key in pairs(data) do
        keys[#keys + 1] = key
    end
    table.sort(keys, function(a, b) return a:lower() < b:lower() end)
    return keys
end

local function alternatives(entry)
    if type(entry.alternatives) ~= 'table' then return '' end
    return table.concat(entry.alternatives, ' / ')
end

function p.table()
    local out = {
        '{| class="wikitable sortable" style="width:100%"',
        '! ' .. table.concat(HEADERS, ' !! '),
    }
    for _, key in ipairs(sorted_keys()) do
        local entry = data[key]
        local status = entry.status or ''
        if entry.removed then status = '表格已删除' end
        out[#out + 1] = '|-'
        out[#out + 1] = '| ' .. table.concat({
            key,
            entry.final or '',
            entry.suggested or '',
            alternatives(entry),
            entry.category or '',
            entry.page or '',
            status,
            entry.note or '',
        }, ' || ')
    end
    out[#out + 1] = '|}'
    return table.concat(out, '\\n')
end

function p.mapping()
    local lines = {}
    for _, key in ipairs(sorted_keys()) do
        local entry = data[key]
        if entry.final and entry.final ~= '' and not entry.removed then
            lines[#lines + 1] = key .. ' → ' .. entry.final
        end
    end
    if #lines == 0 then return '（暂无已确认译名）' end
    return '<pre>' .. table.concat(lines, '\\n') .. '</pre>'
end

return p
"""


def client() -> A.TencentDocsClient:
    A.load_env(A.ENV_FILE)
    instance = A.TencentDocsClient()
    instance.file_id = ITEM_FILE_ID
    instance.sheet_id = ITEM_SHEET_ID
    return instance


def load_grist_key() -> str:
    key = os.environ.get("GRIST_API_KEY", "")
    if key:
        return key
    path = Path("grist.env")
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("GRIST_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError("缺少 GRIST_API_KEY（环境变量或 grist.env）")


class GristSheet:
    """把 Grist 表当作「表格后端」，对外暴露与腾讯文档相同的行结构。"""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {load_grist_key()}",
            "Content-Type": "application/json",
        })
        self.url = (
            f"{GRIST_SERVER}/api/docs/{GRIST_DOC_ID}/tables/{GRIST_TABLE}"
            "/records"
        )

    def fetch(self) -> list[dict[str, Any]]:
        rows = []
        for record in self.session.get(
            self.url, params={"limit": 2000}, timeout=120
        ).json().get("records", []):
            fields = record.get("fields") or {}
            row = {
                "key": fields.get("english", ""),
                "_id": record.get("id"),
                "alternatives": [
                    fields.get(col, "") for col in ALT_COLUMNS
                    if fields.get(col, "")
                ],
            }
            for field in MIRROR_FIELDS:
                if field == "alternatives":
                    continue
                row[field] = fields.get(field, "")
            rows.append(row)
        return rows

    @staticmethod
    def _fields(row: dict[str, Any]) -> dict[str, str]:
        fields = {
            field: row.get(field, "")
            for field in MIRROR_FIELDS if field != "alternatives"
        }
        fields["english"] = row.get("key", "")
        for index, col in enumerate(ALT_COLUMNS):
            values = row.get("alternatives") or []
            fields[col] = values[index] if index < len(values) else ""
        return fields

    def patch(self, rows: list[dict[str, Any]]) -> int:
        groups: dict[tuple, list[dict]] = {}
        for row in rows:
            if not row.get("_id"):
                continue
            payload = {"id": row["_id"], "fields": self._fields(row)}
            groups.setdefault(tuple(sorted(payload["fields"])), []).append(
                payload
            )
        done = 0
        for group in groups.values():
            resp = self.session.patch(
                self.url, json={"records": group}, timeout=300
            )
            if resp.status_code >= 400:
                print("GRIST PATCH 失败:", resp.status_code, resp.text[:200])
                continue
            done += len(group)
        return done

    def add(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        resp = self.session.post(
            self.url,
            json={"records": [
                {"fields": self._fields(row)} for row in rows
            ]},
            timeout=300,
        )
        if resp.status_code >= 400:
            print("GRIST POST 失败:", resp.status_code, resp.text[:200])
            return 0
        return len(rows)


def cell(values: list[Any], index: int) -> str:
    if index < 0 or index >= len(values):
        return ""
    value = values[index]
    return "" if value is None else str(value).strip()


def read_sheet(instance: A.TencentDocsClient) -> tuple[list[dict[str, Any]], list[str]]:
    matrix = instance.get_range("A1:Q200")
    warnings: list[str] = []
    rows: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for offset, values in enumerate(matrix[HEADER_ROW:], start=HEADER_ROW + 1):
        key = cell(values, COLUMNS["key"])
        if not key:
            continue
        category = cell(values, COLUMNS["category"])
        page = cell(values, COLUMNS["page"])
        if not category and not page:
            warnings.append(f"第 {offset} 行 [{key}] 分类与页面状态皆空，已跳过")
            continue
        alternatives = [
            cell(values, index) for index in COLUMNS["alternatives"]
            if cell(values, index)
        ]
        row = {
            "key": key,
            "_row": offset,
            "suggested": cell(values, COLUMNS["suggested"]),
            "alternatives": alternatives,
            "final": cell(values, COLUMNS["final"]),
            "reason": cell(values, COLUMNS["reason"]),
            "category": category,
            "page": page,
            "source": cell(values, COLUMNS["source"]),
            "status": cell(values, COLUMNS["status"]),
            "priority": cell(values, COLUMNS["priority"]),
            "owner": cell(values, COLUMNS["owner"]),
            "confirmed": cell(values, COLUMNS["confirmed"]),
            "note": cell(values, COLUMNS["note"]),
        }
        if key in seen:
            warnings.append(
                f"英文名重复：{key}（第 {seen[key]} 行与第 {offset} 行），"
                "以最后一行为准"
            )
            rows = [item for item in rows if item["key"] != key]
        seen[key] = offset
        rows.append(row)
    return rows, warnings


def payload(row: dict[str, Any]) -> dict[str, Any]:
    """参与比对的字段（覆盖 mirror + editable，不含 removed）。"""
    return {field: row.get(field, "") for field in MIRROR_FIELDS}


def digest(row: dict[str, Any] | None, fields: tuple[str, ...]) -> str:
    if not row:
        return ""
    data = {field: row.get(field, "") for field in fields}
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()


def parse_module(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for match in re.finditer(r"\[\s*'((?:[^'\\]|\\.)*)'\s*\]\s*=\s*\{", text):
        key = A.parse_lua_string("'" + match.group(1) + "'")
        start = match.end() - 1
        try:
            end = A.matching_brace(text, start)
        except ValueError:
            continue
        body = text[start + 1:end]
        row: dict[str, Any] = {"key": key, "alternatives": []}
        for line in body.splitlines():
            field = re.match(r"\s*([A-Za-z_]+)\s*=\s*(.+?),?\s*$", line)
            if not field:
                continue
            name, raw = field.group(1), field.group(2).strip()
            if name == "alternatives":
                items = re.findall(r"'((?:[^'\\]|\\.)*)'", raw)
                row["alternatives"] = [
                    A.parse_lua_string("'" + item + "'") for item in items
                ]
            elif name == "removed":
                row["removed"] = raw == "true"
            elif name in MIRROR_FIELDS:
                row[name] = A.parse_lua_string(raw)
        rows.append(row)
    return rows


def fetch_module() -> tuple[int, list[dict[str, Any]]]:
    site = pywikibot.Site("zhdoors", "zhdoors")
    page = pywikibot.Page(site, MODULE)
    if not page.exists():
        return 0, []
    return page.latest_revision_id, parse_module(page.text)


def render_module(rows: list[dict[str, Any]]) -> str:
    out = [
        "-- 本页由 scripts/item_names_sync.py 自动生成，请勿手工编辑。",
        "-- 数据来源：腾讯文档「DOORS 中文维基物品翻译确认表」",
        f"-- https://docs.qq.com/sheet/{ITEM_URL_ID}",
        "",
        "return {",
    ]
    for row in sorted(rows, key=lambda item: item["key"].lower()):
        out.append(f"[{A.lua_quote(row['key'])}] = {{")
        for field in FIELD_ORDER:
            value = row.get(field)
            if field == "alternatives":
                if value:
                    joined = ", ".join(A.lua_quote(item) for item in value)
                    out.append(f"\talternatives = {{{joined}}},")
                continue
            if value:
                out.append(f"\t{field} = {A.lua_quote(str(value))},")
        if row.get("removed"):
            out.append("\tremoved = true,")
        out.append("},")
    out.append("}")
    return "\n".join(out) + "\n"


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"revision": 0, "rows": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(
    path: Path,
    revision: int,
    wiki_rows: dict[str, dict[str, Any]],
    sheet_rows: dict[str, dict[str, Any]],
    preserve: dict[str, dict[str, Any]] | None = None,
) -> None:
    preserve = preserve or {}
    state_rows = {}
    for key in sorted(set(wiki_rows) | set(sheet_rows)):
        if key in preserve:
            state_rows[key] = preserve[key]
            continue
        wiki = wiki_rows.get(key)
        sheet = sheet_rows.get(key)
        state_rows[key] = {
            "wiki_hash": digest(wiki, MIRROR_FIELDS),
            "sheet_hash": digest(sheet, MIRROR_FIELDS),
            "wiki_editable": digest(wiki, EDITABLE_FIELDS),
        }
    payload_data = {"revision": revision, "rows": state_rows}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    handler = sub.add_parser("sync")
    handler.add_argument("--apply", action="store_true")
    handler.add_argument("--backend", choices=["grist", "tencent"],
                         default="grist")
    sub.add_parser("fetch")
    sub.add_parser("mapping")
    args = parser.parse_args()

    if args.command == "fetch":
        rows, warnings = read_sheet(client())
        JSON_FILE.parent.mkdir(parents=True, exist_ok=True)
        JSON_FILE.write_text(
            json.dumps({"rows": rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        for warning in warnings:
            print("WARN", warning)
        print(f"rows={len(rows)} -> {JSON_FILE}")
        return 0

    if args.command == "mapping":
        _, rows = fetch_module()
        pairs = [
            (row["key"], row["final"]) for row in rows
            if row.get("final") and not row.get("removed")
        ]
        for key, final in pairs:
            print(f"{key}\t{final}")
        print(f"# 已确认 {len(pairs)} 条", file=sys.stderr)
        return 0

    apply = args.apply
    revision, wiki_rows = fetch_module()
    wiki_by_key = {row["key"]: row for row in wiki_rows}
    grist = None
    if args.backend == "grist":
        grist = GristSheet()
        sheet_rows, warnings = grist.fetch(), []
    else:
        sheet_rows, warnings = read_sheet(client())
    sheet_by_key = {row["key"]: row for row in sheet_rows}
    state = load_state(STATE_FILE)
    previous = state.get("rows", {})

    for warning in warnings:
        print("WARN", warning)

    wiki_updates: dict[str, dict[str, Any]] = {}
    sheet_updates: dict[str, dict[str, Any]] = {}
    conflicts: list[str] = []

    for key in sorted(set(wiki_by_key) | set(sheet_by_key) | set(previous)):
        wiki = wiki_by_key.get(key)
        sheet = sheet_by_key.get(key)
        last = previous.get(key, {})
        wiki_mirror = digest(wiki, MIRROR_FIELDS)
        sheet_mirror = digest(sheet, MIRROR_FIELDS)
        wiki_editable = digest(wiki, EDITABLE_FIELDS)
        sheet_editable = digest(sheet, EDITABLE_FIELDS)
        wiki_changed = bool(wiki) and wiki_editable != last.get(
            "wiki_editable", ""
        )
        sheet_changed = bool(sheet) and sheet_mirror != last.get(
            "sheet_hash", ""
        )

        if wiki and not sheet:
            record = dict(wiki)
            record["removed"] = True
            wiki_updates[key] = record
        elif sheet and not wiki:
            wiki_updates[key] = dict(sheet)
        elif wiki and sheet:
            if sheet_changed and not wiki_changed:
                wiki_updates[key] = dict(sheet)
            elif wiki_changed and not sheet_changed:
                pushed = dict(sheet)
                for field in EDITABLE_FIELDS:
                    pushed[field] = wiki.get(field, "")
                sheet_updates[key] = pushed
            elif sheet_changed and wiki_changed and wiki_editable != sheet_editable:
                conflicts.append(key)
            elif sheet_mirror != wiki_mirror:
                # 只读字段（status/priority/category…）以辅表为准。
                # 这里不能要求 not sheet_changed：状态文件缺失或后端切换时
                # 两端都会被视为「有变化」，会导致这些字段永远同步不过去。
                wiki_updates[key] = dict(sheet)

    print(
        f"revision={revision} wiki={len(wiki_rows)} sheet={len(sheet_rows)} "
        f"sheet->wiki={len(wiki_updates)} wiki->sheet={len(sheet_updates)} "
        f"conflicts={len(conflicts)}"
    )
    for key in sorted(wiki_updates)[:20]:
        print(f"PULL\t{key}")
    for key in sorted(sheet_updates)[:20]:
        print(f"PUSH\t{key}")
    for key in conflicts:
        print(f"CONFLICT\t{key}")

    if not apply:
        print("dry-run，未写入")
        return 0

    site = pywikibot.Site("zhdoors", "zhdoors")
    if wiki_updates:
        merged = dict(wiki_by_key)
        merged.update(wiki_updates)
        page = pywikibot.Page(site, MODULE)
        page.text = render_module(list(merged.values()))
        page.save(summary=SUMMARY)
        print(f"saved {MODULE} rev={page.latest_revision_id}")

    if sheet_updates:
        if grist is not None:
            written = grist.patch(list(sheet_updates.values()))
            print(f"WROTE-BACK(grist)\t{written} 条")
        else:
            docs = client()
            for key in sorted(sheet_updates):
                row = sheet_updates[key]
                offset = row.get("_row")
                if not offset:
                    print(f"SKIP writeback {key}: 找不到表格行号")
                    continue
                docs.update_range(f"H{offset}:H{offset}",
                                  [[row.get("final", "")]])
                docs.update_range(f"Q{offset}:Q{offset}",
                                  [[row.get("note", "")]])
                print(f"WROTE-BACK\t{key}\tH{offset} / Q{offset}")

    render_page = pywikibot.Page(site, RENDER_MODULE)
    if not render_page.exists():
        render_page.text = RENDER_LUA
        render_page.save(summary="创建物品译名渲染器")
        print(f"created {RENDER_MODULE}")
    glossary = pywikibot.Page(site, GLOSSARY)
    if not glossary.exists():
        glossary.text = (
            "本页由 [[Module:ItemNames]] 自动渲染，译名请在"
            f"[https://docs.qq.com/sheet/{ITEM_URL_ID} 腾讯文档确认表]中修改。\n\n"
            "== 对照表 ==\n{{#invoke:ItemNames/render|table}}\n\n"
            "== 已确认译名（供全站替换用） ==\n"
            "{{#invoke:ItemNames/render|mapping}}\n"
        )
        glossary.save(summary="创建物品译名对照表")
        print(f"created {GLOSSARY}")

    final_wiki = merged if wiki_updates else wiki_by_key
    final_sheet = dict(sheet_by_key)
    for key, row in sheet_updates.items():
        final_sheet[key] = row
    save_state(
        STATE_FILE,
        revision,
        final_wiki,
        final_sheet,
        preserve={key: previous[key] for key in conflicts if key in previous},
    )
    print("applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
