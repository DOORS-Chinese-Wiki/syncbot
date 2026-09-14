# -*- coding: utf-8 -*-
"""物品译名同步的离线回归测试（render_module ↔ parse_module 往返）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import item_names_sync as S  # noqa: E402

SAMPLES = [
    {
        "key": "Lighter", "suggested": "打火机", "alternatives": [],
        "final": "", "reason": "", "category": "光源 Light", "page": "正文页",
        "source": "中文站现有页面", "status": "待确认", "priority": "",
        "owner": "", "confirmed": "", "note": "",
    },
    {
        "key": "Ransom's Stop Sign", "suggested": "Ransom 的停车牌",
        "alternatives": ["停车牌", "停牌"], "final": "停车牌",
        "reason": "社区常用", "category": "对战 Battle", "page": "重定向页",
        "source": "建议", "status": "已确认", "priority": "高",
        "owner": "Yatmt", "confirmed": "2026-09-15",
        "note": "含撇号与引号“测试”",
    },
    {
        "key": "NVCS-3000", "suggested": "NVCS-3000", "alternatives": [],
        "final": "", "reason": "", "category": "工具 Utility", "page": "正文页",
        "source": "中文站现有页面", "status": "", "priority": "", "owner": "",
        "confirmed": "", "note": "",
    },
]


def main() -> int:
    failures: list[str] = []
    text = S.render_module(SAMPLES)
    parsed = S.parse_module(text)
    by_key = {row["key"]: row for row in parsed}

    for sample in SAMPLES:
        key = sample["key"]
        got = by_key.get(key)
        if not got:
            failures.append(f"往返丢失条目：{key}")
            continue
        if got.get("suggested") != sample["suggested"]:
            failures.append(f"{key} 的 suggested 不一致：{got.get('suggested')!r}")
        if got.get("alternatives") != sample["alternatives"]:
            failures.append(f"{key} 的 alternatives 不一致：{got.get('alternatives')!r}")
        for field in ("final", "category", "page", "status", "owner", "note"):
            if (got.get(field) or "") != (sample[field] or ""):
                failures.append(
                    f"{key} 的 {field} 不一致：{got.get(field)!r} != {sample[field]!r}"
                )

    # 重复英文名只应保留一条
    dup = SAMPLES + [dict(SAMPLES[0], suggested="打火机（重复）")]
    rendered = S.render_module(dup)
    if rendered.count("['Lighter']") != 2:
        failures.append("render_module 未按原样写入重复键（去重应在 read_sheet 完成）")

    if failures:
        print("FAILED:")
        for line in failures:
            print("  -", line)
        return 1
    print(f"ALL OK（{len(SAMPLES)} 条往返一致）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
