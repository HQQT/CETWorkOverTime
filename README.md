# 邮件工作总结汇总系统 (CETWorkOverTime)

一个面向企业邮箱工作日志的 Python Web 工具，支持自动 IMAP 抓取、解析去重、写入 PostgreSQL，并生成按月汇总的 Markdown 报告。

## ✨ 核心特性

- 🌐 **Web 集中管理**：查看邮件抓取状态、报告生成状态与勤奋时间统计。
- 📥 **自动 IMAP 拉取**：按主题关键词从指定邮箱文件夹抓取邮件。
- 📊 **智能解析整合**：
  - 自动识别 `.eml` 多编码格式。
  - 提取每日工作内容、计划与勤奋时间。
  - 同日多封邮件按勤奋时长优先保留更完整的一封。
- 💾 **PostgreSQL 单表持久化**：邮件统一写入 `emails`，抓取/处理缓存写入 `email_meta`。
- 🔒 **两步验证 (2FA)**：基于 TOTP 的登录保护。
- 🐳 **Docker Compose 开箱部署**：内置 PostgreSQL 服务与应用健康检查。

## 🚀 快速开始

### Docker Compose 部署

1. 复制 `.env.example` 为 `.env`，按实际邮箱信息修改。
2. 执行：

```bash
docker compose up -d --build
```

3. 访问 `http://localhost:5000`，首次按页面提示绑定 TOTP。

默认 Compose 会同时启动：

- `postgres`：PostgreSQL 16，数据卷为 `postgres_data`
- `cetworkovertime`：Flask/Gunicorn Web 服务

### 本地原生部署

1. 安装依赖：

```bash
pip install -r requirements.txt -i https://mirrors.huaweicloud.com/repository/pypi/simple
```

2. 准备 PostgreSQL：

- 创建一个可用的 PostgreSQL 实例。
- 保证应用账号可连接目标库；如果没有 `CREATEDB` 权限，请先手动创建 `DB_NAME` 指定的数据库。
- 可选执行初始化脚本：

```bash
psql -U postgres -d postgres -f sql/init.sql
```

3. 本地运行 Web 服务：

```bash
python app.py
```

## ⚙️ 核心环境变量

```env
# ======== 基础配置 ========
WORK_SUMMARY_DIR=工作总结
OUTPUT_DIR=output

# ======== IMAP 邮箱配置 ========
IMAP_SERVER=imap.exmail.qq.com
IMAP_PORT=993
IMAP_USE_SSL=true
EMAIL_USERNAME=your.email@company.com
EMAIL_PASSWORD=your_imap_password
IMAP_MAILBOX=&XeVPXGXlX9c-
IMAP_SEARCH_SUBJECT=--工作日志
IMAP_SEARCH_DAYS=365

# ======== 安全设定 (2FA) ========
TOTP_SECRET=YOUR_32_CHAR_BASE32_SECRET
SECRET_KEY=replace_with_a_long_random_secret

# ======== PostgreSQL 配置 ========
# Docker Compose 默认使用 postgres；本地部署通常改为 localhost
DB_HOST=postgres
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=your_db_password
DB_NAME=cetworkovertime
```

## 📁 主要目录与代码结构

```text
CETWorkOverTime/
├── app.py                  # Flask Web 启动入口
├── config.py               # .env 与默认值配置
├── db.py                   # PostgreSQL 连接池与建库建表初始化
├── email_fetcher.py        # IMAP 抓取逻辑
├── email_parser.py         # .eml 解析
├── email_processor.py      # 解析结果处理、入库与报告生成编排
├── email_repository.py     # PostgreSQL 单表 CRUD
├── report_generator.py     # Markdown/HTML 报告生成
├── sql/init.sql            # PostgreSQL 初始化脚本
├── docker-compose.yml      # 应用 + PostgreSQL 编排
└── templates/              # 前端页面模板
```

## 📦 生成产物

报告默认输出到 `./output`，核心文件名格式为：

- `YYYY年MM月工作总结.md`

## 🐛 常见问题

1. **Docker 内应用连不上数据库**
   - 检查 `docker compose ps` 中 `postgres` 是否健康。
   - Compose 内应用固定使用 `DB_HOST=postgres`、`DB_PORT=5432` 连接内置数据库。

2. **本地原生部署连不上 PostgreSQL**
   - 检查 `.env` 中的 `DB_HOST`、`DB_PORT`、`DB_USER`、`DB_PASSWORD`。
   - 如果应用账号没有建库权限，请先手动创建数据库。

3. **抓取到了邮件但正文为空**
   - 检查 `config.py` 中的 `CONTENT_START_MARKERS` / `CONTENT_END_MARKERS` 是否覆盖你的日报模板。

## 📄 许可证

MIT License
