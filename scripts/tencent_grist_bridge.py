# -*- coding: utf-8 -*-
"""腾讯文档 → Grist 单向同步（腾讯为主，Grist 为辅）。

用法：
    python scripts/tencent_grist_bridge.py             # 干跑，只报告差异
    python scripts/tencent_grist_bridge.py --apply      # 写入 Grist

规则：
    - 腾讯文档是主，Grist 是辅：主表的值覆盖辅表
    - 按 key 匹配（物品用「英文名」，成就用「同步键」）
    - 主表新增行 → 辅表新增；主表缺失的行**不删**，只报告（防误删）
    - 只写真正变化的字段，避免无谓调用
"""
import argparse
import json
import os
import pathlib
import sys

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import achievements_sync as A  # noqa: E402

SERVER = os.environ.get("GRIST_SERVER", "https://sheet.189-24-78-35.sslip.io")
DOC_ID = os.environ.get("GRIST_DOC_ID", "1JRoy2vJar2kh945PXUbFP")
ITEM_FILE_ID = "300000000$" + __import__("base64").b64decode(
    "UkhWU3VFU3NNTFNR"
).decode()
ITEM_SHEET_ID = "000001"
ACH_FILE_ID = "300000000$" + __import__("base64").b64decode(
    "UmpVeG9mTEt1b0Nr"
).decode()
ACH_SHEET_ID = "000001"
STATE = pathlib.Path("data/tencent_grist_bridge_state.json")

# 腾讯表格列（1-based）→ Grist 列
ITEM_MAP = {
    "english": 2, "suggested": 3, "alt1": 4, "alt2": 5, "alt3": 6,
    "alt4": 7, "final": 8, "reason": 9, "category": 10, "page": 11,
    "source": 12, "status": 13, "priority": 14, "owner": 15,
    "confirmed": 16, "note": 17,
}
ACH_MAP = {
    "key": 1, "category": 2, "title": 3, "text": 4, "directions": 5,
    "tutorial": 6, "references": 7, "rewards": 8, "secret": 9,
    "hidden": 10, "obtainable": 11, "badge_id": 12, "old_versions": 13,
    "wiki_rev": 14, "row_hash": 15, "sync_status": 16,
}
MODIFIER_MAP = {
    "key": 1, "category": 2, "title": 3, "description": 4,
    "description_en": 5, "requirements": 6, "exclusive": 7,
    "knobs": 8, "rift": 9, "progress": 10, "group": 11,
    "reason": 12, "wiki_rev": 13, "row_hash": 14, "sync_status": 15,
}


def load_key() -> str:
    key = os.environ.get("GRIST_API_KEY", "")
    if key:
        return key
    path = pathlib.Path("grist.env")
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("GRIST_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise SystemExit("缺少 GRIST_API_KEY")


class Grist:
    def __init__(self, key: str) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        })

    def records(self, table: str) -> list[dict]:
        resp = self.session.get(
            f"{SERVER}/api/docs/{DOC_ID}/tables/{table}/records",
            params={"limit": 2000}, timeout=120,
        )
        resp.raise_for_status()
        return resp.json().get("records") or []

    def add(self, table: str, rows: list[dict]) -> int:
        if not rows:
            return 0
        resp = self.session.post(
            f"{SERVER}/api/docs/{DOC_ID}/tables/{table}/records",
            json={"records": [{"fields": r} for r in rows]}, timeout=300,
        )
        resp.raise_for_status()
        return len(rows)

    def patch(self, table: str, rows: list[dict]) -> int:
        if not rows:
            return 0
        # Grist 要求同一请求内所有记录的字段集一致，按字段集分组发送
        groups: dict[tuple, list[dict]] = {}
        for row in rows:
            groups.setdefault(tuple(sorted(row["fields"])), []).append(row)
        done = 0
        for fields, group in groups.items():
            resp = self.session.patch(
                f"{SERVER}/api/docs/{DOC_ID}/tables/{table}/records",
                json={"records": group}, timeout=300,
            )
            if resp.status_code >= 400:
                print("   PATCH 失败:", resp.status_code, resp.text[:200],
                      "字段:", fields)
                continue
            done += len(group)
        return done


def sheet_matrix(file_id: str, sheet_id: str, rng: str) -> list[list]:
    A.load_env(A.ENV_FILE)
    client = A.TencentDocsClient()
    client.file_id = file_id
    client.sheet_id = sheet_id
    return client.get_range(rng)


def cell(row: list, index: int) -> str:
    pos = index - 1
    if pos >= len(row) or row[pos] is None:
        return ""
    return str(row[pos]).strip()


def rows_from_matrix(matrix: list[list], mapping: dict, header_row: int):
    out = []
    index_by_key: dict[str, int] = {}
    for row in matrix[header_row:]:
        key_field = "english" if "english" in mapping else "key"
        key = cell(row, mapping[key_field])
        if not key:
            continue
        record = {name: cell(row, col) for name, col in mapping.items()}
        if key in index_by_key:
            # 主表同一 key 出现多次时以最后一行为准（与其它读取口径一致）
            out[index_by_key[key]] = record
        else:
            index_by_key[key] = len(out)
            out.append(record)
    return out


def fill_master(grist, apply_changes: bool) -> int:
    """把辅表已有、主表为空的「处理状态/优先级」写回主表 M、N 两列。"""
    matrix = sheet_matrix(ITEM_FILE_ID, ITEM_SHEET_ID, "A1:Q200")
    source = {
        r["fields"].get("english", ""): r["fields"]
        for r in grist.records("ItemNames")
    }
    status_col = [[""]]
    priority_col = [[""]]
    filled = 0
    first_row = 5
    last_row = first_row - 1
    status_values, priority_values = [], []
    for offset, row in enumerate(matrix[first_row - 1:], start=first_row):
        key = cell(row, ITEM_MAP["english"])
        if not key:
            break
        fields = source.get(key) or {}
        status_values.append([fields.get("status", "")])
        priority_values.append([fields.get("priority", "")])
        if fields.get("status") or fields.get("priority"):
            filled += 1
        last_row = offset
    print(f"主表数据行 {first_row}..{last_row}（{len(status_values)} 行），"
          f"其中 {filled} 行可从辅表补齐")
    if not apply_changes:
        for index in range(min(3, len(status_values))):
            print("   示例：", matrix[first_row - 1 + index][1],
                  "->", status_values[index][0], "/", priority_values[index][0])
        print("干跑，未写入。加 --apply 执行。")
        return 0

    A.load_env(A.ENV_FILE)
    docs = A.TencentDocsClient()
    docs.file_id = ITEM_FILE_ID
    docs.sheet_id = ITEM_SHEET_ID
    docs.update_range(f"M{first_row}:M{last_row}", status_values)
    docs.update_range(f"N{first_row}:N{last_row}", priority_values)
    print(f"已写回 M{first_row}:M{last_row} 与 N{first_row}:N{last_row}")
    del status_col, priority_col
    return 0


def sync_table(grist, table, sheet_rows, key_field, apply_changes):
    existing = {r["fields"].get(key_field, ""): r for r in grist.records(table)}
    to_add, to_patch, missing, skipped = [], [], [], []
    for row in sheet_rows:
        key = row[key_field]
        current = existing.get(key)
        if not current:
            to_add.append(row)
            continue
        changed = {}
        for field, value in row.items():
            if field in {key_field, "wiki_rev", "row_hash", "sync_status"}:
                continue
            # 腾讯侧为空视为「没填」，不覆盖辅表已有内容，避免误清
            if value == "":
                if str(current["fields"].get(field, "")) != "":
                    skipped.append((key, field))
                continue
            if table == "Modifiers" and field in {"rift", "progress"}:
                value = (
                    "true"
                    if str(value).strip().lower() in {
                        "是", "true", "1", "yes", "on",
                    }
                    else "false"
                )
            if str(current["fields"].get(field, "")) != str(value):
                changed[field] = value
        if changed:
            to_patch.append({"id": current["id"], "fields": changed})
    sheet_keys = {r[key_field] for r in sheet_rows}
    missing = [k for k in existing if k not in sheet_keys]

    print(f"[{table}] 主表 {len(sheet_rows)} 条 / 辅表 {len(existing)} 条 | "
          f"新增 {len(to_add)} · 更新 {len(to_patch)} · 主表已无 {len(missing)} "
          f"· 主表为空跳过 {len(skipped)}")
    for row in to_add[:10]:
        print("   ADD   ", row[key_field])
    for row in to_patch[:10]:
        print("   PATCH ", row["id"], sorted(row["fields"]))
    for key in missing[:10]:
        print("   ONLY-IN-GRIST", key)
    for key, field in skipped[:10]:
        print(f"   SKIP-EMPTY {key}.{field}（腾讯侧为空，保留辅表值）")

    if apply_changes:
        print(f"   写入：新增 {grist.add(table, to_add)}，"
              f"更新 {grist.patch(table, to_patch)}")
    return {"add": len(to_add), "patch": len(to_patch), "missing": len(missing)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--only", choices=["items", "achievements", "modifiers"])
    parser.add_argument(
        "--fill-master", action="store_true",
        help="把 Grist 的「处理状态/优先级」写回腾讯主表的 M、N 两列",
    )
    args = parser.parse_args()
    grist = Grist(load_key())

    if args.fill_master:
        return fill_master(grist, args.apply)

    result = {}
    if args.only in (None, "items"):
        matrix = sheet_matrix(ITEM_FILE_ID, ITEM_SHEET_ID, "A1:Q200")
        result["items"] = sync_table(
            grist, "ItemNames",
            rows_from_matrix(matrix, ITEM_MAP, header_row=4),
            "english", args.apply,
        )
    if args.only in (None, "achievements"):
        matrix = sheet_matrix(ACH_FILE_ID, ACH_SHEET_ID, "A1:P200")
        result["achievements"] = sync_table(
            grist, "Achievements",
            rows_from_matrix(matrix, ACH_MAP, header_row=1),
            "key", args.apply,
        )
    if args.only in (None, "modifiers"):
        A.load_env(A.ENV_FILE)
        modifier_file_id = os.environ.get("QQDOCS_MODIFIERS_FILE_ID", "")
        modifier_sheet_id = os.environ.get("QQDOCS_MODIFIERS_SHEET_ID", "")
        if not modifier_file_id or not modifier_sheet_id:
            raise RuntimeError(
                "缺少 QQDOCS_MODIFIERS_FILE_ID 或 QQDOCS_MODIFIERS_SHEET_ID"
            )
        matrix = sheet_matrix(
            modifier_file_id, modifier_sheet_id, "A1:O200"
        )
        result["modifiers"] = sync_table(
            grist, "Modifiers",
            rows_from_matrix(matrix, MODIFIER_MAP, header_row=1),
            "key", args.apply,
        )
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
