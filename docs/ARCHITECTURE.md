# Hoshino Blog 详细技术架构文档

> 版本：v2.0（2026-06-30）
> 
> 技术栈：Python 3.12 + Flask 3.x + SQLAlchemy 2.x + MySQL 5.7 + Redis 7.x

---

## 目录

- [一、系统架构总览](#一系统架构总览)
- [二、请求生命周期](#二请求生命周期)
- [三、应用启动流程](#三应用启动流程)
- [四、模块详解](#四模块详解)
- [五、路由表](#五路由表)
- [六、数据库设计](#六数据库设计)
- [七、前端架构](#七前端架构)
- [八、数据流](#八数据流)
- [九、配置系统](#九配置系统)
- [十、安全机制](#十安全机制)
- [十一、错误处理](#十一错误处理)
- [十二、部署运维](#十二部署运维)

---

## 一、系统架构总览

```
┌──────────────────────────────────────────────────────────────┐
│                         Nginx / Caddy                        │  ← 反向代理
└──────────────────────┬───────────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────────┐
│                    Gunicorn / Waitress                        │  ← WSGI 容器
└──────────────────────┬───────────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────────┐
│                    Flask 应用实例 (app.py)                     │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │ CSRF     │  │ Session  │  │ Gzip     │  │ Logging  │     │  ← 中间件
│  │ Protect  │  │ Login    │  │ Compress │  │ Request  │     │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘     │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │                    蓝 图 注 册                        │    │
│  │  ┌──────────┐  ┌──────────┐  ┌───────────────┐      │    │
│  │  │ blog_bp  │  │ admin_bp │  │  price_bp     │      │    │
│  │  │ 前缀: /  │  │前缀:/admin│  │ 前缀: /prices │      │    │
│  │  └────┬─────┘  └────┬─────┘  └──────┬────────┘      │    │
│  └───────┼─────────────┼───────────────┼───────────────┘    │
│          │             │               │                    │
│  ┌───────▼─────────────▼───────────────▼───────────────┐    │
│  │               blog/ 模块目录                        │    │
│  │  routes.py  admin.py  price_routes.py  crawler.py   │    │
│  │  models.py  forms.py  cache.py  logger.py  exa_*   │    │
│  └────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │                    Service Layer                      │    │
│  │  Redis  ─── cache.py  (读写缓存, 降级不阻塞)         │    │
│  │  MySQL  ─── models.py (SQLAlchemy ORM)               │    │
│  │  APScheduler ─── 定时爬虫 / 密钥轮换                 │    │
│  │  Exa API ─── exa_client.py (海外价格搜索)            │    │
│  │  Apify   ─── apify_client.py (Amazon 直爬)           │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

### 层间依赖关系

```
┌──────────────┐
│   Templates  │   ← Jinja2 渲染, 通过蓝图函数引用 url_for()
├──────────────┤
│  Blueprints  │   ← routes.py / admin.py / price_routes.py
├──────────────┤
│   Services   │   ← crawler.py / cache.py / exa_client.py
├──────────────┤
│   ORM / DB   │   ← models.py / MySQL
└──────────────┘
```

---

## 二、请求生命周期

一次 HTTP 请求从进入 Flask 到返回响应的完整路径：

```
1. 客户端请求 → WSGI 服务器
2. WSGI 环境构建 → Flask Request 对象
3. before_request: 无（本应用未注册 before_request，CSRF 由插件隐式处理）
4. 路由匹配 → 调用对应蓝图中的视图函数
5. 视图函数处理（含数据库查询/外部 API/缓存读写）
6. 模板渲染 → Jinja2 生成 HTML
7. after_request: log_request() 记录请求日志
8. Gzip 压缩响应体
9. WSGI 返回 → 客户端
```

### 请求上下文中的可用对象

| 对象 | 来源 | 用途 |
|------|------|------|
| `request` | Flask | 当前 HTTP 请求 |
| `session` | Flask | Session 数据（已签名 Cookie） |
| `g` | Flask | 请求级全局变量（本应用未使用） |
| `current_user` | Flask-Login | 当前登录用户（AnonymousUserMixin 或 User 实例） |
| `current_app` | Flask | 当前 Flask 应用实例 |
| `url_for()` | Flask | 路由反向解析 |
| `csrf_token()` | Flask-WTF | CSRF token 生成（模板中可用） |

---

## 三、应用启动流程

### 完整启动序列（app.py → blog/__init__.py）

```
终端执行 python app.py
  │
  ├─ 1. load_dotenv()                           ← 读取 .env 文件到 os.environ
  │
  ├─ 2. compress = Compress()                   ← Gzip 实例（延迟绑定到 app）
  │
  └─ 3. create_app()                            ← Flask 应用工厂函数
        │
        ├─ 3.1 app = Flask(__name__)
        ├─ 3.2 app.config.from_object('config.ActiveConfig')
        │         ├── SECRET_KEY ← .env 或 .secret_keys 文件
        │         ├── SQLALCHEMY_DATABASE_URI ← DATABASE_URL 或拆分拼接
        │         ├── UPLOAD_FOLDER ← static/uploads/
        │         ├── POSTS_PER_PAGE ← .env 或默认 6
        │         └── BLOG_SUBTITLE ← .env 或硬编码默认值
        │
        ├─ 3.3 CSRFProtect(app)                 ← 全局 CSRF 防护
        ├─ 3.4 app.config['COMPRESS_*']         ← Gzip 级别/阈值配置
        │
        ├─ 3.5 setup_logging(app)               ← 日志系统
        │         ├── 文件处理器 → blog/logs/hoshino.log（每日轮转）
        │         ├── 错误处理器 → blog/logs/error.log
        │         └── 终端处理器（开发模式）
        │
        ├─ 3.6 os.makedirs(UPLOAD_FOLDER)       ← 确保上传目录存在
        │
        ├─ 3.7 init_db(app)                     ← 数据库初始化
        │    ├── db.init_app(app)
        │    ├── db.create_all()                ← 建表（IF NOT EXISTS）
        │    ├── _migrate_category_to_many2many()
        │    │   └── 检测旧版单分类→多对多迁移
        │    ├── 创建默认管理员
        │    └── _migrate_featured_icon()
        │        └── ALTER TABLE featured_cards MODIFY icon VARCHAR(256)
        │
        ├─ 3.8 init_redis(app)                  ← Redis 连接池
        │         └── REDIS_URL 为空时降级（stub 不报错）
        │
        ├─ 3.9 ExaClient 初始化                 ← 启动时获取汇率
        ├─ 3.10 APScheduler 定时任务
        │         ├── 09:00 → crawl_all_active_sources()
        │         └── 03:00 → rotate_secret_key()
        │
        ├─ 3.11 LoginManager                    ← Flask-Login 配置
        │         ├── login_view = 'admin.login'
        │         └── @login_manager.user_loader
        │
        ├─ 3.12 注册蓝图
        │         ├── blog_bp   → /         (routes.py)
        │         ├── admin_bp  → /admin    (admin.py)
        │         └── price_bp  → /prices   (price_routes.py)
        │
        ├─ 3.13 compress.init_app(app)          ← 启用 Gzip
        ├─ 3.14 app.after_request(log_request)  ← 请求日志中间件
        │
        └─ 3.15 return app
```

---

## 四、模块详解

### 4.1 `app.py` — 应用入口

**路径：** `/hoshino_blog/app.py`

**职责：** 创建 Flask 应用实例，组装所有子系统。

**关键函数：**

| 函数 | 用途 |
|------|------|
| `create_app()` | 应用工厂，返回配置好的 Flask 实例 |
| `_init_scheduler(app)` | 初始化 APScheduler 定时任务 |

**导入的模块：**
- `flask` — Flask 核心
- `flask_compress` — Gzip 压缩
- `flask_login` — 登录管理
- `flask_wtf.csrf` — CSRF 防护
- `dotenv` — .env 文件加载
- `blog.*` — 内部模块（日志/数据库/缓存/路由）

**外部依赖：** 无（仅 Flask 扩展）

---

### 4.2 `config.py` — 配置中心

**路径：** `/hoshino_blog/config.py`

**职责：** 集中管理所有 Flask 配置项，支持 .env 覆盖。

**核心类：** `Config`

**子功能：**
- `SECRET_KEY` 管理：.env 固定值或文件自动轮换
- `_build_database_uri()`：自动拼接 DATABASE_URL
- `rotate_secret_key()`：运行时轮换密钥

**配置分组：**

| 分组 | 配置项 | 默认值 | 来源 |
|------|--------|--------|------|
| Flask 核心 | `SECRET_KEY` | 自动生成 | `.env` 或 `.secret_keys` |
| Session | `SESSION_COOKIE_*` | HTTPOnly/Lax/Secure | `.env` 可选覆盖 |
| 数据库 | `SQLALCHEMY_DATABASE_URI` | 拼装 | `DATABASE_URL` 或拆分变量 |
| 上传 | `UPLOAD_FOLDER` | `static/uploads/` | 固定 |
| 上传 | `MAX_CONTENT_LENGTH` | 16MB | `.env` |
| 分页 | `POSTS_PER_PAGE` | 6 | `.env` |
| 分页 | `PER_PAGE_OPTIONS` | [6,12,24,48] | 自动包含 `POSTS_PER_PAGE` |
| 副标题 | `BLOG_SUBTITLE` | 硬编码 | `.env` |
| 主题 | `DEFAULT_THEME` | dark | `.env` |
| 管理员 | `ADMIN_*` | admin/CHANGE_ME | `.env` |
| Redis | `REDIS_URL` | None | `.env` |
| 缓存 TTL | `CACHE_TTL_*` | 300/60/600 | `.env` |
| 代理 | `SCRAPING_PROXY` | '' | `.env` |
| Exa | `EXA_API_KEY` | '' | `.env` |

---

### 4.3 `blog/__init__.py` — 应用工厂

**路径：** `/hoshino_blog/blog/__init__.py`

**职责：** 数据库初始化、蓝图声明、迁移逻辑。

**关键对象：**

| 对象 | 类型 | 用途 |
|------|------|------|
| `db` | `SQLAlchemy` | ORM 实例（延迟绑定） |
| `blog_bp` | `Blueprint` | 前台路由容器 |
| `admin_bp` | `Blueprint` | 后台路由容器 |
| `price_bp` | `Blueprint` | 价格追踪路由容器 |

**关键函数：**

| 函数 | 调用时机 | 用途 |
|------|----------|------|
| `init_db(app)` | 启动时 | 建表 + 迁移 + 默认管理员 |
| `_migrate_category_to_many2many(app)` | 首次启动 | 检测旧版 `category_id` 字段，迁移到多对多 |
| `_migrate_featured_icon(app)` | 首次启动 | MySQL 专用：ALTER 表字段长度 |

**导入结构（防止循环引用）：**
```
1. db = SQLAlchemy()           ← 无依赖
2. 声明 3 个 Blueprint         ← 无依赖
3. init_db() 定义              ← 依赖 db
4. import models               ← 依赖 db
5. import admin / routes / price_routes ← 依赖 models
```

---

### 4.4 `blog/models.py` — 数据模型

**路径：** `/hoshino_blog/blog/models.py`

**职责：** 定义所有 ORM 模型类和关联表。

**关联表：**

| 表名 | 用途 | 关联 |
|------|------|------|
| `post_categories` | Post ↔ Category 多对多 | post_id → posts.id, category_id → categories.id |

**模型类：**

| 类 | 表名 | 行数参考 | 关键字段 | 关系 |
|---|------|---------|---------|------|
| `User` | `users` | 1 | username, email, password_hash, is_admin | 1:N → Post |
| `Post` | `posts` | 100 | title, slug, content, is_published | N:1 → User; N:M → Category |
| `Category` | `categories` | 13 | name, slug | N:M → Post |
| `Comment` | `comments` | 173 | author_name, content, is_approved | N:1 → Post |
| `Product` | `products` | 0+ | name, brand, specs(JSON) | 1:N → ProductSource |
| `ProductSource` | `product_sources` | 0+ | site, url | N:1 → Product; 1:N → PriceRecord |
| `PriceRecord` | `price_records` | 0+ | price | N:1 → ProductSource |
| `FeaturedCard` | `featured_cards` | 6 | title, icon, tag, sort_order | 无外键（tag 逻辑关联 Category.slug） |
| `ExchangeRate` | `exchange_rates` | ~3×天数 | currency, rate | 无外键 |

**模型关系图：**

```
User ──1:N──→ Post ──N:M──→ Category
                │
                1:N
                │
                ↓
              Comment

Product ──1:N──→ ProductSource ──1:N──→ PriceRecord
```

---

### 4.5 `blog/routes.py` — 前台路由

**路径：** `/hoshino_blog/blog/routes.py`

**职责：** 所有公开页面的路由处理。

**蓝图：** `blog_bp`

**辅助函数：**

| 函数 | 用途 |
|------|------|
| `_get_sidebar_data()` | 查询侧边栏 widget 数据（分类列表 + 近期文章），结果走 Redis 缓存 |

**路由视图函数（见第五章路由表）**

**模板变量约定：**

| 变量名 | 来源 | 用途 | 出现页面 |
|--------|------|------|----------|
| `posts` | `Post.query.paginate()` | 分页文章列表 | index, category |
| `categories` | `Category.query.all()` | 侧边栏分类列表 | 所有页面 (via `_sidebar.html`) |
| `recent_posts` | `Post.query.limit(8)` | 侧边栏近期文章 | 所有页面 |
| `featured_cards` | `FeaturedCard.query.filter_by(is_active=True)` | 首页特色卡片 | index |
| `cat_lookup` | `{c.slug: c.name}` | tag slug 转中文名 | index |
| `blog_subtitle` | `config['BLOG_SUBTITLE']` | 英雄区副标题 | index |
| `current_per_page` | URL 参数或 config | 每页文章数 | index |
| `per_page_options` | `config['PER_PAGE_OPTIONS']` | 分页选择器选项 | index |

---

### 4.6 `blog/admin.py` — 后台管理路由

**路径：** `/hoshino_blog/blog/admin.py`

**职责：** 所有后台管理页面的路由处理。

**蓝图：** `admin_bp`，前缀 `/admin`

**装饰器：**

| 装饰器 | 用途 | 来源 |
|--------|------|------|
| `@login_required` | 要求登录 | `flask_login` |
| `@admin_required` | 要求管理员权限 | `functools.wraps` + `current_user.is_admin` |

**路由分组：**

```
/admin/
├── login / logout                    ← 无需认证
├── dashboard (/)                     ← admin_required
├── posts/                            ← admin_required
│   ├── (list)
│   ├── new (create)
│   ├── <id>/edit
│   └── <id>/delete
├── categories/                       ← admin_required
│   ├── (list)
│   ├── new
│   ├── <id>/edit
│   └── <id>/delete
├── comments/                         ← admin_required
│   ├── (list)
│   ├── <id>/approve
│   └── <id>/delete
├── users/                            ← admin_required
│   ├── (list)
│   ├── new
│   ├── <id>/edit
│   └── <id>/delete
├── featured-cards/                   ← admin_required
│   ├── (list)
│   ├── new
│   ├── <id>/edit
│   └── <id>/delete
├── profile                           ← login_required
└── upload-image                      ← login_required
```

**特色卡片 CRUD 流程：**

```
创建卡片 → 检查 Category 是否存在 → 否 → 跳转到分类创建页
                                   ↓ 是
                        表单渲染 (tag 下拉读取 Category)
                                   ↓
                        validate_on_submit → 通过 → db.session.add → redirect
                                           ↓ 失败
                        闪现表单错误 → 重新渲染
```

---

### 4.7 `blog/price_routes.py` — 价格追踪

**路径：** `/hoshino_blog/blog/price_routes.py`

**蓝图：** `price_bp`，前缀 `/prices`

**路由：**

| 路由 | GET | POST | 功能 |
|------|-----|------|------|
| `/prices/` | ✓ | | 价格看板（所有商品） |
| `/prices/<id>` | ✓ | | 商品详情 + 价格图表 |
| `/prices/<id>/add-source` | | ✓ | 添加来源站点 |
| `/prices/<id>/manual-price` | | ✓ | 手动录入价格 |
| `/prices/add-product` | | ✓ | 添加新商品 |
| `/prices/rates` | ✓ | | 汇率查询页面 |

**数据流：**
```
启动时 ExaClient 获取实时汇率 → 存入 exchange_rates 表
每天 09:00 APScheduler → crawl_all_active_sources()
    → 遍历所有 ProductSource
    → 对于每个 source:
        如果是 Amazon → apify_client 爬取
        否则 → crawler._crawl_generic()
    → 提取价格 → PriceRecord 存库
```

---

### 4.8 `blog/forms.py` — 表单定义

**路径：** `/hoshino_blog/blog/forms.py`

**职责：** 所有 WTForms 表单类定义。

**表单类：**

| 表单 | 字段 | 用途 |
|------|------|------|
| `LoginForm` | username, password | 管理员登录 |
| `PostForm` | title, slug, summary, content, cover_image, categories(SelectMultiple), is_published | 文章编辑 |
| `CategoryForm` | name, slug, description | 分类编辑 |
| `CommentForm` | author_name, author_email, content | 访客评论 |
| `ContactForm` | name, email, subject, message | 联系页面 |
| `UserForm` | username, email, password, display_name, bio, avatar, is_admin | 用户编辑 |
| `ProfileForm` | email, display_name, bio | 个人资料编辑 |
| `FeaturedCardForm` | title, description, icon, tag(SelectField), link, image_url, sort_order, is_active | 特色卡片编辑 |

---

### 4.9 `blog/cache.py` — 缓存层

**路径：** `/hoshino_blog/blog/cache.py`

**职责：** 封装 Redis 缓存操作，支持优雅降级。

**核心函数：**

| 函数 | 用途 |
|------|------|
| `init_redis(app)` | 创建 Redis 连接池（连接失败时返回 stub） |
| `cache_get(key)` | 读取缓存，不存在返回 None |
| `cache_set(key, value, ttl)` | 写入缓存 |
| `cache_delete(key)` | 删除缓存 |
| `cache_exists(key)` | 检查 key 是否存在 |

**降级策略：** Redis 不可用时所有操作返回 None/False，不抛异常。

---

### 4.10 `blog/logger.py` — 日志系统

**路径：** `/hoshino_blog/blog/logger.py`

**职责：** 配置并初始化日志系统 + 请求日志中间件。

**日志文件：**

| 文件 | 路径 | 轮转策略 | 级别 |
|------|------|----------|------|
| 主日志 | `blog/logs/hoshino.log` | 每天轮转，保留 30 天 | INFO+ |
| 错误日志 | `blog/logs/error.log` | 每天轮转，保留 30 天 | WARNING+ |

**`log_request(response)`：** 在 `app.after_request` 注册，记录：
- 请求方法、路径、状态码
- 客户端 IP、User-Agent
- 响应内容长度
- 请求处理时间
- 状态码分级：2xx=INFO, 3xx=INFO, 4xx=WARNING, 5xx=ERROR

---

### 4.11 `blog/crawler.py` — 价格爬虫

**路径：** `/hoshino_blog/blog/crawler.py`

**职责：** 多源价格爬取引擎。

**关键函数：**

| 函数 | 用途 |
|------|------|
| `crawl_all_active_sources()` | 遍历所有活跃 ProductSource 并爬取/提取价格 |
| `_crawl_amazon(source)` | 通过 apify_client 爬 Amazon |
| `_crawl_generic(source)` | 通用爬取（requests + BeautifulSoup） |
| `init_sample_products()` | 首次运行时写入示例商品 |

---

### 4.12 `blog/exa_client.py` — Exa 搜索引擎

**路径：** `/hoshino_blog/blog/exa_client.py`

**职责：** Exa AI 搜索引擎 HTTP 客户端（搜索海外电商价格）。

**类：** `ExaClient`

| 方法 | 用途 |
|------|------|
| `__init__(api_key)` | 初始化客户端 + 获取汇率 |
| `search(query, num_results)` | Exa 搜索 |
| `get_rates()` | 获取 USD/EUR/GBP → CNY 汇率 |
| `_fetch_rates()` | 内部：调用 Exa API 搜索汇率数据 |

---

### 4.13 `blog/bilibili/` — B站 视频爬取模块

**路径：** `/hoshino_blog/blog/bilibili/`

**职责：** B站 API 封装、视频爬取调度、Cookie 凭证管理、V2 扫码登录认证。

#### 4.13.1 `bili_api.py` — 核心 API 封装

**关键函数：**

| 函数 | 用途 | 使用 B站 API |
|------|------|-------------|
| `_sync(coro)` | 线程本地事件循环，`Semaphore(5)` 并发限制，30s 超时 | - |
| `get_user_info(mid)` | 名称/头像/粉丝数/视频数 | `x/space/wbi/acc/info` + `x/relation/stat`（粉丝数 fallback） |
| `get_video_list(mid)` | 分页视频列表（pubdate 倒序，风控退避 + Cookie 过期降级） | `x/space/wbi/arc/search` |
| `get_video_stat(bvid)` | 视频统计（播放/点赞/投币/收藏/转发/评论/弹幕） | `Video.get_info()` |
| `get_video_list_from_dynamics(mid)` | 动态发现 — 从用户动态流提取 BVID，捕获 shorts/新视频 | `x/polymer/web-dynamic/v1/feed/space` |
| `extract_mid(url)` | 从空间 URL 提取 mid | - |
| `is_logged_in()` | 检查凭证有效性 | `Credential.verify()` |

**错误降级策略：**

```
凭证存在 → User(mid, credential=cred) 调用 API
    ↓ 失败
_is_auth_error? → 是 → 降级为匿名 User(mid) → 重试
                → 否 → _is_risk_control? → 指数退避重试（30→60→120→…→600s）
                       → 其他错误 → 记录日志，中断
```

**视频发现双路径：**

```
1. arc/search 翻页（主路径）
   → 按 pubdate 倒序，已知视频 skip，新视频入库

2. 动态兜底（始终执行，不依赖 arc/search 结果）
   → get_dynamics_new() → 提取 DYNAMIC_TYPE_AV + forward 的 orig
   → Video.get_info() → 验证 owner_mid == 目标 mid
   → 新视频入库
```

#### 4.13.2 `config.py` — B站 配置

| 常量 | 默认值 | 用途 |
|------|--------|------|
| `REQUEST_INTERVAL` | 5.0s | 翻页间隔 |
| `PAGE_SIZE` | 15 | 每页视频数 |
| `TIMEOUT` | 15s | HTTP 请求超时（login.py 使用） |
| `COOKIE_FILE` | `.bili_cookies.txt` | Cookie 持久化路径 |
| `CREDENTIAL_FILE` | `.bili_credential.json` | 完整 Credential（含 refresh_token） |

#### 4.13.3 `login.py` — 登录认证

| 函数 | 用途 |
|------|------|
| `generate_qr_v2()` | V2 扫码登录 → 生成二维码（base64 PNG） |
| `poll_qr_v2(key)` | 轮询扫码状态（等待→已扫码→已确认→过期） |
| `apply_cookies()` | 启动时加载持久化凭证（优先 `.bili_credential.json`） |
| `save_credential(cred)` | 保存完整 Credential JSON（含 refresh_token，支持自动续期） |
| `save_cookies(str)` | 保存 Cookie 字符串（`SESSDATA= ...` 格式，向后兼容） |

#### 4.13.4 `bili_routes.py` — 爬取调度

**核心函数：**

| 函数 | 用途 |
|------|------|
| `_check_new_videos(mid, app)` | 增量检查 — arc/search 前 10 页 + 动态兜底 + 最新 3 视频跟踪 |
| `_run_scrape(mid, url, app)` | 深扫 — 补全 + 动态兜底 + Hot/Warm/Cold 三层统计更新 |

**三层统计更新策略：**

| 分层 | 时间范围 | 跳过条件 | 配额 |
|------|---------|---------|------|
| Hot | ≤7天 | 不跳过 | 全部处理 |
| Warm | 8~30天 | 1h 内已更新则跳过 | 配额内，最久未更新优先 |
| Cold | >30天 | 24h 内已更新则跳过 | 剩余配额，最久未更新优先 |

**共享状态（线程安全）：**

| 变量 | 类型 | 用途 |
|------|------|------|
| `_scrape_running` | `set[int]` | 深扫运行中的 mid |
| `_incremental_running` | `set[int]` | 增量检查运行中的 mid |
| `_scrape_progress` | `dict[int,list[str]]` | 爬取进度日志 |
| `_scrape_lock` | `threading.Lock` | 保护上述三个共享状态 |

### 4.14 B站 定时任务（app.py 调度）

| 任务 | 触发时间 | 线程超时 | 说明 |
|------|---------|---------|------|
| `_run_bili_incremental_check` | 每 30 分钟 | 10 分钟/UP | 对所有 UP 主并行增量检查 |
| `_run_daily_bili_refresh` | 每天 02:00 | 15 分钟/UP | 所有 UP 主深扫（补全 + 三层更新） |
| `_clean_bili_history` | 每天 04:00 | - | 删除 365 天前的历史快照 |

**互斥保护：** 两个定时任务启动线程前在同一 `_scrape_lock` 下同时检查 `_scrape_running` 和 `_incremental_running`，同一 UP 主不会并发处理。

---

## 五、路由表

### 5.1 前台路由（blog_bp — 前缀: `/`）

| 路由 | 方法 | 视图函数 | 模板 | 认证 | 说明 |
|------|------|----------|------|------|------|
| `/` | GET | `index` | `index.html` | 无 | 首页：分页文章 + 特色卡片 + 分类筛选 |
| `/post/<slug>` | GET, POST | `single_post` | `single-post.html` | POST 无需认证 | 文章详情 + 评论提交 |
| `/category/<slug>` | GET | `category` | `index.html` | 无 | 按分类筛选 |
| `/about` | GET | `about` | `about.html` | 无 | 关于页面 |
| `/contact` | GET, POST | `contact` | `contact.html` | 无 | 联系表单 |
| `/search` | GET | `search` | `index.html` | 无 | 文章搜索 |
| `/feed.xml` | GET | `rss_feed` | XML 直出 | 无 | RSS 2.0 输出 |
| `/sitemap.xml` | GET | `sitemap` | XML 直出 | 无 | SEO Sitemap |
| `/tools` | GET | `tools` | `tools.html` | 无 | 工具集页面 |
| `/thumb` | GET | `thumbnail` | 图片直出 | 无 | 缩放图片输出 |

### 5.2 后台路由（admin_bp — 前缀: `/admin`）

| 路由 | 方法 | 视图函数 | 模板 | 认证 | 说明 |
|------|------|----------|------|------|------|
| `/admin/login` | GET, POST | `login` | `admin/login.html` | 无 | 管理员登录 |
| `/admin/logout` | GET | `logout` | 重定向 | 登录 | 登出 → 首页 |
| `/admin/` | GET | `dashboard` | `admin/dashboard.html` | admin | 仪表盘（缓存 60s） |
| `/admin/posts` | GET | `post_list` | `admin/post-list.html` | admin | 文章列表（分页 20/页） |
| `/admin/posts/new` | GET, POST | `new_post` | `admin/post-form.html` | admin | 新建文章 |
| `/admin/posts/<id>/edit` | GET, POST | `edit_post` | `admin/post-form.html` | admin | 编辑文章 |
| `/admin/posts/<id>/delete` | POST | `delete_post` | 重定向 | admin | 删除文章 |
| `/admin/categories` | GET | `category_list` | `admin/category-list.html` | admin | 分类列表 |
| `/admin/categories/new` | GET, POST | `new_category` | `admin/category-form.html` | admin | 新建分类 |
| `/admin/categories/<id>/edit` | GET, POST | `edit_category` | `admin/category-form.html` | admin | 编辑分类 |
| `/admin/categories/<id>/delete` | POST | `delete_category` | 重定向 | admin | 删除分类 |
| `/admin/comments` | GET | `comment_list` | `admin/comment-list.html` | admin | 评论列表 |
| `/admin/comments/<id>/approve` | POST | `approve_comment` | 重定向 | admin | 审核通过 |
| `/admin/comments/<id>/delete` | POST | `delete_comment` | 重定向 | admin | 删除评论 |
| `/admin/users` | GET | `user_list` | `admin/user-list.html` | admin | 用户列表 |
| `/admin/users/new` | GET, POST | `new_user` | `admin/user-form.html` | admin | 新建用户 |
| `/admin/users/<id>/edit` | GET, POST | `edit_user` | `admin/user-form.html` | admin | 编辑用户 |
| `/admin/users/<id>/delete` | POST | `delete_user` | 重定向 | admin | 删除用户（不能删自己） |
| `/admin/featured-cards` | GET | `featured_card_list` | `admin/featured-card-list.html` | admin | 特色卡片列表 |
| `/admin/featured-cards/new` | GET, POST | `new_featured_card` | `admin/featured-card-form.html` | admin | 新建特色卡片 |
| `/admin/featured-cards/<id>/edit` | GET, POST | `edit_featured_card` | `admin/featured-card-form.html` | admin | 编辑特色卡片 |
| `/admin/featured-cards/<id>/delete` | POST | `delete_featured_card` | 重定向 | admin | 删除特色卡片 |
| `/admin/profile` | GET, POST | `profile` | `admin/profile.html` | 登录 | 个人资料编辑 |
| `/admin/upload-image` | POST | `upload_image` | JSON 返回 | 登录 | RTE 图片上传 |

### 5.3 价格路由（price_bp — 前缀: `/prices`）

| 路由 | 方法 | 视图函数 | 模板 | 认证 | 说明 |
|------|------|----------|------|------|------|
| `/prices/` | GET | `price_dashboard` | `price/dashboard.html` | 无 | 价格看板 |
| `/prices/<id>` | GET | `price_detail` | `price/detail.html` | 无 | 商品详情 + 图表 |
| `/prices/<id>/add-source` | POST | `add_source` | 重定向 | 无 | 添加来源 |
| `/prices/<id>/manual-price` | POST | `manual_price` | 重定向 | 无 | 手动录入 |
| `/prices/add-product` | POST | `add_product` | 重定向 | 无 | 添加商品 |
| `/prices/rates` | GET | `exchange_rates` | `price/rates.html` | 无 | 汇率页面 |

### 5.4 Bilibili 后台路由（bili_bp — 前缀: `/admin/bilibili`）

| 路由 | 方法 | 视图函数 | 认证 | 说明 |
|------|------|----------|------|------|
| `/admin/bilibili/` | GET | `index` | editor | UP 主管理列表（含扫码登录入口） |
| `/admin/bilibili/scrape` | POST | `scrape` | editor | 启动爬取（Ajax，解析 space_url → 后台线程） |
| `/admin/bilibili/scrape-status?mid=` | GET | `scrape_status` | editor | 爬取进度实时 JSON |
| `/admin/bilibili/qr-gen` | GET | `qr_generate` | editor | 生成 V2 登录二维码（base64 PNG） |
| `/admin/bilibili/qr-poll?key=` | GET | `qr_poll` | editor | 轮询扫码状态 |
| `/admin/bilibili/logout-bili` | POST | `logout_bili` | editor | 清除 Cookie/Credential 文件 |
| `/admin/bilibili/up/<up_id>` | GET | `up_detail` | editor | UP 主视频表格（分页 30/页） |
| `/admin/bilibili/refresh/<up_id>` | POST | `refresh_up` | editor | 刷新单 UP（限 30 视频） |
| `/admin/bilibili/refresh-all/<up_id>` | POST | `refresh_up_all` | editor | 强制刷新全部（无配额） |
| `/admin/bilibili/delete/<up_id>` | POST | `delete_up` | editor | 删除 UP 主及所有视频 |
| `/admin/bilibili/delete-video/<id>` | POST | `delete_video` | editor | 删除单条视频 |
| `/admin/bilibili/check-missing` | GET | `check_missing` | editor | 遗漏检查 JSON |

### 5.5 Bilibili 公开路由（bili_public_bp — 前缀: `/bilibili`）

| 路由 | 方法 | 视图函数 | 认证 | 说明 |
|------|------|----------|------|------|
| `/bilibili` | GET | `bili_index` | 无 | UP 主列表（支持搜索） |
| `/bilibili/up/<id>` | GET | `bili_up_detail` | 无 | UP 主视频列表 + 粉丝趋势图 |
| `/bilibili/video/<id>` | GET | `bili_video_detail` | 无 | 视频详情 + 播放量趋势图 |
| `/bilibili/api/video/<id>/history` | GET | `bili_video_history` | 无 | 视频历史统计 JSON API |

---

## 六、数据库设计

### 6.1 ER 关系

```
┌──────────┐      ┌───────────────────┐      ┌──────────────┐
│   User   │ 1:N  │      Post         │ N:M  │   Category   │
│  users   │──────│     posts         │──────│  categories  │
├──────────┤      ├───────────────────┤      ├──────────────┤
│ id (PK)  │      │ id (PK)           │      │ id (PK)      │
│ username │      │ title             │      │ name         │
│ email    │      │ slug (UQ, IDX)    │      │ slug (UQ,IDX)│
│ password │      │ summary           │      │ description  │
│ is_admin │      │ content           │      └──────────────┘
│ avatar   │      │ cover_image       │
└──────────┘      │ author_id (FK)    │ 1:N  ┌──────────────┐
                  │ is_published      │      │   Comment    │
                  │ created_at        │──────│   comments   │
                  └───────────────────┘      ├──────────────┤
                                             │ id (PK)      │
┌──────────────┐  ┌───────────────────┐      │ post_id (FK) │
│   Product    │  │  ProductSource    │ 1:N  │ author_name  │
│   products   │  │ product_sources   │──────│ content      │
├──────────────┤  ├───────────────────┤      │ is_approved  │
│ id (PK)      │  │ id (PK)           │      └──────────────┘
│ name         │  │ product_id (FK)   │
│ brand        │  │ site              │      ┌──────────────┐
│ specs (JSON) │  │ url               │      │ FeaturedCard │
└──────────────┘  │ latest_price      │      │featured_cards│
                  └─────────┬─────────┘      ├──────────────┤
                            │ 1:N            │ id (PK)      │
                  ┌─────────▼─────────┐      │ title        │
                  │   PriceRecord     │      │ icon         │
                  │  price_records    │      │ tag          │
                  ├───────────────────┤      │ link         │
                  │ id (PK)           │      │ sort_order   │
                  │ source_id (FK)    │      │ is_active    │
                  │ product_id (FK)   │      └──────────────┘
                  │ price             │
                  │ recorded_at (IDX) │      ┌──────────────┐
                  └───────────────────┘      │ ExchangeRate │
                                             │exch_rates   │
                                             ├──────────────┤
                                             │ currency(IDX)│
                                             │ rate         │
                                             │ recorded_at  │
                                             └──────────────┘
```

### 6.2 B站 数据模型

```
┌───────────────────────────────────────────────┐
│  BiliUp                                       │
├───────────────────────────────────────────────┤
│  id (PK) · mid · name · avatar · space_url   │
│  follower_count · video_count                 │
│  created_at · updated_at                      │
└───────────────────┬───────────────────────────┘
                    │ 1:N
                    │
┌───────────────────▼───────────────────────────┐
│  BiliVideo                                    │
├───────────────────────────────────────────────┤
│  id (PK) · up_id (FK) · bvid · aid(UNIQUE)   │
│  title · description · duration · pubdate     │
│  pub_date · pub_datetime                      │
│  view_count · like_count · coin_count         │
│  favorite_count · share_count                 │
│  comment_count · danmaku_count                │
│  created_at · updated_at                      │
└───────────────────┬───────────────────────────┘
                    │ 1:N
                    │
┌───────────────────▼───────────────────────────┐
│  BiliVideoHistory                             │
├───────────────────────────────────────────────┤
│  id (PK) · video_id (FK) · view_count        │
│  like_count · coin_count · favorite_count    │
│  share_count · comment_count · danmaku_count  │
│  recorded_at                                  │
└───────────────────────────────────────────────┘

┌───────────────────────────────────────────────┐
│  BiliUpHistory                                │
├───────────────────────────────────────────────┤
│  id (PK) · up_id (FK) · follower_count       │
│  recorded_at                                  │
└───────────────────────────────────────────────┘
```

**索引策略 (B站)：**

| 表 | 索引 | 用途 |
|------|------|------|
| `bili_videos` | `(up_id, pub_datetime)` 复合索引 | 按 UP 主 + 时间查询 |
| `bili_videos` | `(up_id, updated_at)` 复合索引 | Warm/Cold 阶段按最久未更新排序 |
| `bili_videos` | `aid` UNIQUE | aid 去重 |
| `bili_video_history` | `(video_id, recorded_at)` 复合索引 | 视频历史查询 |
| `bili_up_history` | `(up_id, recorded_at)` 复合索引 | UP 主粉丝趋势 |

### 6.3 关联表

```sql
-- Post ↔ Category 多对多
CREATE TABLE post_categories (
    post_id INTEGER NOT NULL,
    category_id INTEGER NOT NULL,
    FOREIGN KEY(post_id) REFERENCES posts(id),
    FOREIGN KEY(category_id) REFERENCES categories(id),
    PRIMARY KEY(post_id, category_id)
);
```

### 6.3 FeaturedCard 特殊设计

`FeaturedCard` 的 `tag` 字段是**逻辑外键**——它存储 `Category.slug` 的值，但没有数据库级别的 FOREIGN KEY 约束。这种方式允许卡片在不同分类间切换而不需要迁移数据库：

```
FeaturedCard.tag = "anime"
    ↓ 渲染时查询
cat_lookup = {"anime": "二次元", "digital": "数码", "military": "军事"}
    ↓ 模板中显示
<span class="featured-card-tag tag-anime">二次元</span>
```

### 6.4 索引策略

| 表 | 索引字段 | 类型 | 用途 |
|------|---------|------|------|
| users | username | UNIQUE | 登录查询 |
| users | email | UNIQUE | 登录/邮箱查重 |
| posts | slug | UNIQUE | URL 路由 |
| categories | slug | UNIQUE | URL 路由 |
| product_sources | product_id | INDEX | 按商品查来源 |
| price_records | source_id | INDEX | 按来源查价格历史 |
| price_records | product_id + recorded_at | INDEX(复合) | 价格图表查询 |
| exchange_rates | currency + recorded_at | INDEX(复合) | 汇率趋势查询 |
| featured_cards | sort_order | INDEX | 首页排序 |

---

## 七、前端架构

### 7.1 模板继承树

```
base.html                          ← 基础骨架（导航/光晕/灯箱/页脚/JS）
├── index.html                     ← 首页（特色卡片 + 文章列表）
├── single-post.html               ← 文章详情
├── about.html                     ← 关于页
├── contact.html                   ← 联系页
├── category-grid.html             ← 分类页
├── tools.html                     ← 工具集
├── _sidebar.html                  ← 侧边栏组件（被 base 通过 include 引入）
├── price/
│   ├── dashboard.html             ← 价格看板
│   ├── detail.html                ← 价格详情
│   └── rates.html                 ← 汇率页
└── admin/
    └── base_admin.html            ← 后台布局（独立于 base.html）
        ├── dashboard.html
        ├── login.html
        ├── post-form.html
        ├── post-list.html
        ├── category-form.html
        ├── category-list.html
        ├── comment-list.html
        ├── user-form.html
        ├── user-list.html
        ├── profile.html
        ├── featured-card-form.html
        └── featured-card-list.html
```

### 7.2 前台模板变量注入

所有前台页面均可访问以下变量（通过 sidebase widget 的渲染函数注入）：

```
categories   → Category.query.all()  (可缓存)
recent_posts → Post.query.limit(8)   (可缓存)
site_name    → 默认 'Hoshino'
format_date  → 日期格式化函数
now          → datetime.utcnow 函数
```

### 7.3 Glow Design System（CSS 架构）

```
glow-design.css （~1270 行）
├── 0. CSS Variables             色板/间距/阴影体系
├── 1. 全局基础                   Reset + 盒模型
├── 2. 背景光晕                   glow-bg + glow-orb 动画
├── 3. 导航栏                     navbar 固定定位 + 毛玻璃
├── 4. 英雄区                     hero + highlight 渐变
├── 4b. 特色卡片                  featured-grid + featured-card
├── 5. 内容区                     .content 容器
├── 6. 瀑布流                     masonry CSS columns
├── 7. 玻璃卡片                   glass-card 光效
├── 8. 标签                       pill-light
├── 9. 表单                       form-group 输入框
├── 9b. 自定义下拉框              glow-select-wrap
├── 10. 按钮                      btn / btn-primary / btn-danger
├── 11. 侧边栏                    widget / profile / search / tags
├── 12. 分页                      pagination
├── 13. 文章详情                  post-detail / post-content
├── 14. 评论区                    comment-item / comment-form
├── 15. 空状态                    empty-state
├── 16. 静态页面                  page-content
├── 17. 提示消息                  flash / alert
├── 18. 徽章                      badge
├── 19. 后台管理布局              admin-sidebar / admin-table
├── 20. Price 卡片                price-card
├── 21. Price 详情                price-table / chart
├── 22. 工具页面                  tools-nav / tools-card
├── 23. 工具标签                  tool-tab
├── 24. 入场动画                  fadeInUp keyframes
├── 25. 布局系统                  container / row / col
├── 26. 页脚                      footer
├── 27. 页面头部                  page-header
├── 28. 价格统计                  price-stat-card
├── 29. 来源卡片                  source-card / detail
├── 30. 价格看板                  product-grid
├── 31. 响应式                    @media max-width:640px / 768px
└── 31b. 移动端抽屉               mobile-drawer / drawer-overlay
```

### 7.4 Glow Controller（JS 架构）

```
glow-controller.js （~440 行）
├── 1. 鼠标光效追踪              IIFE → requestAnimationFrame → CSS vars
│   ├── CONFIG                   maxDist / opacityMin / opacityMax
│   ├── mousemove handler        更新 mouseX/mouseY
│   ├── updateGlow()             距离计算 → opacity → --gx/--gy
│   ├── MutationObserver         自动初始化新增卡片
│   └── mouseleave handler       重置透明渡
│
├── 2. 导航控制
│   ├── toggleDrawer()           移动端抽屉开/关
│   └── toggleAdminSidebar()     后台侧栏开/关
│
├── 3. 工具函数
│   ├── switchTool()             工具页 tab 切换
│   ├── b64Encode / b64Decode    Base64 编解码
│   ├── wordCount()              字数统计
│   ├── colorFromPicker/Hex/RGB  颜色转换
│   ├── jsonFormat / jsonCompact JSON 格式化
│   ├── initTimestamp / tsFrom*  时间戳工具
│   ├── calcHash()               MD5/SHA1/SHA256
│   └── izSelect/Load/Update    图片压缩工具
│
├── 4. 自定义下拉框
│   ├── initGlowSelects()        自动包装 <select> → glow-select-wrap
│   │   └── 对每个 <select>:
│   │       1. 跳过已包装和 RTE 工具栏
│   │       2. 创建 wrap/trigger/menu DOM
│   │       3. 隐藏原生 select
│   │       4. 绑定 click/change 事件
│   └── 全局 click 关闭          点击其他区域收起下拉
│
├── 5. 图片灯箱
│   ├── openLightbox(src)        显示灯箱 + 禁止滚动
│   └── closeLightbox()          关闭灯箱 + 恢复滚动
│
└── 6. 移动端标题点击
    └── navLogo click handler    手机端点击标题→toggleDrawer()
```

### 7.5 前端交互数据流

```
鼠标移动
  → mousemove 事件 (document)
  → 更新 mouseX/mouseY 全局变量
  → requestAnimationFrame(updateGlow)
  → updateGlow()
      → 遍历所有 cardData
      → 计算鼠标到卡片边缘距离
      → 距离 < maxDist → 计算不透明度 (二次缓动)
      → 标准化鼠标位置百分比 (0-100)
      → 设置 CSS custom properties:
          --gx = 鼠标X百分比
          --gy = 鼠标Y百分比
          --glow-opacity = 计算后的透明度
          --glow-intensity = 同上
  → CSS ::before 伪元素使用这些变量渲染径向渐变光晕

图片灯箱
  用户点击特色卡片图片
    → event.stopPropagation() + event.preventDefault()
    → openLightbox(img.src)
    → lightbox.style.display = 'flex'
    → body.style.overflow = 'hidden'
  用户点击灯箱背景
    → closeLightbox()
    → lightbox.style.display = 'none'
    → body.style.overflow = ''
```

---

## 八、数据流

### 8.1 首页渲染数据流

```
浏览器 GET /
  → blog.index()
  → 解析 ?page= & ?per_page= & ?category= 参数
  → 查询: Post.query.filter_by(is_published=True)
      → .options(joinedload(Post.author))   ← N+1 优化
      → .order_by(Post.created_at.desc())
      → .paginate(page, per_page)
  → _get_sidebar_data()
      → cache_get('sidebar_data')
      → 命中 → 返回缓存
      → 未命中:
          → Category.query.all()
          → Post.query.limit(8)
          → cache_set('sidebar_data', ..., ttl=300)
  → FeaturedCard.query.filter_by(is_active=True).order_by(sort_order)
  → cat_lookup = {c.slug: c.name for c in categories}
  → blog_subtitle = current_app.config['BLOG_SUBTITLE']
  → render_template('index.html', ...)
```

### 8.2 特色卡片 CRUD 数据流

```
创建卡片:
  用户访问 /admin/featured-cards/new
    → new_featured_card()
    → Category.query.order_by(Category.name)
    → 如果 categories 为空 → 跳转分类创建页
    → 构造 FeaturedCardForm
    → form.tag.choices = [(c.slug, c.name) for c in categories]
    → render_template('admin/featured-card-form.html')

  用户提交表单 (POST)
    → form.validate_on_submit()
    → 通过: FeaturedCard( ... ) → db.session.add → db.session.commit → flash → redirect
    → 失败: for field, errors → flash 每个错误 → 重新渲染

首页显示:
  用户访问首页
    → blog.index()
    → FeaturedCard.query.filter_by(is_active=True).order_by(FeaturedCard.sort_order)
    → for each card:
        → 判断 icon 路径类型 → emoji / 图片URL
        → cat_lookup[tag] → 分类名
    → render_template('index.html', featured_cards=...)
```

### 8.3 价格爬虫数据流

```
定时器 09:00 触发
  → _run_daily_crawl(app)
  → with app.app_context():
      → crawl_all_active_sources()
          → 查询所有 is_active=True 的 ProductSource
          → 对每个 source:
              如果是 Amazon: → 调用 apify_client
              否则: → _crawl_generic(url) → requests + BeautifulSoup
          → 解析价格 → new PriceRecord(source_id, product_id, price)
          → db.session.commit()

手动添加:
  用户 POST /prices/add-product
    → Product(name=..., brand=..., category=...)
    → ProductSource(product_id=..., site=..., url=...)
    → 立即爬取该来源
    → redirect 到价格看板
```

### 8.4 汇率更新数据流

```
应用启动:
  → ExaClient.__init__()
  → _fetch_rates() 调用 Exa API 搜索 "USD CNY exchange rate"
  → 解析结果得到 USD/EUR/GBP → CNY 汇率
  → 对每种汇率:
      → 查询最近一条记录
      → 如果不存在或变化 > 0.1% → 写入新的 ExchangeRate 记录
  → db.session.commit()

前台查询:
  用户访问 /prices/rates
  → exchange_rates()
  → 查询每种货币的最近 30 条记录
  → 输出为表格 + 简单趋势
```

---

## 九、配置系统

### 9.1 配置加载优先级

```
1. config.py 中的硬编码默认值（最低优先级）
2. .env 文件中的环境变量
3. os.environ 中的系统环境变量
4. .secret_keys 文件中的密钥轮换
```

### 9.2 完整环境变量列表

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `DATABASE_URL` | 拼接 | MySQL 连接串 |
| `DB_HOST` | 127.0.0.1 | 数据库主机 |
| `DB_PORT` | 3306 | 数据库端口 |
| `DB_USER` | hoshino | 数据库用户 |
| `DB_PASS` | hoshino_pass | 数据库密码 |
| `DB_NAME` | hoshino_blog | 数据库名 |
| `SECRET_KEY` | 自动轮换 | Flask 密钥 |
| `ADMIN_USERNAME` | admin | 默认管理员用户名 |
| `ADMIN_PASSWORD` | CHANGE_ME | 默认管理员密码 |
| `ADMIN_EMAIL` | admin@localhost | 默认管理员邮箱 |
| `PORT` | 5000 | 监听端口 |
| `MAX_CONTENT_LENGTH` | 16777216 | 上传大小上限(字节) |
| `POSTS_PER_PAGE` | 6 | 每页文章数 |
| `BLOG_SUBTITLE` | 硬编码 | 首页副标题 |
| `DEFAULT_THEME` | dark | 默认主题色 |
| `REDIS_URL` | (无) | Redis 连接串 |
| `SCRAPING_PROXY` | (无) | 爬虫代理 |
| `EXA_API_KEY` | (无) | Exa API Key |
| `SESSION_COOKIE_SECURE` | true(生产) | HTTPS-only |
| `FLASK_ENV` | (无) | development=调试模式 |

### 9.3 Secret Key 轮换机制

```
启动时:
  .env 中有 SECRET_KEY? → 使用固定值，不轮换
  .env 中无 SECRET_KEY? → 读取 .secret_keys[0] 作为当前密钥
                           .secret_keys[1:] 作为回退密钥

运行时 (每天 03:00):
  rotate_secret_key():
    1. 生成新密钥 (secrets.token_hex(32))
    2. 插入 .secret_keys 列表首位
    3. 截断到最多 10 个
    4. 持久化到 .secret_keys 文件
    5. app.config['SECRET_KEY'] = 新密钥
    6. app.config['SECRET_KEY_FALLBACKS'] = 历史密钥

Session 验证:
  Flask-Login 先尝试用 SECRET_KEY 解密
  失败 → 依次尝试 SECRET_KEY_FALLBACKS 中的每个密钥
  全部失败 → Session 失效（用户需重新登录）
```

---

## 十、安全机制

### 10.1 CSRF 防护

- 全局 `CSRFProtect(app)` 覆盖所有 `POST/PUT/DELETE`
- 表单通过 `{{ form.hidden_tag() }}` 自动注入 CSRF token
- AJAX 请求通过 `<meta name="csrf-token">` 读取 token，在请求头 `X-CSRFToken` 中发送

### 10.2 Session 安全

- `SESSION_COOKIE_HTTPONLY = True` — 不可被 JS 读取
- `SESSION_COOKIE_SAMESITE = 'Lax'` — 阻止跨站请求携带 Cookie
- `SESSION_COOKIE_SECURE = True`（生产环境）— 仅 HTTPS

### 10.3 密码安全

- 使用 `werkzeug.security.generate_password_hash()`（pbkdf2:sha256）
- 密码从不在日志中记录
- 管理员密码首次启动可随机生成

### 10.4 上传安全

- `MAX_CONTENT_LENGTH` 限制（默认 16MB）
- 上传文件通过 uuid 重命名，防止路径遍历
- 仅接受图片类型（通过 PIL 验证）

### 10.5 管理员权限

- `@admin_required` 装饰器检查 `current_user.is_admin`
- 用户不能删除自己的账户
- 普通用户无法访问 `/admin/*` 路径

### 10.6 其他

- 模板自动转义（Jinja2 默认开启 `autoescape`）
- 数据库参数化查询（SQLAlchemy ORM 防止 SQL 注入）
- Rate-limit（通过 Flask-Limiter，配置在路由层）

---

## 十一、错误处理

### 11.1 HTTP 错误码

| 错误码 | 处理方式 | 说明 |
|--------|----------|------|
| 404 | Flask 默认 404 页面 | 资源不存在 |
| 403 | `abort(403)` | 权限不足 |
| 500 | Flask 调试或生产错误页 | 服务器内部错误 |
| 400 | WTForms 验证失败 + flash | 表单数据无效 |

### 11.2 数据库错误

- 连接失败：应用启动时 `init_db()` 会报错，Flask 500
- 唯一约束冲突：SQLAlchemy `IntegrityError` → 表单验证层捕获（`validate_slug` 等）

### 11.3 外部服务降级

- Redis 不可用：`cache.py` 中的 stub 对象静默返回 None，不影响业务
- Exa API 不可用：`ExaClient._ready=False`，跳过汇率更新
- 爬虫失败：`crawl_all_active_sources()` 捕获每个 source 的异常，单 source 失败不影响其他

---

## 十二、部署运维

### 12.1 环境要求

```
Python 3.12+
MySQL 5.7+ / 8.x
Redis 7.x（可选）
Linux / macOS / Windows
```

### 12.2 依赖安装

```bash
pip install -r requirements.txt
```

### 12.3 数据库初始化

首次启动自动完成（`db.create_all()` + 迁移 + 默认管理员）。

手动重置：
```sql
DROP DATABASE hoshino_blog;
CREATE DATABASE hoshino_blog CHARACTER SET utf8mb4;
```

### 12.4 启动命令

| 环境 | 命令 | 说明 |
|------|------|------|
| 开发 | `python app.py` | 热重载 + 调试页 |
| 开发(指定端口) | `PORT=8080 python app.py` |  |
| Linux 生产 | `gunicorn app:create_app() -w 4 -b 0.0.0.0:5000` | 4 workers |
| Windows 生产 | `waitress-serve --port=5000 app:create_app` |  |

### 12.5 日志查看

```bash
tail -f blog/logs/hoshino.log      # 实时查看
tail -f blog/logs/error.log        # 仅错误
```

### 12.6 常见维护

| 场景 | 操作 |
|------|------|
| 修改副标题 | 编辑 `.env` → `BLOG_SUBTITLE=新文本` → 重启 |
| 添加特色卡片 | 后台 → 特色卡片 → 新建 |
| 清理测试数据 | 后台对应管理页面 → 删除 |
| 修改分页数 | 编辑 `.env` → `POSTS_PER_PAGE=12` → 重启 |
| 查看数据库 | `mysql -u hoshino -p hoshino_blog` |
| 强迫更新密钥 | 删除 `.secret_keys` 文件 → 重启 |
| 备份数据库 | `mysqldump -u hoshino -p hoshino_blog > backup.sql` |

### 12.7 文件上传

图片上传后存储在 `static/uploads/`，文件名格式为 `uuid.ext`。
通过 `/thumb?path=uploads/uuid.jpg&w=400` 获取缩略图（PIL 实时缩放）。

---

> 文档维护：请保持与代码同步。修改路由/模型/配置后，请更新对应章节。
