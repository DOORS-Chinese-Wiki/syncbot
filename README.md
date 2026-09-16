# DOORS 中文维基 · 同步工具

把英文 DOORS Wiki 的模板/模块、以及腾讯文档上的成就文本与物品译名，
同步到中文维基（`zh.doorsgame.wiki`）。也负责反向回写。

## 数据流

```
腾讯文档（主，社区编辑）
   │  tencent_grist_bridge.py    每 30 分钟
   ▼
Grist（辅，自建）      ItemNames 98 / Achievements 170
   │  item_names_sync.py         每 5 分钟
   │  achievements_sync.py       每 30 秒
   ▼
Module:ItemNames / Module:BadgeData（Wiki）

doorsgame.wiki（英文站）
   │  sync_templates.py / tencent_grist_bridge.py
   ▼
Template: / Module: 页面
```

- **腾讯文档是主**，Grist 是自建镜像与兜底。腾讯 API 配额出问题时只有第一跳暂停，
  Wiki 侧照常同步。
- 冲突处理用三方状态（`wiki_hash` / `sheet_hash`）：哪边单独变就同步哪边，
  两边都变且不一致就记冲突、两端都不动，交人工处理。

## 主要脚本

| 脚本 | 作用 |
|---|---|
| `achievements_sync.py` | 成就文本双向同步（腾讯或 Grist 后端） |
| `item_names_sync.py` | 物品译名同步，生成 `Module:ItemNames` 与对照表页 |
| `tencent_grist_bridge.py` | 腾讯文档 → Grist 单向桥接 |
| `sync_templates.py` | 从英文站同步 `Template:` / `Module:` 当前修订 |
| `sync_en_redirects.py` | 同步英文站的重定向 |
| `grist_import_exports.py` | 把腾讯导出的 xlsx 导入 Grist |
| `grist_dedupe.py` | 清理 Grist 里的重复 key |
| `diff_en_window.py` | 按时间窗比对英文站改动，用于跟进更新 |
| `sync_project_pages.py` | 同步 `DOORS Wiki:` 项目命名空间页面（英文源 → 中文译文 → 清单 → 推送） |

测试：`python scripts/test_achievements_sync.py`、`test_item_names_sync.py`（离线，不联网）。

## 配置

本项目**不包含任何密钥**，需要自己准备（见 `.gitignore`）：

| 文件 | 内容 |
|---|---|
| `user-config.py` | pywikibot 站点与账号配置 |
| `user-password.py` | pywikibot 密码 |
| `tencent_docs.env` | 腾讯文档 Client ID/Secret、Access Token、File/Sheet ID |
| `grist.env` | Grist 的 `GRIST_SERVER` / `GRIST_DOC_ID` / `GRIST_API_KEY` |

模板见 `tencent_docs.env.example`、`deploy/grist/.env.example`。

安装依赖：

```bash
python -m venv .venv
.venv/bin/pip install pywikibot requests grist-api openpyxl
```

## 部署

`deploy/` 下有 systemd 单元模板：

- `achievements-sync.service`（常驻，30 秒轮询）
- `item-names-sync.service` + `.timer`（每 5 分钟）
- `tencent-grist-bridge.service` + `.timer`（每 30 分钟）
- `grist/`（Grist 自建：docker-compose 与说明）

> 注意：单元模板里**不要写 `User=`**，除非目标机器上确实存在该用户；
> 用户不存在会导致 systemd 报 `217/USER` 并反复重启。

## 许可

本仓库采用 **CC BY-SA 4.0**（署名-相同方式共享 4.0 国际），详见 [LICENSE](LICENSE)。

从 DOORS Wiki 同步的模板、模块与文本内容同样遵循 CC BY-SA 4.0，
版权归原作者与贡献者所有。从游戏文件中提取的资源不在本仓库内。
