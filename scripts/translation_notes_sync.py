#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同步 Module:TranslationNotes 的说明字段到外部表格。

维基始终是最终数据源：
  * 维基新增或修改，外部未变化：写外部并标记“已同步”。
  * 外部修改，维基未变化：保留两边内容，标记“冲突/待审”。
  * 两边同时变化且不一致：保留两边内容，标记“冲突/待审”。

物品说明写入 Grist/腾讯 ItemNames 的 reason、confirmed、note 字段。
实体说明按当前约定只保存在维基，不创建外部实体行。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
from dataclasses import dataclass
from typing import Any

import pywikibot
import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import achievements_sync as A  # noqa: E402
import item_names_sync as I  # noqa: E402

NOTES_MODULE = "Module:TranslationNotes"
STATE_FILE = pathlib.Path("data/translation_notes_sync_state.json")
SYNC_FIELDS = ("reason", "confirmed", "note")
STATUS_SYNCED = "已同步"
STATUS_CONFLICT = "冲突/待审"
STATUS_WIKI_ONLY = "仅维基"


@dataclass(frozen=True)
class Note:
    key: str
    kind: str
    display: str
    literal: str
    rationale: str
    alternatives: tuple[str, ...]
    status: str
    confirmed: str
    discussion: str
    history: tuple[str, ...]


def quoted_strings(body: str) -> tuple[str, ...]:
    return tuple(
        A.parse_lua_string("'" + value + "'")
        for value in re.findall(r"'((?:[^'\\]|\\.)*)'", body)
    )


def parse_group(text: str, group: str) -> list[Note]:
    group_match = re.search(
        rf"\b{group}\s*=\s*\{{",
        text,
        re.IGNORECASE,
    )
    if not group_match:
        return []
    start = group_match.end() - 1
    end = A.matching_brace(text, start)
    body = text[start + 1:end]
    notes: list[Note] = []
    for match in re.finditer(
        r"\[\s*'((?:[^'\\]|\\.)*)'\s*\]\s*=\s*\{",
        body,
    ):
        key = A.parse_lua_string("'" + match.group(1) + "'")
        entry_start = match.end() - 1
        entry_end = A.matching_brace(body, entry_start)
        entry = body[entry_start + 1:entry_end]

        def string_field(name: str) -> str:
            found = re.search(
                rf"\b{name}\s*=\s*'((?:[^'\\]|\\.)*)'",
                entry,
                re.DOTALL,
            )
            return (
                A.parse_lua_string("'" + found.group(1) + "'")
                if found else ""
            )

        def list_field(name: str) -> tuple[str, ...]:
            found = re.search(
                rf"\b{name}\s*=\s*\{{",
                entry,
            )
            if not found:
                return ()
            table_start = found.end() - 1
            table_end = A.matching_brace(entry, table_start)
            return quoted_strings(entry[table_start + 1:table_end])

        notes.append(
            Note(
                key=key,
                kind=group.rstrip("s"),
                display=string_field("display"),
                literal=string_field("literal"),
                rationale=string_field("rationale"),
                alternatives=list_field("alternatives"),
                status=string_field("status"),
                confirmed=string_field("confirmed"),
                discussion=string_field("discussion"),
                history=list_field("history"),
            )
        )
    return notes


def parse_notes_module(text: str) -> list[Note]:
    text = "\n".join(
        line for line in text.splitlines()
        if not line.lstrip().startswith("--")
    )
    return parse_group(text, "items") + parse_group(text, "entities")


def note_payload(note: Note) -> dict[str, str]:
    return {
        "reason": note.rationale,
        "confirmed": note.confirmed,
        "note": format_note(note),
    }


def format_note(note: Note) -> str:
    lines: list[str] = []
    if note.literal:
        lines.append("字面含义：" + note.literal)
    if note.alternatives:
        lines.append("备选译名：" + " / ".join(note.alternatives))
    if note.discussion:
        lines.append("讨论记录：" + note.discussion)
    if note.history:
        lines.append("历史记录：" + "；".join(note.history))
    return "\n".join(lines)


def payload_hash(payload: dict[str, str]) -> str:
    encoded = json.dumps(
        {field: payload.get(field, "") for field in SYNC_FIELDS},
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()


def plan_row(
    wiki: dict[str, str],
    external: dict[str, str] | None,
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    if not wiki.get("reason"):
        return {"status": "待完善", "write": False}
    if external is None:
        return {"status": "无外部记录", "write": False}

    wiki_hash = payload_hash(wiki)
    external_hash = payload_hash(external)
    if not previous:
        if not any(external.get(field, "") for field in SYNC_FIELDS):
            return {"status": STATUS_SYNCED, "write": True}
        return {"status": STATUS_CONFLICT, "write": False}

    wiki_changed = wiki_hash != previous.get("wiki_hash", "")
    external_changed = external_hash != previous.get("external_hash", "")
    conflicted = bool(previous.get("conflict"))

    if conflicted:
        if wiki == external:
            return {"status": STATUS_SYNCED, "write": False}
        return {"status": STATUS_CONFLICT, "write": False}
    if wiki == external:
        return {"status": STATUS_SYNCED, "write": False}
    if wiki_changed and not external_changed:
        return {"status": STATUS_SYNCED, "write": True}
    if external_changed and not wiki_changed:
        return {"status": STATUS_CONFLICT, "write": False}
    return {"status": STATUS_CONFLICT, "write": False}


def load_state(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {"backends": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if "backends" not in data:
            data = {"backends": {"grist": data.get("rows", {})}}
        return data
    except (OSError, json.JSONDecodeError):
        return {"backends": {}}


def save_state(path: pathlib.Path, backends: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"backends": backends}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


class GristItemNames:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {A.load_grist_key()}",
            "Content-Type": "application/json",
        })
        self.url = (
            f"{I.GRIST_SERVER}/api/docs/{I.GRIST_DOC_ID}/tables/"
            "ItemNames/records"
        )

    def fetch(self) -> dict[str, dict[str, Any]]:
        response = self.session.get(
            self.url, params={"limit": 2000}, timeout=120
        )
        response.raise_for_status()
        rows: dict[str, dict[str, Any]] = {}
        for record in response.json().get("records", []):
            fields = record.get("fields") or {}
            key = fields.get("english", "")
            if key:
                rows[key] = {
                    "id": record.get("id"),
                    "fields": fields,
                }
        return rows

    def patch_fields(
        self,
        rows: list[dict[str, Any]],
    ) -> int:
        if not rows:
            return 0
        response = self.session.patch(
            self.url,
            json={"records": rows},
            timeout=300,
        )
        if response.status_code >= 400:
            print("GRIST PATCH 失败:", response.status_code, response.text[:200])
            return 0
        return len(rows)


class TencentItemNames:
    def __init__(self) -> None:
        self.client = I.client()
        self.rows: dict[str, int] = {}
        self.header_ready = False

    def fetch(self) -> dict[str, dict[str, str]]:
        matrix = self.client.get_range("A1:R200")
        header = matrix[3] if len(matrix) >= 4 else []
        self.header_ready = bool(
            len(header) >= 18 and str(header[17]).strip() == "sync_status"
        )
        rows: dict[str, dict[str, str]] = {}
        for offset, values in enumerate(matrix[4:], start=5):
            key = values[1] if len(values) > 1 else ""
            if not key:
                continue
            key = str(key).strip()
            self.rows[key] = offset
            rows[key] = {
                "reason": str(values[8]) if len(values) > 8 else "",
                "confirmed": str(values[15]) if len(values) > 15 else "",
                "note": str(values[16]) if len(values) > 16 else "",
                "sync_status": str(values[17]) if len(values) > 17 else "",
            }
        return rows

    def ensure_header(self) -> None:
        if self.header_ready:
            return
        self.client.update_range("R4:R4", [["sync_status"]])
        self.header_ready = True

    def patch_row(
        self,
        key: str,
        payload: dict[str, str],
        status: str,
    ) -> None:
        row = self.rows.get(key)
        if not row:
            return
        if payload:
            self.client.update_range(f"I{row}:I{row}", [[payload["reason"]]])
            self.client.update_range(f"P{row}:P{row}", [[payload["confirmed"]]])
            self.client.update_range(f"Q{row}:Q{row}", [[payload["note"]]])
        self.client.update_range(f"R{row}:R{row}", [[status]])


def external_payload(
    fields: dict[str, Any],
) -> dict[str, str]:
    return {
        field: str(fields.get(field, "") or "")
        for field in SYNC_FIELDS
    }


def sync_backend(
    name: str,
    notes: list[Note],
    external_rows: dict[str, dict[str, Any]],
    previous_rows: dict[str, Any],
    apply: bool,
) -> tuple[dict[str, Any], int]:
    updated_state = dict(previous_rows)
    writes = 0
    for note in notes:
        if note.kind != "item":
            continue
        wiki = note_payload(note)
        external_row = external_rows.get(note.key)
        if not external_row:
            print(f"{name} 无外部记录\t{note.key}")
            continue
        fields = external_row.get("fields", external_row)
        external = external_payload(fields)
        previous = previous_rows.get(note.key)
        plan = plan_row(wiki, external, previous)
        status = plan["status"]
        print(f"{name}\t{status}\t{note.key}")
        if not apply:
            continue

        if plan.get("write"):
            if name == "grist":
                external_row.setdefault("fields", {}).update(wiki)
                external_row["fields"]["sync_status"] = status
                writes += 1
            elif name == "tencent":
                external_row["patch_row"](note.key, wiki, status)
                writes += 1
        else:
            if name == "grist":
                external_row.setdefault("fields", {})["sync_status"] = status
                writes += 1
            elif name == "tencent":
                external_row["patch_row"](note.key, {}, status)
                writes += 1

        external_after = (
            wiki if plan.get("write") else external
        )
        updated_state[note.key] = {
            "wiki_hash": payload_hash(wiki),
            "external_hash": payload_hash(external_after),
            "conflict": status == STATUS_CONFLICT,
        }
    return updated_state, writes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--backend",
        choices=["grist", "tencent", "both"],
        default="both",
    )
    args = parser.parse_args()

    site = pywikibot.Site("zhdoors", "zhdoors")
    page = pywikibot.Page(site, NOTES_MODULE)
    if not page.exists():
        raise RuntimeError(f"{NOTES_MODULE} 不存在")
    notes = parse_notes_module(page.text)
    item_notes = [note for note in notes if note.kind == "item"]
    entity_notes = [note for note in notes if note.kind == "entity"]
    print(f"wiki notes={len(notes)} items={len(item_notes)} entities={len(entity_notes)}")
    for note in entity_notes:
        print(f"实体说明仅保存在维基\t{note.key}")

    state = load_state(STATE_FILE)
    state_backends = state.get("backends", {})
    grist_state = dict(state_backends.get("grist", {}))
    tencent_state = dict(state_backends.get("tencent", {}))
    any_writes = 0

    if args.backend in ("grist", "both"):
        grist = GristItemNames()
        grist_rows = grist.fetch()
        backend_state, writes = sync_backend(
            "grist",
            notes,
            grist_rows,
            grist_state,
            args.apply,
        )
        any_writes += writes
        state_backends["grist"] = backend_state
        if args.apply and writes:
            payload = []
            for key, row in grist_rows.items():
                note = next((n for n in item_notes if n.key == key), None)
                if not note:
                    continue
                fields = row.get("fields") or {}
                if fields.get("sync_status"):
                    payload.append({
                        "id": row.get("id"),
                        "fields": {
                            field: fields.get(field, "")
                            for field in (*SYNC_FIELDS, "sync_status")
                        },
                    })
            any_writes += grist.patch_fields(payload)

    if args.backend in ("tencent", "both"):
        tencent = TencentItemNames()
        tencent_rows = tencent.fetch()
        if args.apply and item_notes:
            tencent.ensure_header()
        wrapped = {
            key: {
                "fields": payload,
                "patch_row": tencent.patch_row,
            }
            for key, payload in tencent_rows.items()
        }
        backend_state, writes = sync_backend(
            "tencent",
            notes,
            wrapped,
            tencent_state,
            args.apply,
        )
        any_writes += writes
        state_backends["tencent"] = backend_state

    if args.apply:
        save_state(STATE_FILE, state_backends)
        print(f"applied writes={any_writes} state={STATE_FILE}")
    else:
        print("dry-run，未写入。加 --apply 执行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
