# -*- coding: utf-8 -*-
"""清理 Grist 表里重复的 key：每组只保留 record id 最小的那条。

用法：
    python scripts/grist_dedupe.py ItemNames
    python scripts/grist_dedupe.py Achievements --apply
"""
import argparse
import collections
import json
import os
import pathlib

import requests

SERVER = os.environ.get(
    "GRIST_SERVER", "https://sheet.189-24-78-35.sslip.io"
)
DOC_ID = os.environ.get("GRIST_DOC_ID", "1JRoy2vJar2kh945PXUbFP")
KEY_FIELD = {"ItemNames": "english", "Achievements": "key"}


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("table", choices=sorted(KEY_FIELD))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    key_field = KEY_FIELD[args.table]

    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {load_key()}",
        "Content-Type": "application/json",
    })
    url = f"{SERVER}/api/docs/{DOC_ID}/tables/{args.table}/records"
    records = (session.get(url, params={"limit": 5000},
                           timeout=180).json().get("records") or [])
    print(f"{args.table}: {len(records)} 条")

    by_key = collections.defaultdict(list)
    empties = []
    for record in records:
        key = record["fields"].get(key_field, "")
        if not key:
            empties.append(record["id"])
        else:
            by_key[key].append(record["id"])

    drop = list(empties)
    for key, ids in by_key.items():
        if len(ids) > 1:
            drop.extend(sorted(ids)[1:])
    print("空 key 行:", empties, "| 重复多余行:", sorted(drop))
    if not drop:
        print("无需清理")
        return 0
    if not args.apply:
        print("干跑，未删除。加 --apply 执行。")
        return 0

    actions = [["RemoveRecord", args.table, rid] for rid in sorted(drop)]
    resp = session.post(f"{SERVER}/api/docs/{DOC_ID}/apply",
                        json=actions, timeout=300)
    print("apply ->", resp.status_code)
    if resp.status_code >= 400:
        print(resp.text[:300])
        return 1
    left = (session.get(url, params={"limit": 5000},
                        timeout=180).json().get("records") or [])
    print(f"清理后 {args.table}: {len(left)} 条")
    print("重复检查:",
          {k: v for k, v in collections.Counter(
              r["fields"].get(key_field, "") for r in left).items()
           if v > 1} or "无")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
