# -*- coding: utf-8 -*-
"""Read and compare DOORS Wiki achievement data in a round-trip friendly format.

This script intentionally treats Tencent Docs exports as data files. It does not
write to Tencent Docs; the browser connector can feed exports into it later.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import mimetypes
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

import pywikibot
import requests

sys.stdout.reconfigure(encoding="utf-8")


CATEGORY_ORDER = [
    "General",
    "Entities",
    "Items",
    "Floors",
    "Crucifix",
    "Challenges",
    "Battle",
    "Visions",
    "Collab",
    "Events",
    "Legacy",
    "Unlisted",
]

EDITABLE_FIELDS = ("category", "title", "text", "directions", "tutorial", "references")
HEADER_TO_FIELD = {
    "同步键": "key",
    "分类": "category",
    "成就名": "title",
    "描述": "text",
    "达成条件": "directions",
    "攻略": "tutorial",
    "参考资料": "references",
    "奖励": "rewards",
    "Secret": "secret",
    "Hidden": "hidden",
    "Obtainable": "obtainable",
    "Badge ID": "badge_id",
    "旧版本": "old_versions",
    "Wiki 修订": "wiki_rev",
    "行哈希": "row_hash",
    "同步状态": "sync_status",
}
ENV_FILE = Path("tencent_docs.env")
TOKEN_FILE = Path("data/tencent_docs_token.json")
API_ROOT = "https://docs.qq.com"
SUMMARY = "同步成就文本"

# --- Grist 后端（自建，辅） ---
GRIST_SERVER = os.environ.get(
    "GRIST_SERVER", "https://sheet.189-24-78-35.sslip.io"
)
GRIST_DOC_ID = os.environ.get("GRIST_DOC_ID", "1JRoy2vJar2kh945PXUbFP")
GRIST_TABLE = "Achievements"
GRIST_ID_FIELD = "_id"

# 表格「同步状态」列统一使用的中文文案。历史值 "" / "synced" 一律视作已同步。
STATUS_SYNCED = "已同步"
STATUS_WIKI_NEW = "Wiki 新增"
STATUS_SHEET_NEW = "表格新增"
STATUS_WIKI_UPDATED = "Wiki 有更新"
STATUS_SHEET_UPDATED = "表格有更新"
STATUS_CONFLICT = "冲突：两端均变化"
STATUS_WIKI_DELETED = "Wiki 已删除"
STATUS_LEGACY_SYNCED = ("", "synced", STATUS_SYNCED)
MATRIX_WIDTH = 16
CSV_FIELDS = [
    "key",
    "wiki_rev",
    "category",
    "title",
    "text",
    "directions",
    "tutorial",
    "references",
    "rewards",
    "secret",
    "hidden",
    "obtainable",
    "badge_id",
    "old_versions",
    "row_hash",
    "sync_status",
]


def matching_brace(text: str, start: int) -> int:
    depth = 0
    index = start
    quote: str | None = None
    escaped = False
    long_string = False
    while index < len(text):
        char = text[index]
        if long_string:
            if text.startswith("]]", index):
                long_string = False
                index += 2
                continue
            index += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if text.startswith("--", index):
            newline = text.find("\n", index + 2)
            index = len(text) if newline < 0 else newline
            continue
        if text.startswith("[[", index):
            long_string = True
            index += 2
            continue
        if char in "'\"":
            quote = char
            index += 1
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise ValueError("Unmatched Lua table brace")


def top_level_objects(body: str) -> list[str]:
    objects = []
    index = 0
    depth = 0
    quote: str | None = None
    escaped = False
    while index < len(body):
        char = body[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if body.startswith("--", index):
            newline = body.find("\n", index + 2)
            index = len(body) if newline < 0 else newline
            continue
        if char in "'\"":
            quote = char
            index += 1
            continue
        if char == "{" and depth == 0:
            end = matching_brace(body, index)
            objects.append(body[index + 1 : end])
            index = end + 1
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        index += 1
    return objects


def top_level_fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    index = 0
    depth = 0
    quote: str | None = None
    escaped = False
    part_start = 0

    def store(part: str) -> None:
        match = re.match(
            r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\Z",
            part,
            re.S,
        )
        if match:
            fields[match.group(1)] = match.group(2).strip()

    while index < len(body):
        char = body[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if body.startswith("--", index):
            newline = body.find("\n", index + 2)
            index = len(body) if newline < 0 else newline
            continue
        if char in "'\"":
            quote = char
            index += 1
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif char == "," and depth == 0:
            store(body[part_start:index])
            part_start = index + 1
        index += 1
    store(body[part_start:])
    return fields


def parse_lua_string(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] in "'\"" and value[-1] == value[0]:
        return re.sub(r"\\(.)", r"\1", value[1:-1])
    return value


def bool_value(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() == "true"


def string_field(fields: dict[str, str], name: str) -> str:
    if name not in fields:
        return ""
    value = parse_lua_string(fields[name])
    return "" if value == "nil" else value


def row_hash(row: dict[str, Any]) -> str:
    payload = {field: row.get(field, "") for field in EDITABLE_FIELDS}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()


def parse_module(text: str, revision: int) -> list[dict[str, Any]]:
    root_start = text.index("{", text.index("return"))
    root_end = matching_brace(text, root_start)
    root = text[root_start + 1 : root_end]
    rows: list[dict[str, Any]] = []

    for match in re.finditer(
        r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\{",
        root,
    ):
        category = match.group(1)
        if category not in CATEGORY_ORDER:
            continue
        category_start = match.end() - 1
        category_end = matching_brace(root, category_start)
        category_body = root[category_start + 1 : category_end]

        for entry_body in top_level_objects(category_body):
            fields = top_level_fields(entry_body)
            title = string_field(fields, "title")
            if not title:
                continue
            badge_id = string_field(fields, "id")
            if badge_id == "nil":
                badge_id = ""
            key = (
                f"id:{badge_id}:{category}:{title}"
                if badge_id
                else f"title:{category}:{title}"
            )
            row = {
                "key": key,
                "wiki_rev": revision,
                "category": category,
                "title": title,
                "text": string_field(fields, "text"),
                "directions": string_field(fields, "directions"),
                "tutorial": string_field(fields, "tutorial"),
                "references": string_field(fields, "references"),
                "rewards": fields.get("rewards", "nil"),
                "secret": bool_value(fields.get("secret"), False),
                "hidden": bool_value(fields.get("hidden"), False),
                "obtainable": bool_value(fields.get("obtainable"), True),
                "badge_id": badge_id,
                "old_versions": fields.get("oldVersions", "nil"),
            }
            row["row_hash"] = row_hash(row)
            row["sync_status"] = STATUS_SYNCED
            rows.append(row)
    return rows


def fetch_rows() -> tuple[int, list[dict[str, Any]]]:
    site = pywikibot.Site("zhdoors", "zhdoors")
    page = pywikibot.Page(site, "Module:BadgeData")
    return page.latest_revision_id, parse_module(page.text, page.latest_revision_id)


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def normalize_bool(value: Any, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是"}


def merge_sheet_row(row: dict[str, str]) -> dict[str, Any]:
    merged: dict[str, Any] = {
        "category": row.get("category", "").strip(),
        "title": row.get("title", "").strip(),
        "text": row.get("text", ""),
        "directions": row.get("directions", ""),
        "tutorial": row.get("tutorial", ""),
        "references": row.get("references", ""),
        "rewards": row.get("rewards", "nil") or "nil",
        "secret": normalize_bool(row.get("secret"), False),
        "hidden": normalize_bool(row.get("hidden"), False),
        "obtainable": normalize_bool(row.get("obtainable"), True),
        "badge_id": row.get("badge_id", "").strip(),
        "old_versions": row.get("old_versions", "nil") or "nil",
        "wiki_rev": row.get("wiki_rev", ""),
        "sync_status": row.get("sync_status", ""),
    }
    key = row.get("key", "").strip()
    if not key:
        key = (
            f"id:{merged['badge_id']}:{merged['category']}:{merged['title']}"
            if merged["badge_id"]
            else f"title:{merged['category']}:{merged['title']}"
        )
    merged["key"] = key
    merged["row_hash"] = row_hash(merged)
    return merged


class TencentDocsClient:
    def __init__(self) -> None:
        load_env(ENV_FILE)
        self.client_id = os.environ.get("QQDOCS_CLIENT_ID", "")
        self.client_secret = os.environ.get("QQDOCS_CLIENT_SECRET", "")
        self.open_id = os.environ.get("QQDOCS_OPEN_ID", "")
        self.file_id = os.environ.get("QQDOCS_FILE_ID", "")
        self.sheet_id = os.environ.get("QQDOCS_SHEET_ID", "")
        self.access_token = os.environ.get("QQDOCS_ACCESS_TOKEN", "")
        self.refresh_token = os.environ.get("QQDOCS_REFRESH_TOKEN", "")
        self.expires_at = 0.0
        self._load_token_file()

    def _load_token_file(self) -> None:
        if not TOKEN_FILE.exists():
            return
        try:
            data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self.access_token = data.get("access_token") or self.access_token
        self.refresh_token = data.get("refresh_token") or self.refresh_token
        self.open_id = data.get("user_id") or self.open_id
        self.expires_at = float(data.get("expires_at") or 0)

    def _save_tokens(self, payload: dict[str, Any]) -> None:
        self.access_token = payload["access_token"]
        self.refresh_token = payload.get("refresh_token") or self.refresh_token
        self.open_id = payload.get("user_id") or self.open_id
        self.expires_at = time.time() + int(payload.get("expires_in") or 0)
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(
            json.dumps(
                {
                    "access_token": self.access_token,
                    "refresh_token": self.refresh_token,
                    "user_id": self.open_id,
                    "expires_at": self.expires_at,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def refresh_access_token(self) -> None:
        if not all((self.client_id, self.client_secret, self.refresh_token)):
            raise RuntimeError(
                "缺少腾讯文档凭据：需要 QQDOCS_CLIENT_ID、"
                "QQDOCS_CLIENT_SECRET、QQDOCS_REFRESH_TOKEN"
            )
        response = requests.get(
            f"{API_ROOT}/oauth/v2/token",
            params={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if "access_token" not in payload:
            raise RuntimeError(f"腾讯文档刷新 Token 失败：{payload}")
        self._save_tokens(payload)

    def exchange_code(self, code: str, redirect_uri: str) -> None:
        if not all((self.client_id, self.client_secret, redirect_uri, code)):
            raise RuntimeError("client_id、client_secret、redirect_uri 和 code 均为必填")
        response = requests.get(
            f"{API_ROOT}/oauth/v2/token",
            params={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "code": code,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if "access_token" not in payload:
            raise RuntimeError(f"腾讯文档换取 Token 失败：{payload}")
        self._save_tokens(payload)

    def ensure_token(self) -> None:
        if not self.access_token or (self.expires_at and self.expires_at <= time.time() + 60):
            self.refresh_access_token()

    def headers(self) -> dict[str, str]:
        self.ensure_token()
        if not all((self.client_id, self.open_id, self.access_token)):
            raise RuntimeError(
                "缺少腾讯文档配置：QQDOCS_CLIENT_ID、QQDOCS_OPEN_ID、"
                "QQDOCS_ACCESS_TOKEN 或 refresh_token"
            )
        return {
            "Access-Token": self.access_token,
            "Client-Id": self.client_id,
            "Open-Id": self.open_id,
            "Accept": "application/json",
        }

    def get_range(self, range_: str) -> list[list[str]]:
        if not self.file_id or not self.sheet_id:
            raise RuntimeError("缺少 QQDOCS_FILE_ID 或 QQDOCS_SHEET_ID")
        url = (
            f"{API_ROOT}/openapi/spreadsheet/v3/files/"
            f"{urllib.parse.quote(self.file_id, safe='')}/"
            f"{urllib.parse.quote(self.sheet_id, safe='')}/"
            f"{urllib.parse.quote(range_, safe='!:')}"
        )
        response = requests.get(url, headers=self.headers(), timeout=30)
        response.raise_for_status()
        payload = response.json()
        if payload.get("ret", 0) != 0:
            raise RuntimeError(f"腾讯文档读取失败：{payload}")
        grid = (
            payload.get("gridData")
            or (payload.get("data") or {}).get("gridData")
            or {}
        )
        matrix: list[list[str]] = []
        for row in grid.get("rows", []):
            values = []
            for cell in row.get("values", []):
                cell_value = cell.get("cellValue") or {}
                if "text" in cell_value:
                    values.append(str(cell_value["text"]))
                elif "number" in cell_value:
                    values.append(str(cell_value["number"]))
                elif "boolValue" in cell_value:
                    values.append(str(cell_value["boolValue"]).lower())
                else:
                    values.append("")
            matrix.append(values)
        return matrix

    def sheets_info(self) -> list[dict[str, Any]]:
        if not self.file_id:
            raise RuntimeError("缺少 QQDOCS_FILE_ID")
        url = (
            f"{API_ROOT}/openapi/sheetbook/v2/"
            f"{urllib.parse.quote(self.file_id, safe='')}/sheets-info"
        )
        response = requests.get(url, headers=self.headers(), timeout=30)
        response.raise_for_status()
        payload = response.json()
        if payload.get("ret", 0) != 0:
            raise RuntimeError(f"腾讯文档查询工作表失败：{payload}")
        data = payload.get("data") or {}
        return data.get("sheetData") or data.get("getSheet") or []

    def import_file(self, path: Path, title: str | None = None) -> dict[str, Any]:
        file_name = title or path.name
        if not file_name.isascii():
            file_name = "DOORS_Wiki_Achievements.xlsx"
        file_data = path.read_bytes()
        file_md5 = hashlib.md5(file_data).hexdigest()
        response = requests.post(
            f"{API_ROOT}/openapi/drive/v2/files/upload",
            headers={
                **self.headers(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "fileMD5": file_md5,
                "fileName": file_name,
                "fileSize": str(len(file_data)),
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("ret", 0) != 0:
            raise RuntimeError(f"腾讯文档预导入失败：{payload}")
        upload = payload["data"]

        headers = dict(upload.get("CustomHeader") or {})
        headers.setdefault(
            "Content-Type",
            mimetypes.guess_type(file_name)[0] or "application/octet-stream",
        )
        uploaded = requests.put(
            upload["COSPutURL"],
            headers=headers,
            data=file_data,
            timeout=180,
        )
        uploaded.raise_for_status()

        imported = requests.post(
            f"{API_ROOT}/openapi/drive/v2/files/async-import",
            headers={
                **self.headers(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "fileMD5": file_md5,
                "fileName": file_name,
                "COSFileKey": upload["COSFileKey"],
            },
            timeout=60,
        )
        imported.raise_for_status()
        result = imported.json()
        if result.get("ret", 0) != 0:
            raise RuntimeError(f"腾讯文档异步导入失败：{result}")
        query_id = result["data"]["progressQueryID"]

        while True:
            progress_response = requests.get(
                f"{API_ROOT}/openapi/drive/v2/files/import-progress",
                headers=self.headers(),
                params={"progressQueryID": query_id},
                timeout=30,
            )
            progress_response.raise_for_status()
            progress = progress_response.json()
            if progress.get("ret", 0) != 0:
                raise RuntimeError(f"腾讯文档查询导入进度失败：{progress}")
            data = progress.get("data") or {}
            if int(data.get("progress") or 0) >= 100:
                return data
            time.sleep(2)

    def update_range(self, range_: str, values: list[list[Any]]) -> None:
        if not self.file_id or not self.sheet_id:
            raise RuntimeError("缺少 QQDOCS_FILE_ID 或 QQDOCS_SHEET_ID")
        encoded_range = f"{urllib.parse.quote(self.sheet_id, safe='')}!{urllib.parse.quote(range_, safe='!:')}"
        url = (
            f"{API_ROOT}/openapi/sheetbook/v2/"
            f"{urllib.parse.quote(self.file_id, safe='')}/values/{encoded_range}"
        )
        response = requests.put(
            url,
            headers={**self.headers(), "Content-Type": "application/json"},
            json={"values": values},
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("ret", 0) != 0:
            raise RuntimeError(f"腾讯文档写入失败：{payload}")


def matrix_to_rows(matrix: list[list[str]]) -> list[dict[str, Any]]:
    if not matrix:
        raise RuntimeError("腾讯文档返回了空范围")
    header = [value.strip() for value in matrix[0]]
    field_for_column = [HEADER_TO_FIELD.get(value, "") for value in header]
    rows: list[dict[str, Any]] = []
    for values in matrix[1:]:
        if not any(str(value).strip() for value in values):
            continue
        raw = {}
        for index, field in enumerate(field_for_column):
            if field:
                raw[field] = str(values[index]) if index < len(values) else ""
        if not raw.get("title", "").strip():
            continue
        rows.append(merge_sheet_row(raw))
    return rows


def rows_to_matrix(rows: list[dict[str, Any]]) -> list[list[Any]]:
    matrix: list[list[Any]] = [[
        "同步键",
        "分类",
        "成就名",
        "描述",
        "达成条件",
        "攻略",
        "参考资料",
        "奖励",
        "Secret",
        "Hidden",
        "Obtainable",
        "Badge ID",
        "旧版本",
        "Wiki 修订",
        "行哈希",
        "同步状态",
    ]]
    for row in rows:
        matrix.append([
            str(row.get("key", "")),
            str(row.get("category", "")),
            str(row.get("title", "")),
            str(row.get("text", "")),
            str(row.get("directions", "")),
            str(row.get("tutorial", "")),
            str(row.get("references", "")),
            str(row.get("rewards", "nil")),
            str(bool(row.get("secret", False))).lower(),
            str(bool(row.get("hidden", False))).lower(),
            str(bool(row.get("obtainable", True))).lower(),
            str(row.get("badge_id", "")),
            str(row.get("old_versions", "nil")),
            str(row.get("wiki_rev", "")),
            str(row.get("row_hash", row_hash(row))),
            str(row.get("sync_status", STATUS_SYNCED)),
        ])
    return matrix


def pad_matrix(matrix: list[list[Any]], width: int = MATRIX_WIDTH) -> list[list[str]]:
    """把矩阵规整成固定列宽、全部为字符串的形式，便于逐格比较。"""
    padded: list[list[str]] = []
    for row in matrix:
        cells = ["" if cell is None else str(cell) for cell in list(row)[:width]]
        cells.extend([""] * (width - len(cells)))
        padded.append(cells)
    return padded


def lua_quote(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\r", "")
        .replace("\n", "\\n")
    )
    return f"'{escaped}'"


def lua_raw(value: str, indent: str) -> str:
    value = (value or "nil").strip()
    if "\n" not in value:
        return value
    lines = value.splitlines()
    return "\n".join([lines[0]] + [indent + line for line in lines[1:]])


def render_module(rows: list[dict[str, Any]]) -> str:
    grouped: dict[str, list[dict[str, Any]]] = {name: [] for name in CATEGORY_ORDER}
    for row in rows:
        category = row.get("category", "")
        if category in grouped:
            grouped[category].append(row)

    out = ["return {"]
    for category in CATEGORY_ORDER:
        entries = grouped[category]
        if not entries:
            continue
        out.append(f"\t{category} = {{")
        for row in entries:
            text = row.get("text", "")
            directions = row.get("directions", "")
            tutorial = row.get("tutorial", "")
            out.extend([
                "\t\t{",
                f"\t\t\ttitle = {lua_quote(row.get('title', ''))},",
                f"\t\t\ttext = {lua_quote(text) if text else 'nil'},",
                f"\t\t\tdirections = {lua_quote(directions) if directions else 'nil'},",
                f"\t\t\ttutorial = {lua_quote(tutorial) if tutorial else 'nil'},",
            ])
            references = row.get("references", "")
            out.append(
                f"\t\t\treferences = {lua_quote(references) if references else 'nil'},"
            )
            rewards = row.get("rewards", "nil") or "nil"
            out.append(f"\t\t\trewards = {lua_raw(rewards, chr(9) * 3)},")
            out.append(f"\t\t\tsecret = {'true' if row.get('secret') else 'false'},")
            out.append(f"\t\t\thidden = {'true' if row.get('hidden') else 'false'},")
            out.append(
                f"\t\t\tobtainable = {'true' if row.get('obtainable') else 'false'},"
            )
            badge_id = row.get("badge_id", "")
            if badge_id:
                out.append(f"\t\t\tid = {lua_quote(badge_id)},")
            old_versions = row.get("old_versions", "")
            if old_versions and old_versions.strip() != "nil":
                out.append(
                    f"\t\t\toldVersions = {lua_raw(old_versions, chr(9) * 3)},"
                )
            out.append("\t\t},")
        out.append("\t},")
    out.append("}")
    return "\n".join(out) + "\n"


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


def _field_value(row: dict[str, Any], field: str) -> str:
    value = row.get(field, "")
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


class GristSheet:
    """把 Grist 的 Achievements 表当作表格后端，行结构与腾讯侧一致。"""

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
        rows: list[dict[str, Any]] = []
        for record in self.session.get(
            self.url, params={"limit": 2000}, timeout=120
        ).json().get("records", []):
            fields = record.get("fields") or {}
            row = {field: _field_value(fields, field)
                   for field in CSV_FIELDS}
            row[GRIST_ID_FIELD] = record.get("id")
            rows.append(row)
        return rows

    def _payload(self, row: dict[str, Any]) -> dict[str, str]:
        return {field: _field_value(row, field) for field in CSV_FIELDS}

    def patch(self, rows: list[dict[str, Any]]) -> int:
        groups: dict[tuple, list[dict[str, Any]]] = {}
        for row in rows:
            fields = self._payload(row)
            payload = {"id": row[GRIST_ID_FIELD], "fields": fields}
            groups.setdefault(tuple(sorted(fields)), []).append(payload)
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
            json={"records": [{"fields": self._payload(row)} for row in rows]},
            timeout=300,
        )
        if resp.status_code >= 400:
            print("GRIST POST 失败:", resp.status_code, resp.text[:200])
            return 0
        return len(rows)


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
    markers: dict[str, dict[str, bool]] | None = None,
) -> None:
    preserve = preserve or {}
    markers = markers or {}
    state_rows = {}
    for key in sorted(set(wiki_rows) | set(sheet_rows)):
        entry = dict(
            preserve.get(key)
            or {
                "wiki_hash": row_hash(wiki_rows[key]) if key in wiki_rows else "",
                "sheet_hash": row_hash(sheet_rows[key]) if key in sheet_rows else "",
            }
        )
        for flag in ("wiki_deleted", "sheet_deleted"):
            if (markers.get(key) or {}).get(flag):
                entry[flag] = True
            else:
                entry.pop(flag, None)
        state_rows[key] = entry
    payload = {"revision": revision, "rows": state_rows}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def replace_wiki_fields(
    target: dict[str, Any],
    source: dict[str, Any],
) -> dict[str, Any]:
    updated = dict(target)
    for field in EDITABLE_FIELDS:
        updated[field] = source.get(field, "")
    for field in ("rewards", "secret", "hidden", "obtainable", "badge_id", "old_versions"):
        if field in source:
            updated[field] = source[field]
    updated["row_hash"] = row_hash(updated)
    return updated


def save_module_text(site: pywikibot.Site, rows: list[dict[str, Any]]) -> int:
    page = pywikibot.Page(site, "Module:BadgeData")
    previous = page.text
    new_text = render_module(rows)
    page.put(new_text, summary=SUMMARY)
    try:
        data = site.simple_request(
            action="parse",
            text="{{#invoke:BadgeList|main|BadgeCount|All}}",
            title="Project:Sandbox",
            prop="text",
            disablelimitreport="1",
            formatversion="2",
        ).submit()
        rendered = data.get("parse", {}).get("text", "")
        if any(marker in rendered for marker in ("Lua error", "Script error", "LuaError")):
            raise RuntimeError(rendered[:500])
    except Exception:
        pywikibot.Page(site, "Module:BadgeData").put(previous, summary="回滚成就同步")
        raise
    return page.latest_revision_id


def run_sync(apply: bool, state_path: Path, backend: str = "grist") -> int:
    site = pywikibot.Site("zhdoors", "zhdoors")
    revision, wiki_rows = fetch_rows()
    wiki_by_key = {row["key"]: row for row in wiki_rows}
    grist: GristSheet | None = None
    sheet_matrix: list[list[Any]] = []
    if backend == "grist":
        grist = GristSheet()
        sheet_rows = grist.fetch()
    else:
        client = TencentDocsClient()
        sheet_matrix = client.get_range("A1:P500")
        sheet_rows = matrix_to_rows(sheet_matrix)
    sheet_by_key = {row["key"]: row for row in sheet_rows}
    state = load_state(state_path)
    last_rows = state.get("rows", {})

    wiki_updates: dict[str, dict[str, Any]] = {}
    sheet_updates: dict[str, dict[str, Any]] = {}
    conflicts: list[str] = []
    # 两端各自的「主动删除」：识别出来后不再回填，避免删除被反复撤销。
    sheet_deleted: set[str] = set()
    wiki_deleted: set[str] = set()

    for key in sorted(set(last_rows) | set(wiki_by_key) | set(sheet_by_key)):
        wiki = wiki_by_key.get(key)
        sheet = sheet_by_key.get(key)
        previous = last_rows.get(key, {})
        wiki_hash = row_hash(wiki) if wiki else ""
        sheet_hash = row_hash(sheet) if sheet else ""
        wiki_changed = bool(wiki and wiki_hash != previous.get("wiki_hash", ""))
        sheet_changed = bool(sheet and sheet_hash != previous.get("sheet_hash", ""))
        seen_before = bool(
            previous.get("wiki_hash") or previous.get("sheet_hash")
        )

        if wiki and not sheet:
            if previous.get("sheet_deleted"):
                sheet_deleted.add(key)
            elif not seen_before:
                sheet_updates[key] = dict(wiki)
                sheet_updates[key]["sync_status"] = STATUS_WIKI_NEW
            else:
                # 这一行原本同步过、现在表格里没了：判定为表格端删除，保留 Wiki 成就
                sheet_deleted.add(key)
        elif sheet and not wiki:
            if previous.get("wiki_deleted"):
                wiki_deleted.add(key)
            elif not seen_before:
                if not sheet.get("title") or not sheet.get("category"):
                    conflicts.append(key)
                    continue
                wiki_updates[key] = dict(sheet)
                wiki_updates[key]["sync_status"] = STATUS_SHEET_NEW
            else:
                # Wiki 成就已删除：尊重删除，不回填，只在表格里标注
                wiki_deleted.add(key)
                marked = dict(sheet)
                marked["wiki_rev"] = revision
                marked["sync_status"] = STATUS_WIKI_DELETED
                marked["row_hash"] = row_hash(marked)
                sheet_updates[key] = marked
        elif wiki and sheet:
            if wiki_changed and not sheet_changed:
                sheet_updates[key] = dict(wiki)
                sheet_updates[key]["sync_status"] = STATUS_WIKI_UPDATED
            elif sheet_changed and not wiki_changed:
                wiki_updates[key] = replace_wiki_fields(wiki, sheet)
                wiki_updates[key]["sync_status"] = STATUS_SHEET_UPDATED
            elif wiki_changed and sheet_changed and wiki_hash != sheet_hash:
                conflicts.append(key)
            else:
                if sheet.get("sync_status") not in STATUS_LEGACY_SYNCED:
                    merged = dict(sheet)
                    merged["wiki_rev"] = revision
                    merged["sync_status"] = STATUS_SYNCED
                    sheet_updates[key] = merged

    print(
        f"revision={revision} wiki={len(wiki_rows)} sheet={len(sheet_rows)} "
        f"wiki->sheet={len(sheet_updates)} sheet->wiki={len(wiki_updates)} "
        f"conflicts={len(conflicts)} sheet-deleted={len(sheet_deleted)} "
        f"wiki-deleted={len(wiki_deleted)}"
    )
    for key in sorted(sheet_updates)[:30]:
        print(f"PULL\t{key}\t{sheet_updates[key].get('sync_status', '')}")
    for key in sorted(wiki_updates)[:30]:
        print(f"PUSH\t{key}\t{wiki_updates[key].get('sync_status', '')}")
    for key in conflicts[:30]:
        print(f"CONFLICT\t{key}")
    for key in sorted(sheet_deleted)[:30]:
        print(f"SHEET-DELETED\t{key}")
    for key in sorted(wiki_deleted)[:30]:
        print(f"WIKI-DELETED\t{key}")

    if not apply:
        return 0

    if wiki_updates:
        final_wiki_by_key = dict(wiki_by_key)
        final_wiki_by_key.update(wiki_updates)
        final_rows = list(final_wiki_by_key.values())
        revision = save_module_text(site, final_rows)
        wiki_rows = parse_module(
            pywikibot.Page(site, "Module:BadgeData").text,
            revision,
        )
        wiki_by_key = {row["key"]: row for row in wiki_rows}

    if grist is not None:
        # Grist 后端要保留 record id，否则会被当成新增行重复插入
        final_sheet_by_key = {key: dict(row) for key, row in sheet_by_key.items()}
    else:
        # 被判定为「表格端已删除」的行不再回填表格
        final_sheet_by_key = {
            key: row for key, row in wiki_by_key.items()
            if key not in sheet_deleted
        }
    for key, row in sheet_updates.items():
        final_sheet_by_key[key] = row
    if grist is not None:
        for key, row in wiki_updates.items():
            merged = dict(row)
            source = sheet_by_key.get(key) or {}
            if source.get(GRIST_ID_FIELD):
                merged[GRIST_ID_FIELD] = source[GRIST_ID_FIELD]
            final_sheet_by_key[key] = merged
    final_sheet_rows = list(final_sheet_by_key.values())
    for row in final_sheet_rows:
        key = row.get("key")
        if key in conflicts:
            row["sync_status"] = STATUS_CONFLICT
            row["row_hash"] = row_hash(row)
        elif key in wiki_deleted:
            row["sync_status"] = STATUS_WIKI_DELETED
            row["wiki_rev"] = revision
            row["row_hash"] = row_hash(row)
        else:
            row["sync_status"] = STATUS_SYNCED
            row["wiki_rev"] = revision
            row["row_hash"] = row_hash(row)
    if grist is not None:
        original = {row["key"]: row for row in sheet_rows}
        to_patch, to_add = [], []
        # 同步簿记列每轮都会被重算，比对时排除，避免「内容没变也回写」
        compare = tuple(
            field for field in CSV_FIELDS
            if field not in ("wiki_rev", "row_hash", "sync_status")
        )

        def cmp_payload(row: dict[str, Any]) -> dict[str, str]:
            return {field: _field_value(row, field) for field in compare}

        for row in final_sheet_rows:
            if not row.get(GRIST_ID_FIELD):
                to_add.append(row)
                continue
            before = original.get(row.get("key"))
            if not before or cmp_payload(before) != cmp_payload(row):
                to_patch.append(row)
        if to_patch or to_add:
            print(f"grist updated: patch={grist.patch(to_patch)} "
                  f"add={grist.add(to_add)}")
        else:
            print("grist unchanged, skip write")
    else:
        matrix = pad_matrix(rows_to_matrix(final_sheet_rows))
        current = pad_matrix(sheet_matrix)
        # 表格里比脚本管理范围多出来的行原样保留
        while len(matrix) < len(current):
            matrix.append(list(current[len(matrix)]))
        if matrix != current:
            client.update_range(f"A1:P{len(matrix)}", matrix)
            print(f"sheet updated ({len(matrix)} rows)")
        else:
            print("sheet unchanged, skip write")
    save_state(
        state_path,
        revision,
        wiki_by_key,
        {row["key"]: row for row in final_sheet_rows},
        preserve={
            key: last_rows.get(key, {})
            for key in conflicts
            if key in last_rows
        },
        markers={
            **{key: {"sheet_deleted": True} for key in sheet_deleted},
            **{key: {"wiki_deleted": True} for key in wiki_deleted},
        },
    )
    print("applied")
    return 0


def write_json(path: Path, revision: int, rows: list[dict[str, Any]]) -> None:
    payload = {
        "source": "zh.doorsgame.wiki Module:BadgeData",
        "revision": revision,
        "count": len(rows),
        "rows": rows,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in CSV_FIELDS})


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def command_auth_url(args: argparse.Namespace) -> int:
    load_env(ENV_FILE)
    client_id = args.client_id or os.environ.get("QQDOCS_CLIENT_ID", "")
    if not client_id:
        raise RuntimeError("缺少 QQDOCS_CLIENT_ID")
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": args.redirect_uri,
            "new_login": "1",
            "response_type": "code",
            "scope": "all",
            "state": args.state or "doors-wiki-achievements",
        },
        quote_via=urllib.parse.quote,
    )
    print(f"{API_ROOT}/oauth/v2/authorize?{query}")
    return 0


def command_exchange_code(args: argparse.Namespace) -> int:
    client = TencentDocsClient()
    client.exchange_code(args.code, args.redirect_uri)
    print(f"Token 已保存到 {TOKEN_FILE}")
    return 0


def command_sheet_pull(args: argparse.Namespace) -> int:
    client = TencentDocsClient()
    rows = matrix_to_rows(client.get_range(f"A1:P{args.max_rows}"))
    write_json(Path(args.json), 0, rows)
    write_csv(Path(args.csv), rows)
    print(f"sheet rows={len(rows)}")
    return 0


def command_sheets(args: argparse.Namespace) -> int:
    client = TencentDocsClient()
    for sheet in client.sheets_info():
        print(
            f"{sheet.get('sheetID', '')}\t{sheet.get('title', '')}\t"
            f"{sheet.get('rowCount', '')}x{sheet.get('columnCount', '')}"
        )
    return 0


def command_import_file(args: argparse.Namespace) -> int:
    client = TencentDocsClient()
    result = client.import_file(Path(args.path), args.title)
    print(
        f"ID={result.get('ID', '')}\n"
        f"title={result.get('title', '')}\n"
        f"type={result.get('type', '')}\n"
        f"url={result.get('url', '')}"
    )
    return 0


def command_sync(args: argparse.Namespace) -> int:
    return run_sync(args.apply, Path(args.state), args.backend)


def command_watch(args: argparse.Namespace) -> int:
    while True:
        try:
            run_sync(args.apply, Path(args.state), args.backend)
        except Exception as error:
            print(f"sync failed: {type(error).__name__}: {error}", file=sys.stderr)
        time.sleep(args.interval)


def command_init_state(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.json).read_text(encoding="utf-8"))
    rows = payload["rows"]
    state_rows = {
        row["key"]: {
            "wiki_hash": row["row_hash"],
            "sheet_hash": row["row_hash"],
        }
        for row in rows
    }
    state = {"revision": payload["revision"], "rows": state_rows}
    path = Path(args.state)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"state rows={len(state_rows)} revision={payload['revision']}")
    return 0


def command_fetch(args: argparse.Namespace) -> int:
    revision, rows = fetch_rows()
    write_json(Path(args.json), revision, rows)
    write_csv(Path(args.csv), rows)
    print(f"Module:BadgeData revision={revision} rows={len(rows)}")
    return 0


def command_compare(args: argparse.Namespace) -> int:
    revision, wiki_rows = fetch_rows()
    wiki_by_key = {row["key"]: row for row in wiki_rows}
    sheet_rows = read_csv(Path(args.sheet))
    sheet_by_key = {row.get("key", ""): row for row in sheet_rows if row.get("key")}

    added = sorted(set(wiki_by_key) - set(sheet_by_key))
    missing = sorted(set(sheet_by_key) - set(wiki_by_key))
    changed = []
    for key in sorted(set(wiki_by_key) & set(sheet_by_key)):
        sheet = sheet_by_key[key]
        if row_hash(sheet) != wiki_by_key[key]["row_hash"]:
            changed.append(key)

    print(f"revision={revision}")
    print(f"wiki_rows={len(wiki_rows)} sheet_rows={len(sheet_rows)}")
    print(f"wiki_only={len(added)} sheet_only={len(missing)} text_diff={len(changed)}")
    for label, keys in (("WIKI_ONLY", added), ("SHEET_ONLY", missing), ("DIFF", changed)):
        for key in keys[:50]:
            print(f"{label}\t{key}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch = subparsers.add_parser("fetch")
    fetch.add_argument("--json", required=True)
    fetch.add_argument("--csv", required=True)
    fetch.set_defaults(func=command_fetch)

    init_state = subparsers.add_parser("init-state")
    init_state.add_argument("--json", required=True)
    init_state.add_argument("--state", required=True)
    init_state.set_defaults(func=command_init_state)

    auth_url = subparsers.add_parser("auth-url")
    auth_url.add_argument("--client-id")
    auth_url.add_argument("--redirect-uri", required=True)
    auth_url.add_argument("--state")
    auth_url.set_defaults(func=command_auth_url)

    exchange = subparsers.add_parser("exchange-code")
    exchange.add_argument("--code", required=True)
    exchange.add_argument("--redirect-uri", required=True)
    exchange.set_defaults(func=command_exchange_code)

    sheet_pull = subparsers.add_parser("sheet-pull")
    sheet_pull.add_argument("--json", required=True)
    sheet_pull.add_argument("--csv", required=True)
    sheet_pull.add_argument("--max-rows", type=int, default=500)
    sheet_pull.set_defaults(func=command_sheet_pull)

    sheets = subparsers.add_parser("sheets")
    sheets.set_defaults(func=command_sheets)

    import_file = subparsers.add_parser("import-file")
    import_file.add_argument("--path", required=True)
    import_file.add_argument("--title")
    import_file.set_defaults(func=command_import_file)

    sync = subparsers.add_parser("sync")
    sync.add_argument("--state", default="data/achievements_sync_state.json")
    sync.add_argument("--apply", action="store_true")
    sync.add_argument("--backend", choices=["grist", "tencent"],
                      default="grist")
    sync.set_defaults(func=command_sync)

    watch = subparsers.add_parser("watch")
    watch.add_argument("--state", default="data/achievements_sync_state.json")
    watch.add_argument("--interval", type=int, default=300)
    watch.add_argument("--apply", action="store_true")
    watch.add_argument("--backend", choices=["grist", "tencent"],
                       default="grist")
    watch.set_defaults(func=command_watch)

    compare = subparsers.add_parser("compare")
    compare.add_argument("--sheet", required=True)
    compare.set_defaults(func=command_compare)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
