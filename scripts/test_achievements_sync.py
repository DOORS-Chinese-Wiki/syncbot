# -*- coding: utf-8 -*-
"""Offline checks for the achievements sync diff logic (no network)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import achievements_sync as A  # noqa: E402

HEADER = [
    "同步键", "分类", "成就名", "英文名", "描述", "达成条件", "攻略", "参考资料",
    "奖励", "Secret", "Hidden", "Obtainable", "Badge ID", "旧版本",
    "Wiki 修订", "行哈希", "同步状态",
]


def row(key, title, category="General", desc="d"):
    return {
        "key": key, "category": category, "title": title, "text": desc,
        "directions": "", "tutorial": "", "references": "",
        "rewards": "nil", "secret": False, "hidden": False,
        "obtainable": True, "badge_id": "", "old_versions": "nil",
        "row_hash": "", "sync_status": A.STATUS_SYNCED,
    }


class FakeClient:
    def __init__(self, matrix):
        self.matrix = matrix
        self.writes = []

    def get_range(self, range_):
        return [list(r) for r in self.matrix]

    def update_range(self, range_, values):
        self.writes.append((range_, [list(r) for r in values]))


class FakePage:
    def __init__(self, site, title):
        self.text = "return {\n}\n"
        self.latest_revision_id = 124


def matrix_from(rows):
    matrix = [HEADER]
    for item in rows:
        filled = dict(item)
        filled["row_hash"] = A.row_hash(filled)
        filled["wiki_rev"] = 123
        matrix.append([str(c) for c in A.rows_to_matrix([filled])[1]])
    return matrix


def run_case(wiki_rows, sheet_matrix, state_rows):
    client = FakeClient(sheet_matrix)
    saved = {}
    captured = {}
    A.pywikibot.Site = lambda *a, **k: object()
    A.pywikibot.Page = FakePage
    A.fetch_rows = lambda: (123, wiki_rows)
    A.TencentDocsClient = lambda: client
    A.load_state = lambda path: {"revision": 1, "rows": state_rows}
    A.save_state = (
        lambda path, rev, w, s, preserve=None, markers=None: saved.update(
            {"wiki": w, "sheet": s, "markers": markers}
        )
    )
    def fake_save(site, rows):
        captured["module_rows"] = rows
        return 124

    A.save_module_text = fake_save
    A.run_sync(True, Path("unused"), backend="tencent")
    return client, saved, captured


def main():
    failures = []
    parsed = A.parse_module(
        """
return {
	General = {
		{
			title = '欢迎',
			titleEn = 'Welcome',
			text = 'text',
			id = '1',
		},
	},
}
""",
        123,
    )
    if parsed[0]["key"] != "id:1:General:Welcome":
        failures.append("5 解析后的同步键没有使用稳定 Badge ID")
    if parsed[0]["title_en"] != "Welcome":
        failures.append("5 解析后的英文稳定名不正确")

    rendered = A.render_module([dict(parsed[0])])
    if "titleEn = 'Welcome'" not in rendered:
        failures.append("5 渲染时丢失英文稳定名")

    wiki_row = row("id:1:General:Welcome", "欢迎")
    wiki_row["badge_id"] = "1"
    wiki_row["title_en"] = "Welcome"
    sheet_row = dict(wiki_row)
    old_state = {
        "revision": 1,
        "rows": {
            "id:1:General:Welcome": {
                "wiki_hash": "",
                "sheet_hash": "old-sheet",
                "wiki_deleted": True,
            },
            "id:1:General:欢迎": {
                "wiki_hash": A.row_hash(wiki_row),
                "sheet_hash": A.row_hash(sheet_row),
            },
        },
    }
    migrated = A.migrate_state(
        old_state,
        {"id:1:General:Welcome": wiki_row},
        {"id:1:General:Welcome": sheet_row},
    )
    entry = migrated["rows"].get("id:1:General:Welcome")
    if not entry or entry.get("wiki_hash") != A.row_hash(wiki_row):
        failures.append("5 状态迁移没有保留当前显示名的哈希")
    if entry and entry.get("wiki_deleted"):
        failures.append("5 状态迁移保留了旧改名记录的删除标记")

    r1 = row("k1", "Alpha")
    r2 = row("k2", "Beta")
    both = {
        "k1": {"wiki_hash": A.row_hash(r1), "sheet_hash": A.row_hash(r1)},
        "k2": {"wiki_hash": A.row_hash(r2), "sheet_hash": A.row_hash(r2)},
    }

    client, _, _ = run_case([r1, r2], matrix_from([r1, r2]), dict(both))
    if client.writes:
        failures.append("1 未变化却写了表格")

    client2, saved2, _ = run_case([r1, r2], matrix_from([r1]), dict(both))
    if client2.writes:
        failures.append("2 表格端删除被回填")
    if not (saved2.get("markers") or {}).get("k2", {}).get("sheet_deleted"):
        failures.append("2 未记录 sheet_deleted")

    client3, saved3, _ = run_case([r1], matrix_from([r1, r2]), dict(both))
    if not client3.writes:
        failures.append("3 表格未更新")
    else:
        values = client3.writes[0][1]
        keys = [v[0] for v in values]
        idx = HEADER.index("同步状态")
        if "k2" not in keys:
            failures.append("3 k2 行消失")
        elif values[keys.index("k2")][idx] != A.STATUS_WIKI_DELETED:
            failures.append("3 状态不是 " + A.STATUS_WIKI_DELETED)
    if not (saved3.get("markers") or {}).get("k2", {}).get("wiki_deleted"):
        failures.append("3 未记录 wiki_deleted")

    sheet_r1 = row("k1", "Alpha", desc="来自表格的新描述")
    _, _, captured4 = run_case(
        [r1], matrix_from([sheet_r1]), dict(both)
    )
    module_rows = captured4.get("module_rows") or []
    hit = [m for m in module_rows if m.get("key") == "k1"]
    if not hit or hit[0].get("text") != "来自表格的新描述":
        failures.append("4 表格改动没有回写到 Wiki")

    if failures:
        print("FAILED:")
        for item in failures:
            print("  -", item)
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
