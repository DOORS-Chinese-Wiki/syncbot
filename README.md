# SyncBot

DOORS 中文维基的同步工具，用于在英文维基、中文维基、腾讯文档和 Grist 之间同步模板、模块、成就、物品译名与修饰符数据。

这是社区维护项目，与 LSPLASH、Roblox 或 DOORS 官方无隶属关系。

## 功能

- 英文站 `Template:`、`Module:` 和重定向同步到中文站。
- `Module:BadgeData`、`Module:ItemNames`、`Module:TranslationNotes` 和 `Module:ModifierData` 的双向或单向同步。
- 腾讯文档到 Grist 的镜像，以及 Grist 到中文维基的回写。
- 同步前生成计划，默认 dry-run；发生双端冲突时停止自动覆盖。

数据源和同步流程可概括为：

```text
英文维基  ->  中文维基
腾讯文档  ->  Grist  <->  中文维基
```

## 安装

需要 Python 3.10+。

```bash
git clone https://github.com/DOORS-Chinese-Wiki/syncbot.git
cd syncbot
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Windows 下虚拟环境的 Pip 路径为 `.venv\Scripts\pip.exe`。

## 配置

仓库不包含账号或密钥。按需创建以下文件，并确保它们没有被提交：

| 文件 | 用途 |
|---|---|
| `user-config.py` | Pywikibot 站点与账号 |
| `user-password.py` | Pywikibot 密码或 bot password |
| `tencent_docs.env` | 腾讯文档认证和表格 ID |
| `grist.env` | Grist 地址、文档 ID 和 API Key |

可从 `tencent_docs.env.example` 和 `deploy/grist/.env.example` 开始配置。

## 常用命令

```bash
# 检查成就同步计划
python scripts/achievements_sync.py sync --backend grist

# 物品译名与翻译说明
python scripts/item_names_sync.py sync --backend grist
python scripts/translation_notes_sync.py --backend grist

# 修饰符
python scripts/modifiers_sync.py sync

# 腾讯文档 -> Grist
python scripts/tencent_grist_bridge.py

# 英文站模板与模块同步；先检查，再加 --apply
python scripts/sync_templates.py --check-only
python scripts/sync_templates.py --apply
```

写操作默认关闭。确认 dry-run 结果后，再为支持 `--apply` 的脚本加上该参数。

完整脚本清单见 [scripts/README.md](scripts/README.md)，推送清单见 [manifests/README.md](manifests/README.md)。

## 测试

```bash
python scripts/test_achievements_sync.py
python scripts/test_item_names_sync.py
python scripts/test_translation_notes_sync.py
```

这些测试只使用本地样例，不会访问维基、腾讯文档或 Grist。

## 部署

`deploy/` 提供 systemd、timer 和 Grist Docker 配置的示例。部署前请修改示例中的路径、账号和环境文件。

## 许可

代码采用 CC BY-SA 4.0，详见 [LICENSE](LICENSE)。从 DOORS Wiki 同步的文本和模板同样遵循 CC BY-SA 4.0；游戏素材不包含在本仓库中。
