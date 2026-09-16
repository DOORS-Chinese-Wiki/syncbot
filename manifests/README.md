# 推送清单

推送到中文维基的页面清单，格式与 `scripts/push_templates.py` 一致：

```json
[
 ["页面标题", "pages_zh/相对路径.mw"],
 ["Soundtracks/The Hotel", "pages_zh/batch_2026-09-15/Soundtracks__The Hotel.zh.mw"]
]
```

推送（摘要为单个空格，与仓库既有脚本一致）：

```bash
python scripts/push_templates.py manifests/project.json
python scripts/push_templates.py manifests/all.json
```

## 文件

| 文件 | 内容 |
|---|---|
| `project.json` | `DOORS Wiki:` 项目命名空间页面，由 `scripts/sync_project_pages.py --manifest` 维护 |
| `pages-<日期>.json` | 正文页面清单，按批次日期归并（同一标题只保留一条） |
| `all.json` | 上面两者的合集，标题去重，可用于一次性重推全部页面 |
| `history.json` | 完整历史：每条记录带来源批次、路径、以及源文件是否仍在（`file_exists`） |

## 说明

- 清单里只收录**源文件仍存在**的条目，保证任何一条都能直接推送。
- 2026-09-15 那批正文页面曾用 `_sync_out/` 作为中间目录，该目录已清理，
  这 19 条记录保留在 `history.json` 里（`file_exists: false`），仅作追溯，不再推送。
- 新增清单：把文件放好后跑一遍上面的推送命令即可；历史上的散装
  `push_*.json` 已归并到本目录。
