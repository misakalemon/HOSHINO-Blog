# Hoshino Blog 技术架构文档

## 一、项目概述

基于 Flask 的二次元风格个人博客系统，以「小鸟游星野」为设计主题，粉紫色系 UI。集成文章管理、评论、分类、价格追踪、工具集等功能。

**技术栈：**
- 后端：Python 3.12 + Flask 3.x + SQLAlchemy 2.x
- 数据库：MySQL 5.7+（默认） / SQLite（开发可用）
- 前端：原生 CSS（Glow Design System）+ 原生 JS（Glow Controller）
- 缓存：Redis（可选，降级不阻塞）
- 定时任务：APScheduler
- 图标：HarmonyOS Icons（字体图标）

---

## 二、目录结构

```
hoshino_blog/
├── app.py                  # Flask 应用入口
├── config.py               # 集中配置（含 Secret Key 轮换）
├── .env                    # 环境变量（数据库/密钥/API Key）
├── blog/
│   ├── __init__.py         # 应用工厂 + 数据库初始化
│   ├── models.py           # 所有 ORM 模型
│   ├── routes.py           # 前台路由（博客/搜索/RSS）
│   ├── admin.py            # 后台管理路由（CRUD）
│   ├── price_routes.py     # 价格追踪路由
│   ├── forms.py            # WTForms 表单定义
│   ├── crawler.py          # 价格爬虫（Amazon 等）
│   ├── exa_client.py       # Exa AI 搜索引擎客户端
│   ├── apify_client.py     # Apify 爬虫客户端
│   ├── logger.py           # 日志系统
│   └── cache.py            # Redis 缓存封装
├── static/
│   ├── css/glow-design.css # 全套 UI 样式（光感设计系统）
│   ├── js/glow-controller.js # 交互逻辑（光效/导航/工具）
│   └── uploads/            # 用户上传文件
├── templates/
│   ├── base.html           # 基础布局（导航/光晕/灯箱/页脚）
│   ├── index.html          # 首页（特色卡片 + 文章列表）
│   ├── single-post.html    # 文章详情
│   ├── _sidebar.html       # 侧边栏组件
│   ├── admin/              # 后台管理模板
│   └── price/              # 价格追踪模板
└── docs/
    └── ARCHITECTURE.md     # 本文档
```

---

## 三、核心模块说明

### 3.1 应用启动流程（app.py → blog/__init__.py）

```
load_dotenv()                    # 读取 .env
  → create_app()
    → Config 加载                 # config.ActiveConfig
    → CSRFProtect                 # 全局 CSRF 防护
    → setup_logging()            # 日志系统（文件 + 终端）
    → init_db(app)               # 数据库建表 + 迁移
      → db.init_app()
      → db.create_all()
      → _migrate_category_to_many2many()  # v1→v2 迁移
      → _migrate_featured_icon()          # 图标字段扩容
    → init_redis(app)            # Redis 连接池
    → LoginManager               # Session 登录管理
    → 注册 3 个蓝图               # blog_bp / admin_bp / price_bp
    → 定时任务                    # 每天 09:00 爬价格 / 03:00 轮换密钥
    → Gzip 压缩
    → 请求日志中间件
```

### 3.2 蓝图与路由

| 蓝图 | 前缀 | 职责 | 关键文件 |
|------|------|------|----------|
| `blog_bp` | `/` | 前台页面 + 文章 + 搜索 + RSS | `routes.py` |
| `admin_bp` | `/admin` | 后台管理 + 登录 + CRUD | `admin.py` |
| `price_bp` | `/prices` | 价格追踪 + 汇率 | `price_routes.py` |

### 3.3 数据库模型（blog/models.py）

| 模型 | 表名 | 用途 |
|------|------|------|
| User | users | 用户/管理员 |
| Post | posts | 文章（Markdown 内容） |
| Category | categories | 文章分类 |
| Comment | comments | 文章评论 |
| FeaturedCard | featured_cards | 首页特色卡片 |
| Product | products | 价格追踪商品 |
| ProductSource | product_sources | 商品来源站点 |
| PriceRecord | price_records | 价格历史记录 |
| ExchangeRate | exchange_rates | 汇率记录 |

**多对多关系：** Post ↔ Category 通过 `post_categories` 关联表实现。

### 3.4 特色卡片系统（FeaturedCard）

- 首页顶部网格展示，支持排序和启用/禁用
- `tag` 字段对应 Category 的 `slug`，共用分类数据库
- `icon` 支持 emoji 或图片路径（自动识别渲染方式）
- `link` 使整张卡片可点击跳转
- 图标的图片支持点击灯箱查看全图

### 3.5 前台路由表（blog/routes.py）

| 路由 | 方法 | 功能 |
|------|------|------|
| `/` | GET | 首页（分页文章 + 特色卡片） |
| `/post/<slug>` | GET, POST | 文章详情 + 评论提交 |
| `/category/<slug>` | GET | 按分类筛选文章 |
| `/about` | GET | 关于页 |
| `/contact` | GET, POST | 联系表单 |
| `/search` | GET | 文章搜索 |
| `/feed.xml` | GET | RSS 输出 |
| `/sitemap.xml` | GET | SEO Sitemap |
| `/tools` | GET | 工具集页面 |
| `/thumb` | GET | 图片缩略图 |

### 3.6 后台路由表（blog/admin.py）

| 路由 | 方法 | 功能 |
|------|------|------|
| `/admin/login` | GET, POST | 管理员登录 |
| `/admin/logout` | GET | 登出 |
| `/admin/` | GET | 仪表盘 |
| `/admin/posts` | GET | 文章列表 |
| `/admin/posts/new` | GET, POST | 新建文章 |
| `/admin/posts/<id>/edit` | GET, POST | 编辑文章 |
| `/admin/posts/<id>/delete` | POST | 删除文章 |
| `/admin/categories/*` | GET, POST | 分类 CRUD |
| `/admin/comments/*` | GET, POST | 评论管理 |
| `/admin/users/*` | GET, POST | 用户管理 |
| `/admin/featured-cards/*` | GET, POST | 特色卡片 CRUD |
| `/admin/profile` | GET, POST | 个人资料编辑 |
| `/admin/upload-image` | POST | 图片上传（RTE） |

---

## 四、前端设计系统

### 4.1 Glow Design System（glow-design.css）

基于 CSS 变量的光感设计系统：

```
:root {
  --bg-primary: #0b0e17;        # 深色背景
  --accent: #6c42d1;             # 紫色主色
  --accent-hover: #845ef7;       # 紫色 hover
  --bg-card: #1a2235;            # 卡片底
  --text-primary: #e8edf5;       # 主文字
  --border-subtle: rgba(255,255,255,0.06);
}
```

**核心组件：**
- 背景光晕：3 个浮动粉色/紫色光球（radial-gradient + animation）
- 玻璃卡片：`backdrop-filter: blur(10px)` 高斯模糊
- 鼠标光效：JS 追踪鼠标位置，CSS custom property (--gx, --gy) 驱动渐变光晕
- 瀑布流：CSS columns 实现文章卡片多列布局
- 自定义下拉框：`glow-select-wrap` + JS 完全自定义样式
- 图片灯箱：fixed 全屏遮罩 + 缩放图片

### 4.2 Glow Controller（glow-controller.js）

交互功能分布：

| 功能 | 行号 | 说明 |
|------|------|------|
| 鼠标光效追踪 | 1-88 | mousemove → requestAnimationFrame → CSS变量更新 |
| 移动端抽屉 | after 88 | 点击标题弹出侧栏导航 |
| 工具函数 | 103-254 | Base64 / 字数统计 / 颜色转换 / JSON / 时间戳 / Hash / 图片压缩 |
| 自定义下拉框 | 256-335 | 自动包装 select → glow-select-wrap 组件 |
| 图片灯箱 | after 335 | openLightbox / closeLightbox |

---

## 五、配置指南

### 5.1 核心配置（.env）

```
DATABASE_URL=mysql+pymysql://user:pass@host:3306/db
SECRET_KEY=随机字符串（不设则自动轮换）
ADMIN_USERNAME=admin
ADMIN_PASSWORD=管理员密码
BLOG_SUBTITLE=首页英雄区副标题
REDIS_URL=redis://127.0.0.1:6379/0（可选）
EXA_API_KEY=exa.ai API密钥（可选）
POSTS_PER_PAGE=15
```

### 5.2 Secret Key 轮换

- 未在 `.env` 中显式设置 `SECRET_KEY` 时，系统自动轮换
- 历史密钥保存在 `.secret_keys` 文件中
- 每天 03:00 定时轮换一次
- 保留最近 10 个历史密钥，旧 session 不失效

---

## 六、部署

### 开发环境：
```bash
python app.py          # 默认 http://127.0.0.1:5000
```

### 生产环境（Linux）：
```bash
gunicorn app:create_app() -w 4 -b 0.0.0.0:5000
```

### 生产环境（Windows）：
```bash
waitress-serve --port=5000 app:create_app
```

---

## 七、常见维护操作

| 操作 | 方法 |
|------|------|
| 新增分类 | 后台「分类管理」或 MySQL 直接 INSERT |
| 修改副标题 | .env 中 BLOG_SUBTITLE → 重启 |
| 添加特色卡片 | 后台「特色卡片」→ 新建 |
| 清理测试数据 | 后台对应管理页面删除 |
| 查看日志 | blog/logs/hoshino.log（每日轮转） |
| 修改分页数 | .env 中 POSTS_PER_PAGE → 重启 |
