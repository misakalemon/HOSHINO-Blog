# Hoshino Blog 完整技术文档

> 最后更新：2026-07-28

---

## 目录

1. [项目概述](#1-项目概述)
2. [目录结构](#2-目录结构)
3. [环境要求与部署](#3-环境要求与部署)
4. [依赖库详解](#4-依赖库详解)
5. [数据库 Schema](#5-数据库-schema)
6. [配置系统](#6-配置系统)
7. [入口文件：app.py](#7-入口文件apppy)
8. [后台工作进程：worker.py](#8-后台工作进程workerpy)
9. [任务队列：task_queue.py](#9-任务队列task_queuepy)
10. [数据模型：models.py](#10-数据模型modelspy)
11. [前台路由：routes.py](#11-前台路由routespypy)
12. [后台管理路由：admin.py](#12-后台管理路由adminpy)
13. [B站管理路由：bili_routes.py](#13-b站管理路由bili_routespypy)
14. [B站公开路由：bili_public_routes.py](#14-b站公开路由bili_public_routespypy)
15. [词云模块：wordcloud.py](#15-词云模块wordcloudpy)
16. [B站 API 封装：bilibili/](#16-b站-api-封装bilibili)
17. [缓存系统：cache.py](#17-缓存系统cachepy)
18. [日志系统：logger.py](#18-日志系统loggerpy)
19. [表单定义：forms.py](#19-表单定义formspy)
20. [邮件模块：mail.py](#20-邮件模块mailpy)
21. [Amazon 爬虫：apify_client.py](#21-amazon-爬虫apify_clientpy)
22. [安全机制](#22-安全机制)
23. [进程间通信协议](#23-进程间通信协议)
24. [定时任务清单](#24-定时任务清单)
25. [完整 API 端点列表](#25-完整-api-端点列表)

---

## 1. 项目概述

Hoshino Blog 是一个基于 Flask 的个人博客系统，支持文章发布、B站数据可视化、词云展示等功能。

### 核心架构

```
┌──────────────────────────────────────────────────────────┐
│                   用户 (浏览器)                            │
└────────────────────┬─────────────────────────────────────┘
                     │ HTTP
                     ▼
┌──────────────────────────────────────────────────────────┐
│              Nginx / 反向代理 (端口 443/80)               │
│   → 静态资源 /static/ (直接返回)                          │
│   → 动态请求 / 代理到 Flask (端口 5000)                  │
└────────────────────┬─────────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────────┐
│              Flask Web 进程 (端口 5000)                    │
│                                                          │
│  blog_bp (/)          admin_bp (/admin)                  │
│  bili_public_bp (/bili)  bili_bp (/admin/bilibili)       │
│                                                          │
│  ┌─ Flask-Login (session 认证)                           │
│  ├─ Flask-WTF (CSRF 保护)                                │
│  ├─ Flask-Compress (Gzip 压缩)                           │
│  ├─ Flask-Migrate (数据库迁移)                            │
│  └─ SQLAlchemy (ORM, MySQL)                              │
│                                                          │
│  启动时自动创建子进程 → Worker                            │
└────────┬────────────────────────────┬────────────────────┘
         │                            │
         ▼                            ▼
   MySQL (数据库)               Redis (缓存 + 队列)
                                    │
                                    │ BRPOP/LPUSH
                                    ▼
┌──────────────────────────────────────────────────────────┐
│              Worker 进程 (后台)                            │
│                                                          │
│  ┌─ APScheduler (定时任务)                               │
│  │  • 02:00 B站深扫                                       │
│  │  • 03:00 密钥轮换                                      │
│  │  • 03:00 快照清理                                      │
│  │  • 02:10/02:15 词云重算                                │
│  │  • 每轮+40min 增量检查                                 │
│  │                                                        │
│  └─ ThreadPoolExecutor (3 线程) ← 多线程改造             │
│     • refresh_up/refresh_all → _run_scrape                │
│     • bili_wordcloud → precompute_up_wordclouds           │
│     • comment_refresh → _crawl_video_comments             │
│                                                            │
│  APScheduler 线程池 (10 线程) 与任务池互不干扰             │
│  _scrape_lock (threading.Lock) 保护共享状态               │
└──────────────────────────────────────────────────────────┘
```

### 核心决策

| 决策 | 选择 | 理由 |
|------|------|------|
| Web 框架 | Flask (无 Django/Starlette) | 轻量、灵活，适合个人项目 |
| 数据库 | MySQL + PyMySQL | 成熟稳定，FULLTEXT 索引支持中文全文搜索 |
| 缓存/队列 | Redis | 单进程缓存 + 跨进程任务队列，一个服务解决两个问题 |
| 爬虫引擎 | curl_cffi (模拟浏览器) | 绕过 B站/Amazon 的反爬检测 |
| B站 SDK | bilibili-api-python | 封装完善，支持扫码登录 |
| 模板引擎 | Jinja2 (无前后端分离) | SSR 直出，首屏快，无需 SPA 框架 |
| 后台任务 | 独立 Worker 进程 | 爬虫/定时任务不阻塞 HTTP 请求 |
| 词云 | jieba + wordcloud + Pillow | 中文分词 + 词云生成，支持自定义形状/配色 |
| 部署 | waitress (Windows) / gunicorn (Linux) | 生产级 WSGI 服务器 |
| GUI | Eel (Chromium 嵌入式) | 桌面启动器，一键启动全栈 |

---

## 2. 目录结构

```
D:\Project\hoshino-blog\
│
├── app.py                          # Flask 应用入口 + Worker 子进程管理
├── worker.py                       # 后台 Worker 进程（多线程任务消费者）
├── config.py                       # 配置管理（SECRET_KEY 轮换、数据库 URI 构建）
├── launcher.py                     # Eel GUI 启动器
├── seed_data.py                    # 初始数据（分类、管理员、特色卡片）
├── requirements.txt                # pip 依赖清单（71 行）
│
├── blog/                           # 核心应用包
│   ├── __init__.py                 # Blueprint 声明 + init_db() + 30+ 迁移函数
│   ├── models.py                   # 872 行 — 19 个 ORM 模型
│   ├── routes.py                   # 1058 行 — 前台所有路由
│   ├── admin.py                    # ~1800 行 — 后台所有路由
│   ├── bili_routes.py              # ~1800 行 — B站管理路由 + 爬虫核心
│   ├── bili_public_routes.py       # B站公开展示路由
│   ├── task_queue.py               # 137 行 — Redis 任务队列封装
│   ├── wordcloud.py                # 词云生成模块
│   ├── cache.py                    # Redis 缓存封装
│   ├── forms.py                    # 277 行 — WTForms 表单定义
│   ├── mail.py                     # SMTP 邮件发送
│   ├── logger.py                   # 日志系统（文件 + 终端）
│   ├── apify_client.py             # Amazon Apify 爬虫
│   │
│   └── bilibili/                   # B站集成层
│       ├── __init__.py
│       ├── bili_api.py             # B站 API 封装（get_up_info / get_subtitle / get_comments ...）
│       ├── login.py                # QR 扫码登录 + Cookie 持久化
│       └── config.py               # B站爬虫配置（超时、重试、UA）
│
├── scripts/                        # 独立运维脚本
│   ├── bili_daily_scrape.py        # 独立深扫脚本（可 cron 调度）
│   ├── bili_incremental.py         # 独立增量脚本
│   └── fix_timestamps.py           # 时间戳修复脚本
│
├── templates/                      # 42 个 Jinja2 模板
│   ├── index.html                  # 首页（词云 + 特色卡片 + 文章瀑布流）
│   ├── single-post.html            # 文章详情页
│   ├── html-post.html              # 内联 HTML 文章展示页
│   ├── category-grid.html          # 分类筛选页
│   ├── about.html                  # 关于页
│   ├── contact.html                # 联系页
│   ├── tools.html                  # 工具箱页（Base64/字数/颜色/JSON/时间戳）
│   ├── rss.xml                     # RSS 订阅模板
│   ├── search.html                 # 搜索结果页
│   ├── errors/                     # 错误页面 (403/404/500)
│   └── admin/                      # 后台模板 (dashboard/login/users/posts/...)
│
├── static/                         # 静态资源
│   ├── css/                        # 样式文件
│   ├── js/                         # JavaScript 文件
│   ├── images/                     # 图片资源
│   ├── uploads/                    # 用户上传文件
│   └── .thumb_cache/               # 缩略图缓存目录
│
└── migrations/                     # Flask-Migrate 数据库迁移
    ├── env.py
    ├── alembic.ini
    └── versions/
        ├── b76f487c0ae9_initial_migration.py
        └── 88e5c1b3f4d2_add_bili_video_tags_and_comments.py
```

---

## 3. 环境要求与部署

### 3.1 环境要求

| 组件 | 版本要求 |
|------|----------|
| Python | 3.10+（推荐 3.12） |
| MySQL | 5.7+（推荐 8.0） |
| Redis | 6.0+（推荐 7.0） |
| Node.js | 可选（仅 Eel 启动器需要） |

### 3.2 快速部署

```bash
# 1. 克隆
git clone <repo> hoshino-blog
cd hoshino-blog

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
copy .env.example .env
# 编辑 .env 填写数据库连接信息、SECRET_KEY 等

# 4. 启动 MySQL 和 Redis 服务

# 5a. 开发运行（自动启动 Worker）
python app.py

# 5b. 生产运行
# 先单独启动 Worker：
start python worker.py
# 再启动 Web：
waitress-serve --port=5000 app:create_app
```

### 3.3 完整 .env 配置项

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATABASE_URL` | — | 完整数据库 URI（优先级最高，示例：`mysql+pymysql://user:pass@host:3306/db?charset=utf8mb4`） |
| `DB_HOST` | `127.0.0.1` | 数据库主机 |
| `DB_PORT` | `3306` | 数据库端口 |
| `DB_USER` | `hoshino` | 数据库用户 |
| `DB_PASS` | `hoshino_pass` | 数据库密码 |
| `DB_NAME` | `hoshino_blog` | 数据库名 |
| `REDIS_URL` | — | Redis 连接串（示例：`redis://:password@127.0.0.1:6379/0`）。留空则禁用 Redis，缓存/队列降级 |
| `SECRET_KEY` | — | 显式指定密钥。不指定则自动生成并轮换 |
| `SERVER_NAME` | — | 服务器主机名（用于 url_for(_external=True) 构建绝对 URL） |
| `PREFERRED_URL_SCHEME` | `http` | 外部 URL 协议（生产环境设为 `https`） |
| `SESSION_COOKIE_SECURE` | 根据 FLASK_ENV 自动 | HTTPS 下应为 `true` |
| `FLASK_ENV` | — | 设为 `development` 启用调试模式 |
| `PORT` | `5000` | Web 端口 |
| `POSTS_PER_PAGE` | `6` | 每页文章数 |
| `BLOG_SUBTITLE` | 长串默认值 | 首页副标题 |
| `SITE_NAME` | `Hoshino` | 站点名称（邮件标题等处） |
| `DEFAULT_THEME` | `dark` | 默认主题 |
| `ADMIN_USERNAME` | `admin` | 默认管理员用户名（首次启动自动创建） |
| `ADMIN_PASSWORD` | `CHANGE_ME` | 默认管理员密码（首次启动生效，之后不改） |
| `ADMIN_EMAIL` | `admin@localhost` | 默认管理员邮箱 |
| `ADMIN_DISPLAY_NAME` | `Admin` | 默认管理员显示名 |
| `ENABLE_REGISTRATION` | `false` | 是否开放用户注册 |
| `MAX_CONTENT_LENGTH` | `16MB` | 最大上传文件大小 |
| `CACHE_TTL_SIDEBAR` | `300` | 侧边栏数据缓存时长（秒） |
| `CACHE_TTL_DASHBOARD` | `60` | 仪表盘统计缓存时长（秒） |
| `CACHE_TTL_RSS` | `600` | RSS 订阅缓存时长（秒） |
| `SCRAPING_PROXY` | — | Amazon 爬虫代理地址（国内服务器必须设置海外代理） |
| `MAIL_SERVER` | — | SMTP 服务器地址 |
| `MAIL_PORT` | `587` | SMTP 端口 |
| `MAIL_USE_SSL` | `false` | 是否使用 SSL |
| `MAIL_USE_TLS` | `true` | 是否使用 TLS |
| `MAIL_USERNAME` | — | SMTP 用户名 |
| `MAIL_PASSWORD` | — | SMTP 密码 |
| `MAIL_DEFAULT_SENDER` | — | 默认发件人地址 |
| `WORKER_THREADS` | `3` | Worker 并行任务数 |

### 3.4 Nginx 反向代理配置

```nginx
server {
    listen 443 ssl;
    server_name hoshino.example.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    # 静态资源直接由 Nginx 处理
    location /static/ {
        alias /path/to/hoshino-blog/static/;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }

    # 动态请求转发到 Flask
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket 支持（B站爬虫进度推送）
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

---

## 4. 依赖库详解

### 4.1 Web 框架层

| 库 | 版本 | 用途 | 关键用法 |
|---|------|------|----------|
| **Flask** | 3.1.0 | 核心 Web 框架 | `Flask(__name__)`, `Blueprint`, `render_template` |
| **Werkzeug** | 3.1.8 | WSGI 工具集 | `generate_password_hash`, `check_password_hash`, `RequestEntityTooLarge` |
| **Jinja2** | 3.1.6 | 模板引擎 | `{% extends %}`, `{% block %}`, `{{ \|safe }}` |
| **itsdangerous** | 2.2.0 | 签名工具 | `URLSafeTimedSerializer` — session 多密钥验签 |
| **blinker** | 1.9.0 | 信号库 | Flask 内部信号机制 |

### 4.2 数据库层

| 库 | 版本 | 用途 | 关键用法 |
|---|------|------|----------|
| **SQLAlchemy** | 2.0.50 | ORM | `declarative_base()`, `relationship()`, `joinedload()`, `db.session` |
| **Flask-SQLAlchemy** | 3.1.1 | Flask 集成 | `SQLAlchemy(app)`, `db.init_app(app)` |
| **PyMySQL** | 1.2.0 | MySQL 驱动 | 作为 `mysql+pymysql://` URI 的驱动 |
| **Flask-Migrate** | ≥4.0 | 数据库迁移 | `Migrate(app, db)` — 基于 Alembic |

### 4.3 认证与表单

| 库 | 版本 | 用途 | 关键用法 |
|---|------|------|----------|
| **Flask-Login** | 0.6.3 | 用户认证 | `LoginManager()`, `@login_required`, `login_user()`, `current_user` |
| **WTForms** | 3.2.1 | 表单生成/验证 | `StringField`, `PasswordField`, `DataRequired` |
| **Flask-WTF** | 1.2.2 | CSRF + Flask 集成 | `FlaskForm`, `CSRFProtect`, `{{ form.hidden_tag() }}` |
| **email-validator** | 2.3.0 | 邮箱格式校验 | `Email()` 验证器 |

### 4.4 爬虫层

| 库 | 版本 | 用途 | 关键用法 |
|---|------|------|----------|
| **requests** | ≥2.28 | HTTP 请求 | `requests.get()`, `requests.Session` |
| **curl_cffi** | 0.15.0 | 模拟浏览器指纹 | `requests.Session()` 替代，绕过 Cloudflare/B站反爬 |
| **beautifulsoup4** | 4.12.2 | HTML 解析 | `BeautifulSoup(html, 'lxml')` |
| **lxml** | 4.9.3 | XML/HTML 解析器 | bs4 后端解析器 |
| **selenium** | 4.29.0 | Docker 浏览器自动化 | `webdriver.Remote()` — 浏览器池爬虫 |
| **bilibili-api-python** | ≥17.0.0 | B站 API SDK | `sync(get_user_info())`, `sync(get_videos())`, `qr_login()` |
| **qrcode** | ≥7.4 | QR 码生成 | `qrcode.make(data)` — B站扫码登录 |

### 4.5 其他

| 库 | 版本 | 用途 | 关键用法 |
|---|------|------|----------|
| **APScheduler** | 3.11.0 | 定时任务 | `BackgroundScheduler()`, `scheduler.add_job(trigger='cron')` |
| **redis** | 5.2.1 | Redis 客户端 | `Redis.from_url(url)`, `lpush`, `brpop`, `setex`, `hset` |
| **Pillow** | 11.1.0 | 图片处理 | `Image.open()`, `Image.resize(LANCZOS)`, `img.save(buf, 'WEBP')` |
| **jieba** | ≥0.42 | 中文分词 | `jieba.analyse.extract_tags(text, topK)` — 词云关键词提取 |
| **Markdown** | 3.7 | Markdown→HTML | `markdown(text, extensions=['fenced_code', 'codehilite', 'tables'])` |
| **Pygments** | 2.19.1 | 代码语法高亮 | codehilite 扩展依赖 |
| **bleach** | ≥6.0 | HTML 清理（XSS 防护） | `bleach.clean(html, tags=..., attributes=...)` |
| **Flask-Compress** | 1.24 | Gzip 压缩 | `Compress(app)` — 自动压缩 text/* 响应 |
| **brotli** | 1.2.0 | Brotli 压缩算法 | Flask-Compress 的备选压缩器 |
| **waitress** | 3.0.2 | 生产 WSGI 服务器 | `waitress-serve --port=5000 app:create_app` |
| **python-dotenv** | 1.1.0 | 环境变量加载 | `load_dotenv()` — 从 .env 文件加载配置 |
| **Eel** | ≥0.18 | GUI 启动器 | `eel.start('index.html')` — 桌面级启动界面 |

---

## 5. 数据库 Schema

### 5.1 表总览

```
users                  → 用户
posts                  → 文章
post_categories        → 文章←→分类多对多关联表
categories             → 分类
comments               → 评论
contact_messages       → 联系表单留言
featured_cards         → 首页特色卡片
hero_images            → 首页粒子画像
bili_ups               → B站 UP 主
bili_videos            → B站视频
bili_up_history        → UP 主粉丝数历史快照
bili_video_history     → 视频统计数据历史快照
bili_watched_videos    → 重点追踪视频
bili_subscriptions     → B站邮件订阅
bili_cleanup_config    → 快照清理配置
bili_video_comments    → B站视频评论（爬取存储）
wordcloud_data         → 词云数据（ZLIB 压缩存储）
wordcloud_config       → 词云配置
```

### 5.2 逐表字段

#### users

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTO_INCREMENT | 用户 ID |
| `username` | VARCHAR(64) | UNIQUE, NOT NULL, INDEX | 登录名 |
| `email` | VARCHAR(120) | UNIQUE, NOT NULL, INDEX | 邮箱 |
| `password_hash` | VARCHAR(256) | NOT NULL | PBKDF2-SHA256 哈希 |
| `display_name` | VARCHAR(128) | DEFAULT '' | 显示昵称 |
| `bio` | TEXT | | 个人简介 |
| `avatar` | VARCHAR(256) | DEFAULT 'images/avatar/main-avatar.jpg' | 头像路径 |
| `website` | VARCHAR(256) | DEFAULT '' | 个人网站 |
| `gitcode_url` | VARCHAR(256) | DEFAULT '' | GitCode |
| `github_url` | VARCHAR(256) | DEFAULT '' | GitHub |
| `gitee_url` | VARCHAR(256) | DEFAULT '' | Gitee |
| `bilibili_url` | VARCHAR(256) | DEFAULT '' | Bilibili |
| `about_content` | MEDIUMTEXT | | 关于页富文本 |
| `role` | VARCHAR(16) | DEFAULT 'user' | 角色：admin / editor / user |
| `is_active` | BOOLEAN | DEFAULT TRUE | 是否激活 |
| `last_login_at` | DATETIME | NULL | 最后登录时间 |
| `last_login_ip` | VARCHAR(45) | DEFAULT '' | 最后登录 IP |
| `login_count` | INTEGER | DEFAULT 0 | 登录次数 |
| `created_at` | DATETIME | DEFAULT CST_NOW | 创建时间 |

**关系**：`User.posts` → `Post.author_id`（一对多，1:N，级联删除）

#### posts

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTO_INCREMENT | 文章 ID |
| `title` | VARCHAR(256) | NOT NULL | 标题 |
| `slug` | VARCHAR(256) | UNIQUE, NOT NULL | URL 标识 |
| `summary` | TEXT | | 摘要 |
| `content` | MEDIUMTEXT | NOT NULL | Markdown 正文（扩展为 MEDIUMTEXT） |
| `cover_image` | VARCHAR(512) | DEFAULT '' | 封面图 URL |
| `is_published` | BOOLEAN | DEFAULT FALSE | 是否发布 |
| `author_id` | INTEGER | FK → users.id, NOT NULL | 作者 ID |
| `html_file_url` | VARCHAR(512) | DEFAULT '' | HTML 文件路径（弃用） |
| `html_content` | MEDIUMTEXT | | 内联 HTML 源码（优先级最高） |
| `created_at` | DATETIME | DEFAULT CST_NOW | 创建时间 |
| `updated_at` | DATETIME | DEFAULT CST_NOW ON UPDATE | 更新时间 |

**索引**：
- `ix_post_fulltext` — FULLTEXT(title, content) 中文全文搜索
- `ix_post_slug` — UNIQUE(slug)

**关系**：
- `Post.author` → `User`（多对一，N:1）
- `Post.categories` → `Category`（多对多，M:N，通过 `post_categories`）
- `Post.comments` → `Comment`（一对多，1:N，级联删除）

#### post_categories（关联表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `post_id` | INTEGER | PK, FK → posts.id ON DELETE CASCADE | 文章 ID |
| `category_id` | INTEGER | PK, FK → categories.id ON DELETE CASCADE | 分类 ID |

#### categories

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTO_INCREMENT | 分类 ID |
| `name` | VARCHAR(64) | UNIQUE, NOT NULL | 分类名称 |
| `slug` | VARCHAR(64) | UNIQUE, NOT NULL | URL 标识 |
| `description` | TEXT | | 分类描述 |

#### comments

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTO_INCREMENT | 评论 ID |
| `post_id` | INTEGER | FK → posts.id ON DELETE CASCADE, NOT NULL | 所属文章 |
| `author_name` | VARCHAR(64) | NOT NULL | 评论者名 |
| `author_email` | VARCHAR(120) | DEFAULT '' | 评论者邮箱 |
| `content` | TEXT | NOT NULL | 评论正文 |
| `is_approved` | BOOLEAN | DEFAULT FALSE | 是否审核通过 |
| `created_at` | DATETIME | DEFAULT CST_NOW | 创建时间 |

#### contact_messages

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTO_INCREMENT | ID |
| `name` | VARCHAR(64) | NOT NULL | 姓名 |
| `email` | VARCHAR(120) | NOT NULL | 邮箱 |
| `subject` | VARCHAR(256) | DEFAULT '' | 主题 |
| `content` | TEXT | NOT NULL | 内容 |
| `created_at` | DATETIME | DEFAULT CST_NOW | 时间 |

#### featured_cards

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTO_INCREMENT | 卡片 ID |
| `title` | VARCHAR(128) | NOT NULL | 标题 |
| `description` | TEXT | | 描述 |
| `icon` | VARCHAR(256) | DEFAULT '✦' | 图标（CSS class 或 Unicode） |
| `tag` | VARCHAR(64) | DEFAULT '' | 关联分类 slug |
| `link` | VARCHAR(256) | DEFAULT '' | 链接 |
| `image_url` | VARCHAR(512) | DEFAULT '' | 图片 URL |
| `sort_order` | INTEGER | DEFAULT 0 | 排序权重 |
| `is_active` | BOOLEAN | DEFAULT TRUE | 是否激活 |

#### hero_images

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTO_INCREMENT | ID |
| `title` | VARCHAR(128) | DEFAULT '' | 标题 |
| `image_url` | VARCHAR(512) | NOT NULL | 图片路径 |
| `alt_text` | VARCHAR(256) | DEFAULT '' | 替代文本 |
| `sort_order` | INTEGER | DEFAULT 0 | 排序 |
| `is_active` | BOOLEAN | DEFAULT TRUE | 是否激活 |
| `created_at` | DATETIME | DEFAULT CST_NOW | 创建时间 |

#### bili_ups

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTO_INCREMENT | UP 主 ID |
| `mid` | INTEGER | UNIQUE, NOT NULL, INDEX | B站 mid |
| `name` | VARCHAR(128) | DEFAULT '' | UP 主名 |
| `avatar` | VARCHAR(512) | DEFAULT '' | 头像 URL |
| `space_url` | VARCHAR(512) | DEFAULT '' | 空间页链接 |
| `description` | TEXT | | 描述 |
| `follower_count` | INTEGER | DEFAULT 0 | 粉丝数 |
| `video_count` | INTEGER | DEFAULT 0 | 视频总数 |
| `is_active` | BOOLEAN | DEFAULT TRUE | 是否活跃（启用爬取） |
| `last_scraped_at` | DATETIME | NULL | 最后爬取时间 |
| `created_at` | DATETIME | DEFAULT CST_NOW | 创建时间 |
| `updated_at` | DATETIME | DEFAULT CST_NOW ON UPDATE | 更新时间 |

**关系**：`BiliUp.videos` → `BiliVideo.up_id`（1:N，级联删除）

#### bili_videos

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTO_INCREMENT | 视频 ID |
| `up_id` | INTEGER | FK → bili_ups.id, NOT NULL, INDEX | 所属 UP 主 |
| `bvid` | VARCHAR(32) | UNIQUE, NOT NULL | B站 BVID |
| `aid` | INTEGER | UNIQUE, NOT NULL | B站 AID |
| `title` | VARCHAR(256) | DEFAULT '' | 标题 |
| `description` | TEXT | | 描述 |
| `cover_url` | VARCHAR(512) | DEFAULT '' | 封面图 URL |
| `duration` | INTEGER | DEFAULT 0 | 时长（秒） |
| `pubdate` | INTEGER | DEFAULT 0 | 发布时间戳（秒） |
| `pub_datetime` | DATETIME | NULL | 发布时间（DATETIME 格式） |
| `view_count` | INTEGER | DEFAULT 0 | 播放数 |
| `like_count` | INTEGER | DEFAULT 0 | 点赞数 |
| `coin_count` | INTEGER | DEFAULT 0 | 投币数 |
| `favorite_count` | INTEGER | DEFAULT 0 | 收藏数 |
| `share_count` | INTEGER | DEFAULT 0 | 转发数 |
| `comment_count` | INTEGER | DEFAULT 0 | 评论数 |
| `danmaku_count` | INTEGER | DEFAULT 0 | 弹幕数 |
| `tags` | JSON | NULL | 标签数组（MySQL JSON 类型） |
| `subtitle_text` | MEDIUMTEXT | NULL, COMMENT 'AI字幕文本' | AI 字幕（扩展为 MEDIUMTEXT） |
| `comments_crawled_at` | DATETIME | NULL | 评论最后爬取时间 |
| `created_at` | DATETIME | DEFAULT CST_NOW | 创建时间 |
| `updated_at` | DATETIME | DEFAULT CST_NOW ON UPDATE | 更新时间 |

**索引**：
- `ix_bili_video_up_pubdatetime` — (up_id, pub_datetime) — 按 UP 主 + 时间排序
- `ix_bili_video_up_updated` — (up_id, updated_at) — 按 UP 主 + 更新时间排序

#### bili_up_history

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTO_INCREMENT | ID |
| `up_id` | INTEGER | FK → bili_ups.id, NOT NULL | UP 主 ID |
| `follower_count` | INTEGER | DEFAULT 0 | 粉丝数 |
| `recorded_at` | DATETIME | DEFAULT CST_NOW | 记录时间 |

#### bili_video_history

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTO_INCREMENT | ID |
| `video_id` | INTEGER | FK → bili_videos.id, NOT NULL | 视频 ID |
| `view_count` | INTEGER | DEFAULT 0 | 播放数 |
| `like_count` | INTEGER | DEFAULT 0 | 点赞数 |
| `coin_count` | INTEGER | DEFAULT 0 | 投币数 |
| `favorite_count` | INTEGER | DEFAULT 0 | 收藏数 |
| `share_count` | INTEGER | DEFAULT 0 | 转发数 |
| `comment_count` | INTEGER | DEFAULT 0 | 评论数 |
| `danmaku_count` | INTEGER | DEFAULT 0 | 弹幕数 |
| `recorded_at` | DATETIME | DEFAULT CST_NOW | 记录时间 |

**索引**：`ix_bili_video_history_video_recorded` — (video_id, recorded_at)

#### bili_watched_videos

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTO_INCREMENT | ID |
| `up_id` | INTEGER | FK → bili_ups.id, NOT NULL | UP 主 ID |
| `video_id` | INTEGER | FK → bili_videos.id, NOT NULL | 视频 ID |
| `note` | VARCHAR(256) | DEFAULT '' | 备注 |
| `created_at` | DATETIME | DEFAULT CST_NOW | 创建时间 |

#### bili_subscriptions

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTO_INCREMENT | ID |
| `up_id` | INTEGER | FK → bili_ups.id, NOT NULL | UP 主 ID |
| `email` | VARCHAR(120) | NOT NULL | 订阅邮箱 |
| `token` | VARCHAR(128) | INDEX | 验证/取消令牌（非 UNIQUE，支持批量订阅共用令牌） |
| `is_verified` | BOOLEAN | DEFAULT FALSE | 是否已验证 |
| `is_active` | BOOLEAN | DEFAULT TRUE | 是否激活 |
| `verified_at` | DATETIME | NULL | 验证时间 |
| `created_at` | DATETIME | DEFAULT CST_NOW | 创建时间 |

#### bili_cleanup_config

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTO_INCREMENT | ID |
| `up_id` | INTEGER | FK → bili_ups.id, UNIQUE, NOT NULL | UP 主 ID |
| `keep_days` | INTEGER | DEFAULT 365 | 保留天数 |
| `max_history_per_video` | INTEGER | DEFAULT 30 | 每个视频最多保留的快照数 |
| `enabled` | BOOLEAN | DEFAULT TRUE | 是否启用 |
| `last_run_at` | DATETIME | NULL | 最后执行时间 |
| `created_at` | DATETIME | DEFAULT CST_NOW | |

#### bili_video_comments

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTO_INCREMENT | ID |
| `video_id` | INTEGER | FK → bili_videos.id CASCADE, NOT NULL, INDEX | 视频 ID |
| `content` | TEXT | NOT NULL | 评论内容 |
| `author` | VARCHAR(64) | DEFAULT '' | 评论者名 |
| `ctime` | INTEGER | DEFAULT 0 | 评论时间戳 |
| `like_count` | INTEGER | DEFAULT 0 | 点赞数 |

#### wordcloud_data

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTO_INCREMENT | ID |
| `post_id` | INTEGER | FK → posts.id CASCADE, NULL | 关联文章（NULL=全站词云） |
| `data` | LONGBLOB (ZLIB) | NOT NULL | 压缩后的词云词频 JSON [{text, weight, ...}] |
| `period` | VARCHAR(32) | DEFAULT 'all' | 时段（'all', '2026-01', ...） |
| `source` | VARCHAR(16) | DEFAULT 'blog' | 来源（'blog' / 'bili'） |
| `updated_at` | DATETIME | DEFAULT CST_NOW ON UPDATE | 更新时间 |

**说明**：`data` 列使用 `CompressedJSON` TypeDecorator，读写透明压缩/解压：
- 写入：Python dict → JSON → zlib.compress → BLOB
- 读取：BLOB → zlib.decompress → JSON → Python dict
- MySQL COMPRESS()/UNCOMPRESS() 兼容（RFC 1950 zlib 格式）

#### wordcloud_config

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTO_INCREMENT | ID |
| `shape` | VARCHAR(20) | NOT NULL DEFAULT 'circle' | 词云形状 |
| `max_font` | INTEGER | NOT NULL DEFAULT 48 | 最大字号 |
| `min_font` | INTEGER | NOT NULL DEFAULT 14 | 最小字号 |
| `top_n_article` | INTEGER | NOT NULL DEFAULT 60 | 单篇文章分词数 |
| `top_n_site` | INTEGER | NOT NULL DEFAULT 50 | 全站词云分词数 |
| `top_n_bili` | INTEGER | NOT NULL DEFAULT 100 | B站词云分词数 |
| `canvas_height` | INTEGER | NOT NULL DEFAULT 350 | 画布高度 |
| `color_scheme` | VARCHAR(20) | NOT NULL DEFAULT 'glow' | 配色方案 |
| `enabled_article` | TINYINT(1) | NOT NULL DEFAULT 1 | 文章词云启用 |
| `enabled_site` | TINYINT(1) | NOT NULL DEFAULT 1 | 全站词云启用 |
| `shape_image` | VARCHAR(256) | NOT NULL DEFAULT '' | 自定义形状图片路径 |
| `stop_words` | TEXT | NOT NULL DEFAULT '' | 停用词列表（逗号分隔） |

---

## 6. 配置系统

### 6.1 配置加载流程

```
load_dotenv()  →  读取 .env 文件到 os.environ
        │
        ▼
Config 类定义     →  os.environ.get('KEY') 或 Python 默认值
        │
        ▼
app.config.from_object('config.ActiveConfig')
        │
        ▼
create_app() 补充：
  • MAX_CONTENT_LENGTH = 200MB（覆盖 Config 的 16MB）
  • SQLALCHEMY_ENGINE_OPTIONS 扩大连接池（pool_size=30）
  • JSON_AS_ASCII = False
```

### 6.2 SECRET_KEY 轮换机制

```
文件 .secret_keys（JSON 数组，最新在前）
  ["new_key", "old_key_1", "old_key_2", ...]

轮换流程（每天 03:00）：
  1. 生成 secrets.token_hex(32) 新密钥
  2. 插入到列表头部，截断到 10 个
  3. 写入文件（原子写入：临时文件 → fsync → os.replace）
  4. 更新 app.config['SECRET_KEY'] = 最新密钥
  5. 更新 app.config['SECRET_KEY_FALLBACKS'] = 历史密钥列表

验签流程（session 加载时）：
  1. 用当前 SECRET_KEY 尝试解密
  2. 如果 BadSignature，逐个尝试 FALLBACKS
  3. 全部失败 → session 失效（用户需重新登录）
```

### 6.3 多密钥 Session Interface

`app.py` 中的 `_MultiKeySessionInterface`：
- `dumps()` — 只用当前 `SECRET_KEY` 签名
- `loads()` — 逐一尝试 `SECRET_KEY` + `SECRET_KEY_FALLBACKS`
- 密钥轮换后已登录用户的 session 不会立即失效

---

## 7. 入口文件：app.py

### 7.1 create_app() 初始化流程

```
create_app()
│
├─ 1. Flask(__name__)
├─ 2. app.config.from_object('config.ActiveConfig')
├─ 3. 覆盖配置（JSON_AS_ASCII, MAX_CONTENT_LENGTH 等）
├─ 4. CSRFProtect(app)
├─ 5. Flask-Compress 配置
│
├─ 6. setup_logging(app)        → 日志系统
├─ 7. os.makedirs(UPLOAD_FOLDER)
│
├─ 8. init_db(app)              → 数据库（建表 + 迁移 + 默认管理员）
│    ├─ db.init_app(app)
│    ├─ db.create_all()
│    ├─ _migrate_category_to_many2many()
│    ├─ _migrate_is_admin_to_role()
│    ├─ _migrate_user_profile_fields()
│    ├─ _migrate_bili_up_fields()
│    ├─ _migrate_bili_video_fields()
│    ├─ _migrate_bili_indexes()
│    ├─ _migrate_bili_sub_token_index()
│    ├─ _migrate_wordcloud_data_fields()
│    ├─ _migrate_wordcloud_config_fields()
│    ├─ _migrate_post_fulltext_index()
│    ├─ _migrate_bili_video_tags()
│    ├─ _migrate_bili_video_comments_table()
│    ├─ 创建默认管理员
│    └─ ... 更多 _migrate_* 函数
│
├─ 9. init_redis(app)           → Redis 连接池
├─ 10. init_task_queue(app)     → 任务队列（复用 Redis 连接）
│
├─ 11. 初始化 Amazon 爬虫代理
├─ 12. 加载 B站 Cookie
│
├─ 13. LoginManager + user_loader
├─ 14. _MultiKeySessionInterface
│
├─ 15. 注册 Blueprint：
│    ├─ blog_bp       → /
│    ├─ admin_bp      → /admin
│    ├─ bili_bp       → /admin/bilibili
│    └─ bili_public_bp → /bili
│
├─ 16. compress.init_app(app)
├─ 17. 错误页面（404/403/500）
├─ 18. 请求日志中间件
├─ 19. 安全响应头
├─ 20. teardown_appcontext → db.session.remove()
└─ 21. Jinja2 过滤器（paragraphify）
```

### 7.2 启动流程（__main__ 块）

```
if __name__ == '__main__':
    app = create_app()
    
    # 启动 Worker 子进程（stderr 连接到终端）
    worker_proc = subprocess.Popen(
        [sys.executable, worker_py],
        stdout=subprocess.DEVNULL,
        stderr=sys.stderr,       # ← Worker 日志出现在 Flask 终端
        stdin=subprocess.DEVNULL
    )
    
    # 注册退出清理
    atexit.register → _stop_worker()  # terminate → wait(5s) → kill
    signal.signal(SIGTERM) → _stop_worker() + sys.exit(0)
    
    app.run(host=..., port=..., debug=...)
```

### 7.3 _init_scheduler()

```
_init_scheduler(app)
│
├─ BackgroundScheduler()
│
├─ cron(03:00)  → rotate_secret_key(app)
├─ cron(02:00)  → run_daily_scrape(app)
├─ date(+10s)   → _run_bili_incremental_check(app)  # 首次延迟 10s
├─ cron(03:00)  → auto_cleanup_history(app)
├─ cron(02:10)  → precompute_all_wordclouds()
└─ cron(02:15)  → precompute_bili_wordclouds()
```

---

## 8. 后台工作进程：worker.py

### 8.1 架构

```
worker.py main()
│
├─ 1. create_app()
├─ 2. _init_scheduler(app)  → APScheduler 定时任务
├─ 3. init_task_queue(app)  → Redis 队列
│
├─ 4. ThreadPoolExecutor(max_workers=3)
│    └─ 主循环：get_task() → executor.submit(_run_task, task, app)
│
└─ 5. 信号处理 → shutdown → executor.shutdown(wait=True, timeout=30)
```

### 8.2 多线程模型

```
主线程（消费者循环）
│
│  while not shutdown:
│      task = get_task()          ← Redis BRPOP（最长阻塞 5s）
│      future = executor.submit(_run_task, ...)  ← 立即返回
│
├── [线程池：Worker-1]  _run_task(task_1, app)
│   ├── with app.app_context():
│   │   ├── _run_scrape(mid=111, ...)
│   │   └── ... 耗时 2 分钟 ...
│   └── finally: mark_done(mid) + db.session.remove()
│
├── [线程池：Worker-2]  _run_task(task_2, app)
│   ├── with app.app_context():
│   │   ├── _run_scrape(mid=222, ...)
│   │   └── ... 耗时 1 分钟 ...
│   └── finally: mark_done(mid) + db.session.remove()
│
└── [线程池：Worker-3]  _run_task(task_3, app)
    ├── with app.app_context():
    │   ├── wordcloud precompute
    │   └── ...
    └── finally: ...
```

### 8.3 _run_task() 安全保障

```python
def _run_task(task, app):
    task_type = task.get('type')
    data = task.get('data', {})
    
    try:
        with app.app_context():
            if task_type == 'refresh_up':
                _run_scrape(...)
            elif task_type == 'refresh_all':
                _run_scrape(..., force=True)
            # ...
    except Exception as e:
        logger.error('任务失败: %s', e, exc_info=True)
    finally:
        # 始终清除 Redis 运行标记，防止卡死
        if task_type in ('refresh_up', 'refresh_all'):
            mark_done(data['mid'])
        db.session.remove()
```

**关键改进**：`mark_done()` 移入 `finally` 块，无论任务成功/失败/异常都会执行，避免 UP 主状态卡在"运行中"。

---

## 9. 任务队列：task_queue.py

### 9.1 Redis Key 规范

| Key | 类型 | 用途 | 过期 |
|-----|------|------|------|
| `hblog:task:queue` | List | 待处理任务列表 | 无（持久） |
| `hblog:task:progress:{mid}` | String | 任务进度日志 JSON 数组 | 1 小时 |
| `hblog:task:running` | Hash | 运行中任务 `{mid: timestamp}` | 无 |

### 9.2 API 参考

| 函数 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `init_task_queue(app)` | Flask app | None | 复用 Redis 缓存连接 |
| `submit_task(task_type, **kwargs)` | str, **kwargs | str \| None | LPUSH 到队列，返回 task_id 或 None（降级） |
| `get_task()` | — | dict \| None | BRPOP 5s 超时，返回任务字典或 None |
| `update_progress(mid, lines)` | int, list | None | SETEX 更新进度（1h 过期） |
| `get_progress(mid)` | int | (lines, running) | 获取进度 + 运行状态 |
| `mark_running(mid)` | int | None | HSET 标记运行中 |
| `mark_done(mid)` | int | None | HDEL 清除运行标记 |
| `is_running(mid)` | int | bool | HEXISTS 检查是否在运行 |

### 9.3 降级机制

当 `REDIS_URL` 未配置或 Redis 不可用时：
- `submit_task()` → 返回 `None`（调用方降级到本地线程）
- `get_task()` → 返回 `None`
- `update_progress()` → 静默失败
- `get_progress()` → 返回 `([], False)`
- `mark_running()` / `mark_done()` / `is_running()` → 静默失败

Flask 端降级路径：
```python
if task_id := submit_task('refresh_up', mid=mid, space_url=space_url):
    mark_running(mid)
    return {'ok': True, 'mid': mid, 'task_id': task_id}
# Redis 不可用，降级到本地线程
with _scrape_lock:
    _scrape_running.add(mid)
t = threading.Thread(target=_run_scrape, args=(mid, space_url, app), daemon=True)
t.start()
return {'ok': True, 'mid': mid, 'task_id': None}
```

### 9.4 任务数据格式

```python
{
    "id": "a1b2c3d4",          # UUID 前 8 位
    "type": "refresh_up",       # 任务类型
    "submitted_at": 1712345678.0,  # 提交时间戳
    "data": {                    # 任务参数
        "mid": 12345,
        "space_url": "https://space.bilibili.com/12345",
        "max_videos": 30         # 可选
    }
}
```

---

## 10. 数据模型：models.py

详见 [第五章：数据库 Schema](#5-数据库-schema)。

### 10.1 CompressedJSON TypeDecorator

词云数据列的透明压缩/解压缩器：

```python
class CompressedJSON(db.TypeDecorator):
    impl = db.LargeBinary  # 底层存储为 LONGBLOB
    
    def process_bind_param(self, value, dialect):
        # Python dict → JSON → zlib.compress → bytes
        return zlib.compress(json.dumps(value, ensure_ascii=False).encode('utf-8'))
    
    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            # 兼容 MySQL COMPRESS() 格式（RFC 1950 zlib）
            data = zlib.decompress(value)
            return json.loads(data.decode('utf-8'))
        except zlib.error:
            # 非压缩数据（旧版 TEXT 格式），直接 JSON 解析
            return json.loads(value.decode('utf-8'))
```

---

## 11. 前台路由：routes.py

### 11.1 Blueprint：blog_bp（前缀 `/`）

| 路由 | 方法 | 函数 | URL 参数 | 模板 | 说明 |
|------|------|------|----------|------|------|
| `/` | GET | `index()` | `page`(int,1), `category`(str,None), `per_page`(int,config) | `index.html` | 首页：文章瀑布流 + 词云 + 特色卡片 |
| `/post/<slug>` | GET/POST | `single_post(slug)` | 路径: slug | `single-post.html` / `html-post.html` | 文章详情 + 评论表单 |
| `/post/<slug>/html-frame` | GET | `post_html_frame(slug)` | 路径: slug | 无模板，直接返回 HTML | 内联 HTML 独立帧（sandbox iframe） |
| `/category/<slug>` | GET | `category(slug)` | `page`(int,1), `per_page`(int,config) | `category-grid.html` | 分类筛选 |
| `/about` | GET | `about()` | — | `about.html` | 关于页（管理员 about_content） |
| `/contact` | GET/POST | `contact()` | — | `contact.html` | 联系表单 |
| `/tools` | GET | `tools()` | — | `tools.html` | 工具箱 |
| `/search` | GET | `search()` | `q`(str,必填), `page`(int,1), `per_page`(int) | `index.html` | 全文搜索（FULLTEXT → ILIKE 降级） |
| `/feed.xml` | GET | `rss_feed()` | — | `rss.xml` | RSS 订阅（10 分钟缓存） |
| `/thumb` | GET | `thumbnail()` | `path`(str), `w`(int,400), `fmt`(str,webp) | 无，返回图片二进制 | 动态缩略图生成（磁盘缓存） |

### 11.2 侧边栏数据缓存

`_get_sidebar_data()` 使用 3 线程并行查询：
1. 所有分类（排序）
2. 分类文章数统计（聚合查询）
3. 最新 4 篇文章（Redis 缓存优先）

### 11.3 全文搜索策略

```
search(q)
│
├─ 方言判断
│   ├─ PostgreSQL → to_tsvector + plainto_tsquery
│   ├─ MySQL → MATCH ... AGAINST (BOOLEAN MODE)
│   │   └─ 过滤 +-<>()~*@" 操作符防滥用
│   └─ SQLite → title.match(q) | content.match(q)
│
├─ 全文搜索（优先）
│   └─ 无结果或异常 → ILIKE 降级
│       ├─ title.ilike(f'%{safe_q}%')
│       ├─ summary.ilike(f'%{safe_q}%')
│       └─ content.ilike(f'%{safe_q}%')
│
└─ 使用 escape 转义 % 和 _，防止 SQL 注入构造 DoS 查询
```

### 11.4 动态缩略图

```python
URL: /thumb?path=uploads/photo.jpg&w=400&fmt=webp

流程：
  1. 路径规范化 + 安全检查（禁止 ../ 遍历）
  2. 缓存检查（.thumb_cache/{version}_{path}_{w}.webp）
  3. 未命中 → Pillow 缩放（LANCZOS，只缩小不放大）
  4. 默认输出 WebP（quality=80, method=6）
  5. 并发写锁防止多线程重复生成
  6. 每小时清理一次旧版本缓存
```

---

## 12. 后台管理路由：admin.py

### 12.1 Blueprint：admin_bp（前缀 `/admin`）

#### 认证

| 路由 | 方法 | 权限 | 说明 |
|------|------|------|------|
| `/admin/login` | GET/POST | 无 | 登录（LRU IP 限速，10 次/分钟） |
| `/admin/logout` | GET | @login_required | 登出 |
| `/admin/register` | GET/POST | 无 | 注册（默认关闭，ENABLE_REGISTRATION 控制） |

#### 仪表盘

| 路由 | 方法 | 权限 | 说明 |
|------|------|------|------|
| `/admin/` | GET | @editor_required | 仪表盘（6 线程并行统计 + 60s 缓存） |

#### 文章管理

| 路由 | 方法 | 权限 | 说明 |
|------|------|------|------|
| `/admin/posts` | GET | @author_required | 文章列表（分页 + 搜索） |
| `/admin/posts/new` | GET/POST | @author_required | 新建文章（Markdown + HTML 双模式） |
| `/admin/posts/<id>/edit` | GET/POST | @author_required | 编辑文章（作者只能编辑自己的） |
| `/admin/posts/<id>/delete` | POST | @author_required | 删除文章（级联删除评论） |

#### 分类管理

| 路由 | 方法 | 权限 | 说明 |
|------|------|------|------|
| `/admin/categories` | GET | @editor_required | 分类列表 |
| `/admin/categories/new` | GET/POST | @editor_required | 新建分类（name + slug 唯一） |
| `/admin/categories/<id>/edit` | GET/POST | @editor_required | 编辑分类 |
| `/admin/categories/<id>/delete` | POST | @editor_required | 删除分类（解除所有关联） |

#### 评论管理

| 路由 | 方法 | 权限 | 说明 |
|------|------|------|------|
| `/admin/comments` | GET | @editor_required | 评论列表（待审核/已通过独立分页） |
| `/admin/comments/<id>/approve` | POST | @editor_required | 审核通过 |
| `/admin/comments/<id>/delete` | POST | @editor_required | 删除评论 |

#### 用户管理

| 路由 | 方法 | 权限 | 说明 |
|------|------|------|------|
| `/admin/users` | GET | @admin_required | 用户列表 |
| `/admin/users/new` | GET/POST | @admin_required | 新建用户 |
| `/admin/users/<id>/edit` | GET/POST | @admin_required | 编辑角色 |
| `/admin/users/<id>/delete` | POST | @admin_required | 删除用户（级联删除文章） |
| `/admin/users/<id>/toggle-active` | POST | @admin_required | 禁用/启用 |

#### 个人资料

| 路由 | 方法 | 权限 | 说明 |
|------|------|------|------|
| `/admin/profile` | GET/POST | @author_required | 编辑资料（头像/邮箱/密码/关于页） |

#### 图片上传

| 路由 | 方法 | 权限 | 说明 |
|------|------|------|------|
| `/admin/upload-image` | POST | @author_required | 富文本编辑器图片上传（Magic Bytes 校验 + 统一转 WebP） |

#### 特色卡片

| 路由 | 方法 | 权限 | 说明 |
|------|------|------|------|
| `/admin/featured-cards` | GET | @admin_required | 卡片列表 |
| `/admin/featured-cards/new` | GET/POST | @admin_required | 新建卡片 |
| `/admin/featured-cards/<id>/edit` | GET/POST | @admin_required | 编辑卡片 |
| `/admin/featured-cards/<id>/delete` | POST | @admin_required | 删除卡片 |

#### 诊断端点

| 路由 | 方法 | 权限 | 说明 |
|------|------|------|------|
| `/admin/_bili_debug/<mid>` | GET | @admin_required | B站 API 诊断 |
| `/admin/_debug` | GET | @admin_required | Session/请求诊断 |

### 12.2 权限装饰器

```python
@admin_required   → @login_required + is_admin → 403
@editor_required  → @login_required + role in (admin, editor) → 403
@author_required  → @login_required + role in (admin, editor, author) → 403
```

### 12.3 登录频率限制

```python
_LRUDict(maxsize=10000) → IP → [尝试时间戳列表]
每一分钟最多 10 次尝试
超过限制 → flash('登录尝试过于频繁') → 渲染表单
登录成功 → 清空该 IP 的尝试记录
```

### 12.4 HTML 净化

管理员提交的 HTML 内容经过两层 bleach 过滤：

```python
# 前台评论（严格，只保留纯文本）
bleach.clean(content, tags=[], strip=True)

# 后台文章（宽松，保留富文本标签）
_HTML_CLEAN_TAGS = ['p', 'div', 'h1-h6', 'a', 'img', 'iframe', 'video', ...]
_HTML_STRIP_ATTRS = {'*': ['id', 'class', 'style'], 'a': ['href', 'title'], ...}
_sanitize_html(html) → bleach.clean(html, tags=tags, attributes=attrs, strip=True)
```

---

## 13. B站管理路由：bili_routes.py

### 13.1 Blueprint：bili_bp（前缀 `/admin/bilibili`）

| 路由 | 方法 | 权限 | 函数 | 说明 |
|------|------|------|------|------|
| `/admin/bilibili/` | GET | @editor_required | `index()` | UP 主列表 |
| `/admin/bilibili/qr-gen` | GET | @editor_required | `qr_generate()` | 生成 B站 扫码登录二维码 |
| `/admin/bilibili/qr-poll` | GET | @editor_required | `qr_poll()` | 轮询扫码状态 |
| `/admin/bilibili/logout-bili` | POST | @editor_required | `logout_bili()` | 登出 B站 |
| `/admin/bilibili/up/<up_id>` | GET | @editor_required | `up_detail(up_id)` | UP 主详情（视频列表） |
| `/admin/bilibili/refresh/<up_id>` | POST | @editor_required | `refresh_up(up_id)` | 手动刷新（最近 30 视频） |
| `/admin/bilibili/refresh-all/<up_id>` | POST | @editor_required | `refresh_up_all(up_id)` | 强制全量刷新 |
| `/admin/bilibili/up/<up_id>/refresh-comments` | POST | @editor_required | `refresh_up_comments(up_id)` | 刷新评论 |
| `/admin/bilibili/up/<up_id>/refresh-subtitles` | POST | @editor_required | `refresh_up_subtitles(up_id)` | 刷新字幕 |
| `/admin/bilibili/delete/<up_id>` | POST | @editor_required | `delete_up(up_id)` | 删除 UP 主（级联） |
| `/admin/bilibili/delete-video/<video_id>` | POST | @editor_required | `delete_video(video_id)` | 删除单视频 |
| `/admin/bilibili/video/<video_id>/watch` | POST | @editor_required | `watch_video(video_id)` | 重点追踪 |
| `/admin/bilibili/video/<video_id>/unwatch` | POST | @editor_required | `unwatch_video(video_id)` | 取消追踪 |
| `/admin/bilibili/check-missing` | GET | @editor_required | `check_missing()` | 对比 API 与 DB 视频数 |
| `/admin/bilibili/scrape-status` | GET | @editor_required | `scrape_status()` | 查看爬取进度 |
| `/admin/bilibili/scrape` | POST | @editor_required | `scrape()` | 添加新 UP 主并爬取 |
| `/admin/bilibili/add-video` | POST | @editor_required | `add_single_video()` | **添加单个视频（BV/AV 号）** |

### 13.2 爬取核心函数

#### `add_single_video()` — 单个视频添加（2026-07-28 新增）

```
流程图：
┌─ 1. 解析输入
│   ├─ BV 号：直接提取（如 BV1xx411c7mD）
│   ├─ AV 号：转换为 BV 号（AV→BV 算法）
│   └─ 视频链接：正则提取 BV 号
│
├─ 2. 检查是否已存在
│   ├─ 存在 → 返回 {exists: True} → 前端确认 → force_update=True
│   └─ 不存在 → 继续
│
├─ 3. 获取视频完整信息
│   └─ get_video_full_info(bvid) → 标题/播放量/封面/UP主信息
│
├─ 4. 创建/更新 UP 主（仅基本信息）
│   ├─ 只保存：mid、名称、头像
│   └─ 不爬取：video_count、follower_count
│
├─ 5. 创建/更新视频记录
│   ├─ 保存：aid、bvid、title、description、duration、pic
│   ├─ 保存统计：view/like/coin/favorite/share/comment/danmaku
│   └─ 创建历史记录：BiliVideoHistory
│
└─ 6. 返回成功提示
```

**AV 转 BV 算法**：
```python
table = 'fZodR9XQDSUm21yCkr6zBqiveYah8bt4xsWpHnJE7jL5VG3guMTNNPAcF'
aid = (aid ^ 177456) // 100
arr = [table[aid // 58**i % 58] for i in range(9)]
bvid = 'BV' + ''.join(arr[::-1])
```

#### `_run_scrape(mid, space_url, app, max_videos=None, force=False)`

```
流程图：
┌─ A. 获取/更新 UP 主信息（name, avatar, follower_count）
├─ B. 补全缺失视频
│   ├─ should_fill = (DB_count == 0) or (DB_count < API_count) or force
│   ├─ arc/search API 翻全量，已知 BVID/AID 跳过
│   ├─ 每 20 条批量提交，减少事务压力
│   └─ 每视频 7~10s 随机间隔 + 指数退避重试（30s→600s）
│
├─ C. 动态流兜底
│   ├─ get_video_list_from_dynamics()
│   └─ 捕获 arc/search 可能遗漏的 shorts/新视频
│
└─ D. 三层统计更新
    ├─ Hot (≤7d)    → 全部更新，min_age=0
    ├─ Warm (8~30d) → 配额剩余时更新，min_age=1h
    └─ Cold (>30d)  → 配额剩余时处理，min_age=24h
```

#### `_check_new_videos(mid, app)`

```
增量检查流程（每 40 分钟运行）：
  1. arc/search API 翻前 10 页
  2. 对比 DB 中已有的 BVID/AID
  3. 新视频入库 + BiliVideoHistory
  4. 重点追踪视频强制更新统计
  5. 动态流兜底
```

#### `_crawl_video_comments(video, hot_pages=5, newest_pages=3)`

```
评论爬取流程：
  1. B站 API 获取热门评论（hot_pages）
  2. B站 API 获取最新评论（newest_pages）
  3. 写入 bili_video_comments 表
  4. 更新 bili_videos.comments_crawled_at
```

#### `get_subtitle(video_id)`

```
AI 字幕爬取流程：
  1. B站 API 获取字幕列表（可能多语言）
  2. 过滤：中文 > 中英双语 > 英文（优先级）
  3. 拼接所有字幕片段为纯文本
  4. 写入 bili_videos.subtitle_text → 用于词云
```

### 13.3 防反爬机制

```python
# 每视频请求后随机睡眠
time.sleep(_VIDEO_SLEEP_BASE + random.random() * _VIDEO_SLEEP_JITTER)  # 7~10s

# 全局熔断器（412 IP 封禁检测）
_circuit_open_until = 0.0  # 熔断到期时间戳
_CIRCUIT_COOLDOWN = 60 * 60  # 熔断时长 60 分钟

# 指数退避
retry_delay = 30  # 起始 30s
retry_delay = min(retry_delay * 2, 600)  # 翻倍，最大 600s（10 分钟）

# 增量熔断冷却时间计算
def _circuit_compute_cooldown():
    # 5min → 10min → 20min → 60min（连续 412 时递增，1h 无 412 重置）
```

---

## 14. B站公开路由：bili_public_routes.py

### 14.1 Blueprint：bili_public_bp（前缀 `/bili`）

| 路由 | 方法 | 函数 | 说明 |
|------|------|------|------|
| `/bili` | GET | `index()` | B站数据首页 |
| `/bili/up/<mid>` | GET | `up_detail(mid)` | UP 主主页 + 视频列表 |
| `/bili/video/<bvid>` | GET | `video_detail(bvid)` | 视频详情（统计 + 词云 + 字幕） |
| `/bili/search` | GET | `search()` | B站视频搜索 |
| `/bili/subscribe` | POST | `subscribe()` | 创建邮件订阅（发送验证邮件） |
| `/bili/subscribe/verify/<token>` | GET | `verify_subscription(token)` | 验证订阅 |
| `/bili/subscribe/unsubscribe/<token>` | GET | `unsubscribe(token)` | 取消订阅 |
| `/bili/api/up/<mid>/follower-history` | GET | `follower_history(mid)` | 粉丝数趋势 API（JSON） |
| `/bili/api/video/<bvid>/stat-history` | GET | `stat_history(bvid)` | 视频统计趋势 API（JSON） |

### 14.2 视频详情页图表功能

#### 自定义日历选择器

**布局结构**（从上到下）：
```
年份选择行：[‹] [2026] [›]
月份选择行：[‹] [7月] [›]
星期表头：日 一 二 三 四 五 六
日期网格：6行×7列完整矩阵
```

**核心功能**：
- **拖拽选择**：鼠标按下记录起始日期，移动实时预览范围，松开确认选择
- **跨月选择**：拖拽到边缘自动切换月份（300ms 间隔）
- **智能日期解析**：时间标签格式 `MM/DD HH:MM`，根据前一个日期推断年份
- **数据点采样**：基于比例采样，保留约 120 个点
- **清除选择**：一键重置，显示所有数据

**日期范围计算**：
```javascript
minDate: 数据最早日期的 00:00:00
maxDate: 数据最晚日期的 23:59:59
确保所有数据日期都可选
```

**智能年份推断**：
```javascript
第一个数据点 → 使用系统年份
后续数据点 → 根据前一个日期推断
月份跳跃 > 1 → 跨年（年份+1）
月份倒退 > 1 → 前一年（年份-1）
```

---

## 15. 词云模块：wordcloud.py

### 15.1 核心函数

| 函数 | 参数 | 说明 |
|------|------|------|
| `precompute_all_wordclouds()` | — | 重算全站博客词云（按月分段） |
| `precompute_bili_wordclouds()` | — | 重算全站 B站词云 |
| `precompute_up_wordclouds(up_id)` | up_id | 重算单个 UP 主的词云 |
| `submit_task(task_type, **kwargs)` | str, kwargs | 投递异步词云计算任务 |
| `recompute_wordcloud(post=None)` | Post\|None | 单篇文章或全站词云重算 |

### 15.2 词云生成流程

```
1. 获取文本来源
   ├─ 博客文章 → Post.content + Post.title
   └─ B站视频 → bili_videos.subtitle_text + bili_videos.title

2. jieba 分词 + TF-IDF 关键词提取
   ├─ jieba.analyse.extract_tags(text, topK=config.top_n_XXX)
   └─ 过滤停用词（wordcloud_config.stop_words）

3. 按 period 分段
   ├─ 'all' — 全部数据
   └─ '2026-01' — 按月分段

4. 生成词云词频列表
   ├─ [{"text": "碧蓝档案", "weight": 0.85}, ...]
   └─ 写入 wordcloud_data（CompressedJSON 压缩存储）

5. 定时重算
   ├─ 02:10 — 全站博客词云
   ├─ 02:15 — 全站 B站词云
   └─ 文章发布/编辑后 → submit_task('post', post_id=id) → 单篇词云
```

---

## 16. B站 API 封装：bilibili/

### 16.1 blog/bilibili/bili_api.py

#### B站 API 函数

| 函数 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `extract_mid(url)` | str | int | 从空间页 URL 提取 mid |
| `get_user_info(mid)` | int | dict | 获取 UP 主信息（name, avatar, follower_count, video_count） |
| `get_video_list(mid, page_start=1, page_end=None)` | int, int, int\|None | Generator[dict] | 遍历视频列表（分页翻取） |
| `get_video_list_from_dynamics(mid)` | int | list[dict] | 从动态流获取视频（兜底） |
| `get_video_stat(bvid)` | str | dict | 获取视频统计数据（view, like, coin, fav, share, comment, danmaku） |
| `get_video_info(bvid)` | str | dict | 获取视频详细信息（含分P数据） |
| `get_pages(bvid)` | str | list[VideoPage] | 获取视频分 P 列表（每个 P 有 cid） |
| `get_subtitle(cid)` | int | str | 获取 AI 字幕文本（自动选择：中文 > 中英双语 > 英文） |
| `get_comments(cid, page=1)` | int, int | list[dict] | 获取视频评论 |
| `_is_risk_control(e)` | Exception | bool | 判断异常是否为 B站风控 |
| `_is_ip_blocked(e)` | Exception | bool | 判断异常是否为 IP 封禁（412） |
| `was_recently_blocked(cooldown=300)` | int | bool | 检查近期是否被 412 封禁 |

#### B站 API 错误处理

```python
# 412 响应 → _is_ip_blocked() → True → 全局熔断
# 429/频率限制 → _is_risk_control() → True → 指数退避重试
# 网络超时 → requests.Timeout → 重试 3 次后跳过
# JSON 解析错误 → 记录日志 + 跳过当前页面
```

### 16.2 blog/bilibili/login.py

| 函数 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `apply_cookies()` | — | None | 从 Cookie 文件加载凭证到 bilibili-api 会话 |
| `save_cookies(cookies)` | dict | None | 保存 Cookie 到文件 |
| `qr_generate_v2()` | — | dict | 生成 V2 版扫码登录二维码 |
| `poll_qr_v2(key)` | str | dict | 轮询 V2 版扫码状态 |
| `have_cookies()` | — | bool | 检查本地是否有有效 Cookie |

Cookie 文件路径：`blog/bilibili/cookies.json`（包含 buvid3, b_nut, b_lsid, SESSDATA, bili_jct 等）

### 16.3 blog/bilibili/config.py

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `BILI_UA` | Mozilla/5.0 ... Chrome/120 | B站 API 请求 User-Agent |
| `BILI_REFERER` | https://www.bilibili.com | Referer |
| `BILI_API_TIMEOUT` | 30 | API 超时（秒） |
| `BILI_VIDEO_SLEEP_BASE` | 7 | 视频间基础延迟（秒） |
| `BILI_VIDEO_SLEEP_JITTER` | 3 | 视频间随机延迟（秒） |
| `BILI_COMMENT_HOT_PAGES` | 5 | 热门评论翻页数 |
| `BILI_COMMENT_NEWEST_PAGES` | 3 | 最新评论翻页数 |

---

## 17. 缓存系统：cache.py

### 17.1 Redis Key 规范

| Key | TTL | 用途 |
|-----|-----|------|
| `hblog:cache:sidebar:recent_posts` | 300s (5min) | 侧边栏最新文章 |
| `hblog:cache:home:featured_cards` | 300s (5min) | 首页特色卡片 |
| `hblog:cache:post:rendered:{id}:{ts}` | 3600s (1h) | 文章 Markdown 渲染缓存 |
| `hblog:cache:dashboard:stats` | 60s (1min) | 仪表盘统计 |
| `hblog:cache:rss:feed` | 600s (10min) | RSS 输出 |
| `hblog:cache:admin:social_links` | 300s (5min) | 管理员社交链接 |
| `hblog:cache:wordcloud:{period}` | 3600s (1h) | 词云数据 |

### 17.2 API 参考

| 函数 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `init_redis(app)` | Flask app | None | 从 REDIS_URL 创建连接池 |
| `cache_get(key)` | str | Any \| None | GET 并 JSON 反序列化 |
| `cache_set(key, value, ttl=300)` | str, Any, int | None | JSON 序列化后 SETEX |
| `cache_delete(key)` | str | None | DEL |
| `cache_delete_pattern(pattern)` | str | None | SCAN + DEL 批量删除 |

### 17.3 降级策略

```python
if _redis_client is None:
    return None  # 缓存未命中
try:
    data = _redis_client.get(key)
    return json.loads(data) if data else None
except (ConnectionError, TimeoutError, json.JSONDecodeError):
    return None  # Redis 异常 → 降级到 DB 查询
```

---

## 18. 日志系统：logger.py

### 18.1 日志配置

| Handler | 输出目标 | 级别 | 格式 | 轮转策略 |
|---------|----------|------|------|----------|
| file_handler | `blog/logs/hoshino.log` | DEBUG | 详细（含模块/行号） | 每日轮转，保留 30 天 |
| error_handler | `blog/logs/error.log` | ERROR | 详细 | 大小轮转，10MB×5 |
| console_handler | 终端 stderr | INFO | 简洁 | 无 |

### 18.2 请求日志中间件

```python
@app.after_request
def log_request(response):
    GET  /admin/posts  200  → 终端 INFO
    POST /admin/login  403  → 终端 WARNING
    GET  /admin/bili/  500  → 终端 ERROR
    # 文件同时记录完整详情（IP, UA, 路径, 状态码）
```

### 18.3 第三方库压制

| 库 | 日志级别 |
|---|----------|
| selenium.webdriver.remote | WARNING |
| urllib3 | WARNING |
| requests | WARNING |
| sqlalchemy.engine | WARNING |
| werkzeug | WARNING（终端）/ DEBUG（文件） |

---

## 19. 表单定义：forms.py

| 表单类 | 字段 | 说明 |
|--------|------|------|
| `LoginForm` | username, password | 登录表单 |
| `RegisterForm` | username, email, password, password_confirm, display_name | 注册表单 |
| `PostForm` | title, slug, summary, content, categories, cover_image, html_file, html_content, is_published | 文章表单（Markdown + HTML 双模式） |
| `CategoryForm` | name, slug, description | 分类表单 |
| `UserForm` | username, email, password, display_name, bio, website, role | 用户管理表单 |
| `ProfileForm` | display_name, bio, website, gitcode_url, github_url, gitee_url, bilibili_url, email, password, current_password, about_content, avatar | 个人资料表单 |
| `FeaturedCardForm` | title, description, icon, tag, link, image_url, sort_order, is_active | 特色卡片表单 |
| `HeroImageForm` | title, image_url, alt_text, sort_order, is_active | 背景画像表单 |
| `CommentForm` | author_name, author_email, content | 评论表单 |
| `ContactForm` | name, email, message | 联系表单 |

---

## 20. 邮件模块：mail.py

### 20.1 功能

| 函数 | 参数 | 说明 |
|------|------|------|
| `send_email(to, subject, body)` | str, str, str | 发送纯文本邮件 |
| `send_verification_email(email, token, site_name)` | str, str, str | 发送订阅验证邮件 |
| `send_new_video_notification(email, up_name, videos, token, site_name)` | str, str, list, str, str | 发送新视频通知邮件 |

### 20.2 配置

```python
MAIL_SERVER = os.environ.get('MAIL_SERVER', '')
MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
MAIL_USE_TLS = True  # 默认
MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '')
MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')
```

---

## 21. Amazon 爬虫：apify_client.py

### 21.1 功能

使用 curl_cffi 模拟浏览器指纹爬取 Amazon 商品数据。

| 函数 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `search_products(query, limit=10)` | str, int | list[dict] | Amazon 商品搜索 |
| `get_product_details(asin)` | str | dict | Amazon 商品详情 |

### 21.2 代理配置

```python
scraper._proxy = app.config.get('SCRAPING_PROXY') or None
# 国内服务器必须设置海外代理
# SCRAPING_PROXY=http://user:pass@host:port
```

---

## 22. 安全机制

### 22.1 完整安全防护清单

| 防护类型 | 实现方式 | 位置 |
|----------|----------|------|
| **CSRF** | Flask-WTF CSRFProtect，全局所有 POST/PUT/DELETE | `app.py:163` |
| **XSS** | bleach.clean() 白名单过滤（前后台各自独立白名单） | `routes.py`, `admin.py` |
| **SQL 注入** | SQLAlchemy 参数化查询 + 全文搜索特殊字符过滤 | `routes.py:698`, `bili_routes.py` |
| **路径遍历** | os.path.realpath + startswith 检查 | `routes.py:835-838` |
| **登录暴力** | LRU IP 限速，10 次/分钟，每 IP 独立滑动窗口 | `admin.py:311-314` |
| **注册滥用** | 每 IP 每小时最多 3 次 | `admin.py:415-416` |
| **URL 注入** | `_is_safe_url()` 阻止 javascript:/data:/vbscript: | `routes.py:89-111` |
| **图片伪造** | Magic Bytes 校验文件头（PNG/JPEG/GIF/WEBP） | `admin.py:1197-1208` |
| **密钥安全** | SECRET_KEY 自动轮换 + 多密钥 session 兼容 | `config.py`, `app.py:47-97` |
| **响应头** | CSP / HSTS / X-Content-Type-Options / X-Frame-Options | `app.py:316-335` |
| **session 安全** | HttpOnly + SameSite=Lax + Secure（生产环境） | `config.py:206-213` |
| **上传限制** | MAX_CONTENT_LENGTH=200MB + MAX_FORM_MEMORY_SIZE=100MB | `app.py:144-146` |
| **隐私日志** | URL 中 token/secret/key/password 自动脱敏 | `logger.py:201-209` |
| **Worker 隔离** | 独立进程运行，不阻塞 HTTP | `app.py:587-594` |

### 22.2 CSP 策略

```python
Content-Security-Policy:
  default-src 'self'
  script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net
  style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net
  img-src 'self' data: https:
  font-src 'self' https://fonts.gstatic.com
  connect-src 'self'
  frame-ancestors 'self'
```

---

## 23. 进程间通信协议

### 23.1 任务提交流程

```
Flask Web 进程                               Worker 进程
─────────────────                        ────────────────
scrape() route
│
├─ submit_task('refresh_up', mid=123,        │
│   space_url='...', max_videos=30)          │
│   │                                        │
│   ▼                                        │
│   Redis LPUSH hblog:task:queue             │
│   │                                        │
│   mark_running(123)                        │
│   Redis HSET hblog:task:running 123 ts     │
│   │                                        │
│   return {ok:true, mid:123}                │
│                                            │
│  [前端轮询 scrape-status?mid=123]          │
│   │                                        │
│   ▼                                        │
│   Redis GET hblog:task:progress:123        │
│   ← ["[10:30:01] UP主信息获取中...", ...]   │
│   ← running: true                          │
│                                            │
│                                       BRPOP hblog:task:queue
│                                       ← {id, type, data, submitted_at}
│                                       │
│                                       _run_scrape(mid=123, ...)
│                                       │
│                                       update_progress(123, lines)
│                                       Redis SETEX (TTL 1h)
│                                       │
│                                       ... 爬取完成
│                                       │
│                                       mark_done(123)
│                                       Redis HDEL hblog:task:running 123
│
│  [前端轮询 scrape-status?mid=123]
│   ← running: false
│   ← lines: [最终日志]
```

### 23.2 任务 JSON 格式

```python
# 提交端（Flask submit_task）
{
    "id": "a1b2c3d4",           # uuid4()[:8]
    "type": "refresh_up",        # 任务类型
    "data": {                    # 任务参数
        "mid": 12345,
        "space_url": "https://...",
        "max_videos": 30
    },
    "submitted_at": 1743201234.56  # time.time()
}

# 消费端（Worker get_task）
# 完全相同的结构，从 Redis 弹出 (BRPOP 返回值 JSON 解码)
```

### 23.3 实时进度协议

```python
# Worker 进度更新
update_progress(mid, prog_list)  # SETEX hblog:task:progress:{mid} 3600 json

# 进度列表格式
["[10:30:01] [UP主名] UP主信息  |  粉丝: 123,456  |  视频总数: 50",
 "[10:30:08] [UP主名] [补全] (1) 「视频标题」",
 "[10:30:16] [UP主名] [补全] (2) 「视频标题」",
 ...]

# Flask 轮询读取
scrape_status(mid)
├─ redis_lines, redis_running = get_progress(mid)  # 从 Redis 读
├─ local_lines = _scrape_progress.get(mid, [])     # 本地线程降级
├─ local_running = mid in _scrape_running
└─ return {running: bool, lines: list}
```

### 23.4 降级流程

```
┌─ Redis 可用？
│   ├─ Yes → 提交到队列，mark_running Redis HSET
│   │        Worker 消费，update_progress Redis SETEX
│   │        Worker 完成 → mark_done Redis HDEL
│   │
│   └─ No  → 本地线程 _run_scrape()
│            _scrape_running.add(mid)
│            _scrape_progress[mid] = []
│            _run_scrape 直接操作本地状态
│            finally: _scrape_running.discard(mid)
│                     _scrape_progress.pop(mid, None)
```

---

## 24. 定时任务清单

### 24.1 APScheduler 任务

所有定时任务由 Worker 进程的 `_init_scheduler()` 注册：

| 任务 ID | Trigger | 执行时间 | 函数 | 说明 |
|---------|---------|----------|------|------|
| `rotate_secret_key` | cron | 每天 03:00 | `rotate_secret_key(app)` | 生成新密钥，旧密钥移入历史列表 |
| `daily_bili_refresh` | cron | 每天 02:00 | `run_daily_scrape(app)` | 深扫所有 UP 主（分批并发，每批 5 个） |
| `bili_incremental_check` | date + 自调度 | 首次 +10s，后续每轮 +40min | `_run_bili_incremental_check(app)` | 增量检查新视频 |
| `bili_auto_cleanup` | cron | 每天 03:00 | `auto_cleanup_history(app)` | 清理过期历史快照 |
| `daily_wordcloud_recompute` | cron | 每天 02:10 | `precompute_all_wordclouds()` | 重算博客词云 |
| `daily_bili_wordcloud_recompute` | cron | 每天 02:15 | `precompute_bili_wordclouds()` | 重算 B站词云 |

### 24.2 增量检查自调度机制

```python
def _run_bili_incremental_check(app):
    retry_seconds = 30 * 60  # 默认 30 分钟后重试
    
    # ... 执行增量检查 ...
    
    if 'MySQL not reachable' in error:
        retry_seconds = 30  # DB 不可用时 30s 后重试
    
    # 自调度下一轮
    app.scheduler.add_job(
        func=lambda: _run_bili_incremental_check(app),
        trigger='date',
        run_date=datetime.now() + timedelta(seconds=retry_seconds),
        id='bili_incremental_check',
        replace_existing=True,
    )
```

### 24.3 每日深扫并行模型

```python
run_daily_scrape(app):
    ups = BiliUp.query.all()
    for i in range(0, len(ups), _BATCH_SIZE):       # 每批 5 个
        batch = ups[i:i + _BATCH_SIZE]
        threads = []
        for up in batch:
            t = Thread(target=_run_scrape, args=(...), daemon=True)
            t.start()
            threads.append((t, up.mid))
            time.sleep(random.uniform(0.5, 2.0))     # 错开启动
        for t, mid in threads:
            t.join(timeout=15 * 60)                   # 15 分钟超时保护
            if t.is_alive():
                _scrape_running.discard(mid)           # 清理卡死线程
```

---

## 25. 完整 API 端点列表

### 25.1 前台 API（blog_bp）

| 端点 | 方法 | 参数 | 返回 |
|------|------|------|------|
| `GET /` | HTML | `page`, `category`, `per_page` | `index.html` |
| `GET /post/<slug>` | HTML | 路径 | `single-post.html` |
| `POST /post/<slug>` | 表单 | `author_name`, `author_email`, `content` | 重定向到文章页 |
| `GET /post/<slug>/html-frame` | 纯 HTML | 路径 | 内联 HTML + CSP 头 |
| `GET /category/<slug>` | HTML | `page`, `per_page` | `category-grid.html` |
| `GET /about` | HTML | — | `about.html` |
| `GET /contact` | HTML | — | `contact.html` |
| `POST /contact` | 表单 | `name`, `email`, `message` | 重定向到联系页 |
| `GET /tools` | HTML | — | `tools.html` |
| `GET /search` | HTML | `q`(必填), `page`, `per_page` | `index.html` |
| `GET /feed.xml` | XML | — | RSS XML |
| `GET /thumb` | 图片 | `path`, `w`(默认400), `fmt`(默认webp) | 缩略图二进制 |

### 25.2 后台 API（admin_bp）

| 端点 | 方法 | 说明 |
|------|------|------|
| `GET /admin/login` | HTML | 登录页 |
| `POST /admin/login` | 表单 | `username`, `password` |
| `GET /admin/logout` | 重定向 | 登出 |
| `GET /admin/register` | HTML | 注册页 |
| `POST /admin/register` | 表单 | 注册表单 |
| `GET /admin/` | HTML | 仪表盘 |
| `GET /admin/posts` | HTML | 文章列表 |
| `GET /admin/posts/new` | HTML | 新建文章页 |
| `POST /admin/posts/new` | 表单 | 新建文章 |
| `GET /admin/posts/<id>/edit` | HTML | 编辑文章页 |
| `POST /admin/posts/<id>/edit` | 表单 | 更新文章 |
| `POST /admin/posts/<id>/delete` | 重定向 | 删除文章 |
| `GET /admin/categories` | HTML | 分类列表 |
| `GET /admin/categories/new` | HTML | 新建分类页 |
| `POST /admin/categories/new` | 表单 | 创建分类 |
| `GET /admin/categories/<id>/edit` | HTML | 编辑分类页 |
| `POST /admin/categories/<id>/edit` | 表单 | 更新分类 |
| `POST /admin/categories/<id>/delete` | 重定向 | 删除分类 |
| `GET /admin/comments` | HTML | 评论列表 |
| `POST /admin/comments/<id>/approve` | 重定向 | 审核通过 |
| `POST /admin/comments/<id>/delete` | 重定向 | 删除评论 |
| `GET /admin/users` | HTML | 用户列表 |
| `GET /admin/users/new` | HTML | 新建用户页 |
| `POST /admin/users/new` | 表单 | 创建用户 |
| `GET /admin/users/<id>/edit` | HTML | 编辑用户页 |
| `POST /admin/users/<id>/edit` | 表单 | 更新角色 |
| `POST /admin/users/<id>/delete` | 重定向 | 删除用户 |
| `POST /admin/users/<id>/toggle-active` | 重定向 | 禁用/启用 |
| `GET /admin/profile` | HTML | 个人资料页 |
| `POST /admin/profile` | 表单 | 更新资料 |
| `POST /admin/upload-image` | JSON | 图片上传 |
| `GET /admin/featured-cards` | HTML | 卡片列表 |
| `GET /admin/featured-cards/new` | HTML | 新建卡片页 |
| `POST /admin/featured-cards/new` | 表单 | 创建卡片 |
| `GET /admin/featured-cards/<id>/edit` | HTML | 编辑卡片页 |
| `POST /admin/featured-cards/<id>/edit` | 表单 | 更新卡片 |
| `POST /admin/featured-cards/<id>/delete` | 重定向 | 删除卡片 |
| `GET /admin/_bili_debug/<mid>` | JSON | B站 API 诊断 |
| `GET /admin/_debug` | JSON | Session 诊断 |

### 25.3 B站管理 API（bili_bp）

| 端点 | 方法 | 参数 | 返回 |
|------|------|------|------|
| `GET /admin/bilibili/` | HTML | — | UP 主列表 |
| `GET /admin/bilibili/qr-gen` | JSON | — | `{ok, qrcode_key, img(base64)}` |
| `GET /admin/bilibili/qr-poll` | JSON | `key` | 扫码状态 |
| `POST /admin/bilibili/logout-bili` | 重定向 | — | 清空 Cookie |
| `GET /admin/bilibili/up/<up_id>` | HTML | `page` | 视频列表 |
| `POST /admin/bilibili/refresh/<up_id>` | 重定向 | — | 提交刷新任务 |
| `POST /admin/bilibili/refresh-all/<up_id>` | 重定向 | — | 提交全量刷新 |
| `POST /admin/bilibili/up/<up_id>/refresh-comments` | 重定向 | — | 刷新评论 |
| `POST /admin/bilibili/up/<up_id>/refresh-subtitles` | 重定向 | — | 刷新字幕 |
| `POST /admin/bilibili/delete/<up_id>` | 重定向 | — | 删除 UP |
| `POST /admin/bilibili/delete-video/<video_id>` | 重定向 | — | 删除视频 |
| `POST /admin/bilibili/video/<video_id>/watch` | JSON | — | 重点追踪 |
| `POST /admin/bilibili/video/<video_id>/unwatch` | JSON | — | 取消追踪 |
| `GET /admin/bilibili/check-missing` | JSON | — | 视频遗漏检测 |
| `GET /admin/bilibili/scrape-status` | JSON | `mid` | `{running, lines}` |
| `POST /admin/bilibili/scrape` | JSON/重定向 | `space_url` | `{ok, mid, task_id}` |

### 25.4 B站公开 API（bili_public_bp）

| 端点 | 方法 | 参数 | 返回 |
|------|------|------|------|
| `GET /bili` | HTML | — | B站首页 |
| `GET /bili/up/<mid>` | HTML | `page` | UP 主详情 |
| `GET /bili/video/<bvid>` | HTML | — | 视频详情 |
| `GET /bili/search` | HTML | `q`, `page` | 视频搜索 |
| `POST /bili/subscribe` | JSON/重定向 | `email`, `mid` | 创建订阅 |
| `GET /bili/subscribe/verify/<token>` | HTML | 路径 | 验证订阅 |
| `GET /bili/subscribe/unsubscribe/<token>` | HTML | 路径 | 取消订阅 |
| `GET /bili/api/up/<mid>/follower-history` | JSON | — | 粉丝趋势数据 |
| `GET /bili/api/video/<bvid>/stat-history` | JSON | — | 统计数据趋势 |

---

> **文档版本**：v2.0（2026-07-24）
>
> **修改日志**：
> - v2.0: Worker 多线程改造、app.py stderr 重定向修复、技术文档重写
> - v1.0: 初始版本