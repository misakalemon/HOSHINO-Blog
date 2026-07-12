# HOSHINO Blog

> 暗色科技风个人博客系统 · Flask + MySQL 构建

![Theme](https://img.shields.io/badge/Theme-Hoshino%20Pink-ff6b9d)
![Flask](https://img.shields.io/badge/Flask-3.1-000?logo=flask)
![License](https://img.shields.io/badge/License-MIT-green)

---

## 项目简介

HOSHINO Blog 是一个基于 Python Flask 框架构建的个人博客系统。前端采用**粉紫暗色科技主题**，集成 **零依赖富文本编辑器**、**自定义下拉框组件**，支持文章发布、多用户角色、特色卡片、价格追踪、RSS 订阅等完整功能。

**关键词**: 暗色科技风 · 粉紫渐变 · 富文本编辑 · 多用户角色 · 响应式设计 · 零外部依赖

---

## 目录

- [技术栈](#技术栈)
- [功能特性](#功能特性)
- [权限体系](#权限体系)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [项目结构](#项目结构)
- [数据库模型](#数据库模型)
- [API 路由](#api-路由)
- [自定义配置](#自定义配置)
- [常见问题](#常见问题)
- [开发日志](#开发日志)

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | Python **Flask** 3.1 |
| ORM | Flask-SQLAlchemy 3.1 |
| 数据库 | **MySQL** 8.0+（仅支持 MySQL） |
| 认证授权 | Flask-Login（多角色体系） |
| 表单处理 | Flask-WTF + WTForms |
| 前端主题 | **粉紫暗色科技风**（纯 CSS 自研） |
| 富文本编辑器 | **零外部依赖** contentEditable 编辑器 |
| 内容渲染 | 原生 HTML（支持富文本标签 + Prism 代码高亮） |
| 缓存 | Redis（可选，侧边栏/RSS/仪表盘降级友好） |
| RSS 订阅 | 标准 RSS 2.0 |
| 定时任务 | APScheduler（价格爬取 / SECRET_KEY 轮换） |

---

## 功能特性

### 前台

| 功能 | 说明 |
|------|------|
| 文章列表 | 分页浏览 + 分类筛选 + 全站搜索 |
| 文章详情 | 富文本 HTML 渲染 + Prism 代码高亮 |
| 评论系统 | 需管理员审核后显示 |
| 分类页面 | 按分类查看文章 |
| 关于页面 | 管理员通过富文本编辑器自定义内容 |
| 联系表单 | 访客留言 |
| 价格看板 | 商品价格追踪与历史走势图（ECharts） |
| **B站数据** | **UP 主视频数据爬取、新视频自动发现、粉丝/播放量趋势图、全局视频搜索** |
| 工具箱 | 密码生成器、图片压缩、颜色选择器、Base64/JSON/哈希/时间戳 |
| RSS 订阅 | `/feed.xml` 标准 RSS 输出 |
| 响应式设计 | PC / 平板 / 手机全适配 |

### 管理后台（`/admin`）

| 功能 | 说明 |
|------|------|
| 仪表盘 | 文章/评论/用户统计概览 |
| 富文本编辑器 | 所见即所得，支持标题/粗体/列表/引用/代码块/链接/字体大小 |
| 文章管理 | CRUD + 发布/草稿切换 + 多分类 |
| 分类管理 | 新增/编辑/删除分类 |
| 特色卡片 | 首页精选卡片管理，支持图片/图标/链接 |
| 评论审核 | 待审核/已通过双列表分页，一键审批 |
| 用户管理 | 列表显示头像，编辑角色，启用/禁用/删除 |
| 个人资料 | 头像上传、GitCode/GitHub/Gitee/Bilibili 链接、关于页富文本编辑、密码修改 |
| **B站数据** | **UP 主管理、V2 扫码登录、视频爬取/增量发现、爬取进度实时查看、粉丝/播放量趋势图表** |

### 科技风设计亮点

- **粉紫色调**: 主色 `#ff6b9d` 粉红 + `#a855f7` 紫色渐变
- **玻璃态卡片**: `backdrop-filter blur` + 半透明背景
- **自定义下拉框**: 自研 `glow-select-wrap` 组件，全站统一风格
- **图片灯箱**: 点击图片全屏查看

---

## 权限体系

| 角色 | 权限 |
|------|------|
| **admin** | 全部权限 — 用户管理、特色卡片、仪表盘、文章/分类/评论全部管理 |
| **editor** | 内容管理 — 仪表盘、文章/分类/评论管理 |
| **user** | 写作者 — 撰写和管理自己的文章、编辑个人资料 |

### 安全机制

- **实时活性校验**: 所有权限装饰器每次请求检查 `user.is_active`，禁用用户 session 即时失效
- **当前密码验证**: 修改密码需输入当前密码
- **密码确认**: 注册和修改密码均需二次确认
- **编辑安全**: 编辑用户时仅角色可修改，其他字段只读（后端仅保存 role）
- **注册开关**: 通过 `ENABLE_REGISTRATION` 控制，生产环境默认关闭
- **速率限制**: 登录接口 IP 级别频率限制（每分钟 10 次）
- **SECRET_KEY 轮换**: 每天 03:00 自动轮换，历史密钥保留 10 个

---

## 快速开始

### 环境要求

- Python 3.9+
- MySQL 8.0+
- Redis（可选，缓存降级友好）

### 安装步骤

```bash
# 1. 克隆项目
git clone <your-repo-url>
cd hoshino_blog

# 2. 通过 Conda 创建环境（自动安装全部依赖）
conda env create -f environment.yml

# 3. 激活环境
conda activate hoshino-blog

# 4. 创建 MySQL 数据库
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS hoshino_blog DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# 5. 配置环境变量
cp .env.example .env
# 编辑 .env 修改数据库连接信息

# 6. 启动应用（首次运行自动建表 + 创建管理员）
python app.py

# 7. 访问
#    前台: http://localhost:5000
#    后台: http://localhost:5000/admin
#    默认管理员: admin / admin123
```

### 快速使用

1. 访问 `/admin` 使用 `admin / admin123` 登录
2. 点击 **"写文章"** 进入富文本编辑器
3. 编写内容后勾选"发布"并提交
4. 返回首页即可看到发布的文章

---

## 配置说明

所有配置集中在 `config.py`，通过 `.env` 文件或环境变量覆盖：

### 核心配置

```ini
# .env 文件
DATABASE_URL=mysql+pymysql://user:pass@localhost:3306/hoshino_blog?charset=utf8mb4
SECRET_KEY=your-strong-secret-key
```

### 可选配置

```ini
# 用户注册开关（默认关闭）
ENABLE_REGISTRATION=true

# 默认管理员
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin123
ADMIN_EMAIL=admin@localhost

# 每页文章数
POSTS_PER_PAGE=15

# Redis 缓存
REDIS_URL=redis://127.0.0.1:6379/0

# 默认主题（dark / light）
DEFAULT_THEME=dark

# Session 安全
SESSION_COOKIE_SECURE=false   # HTTP 环境必须 false
```

---

## 项目结构

```
hoshino_blog/
├── app.py                     # 应用入口 / 工厂函数
├── config.py                  # 集中配置（含 SECRET_KEY 自动轮换）
├── .env                       # 环境变量（数据库/密钥/缓存）
├── requirements.txt           # Python 依赖
│
├── blog/                      # 业务逻辑包
│   ├── __init__.py            # Blueprint + 数据库初始化 + 自动迁移
│   ├── models.py              # 数据模型（User/Post/Category/Comment/BiliUp 等）
│   ├── forms.py               # WTForms 表单定义
│   ├── routes.py              # 前台路由（首页/文章/搜索/RSS/工具）
│   ├── admin.py               # 后台路由（认证/文章/分类/评论/用户）
│   ├── price_routes.py        # 价格看板路由
│   ├── bili_routes.py         # Bilibili 后台管理路由（爬取/扫码登录/UP 主管理）
│   ├── bili_public_routes.py  # Bilibili 公开页面路由（UP 主列表/视频详情/搜索）
│   ├── cache.py               # Redis 缓存封装
│   ├── crawler.py             # 价格爬虫
│   ├── apify_client.py        # Amazon 直爬
│   └── exa_client.py          # Exa 搜索引擎 API
│   ├── bilibili/              # Bilibili 模块
│   │   ├── __init__.py        # 包标记
│   │   ├── config.py          # 请求间隔/Cookie 路径/UA/HEADERS
│   │   ├── bili_api.py        # B站 API 封装（视频列表/统计/用户信息/动态发现/关系查询）
│   │   └── login.py           # V2 扫码登录 + Credential/Cookie 持久化 + 自动加载
│
├── templates/                 # Jinja2 模板
│   ├── base.html              # 基础布局（导航栏 + 页脚 + 灯箱 + 抽屉菜单）
│   ├── index.html             # 首页（特色卡片 + 文章瀑布流）
│   ├── single-post.html       # 文章详情
│   ├── about.html             # 关于页（动态内容）
│   ├── contact.html           # 联系页
│   ├── _sidebar.html          # 侧边栏组件（用户卡片/搜索/文章/分类）
│   ├── category-grid.html     # 分类文章列表
│   ├── tools.html             # 工具箱
│   ├── rss.xml                # RSS Feed 模板
│   └── admin/                 # 后台模板
│       ├── base_admin.html    # 后台布局（侧边栏按角色动态显示）
│       ├── dashboard.html     # 仪表盘
│       ├── post-list.html     # 文章列表（含作者列）
│       ├── post-form.html     # 富文本编辑器
│       ├── category-list.html # 分类列表
│       ├── category-form.html # 分类表单
│       ├── comment-list.html  # 评论管理（双列表分页）
│       ├── user-list.html     # 用户列表（含头像）
│       ├── user-form.html     # 用户表单（编辑模式仅角色可改）
│       ├── profile.html       # 个人资料（社交链接 + 关于页编辑器）
│       ├── login.html         # 登录
│       ├── register.html      # 注册
│       ├── featured-card-list.html
│       ├── featured-card-form.html
│       ├── _cookie_banner.html
│       └── _pagination.html
│
└── static/
    ├── css/
    │   └── glow-design.css    # 完整样式表
    ├── images/
    │   ├── avatar/
    │   └── categories/
    └── uploads/               # 用户上传（头像/图片）
```

---

## 数据库模型

```
┌──────────────────────────────────────────────────────────────────┐
│  User                                                           │
├──────────────────────────────────────────────────────────────────┤
│  id · username · email · password_hash · display_name · bio    │
│  avatar · website · gitcode_url · github_url                   │
│  role(user/editor/admin) · is_active · about_content(MEDIUMTEXT)│
│  last_login_at · last_login_ip · login_count · created_at      │
└───────────────────────┬──────────────────────────────────────────┘
                        │ 1
                        │
                        │ *
┌───────────────────────▼──────────────────────────────────────────┐
│  Post                                                            │
├──────────────────────────────────────────────────────────────────┤
│  id · title · slug(unique) · summary · content(MEDIUMTEXT)      │
│  cover_image · author_id · is_published · created_at · updated_at│
└───────┬────────────────────────────┬─────────────────────────────┘
        │ *                          │ *
        │                            │
┌───────▼──────────┐  ┌──────────────▼─────────────────────────────┐
│  Category        │  │  Comment                                   │
├──────────────────┤  ├────────────────────────────────────────────┤
│  id · name · slug│  │  id · post_id · author_name · author_email │
│  description     │  │  content · is_approved · created_at       │
│  created_at      │  └────────────────────────────────────────────┘
└──────────────────┘

┌───────────────────────────────────────────────┐
│  FeaturedCard                                 │
├───────────────────────────────────────────────┤
│  id · title · description · icon · tag(slug) │
│  link · image_url · sort_order · is_active    │
│  created_at · updated_at                      │
└───────────────────────────────────────────────┘

┌───────────────────────────────────────────────┐
│  Product · ProductSource · PriceRecord        │
│  ExchangeRate                                 │
└───────────────────────────────────────────────┘
```

---

## B站 视频爬取架构

### 定时任务

| 任务 | 时间 | 说明 |
|------|------|------|
| **增量检查** | 每 30 分钟 | 发现各 UP 主新视频，入库 + 写历史快照（翻前 10 页 + 动态兜底） |
| **每日深扫** | 凌晨 02:00 | 三层统计更新（Hot ≤7d / Warm 8~30d / Cold >30d），每个 UP 主最多更新 30 个视频 |
| **历史清理** | 凌晨 04:00 | 删除 365 天前的 `BiliVideoHistory` 记录 |

### 视频发现双路径

```
arc/search API（按 pubdate 倒序翻页）
        ↓ 
        已知视频 → 跳过
        新视频 → get_video_stat → 入库 → BiliVideoHistory
        ↓ (arc/search 可能遗漏 shorts/短视频)
动态兜底（get_dynamics_new → 用户动态流）
        ↓ 提取 DYNAMIC_TYPE_AV 事件 → Video.get_info()
        ↓ 验证 owner_mid == 目标 UP 主（排除转发）
        ↓ 入库 + 写历史
```

### 互斥保护

深扫与增量检查启动前在同一锁下检查 `_scrape_running` + `_incremental_running`，同一 UP 主不会并发处理。

### Cookie 管理

- V2 扫码登录（`bilibili-api` 官方库）
- Cookie + Credential 双持久化（`.bili_cookies.txt` / `.bili_credential.json`）
- Cookie 过期自动降级为匿名访问（含 `relation/stat` 粉丝数 fallback）

### 风控处理

- 并发信号量 `Semaphore(5)` 限制同时请求数
- 风控指数退避（30s → 60s → 120s → … → 600s）
- 每视频请求间隔 7~10 秒
- `_sync` 统一 30s 超时 + 线程本地事件循环生命周期管理

---

## API 路由

### 前台路由

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 首页（特色卡片 + 文章列表） |
| GET | `/post/<slug>` | 文章详情 + 评论 |
| GET | `/category/<slug>` | 分类文章列表 |
| GET | `/about` | 关于页（动态内容） |
| GET/POST | `/contact` | 联系页 |
| GET | `/search?q=` | 搜索文章 |
| GET | `/feed.xml` | RSS 订阅 |
| GET | `/tools` | 工具箱 |
| GET | `/thumb` | 图片缩略图处理 |
| GET | `/bilibili` | B站 UP 主列表（支持搜索） |
| GET | `/bilibili/up/<id>` | UP 主视频列表 + 粉丝趋势图 |
| GET | `/bilibili/video/<id>` | 视频详情 + 播放量趋势图 |

### 价格看板

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/prices/` | 价格看板首页 |
| GET | `/prices/product/<id>` | 商品详情 + 价格趋势图 |
| GET | `/prices/api/product/<id>/history` | 价格历史 JSON API |
| GET | `/prices/rates` | 汇率看板 |
| GET | `/prices/api/rates` | 汇率 JSON API |
| POST | `/prices/crawl` | 手动触发爬取（editor+） |
| POST | `/prices/manual-price` | 手动录入价格（editor+） |
| POST | `/prices/add-product` | 添加新品（editor+） |

### 后台路由

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/admin/login` | 登录 |
| GET | `/admin/logout` | 退出 |
| GET | `/admin/register` | 注册（需 `ENABLE_REGISTRATION=true`） |
| GET | `/admin/_debug` | 诊断端点 |
| GET | `/admin/` | 仪表盘（editor+） |
| GET | `/admin/posts` | 文章列表（user+） |
| GET/POST | `/admin/posts/new` | 新建文章（user+） |
| GET/POST | `/admin/posts/<id>/edit` | 编辑文章（user+，仅能编辑自己的） |
| POST | `/admin/posts/<id>/delete` | 删除文章（user+，仅能删除自己的） |
| GET | `/admin/categories` | 分类列表（editor+） |
| GET/POST | `/admin/categories/new` | 新建分类（editor+） |
| GET/POST | `/admin/categories/<id>/edit` | 编辑分类（editor+） |
| POST | `/admin/categories/<id>/delete` | 删除分类（editor+） |
| GET | `/admin/comments` | 评论管理（editor+） |
| POST | `/admin/comments/<id>/approve` | 通过评论（editor+） |
| POST | `/admin/comments/<id>/delete` | 删除评论（editor+） |
| GET | `/admin/users` | 用户列表（admin） |
| GET/POST | `/admin/users/new` | 新建用户（admin） |
| GET/POST | `/admin/users/<id>/edit` | 编辑用户角色（admin） |
| POST | `/admin/users/<id>/delete` | 删除用户（admin） |
| POST | `/admin/users/<id>/toggle-active` | 启用/禁用用户（admin） |
| GET/POST | `/admin/profile` | 个人资料 |
| POST | `/admin/upload-image` | 图片上传（user+） |
| GET | `/admin/featured-cards` | 特色卡片（admin） |
| GET/POST | `/admin/featured-cards/new` | 新建卡片（admin） |
| GET/POST | `/admin/featured-cards/<id>/edit` | 编辑卡片（admin） |
| POST | `/admin/featured-cards/<id>/delete` | 删除卡片（admin） |

### Bilibili 后台

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/bilibili/` | UP 主管理列表（含扫码登录入口） |
| GET | `/admin/bilibili/up/<id>` | UP 主视频数据表格（分页 30 条） |
| POST | `/admin/bilibili/scrape` | 启动爬取（Ajax，解析 space_url → 后台线程） |
| GET | `/admin/bilibili/scrape-status?mid=` | 爬取进度实时 JSON |
| POST | `/admin/bilibili/refresh/<up_id>` | 刷新单 UP 主数据（限 30 个视频） |
| POST | `/admin/bilibili/refresh-all/<up_id>` | 强制刷新全部视频（无配额限制） |
| DELETE | `/admin/bilibili/delete/<up_id>` | 删除 UP 主及其所有视频 |
| DELETE | `/admin/bilibili/delete-video/<id>` | 删除单条视频记录 |
| GET | `/admin/bilibili/qr-gen` | 生成 V2 登录二维码（base64 图片） |
| GET | `/admin/bilibili/qr-poll?key=` | 轮询扫码状态 |
| POST | `/admin/bilibili/logout-bili` | 清除 B站 Cookie/Credential |
| GET | `/admin/bilibili/check-missing` | 遗漏检查 — 对比 API video_count vs DB 实际数 |

---

## 自定义配置

### 修改每页文章数

```ini
# .env
POSTS_PER_PAGE=10
```

### 开启用户注册

```ini
# .env
ENABLE_REGISTRATION=true
```

### 修改默认主题

```ini
# .env
DEFAULT_THEME=light    # 或 dark
```

### 启用 Redis 缓存

```ini
# .env
REDIS_URL=redis://127.0.0.1:6379/0
```

---

## 常见问题

### 为什么富文本编辑器不显示？

编辑器是**零外部依赖**的纯前端实现。请确认：
- 使用现代浏览器（Chrome / Firefox / Edge 最新版）
- 浏览器未禁用 JavaScript

### 如何彻底重置数据？

```bash
mysql -u root -p hoshino_blog -e "DROP TABLE IF EXISTS users, posts, categories, comments, featured_cards, products, product_sources, price_records, exchange_rates, post_categories;"
# 重启应用自动重建
python app.py
```

### 发布文章时提示"链接标识已被使用"？

文章 Slug 必须全局唯一。换一个不同的 slug 即可。

### 生产环境部署需要注意什么？

- 设置强 `SECRET_KEY` 环境变量
- 关闭调试模式（`FLASK_ENV=production`）
- 设置 `SESSION_COOKIE_SECURE=true`（HTTPS 环境）
- 使用正式 WSGI 服务器（Gunicorn / uWSGI）
- 前端使用 Nginx 反向代理 + 静态文件缓存

### 关于页内容在哪里编辑？

登录后台 → 个人资料 → 关于页面内容。使用富文本编辑器编写，保存后前台 `/about` 即时生效。

### 如何禁用某个用户？

管理员 → 用户管理 → 点击该用户的"禁用"按钮。被禁用的用户无法登录，已有 session 即时失效。

---

## 开发日志

- [2026-07-13 — 动态发现兜底 + 事件循环修复 + 粉丝数 fallback + 互斥/超时/内存泄漏修复](docs/CHANGELOG-2026-07-13.md)
- [2026-07-12 — B站 爬取架构重构 — 三层更新/凭证持久化/并发优化/匿名降级](docs/CHANGELOG-2026-07-12.md)
- [2026-07-09 — B站 数据集成、搜索/图表/定时刷新/多 UP 主并行爬取](docs/CHANGELOG-2026-07-06.md)
- [2026-07-03 — 权限体系重构、社交链接、密码安全](docs/CHANGELOG-2026-07-03.md)
- [2026-06-30 — 全站主题改版（Hoshino）、特色卡片系统](docs/CHANGELOG_2026-06-30.md)
- [2026-06-09 — 数据库迁移、分页增强、主题切换](docs/CHANGELOG-2026-06-09.md)
- [2026-06-05 — 项目初始构建](docs/CHANGELOG-2026-06-05.md)

---

## License

MIT License

---

*HOSHINO Blog — 粉紫暗色科技风个人博客系统*

---

> 🤖 本项目由 **DeepSeek-V4-Pro** + **AtomCode** 辅助生成  
> 代码托管于 [GitCode](https://gitcode.com/hoshino5/hoshino-blog)
