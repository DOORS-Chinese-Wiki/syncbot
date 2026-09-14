# 成就文本双向同步

## 表格

初始表格：

`outputs/achievements-2026-09-14/DOORS_中文维基_成就文本.xlsx`

- `成就文本`：每行一个成就。
- `同步键`：不要修改，用于把表格行映射回 Wiki。
- `分类`、`成就名`、`描述`、`达成条件`、`攻略`、`参考资料`：可编辑。
- `奖励`、`Secret`、`Hidden`、`Obtainable`、`Badge ID`、`旧版本`：Lua 数据字段。
- `Wiki 修订`、`行哈希`、`同步状态`：同步脚本使用，不要手动改。

## 腾讯文档配置

当前工作簿已导入腾讯文档：

https://docs.qq.com/sheet/DUmpVeG9mTEt1b0Nr

`tencent_docs.env` 已填写：

- `QQDOCS_CLIENT_ID`
- `QQDOCS_CLIENT_SECRET`
- `QQDOCS_ACCESS_TOKEN`
- `QQDOCS_OPEN_ID`
- `QQDOCS_FILE_ID`
- `QQDOCS_SHEET_ID`

当前开发者账号没有配置 OAuth 回调地址，应用级账号 Token 接口对该账号返回
`10002`，所以暂时拿不到 Refresh Token。Access Token 有效期为 30 天，到期后需要在
开放平台点击“重置”，重新复制 Access Token 并更新服务器上的 `tencent_docs.env`。

如果以后创建了标准 OAuth 应用，可改用脚本内置的授权流程：

```powershell
python scripts\achievements_sync.py auth-url --redirect-uri https://你的回调地址
python scripts\achievements_sync.py exchange-code --code CODE --redirect-uri https://你的回调地址
```

服务器上可直接重新查询工作表 ID：

```powershell
python scripts\achievements_sync.py sheets
```

## 同步

先干跑，检查双向差异：

```powershell
python scripts\achievements_sync.py sync
```

确认后执行双向同步：

```powershell
python scripts\achievements_sync.py sync --apply
```

每 5 分钟自动执行：

```powershell
python scripts\achievements_sync.py watch --interval 30 --apply
```

## 服务器部署

模板位于 `deploy/achievements-sync.service.example`。默认约定：

- 项目目录：`/opt/doors-wiki`
- 环境文件：`/etc/doors-wiki/tencent_docs.env`
- 运行用户：`doorswiki`
- 轮询间隔：30 秒

部署后执行：

```bash
cd /opt/doors-wiki
python3 -m venv .venv
.venv/bin/pip install pywikibot requests

sudo install -d -m 700 /etc/doors-wiki
sudo install -m 600 tencent_docs.env /etc/doors-wiki/tencent_docs.env
sudo cp deploy/achievements-sync.service.example /etc/systemd/system/achievements-sync.service
sudo systemctl daemon-reload
sudo systemctl enable --now achievements-sync
sudo journalctl -u achievements-sync -f
```

`tencent_docs.env` 只放在服务器权限受限的目录中，不要提交到公开仓库。
服务器还需要可用的 pywikibot 登录配置，包括 `user-config.py`、`user-password.py`
和可选的 `pywikibot-Yatmt.lwp`。

同步规则：

- 只有腾讯文档变化：回写 `Module:BadgeData`。
- 只有 Wiki 变化：刷新腾讯文档对应行。
- 两端同时变化：标记为「冲突：两端均变化」，不自动覆盖，也不改动任何一端。
- 表格中新增行：追加到 Wiki。
- Wiki 中新增成就：追加到腾讯文档。
- **表格中删除行**：判定为表格端的主动删除，不再回填；Wiki 里的成就保留不动。
  删除决定会记进状态文件（`sheet_deleted`），后续轮询不会把它重新写回表格。
- **Wiki 中删除成就**：同样尊重删除，不会把它加回 Wiki；表格里对应行保留，
  并把「同步状态」标成「Wiki 已删除」，方便人工确认。

写入策略：

- 每轮都会比对「当前表格内容」与「本轮算出的表格内容」，**只有确实不同时才写**。
  以前是无条件整段回写 `A1:P{行数}`，没有变化也会每 30 秒写一次，现已修掉。
- Wiki 侧只在真的有改动时才保存 `Module:BadgeData`，保存后会用
  `{{#invoke:BadgeList|main|BadgeCount|All}}` 渲染自检，出现 Lua error 自动回滚。
- 「同步状态」列统一使用中文文案：`已同步` / `Wiki 新增` / `表格新增` /
  `Wiki 有更新` / `表格有更新` / `冲突：两端均变化` / `Wiki 已删除`。
  历史值 `""` 和 `synced` 仍按「已同步」处理。

回归测试：

```powershell
python scripts\test_achievements_sync.py
```

离线跑四条分支（无变化不写表、表格删行不回填、Wiki 删成就标注、表格改动回写 Wiki），
不访问网络。
