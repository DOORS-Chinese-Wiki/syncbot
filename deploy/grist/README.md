# Grist 自建（替代腾讯文档）

用途：给「物品译名确认表」「成就文本」提供一个不受第三方 API 配额限制的协作表格。

## 为什么要换

腾讯文档 OpenAPI 有月度调用配额，成就同步原本每 30 秒整段回写一次
`A1:P171`，约 8.6 万次写/月，把配额烧光。换到自建 Grist 后：

- 没有配额，也没有单次调用的计费
- API 支持**按行**读写，不用整段读写，天然更省
- 可以自己控制备份、权限和公开链接

## 机器要求

实测现有服务器（Debian 12）在跑 MySQL / PHP-FPM / Nginx / 宝塔 / NapCat /
DDBot / DiffBot / MaiBot 的情况下，可用内存只剩约 150MB，跑不动 Grist。

建议配置：

| 项目 | 建议 | 说明 |
|---|---|---|
| 内存 | **4GB**（最低 2GB + 2GB swap） | 现有服务约 1.8GB，Grist + Node 约 400–600MB |
| CPU | 2 核 | 够用 |
| 磁盘 | 现有 40GB 够 | Grist 数据是 SQLite 文件，很小 |

## 安装

```bash
# 1. 安装 Docker（Debian 12 官方源）
apt update
apt install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg \
  | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/debian bookworm stable" \
  > /etc/apt/sources.list.d/docker.list
apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# 2. 部署 Grist
mkdir -p /opt/grist && cd /opt/grist
cp <本目录>/docker-compose.yml .
cp <本目录>/.env.example .env
vim .env          # 填 APP_HOME_URL / GRIST_SINGLE_ORG / GRIST_SESSION_SECRET / 邮箱
openssl rand -hex 32   # 生成 GRIST_SESSION_SECRET

docker compose up -d
docker compose logs -f --tail=50
```

## Nginx 反向代理

Grist 用 WebSocket 做实时协作，反代必须带 Upgrade 头，否则多人同时编辑会断。

```nginx
location / {
    proxy_pass http://127.0.0.1:8484;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 600s;
}
```

配好后用宝塔申请该域名的 Let's Encrypt 证书即可。

## 拿到 API Key

1. 浏览器打开 `APP_HOME_URL`，用 `GRIST_DEFAULT_EMAIL` 注册首个账号
2. 右上角头像 → **Account settings** → **API** → 创建 API key
3. 记录：
   - `GRIST_API_KEY`
   - `GRIST_DOC_ID`（文档 URL 里的那一段，形如 `https://…/o/doorswiki/<docId>`）

同步脚本会用官方 `grist-api` 包：

```bash
/opt/doors-wiki/.venv/bin/pip install grist-api
```

## 同步脚本要改什么

数据模型不变（一行 = 一个 key + 若干字段），只需把腾讯文档 client 换成 Grist：

| 现在 | 换到 Grist 后 |
|---|---|
| `client.get_range("A1:P200")` 整段读 | `api.fetch_table("物品译名")` 按行读 |
| `client.update_range(...)` 整段写 | `api.update_records(table, [{"id": …, 字段: 值}])` 只写变化的行 |
| 行号定位（H 列 / Q 列） | 用 Grist 的 `id`，不用再算列字母 |

diff、三方状态（`wiki_hash` / `sheet_hash`）、冲突检测、`sheet_deleted` /
`wiki_deleted` 标记这些逻辑可以原样复用。

## 迁移步骤

1. 腾讯文档配额虽然用完了，但**网页端导出不受影响**：打开两个表格 →
   文件 → 导出为 CSV/Excel，把文件给我
2. 我把导出数据 + Wiki 上现有的 `Module:ItemNames`（97 条）和
   `Module:BadgeData`（170 条）合并，导入 Grist 两张表
3. 切换两个同步脚本的 client，先在本地干跑比对，再部署
4. 观察一段时间，确认无差异后再停用腾讯文档同步
