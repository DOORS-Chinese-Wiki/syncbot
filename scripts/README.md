# SyncBot 源码目录

本目录只收录持续维护的同步工具。带日期、`sync6_*`、`sync_batch*`、`sync_mini_*`
之类的文件属于当轮迁移记录，沿用后应当删除或移出仓库，不提交到这里。

## 常驻与定时任务

| 文件 | 入口 | 作用 |
|---|---|---|
| `achievements_sync.py` | `sync` / `watch` | `Module:BadgeData` 与 Grist/腾讯表格双向同步 |
| `item_names_sync.py` | `sync` / `fetch` / `mapping` | 物品译名、`Module:ItemNames` 与对照表同步 |
| `translation_notes_sync.py` | `sync` | `Module:TranslationNotes` 与外部表格说明字段同步 |
| `modifiers_sync.py` | `sync` / `watch` / `dump` | `Module:ModifierData` 与 Grist 中文描述同步 |
| `tencent_grist_bridge.py` | 定时运行 | 腾讯文档单向写入 Grist |

## 站点同步与维护

| 文件 | 作用 |
|---|---|
| `sync_templates.py` | 从英文站同步模板与模块，支持 `--check-only` |
| `sync_en_redirects.py` | 同步英文站重定向 |
| `sync_project_pages.py` | 同步项目命名空间页面 |
| `diff_en_window.py` | 查看英文站在时间窗内的改动 |
| `collect_refs.py` | 统计被引用页面与翻译状态 |
| `massedit_regex.py` | 通过 MassEditRegex 执行定点替换 |
| `push_templates.py` | 按清单推送本地模板 |
| `wiki_site.py` | 统一中文站账号选择与空摘要保存 |

## 数据工具

| 文件 | 作用 |
|---|---|
| `grist_import_exports.py` | 导入腾讯导出表；不会删除独立维护的 `Modifiers` 表 |
| `grist_dedupe.py` | 清理 Grist 重复行 |
| `tencent_oauth_callback.py` | 接收腾讯文档 OAuth 回调 |
| `build_badgedata.py` | 重建 `Module:BadgeData` 的本地工具 |
| `build_achievements_workbook.mjs` | 生成成就工作簿 |

## 测试

从仓库根目录运行：

```bash
python scripts/test_achievements_sync.py
python scripts/test_item_names_sync.py
python scripts/test_translation_notes_sync.py
```

这些测试均为离线测试，不会访问 Wiki、腾讯文档或 Grist。

## 新增代码约定

1. 新功能优先修改上表中的现有入口，不再新增带日期的副本。
2. 执行写操作前默认提供 dry-run，并保留 `--apply` 开关。
3. 页面编辑摘要按项目约定保持空白；需要显式传 `summary=""`。
4. 新增或修改解析、冲突判定、表格映射时，同时补离线测试。
5. 密钥、页面正文、图片、运行状态和一次性脚本都不得提交。
