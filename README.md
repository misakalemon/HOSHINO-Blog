# HOSHINO Blog

> 暗色科技风个人博客系统 · Flask + MySQL 构建

![Tech Theme](https://img.shields.io/badge/Theme-Cyberpunk%20Tech-00f0ff)
![Flask](https://img.shields.io/badge/Flask-3.1-000?logo=flask)
![License](https://img.shields.io/badge/License-MIT-green)

---

## 项目简介

HOSHINO Blog 是一个基于 Python Flask 框架构建的个人博客系统。前端采用**暗色科技主题**，集成 **HarmonyOS 风格 SVG 图标库**、**零依赖富文本编辑器**，整体风格统一为赛博科技感。支持文章发布、分类管理、评论审核、RSS 订阅等完整博客功能。

**关键词**：暗色科技风 · 赛博朋克 · 富文本编辑 · 响应式设计 · 零外部依赖图标

---

## 目录

- [技术栈](#技术栈)
- [功能特性](#功能特性)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [项目结构](#项目结构)
- [数据库模型](#数据库模型)
- [API 路由](#api-路由)
- [自定义配置](#自定义配置)
- [常见问题](#常见问题)

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | Python **Flask** 3.1 |
| ORM | Flask-SQLAlchemy 3.1 |
| 数据库 | **MySQL**（仅支持 MySQL） |
| 认证授权 | Flask-Login |
| 表单处理 | Flask-WTF + WTForms |
| 前端主题 | **暗色科技风**（纯 CSS 自研） |
| 图标系统 | HarmonyOS 风格 **内联 SVG 图标库** |
| 富文本编辑器 | **零外部依赖** contentEditable 编辑器 |
| 内容渲染 | 原生 HTML（支持富文本标签） |
| RSS 订阅 | 标准 RSS 2.0 + Atom |

---

## 功能特性

### 前台

| 功能 | 说明 |
|------|------|
| 文章列表 | 分页浏览 + 分类筛选 + 全站搜索 |
| 文章详情 | 富文本 HTML 渲染 + 代码高亮 |
| 评论系统 | 需管理员审核后显示 |
| 分类页面 | 按分类查看文章 |
| 关于/联系 | 自定义页面 + 联系表单 |
| RSS 订阅 | `/feed.xml` 标准 RSS 输出 |
| 响应式设计 | PC / 平板 / 手机全适配 |
| **暗色科技主题** | 渐变背景、玻璃态卡片、霓虹光效 |
| **HarmonyOS 图标** | 导航/页脚/按钮全部使用内联 SVG 图标 |

### 管理后台（`/admin`）

| 功能 | 说明 |
|------|------|
| 仪表盘 | 文章/评论/用户统计概览 |
| 文章管理 | CRUD + 发布/草稿切换 |
| **富文本编辑器** | 所见即所得，支持标题/粗体/列表/引用/代码块/链接 |
| 分类管理 | 新增/编辑/删除分类 |
| 评论审核 | 待审核/已通过双列表，一键审批 |
| 用户管理 | 管理员专属，支持多用户 |
| 个人资料 | 修改显示名、邮箱、密码 |

### 科技风设计亮点

- **深色背景** `#0a0a1a` + 紫色/青色渐变光晕
- **玻璃态卡片** backdrop-filter blur + 半透明背景
- **霓虹点缀** cyan `#00f0ff` / purple `#7c3aed` / green `#00ff88`
- **发光交互** 卡片 hover 上浮、图片缩放、导航下划线动效
- **渐变文字** CSS `background-clip: text` 渐变标题
- **无图占位** 文章无封面图时自动显示渐变背景 + 图标

---

## 快速开始

### 环境要求

- Python 3.9+
- pip（Python 包管理器）

### 安装步骤

```bash
# 1. 克隆项目
git clone <your-repo-url>
cd hoshino_blog

# 2. 创建虚拟环境（推荐）
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# 或
venv\Scripts\activate     # Windows

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置 MySQL 连接
#    复制 .env.example 为 .env 并修改数据库连接信息
cp .env.example .env

# 5. 创建 MySQL 数据库
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS hoshino_blog DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# 6. 启动应用（首次运行自动创建表和默认管理员）
python app.py

# 7. 打开浏览器访问
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

所有配置集中在 `config.py` 或通过环境变量覆盖：

```python
# config.py
import os

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    # 密钥（用于 Session / CSRF 保护）
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-here'

    # 数据库连接（MySQL）
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'mysql+pymysql://用户名:密码@localhost:3306/hoshino_blog?charset=utf8mb4'
```

### 环境变量配置

推荐通过 `.env` 文件或环境变量配置：

```bash
# .env 文件
DATABASE_URL=mysql+pymysql://用户名:密码@localhost:3306/hoshino_blog?charset=utf8mb4
SECRET_KEY=your-strong-secret-key
```

---

## 项目结构

```
hoshino_blog/
├── app.py                     # 应用入口 / 工厂函数
├── config.py                  # 集中配置
├── requirements.txt           # Python 依赖清单
├── .gitignore                 # Git 忽略规则
│
├── blog/                      # 业务逻辑包
│   ├── __init__.py            # Blueprint 定义 + 数据库初始化
│   ├── models.py              # 数据模型（User/Post/Category/Comment）
│   ├── forms.py               # WTForms 表单定义
│   ├── routes.py              # 前台路由（首页/文章/搜索/RSS）
│   └── admin.py               # 后台路由（需登录）
│
├── templates/                 # Jinja2 模板
│   ├── base.html              # 基础布局（导航栏 + SVG 图标库 + 页脚）
│   ├── index.html             # 首页（文章列表 + 侧边栏）
│   ├── single-post.html       # 文章详情（正文 + 评论）
│   ├── category-grid.html     # 分类文章列表
│   ├── about.html             # 关于页
│   ├── contact.html           # 联系页（含表单）
│   ├── login.html             # 登录页
│   ├── _sidebar.html          # 侧边栏组件
│   ├── rss.xml                # RSS Feed 模板
│   └── admin/                 # 后台模板
│       ├── base_admin.html    # 后台基础布局（侧边栏）
│       ├── dashboard.html     # 仪表盘
│       ├── post-list.html     # 文章列表
│       ├── post-form.html     # 文章编辑（富文本编辑器）
│       ├── category-list.html # 分类列表
│       ├── category-form.html # 分类表单
│       ├── comment-list.html  # 评论管理
│       ├── user-list.html     # 用户列表
│       ├── user-form.html     # 用户表单
│       └── profile.html       # 个人资料
│
└── static/                    # 静态资源
    ├── css/
    │   └── tech.css           # 暗色科技风完整样式表（~750 行）
    ├── images/
    │   ├── icons.svg          # HarmonyOS 风格 SVG 图标库
    │   ├── logo/
    │   │   └── favicon.svg    # 网站图标
    │   ├── avatar/
    │   │   └── main-avatar.jpg # 默认头像
    │   └── categories/
    │       ├── item-1.jpg     # 文章封面占位
    │       └── item-2.jpg     # 侧边栏缩略图占位
    └── uploads/               # 用户上传目录（自动创建）
```

---

## 数据库模型

```
┌─────────────────────────────────────────────────────────┐
│  User                                                  │
├─────────────────────────────────────────────────────────┤
│  id · username · email · password_hash                 │
│  display_name · bio · avatar · is_admin · is_active    │
│  created_at · [posts]                                  │
└───────────┬─────────────────────────────────────────────┘
            │ 1
            │
            │ *
┌───────────▼─────────────────────────────────────────────┐
│  Post                                                  │
├─────────────────────────────────────────────────────────┤
│  id · title · slug(unique) · summary · content(HTML)   │
│  cover_image · category_id · author_id · is_published  │
│  created_at · updated_at · [comments]                  │
└───────────┬────────────────────────┬────────────────────┘
            │ *                      │ *
            │                        │
┌───────────▼──────────┐  ┌──────────▼─────────────────────┐
│  Category            │  │  Comment                       │
├──────────────────────┤  ├────────────────────────────────┤
│  id · name · slug    │  │  id · post_id · author_name    │
│  description         │  │  author_email · content        │
│  created_at · [posts]│  │  is_approved · created_at      │
└──────────────────────┘  └────────────────────────────────┘
```

---

## API 路由

### 前台路由

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 首页（文章列表） |
| GET | `/post/<slug>` | 文章详情 + 评论 |
| GET | `/category/<slug>` | 分类文章列表 |
| GET | `/about` | 关于页 |
| GET/POST | `/contact` | 联系页（表单提交） |
| GET | `/search?q=` | 搜索文章 |
| GET | `/feed.xml` | RSS 订阅 |

### 后台路由（需登录）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/admin/login` | 登录 |
| GET | `/admin/logout` | 退出 |
| GET | `/admin/` | 仪表盘 |
| GET | `/admin/posts` | 文章列表 |
| GET/POST | `/admin/posts/new` | 新建文章 |
| GET/POST | `/admin/posts/<id>/edit` | 编辑文章 |
| POST | `/admin/posts/<id>/delete` | 删除文章 |
| GET | `/admin/categories` | 分类列表 |
| GET/POST | `/admin/categories/new` | 新建分类 |
| GET/POST | `/admin/categories/<id>/edit` | 编辑分类 |
| POST | `/admin/categories/<id>/delete` | 删除分类 |
| GET | `/admin/comments` | 评论管理 |
| POST | `/admin/comments/<id>/approve` | 通过评论 |
| POST | `/admin/comments/<id>/delete` | 删除评论 |
| GET | `/admin/users` | 用户列表（管理员） |
| GET/POST | `/admin/users/new` | 新建用户 |
| GET/POST | `/admin/profile` | 个人资料 |

---

## 自定义配置

### 修改每页文章数

```python
# config.py
POSTS_PER_PAGE = 10  # 默认 6
```

### 修改网站名称

```python
# templates/base.html
<title>{% block title %}{{ site_name|default('HOSHINO Blog') }}{% endblock %}</title>
```

### 修改默认管理员账号

```python
# blog/__init__.py 中的 init_db 函数
admin = User(
    username='admin',          # 改为你想要的用户名
    email='admin@localhost',   # 改为你想要的邮箱
    ...
)
admin.set_password('admin123') # 改为你想要的密码
```

> ⚠️ 修改后需删除已有 `blog.db` 重新生成。

---

## 常见问题

### Q: 为什么富文本编辑器不显示？

编辑器是**零外部依赖**的纯前端实现，使用 `document.execCommand` API。请确认：
- 使用现代浏览器（Chrome / Firefox / Edge 最新版）
- 浏览器未禁用 JavaScript

### Q: 如何彻底重置数据？

```bash
# 清空所有表并重建（保留数据库）
mysql -u root -p hoshino_blog -e "DROP TABLE IF EXISTS users, posts, categories, comments;"
# 重启应用会自动重建表和默认管理员
python app.py
```

### Q: 发布文章时提示"链接标识已被使用"？

文章 Slug（URL 标识）必须全局唯一。换一个不同的 slug 即可。

### Q: 生产环境部署需要注意什么？

- 设置强 `SECRET_KEY` 环境变量
- 关闭调试模式（`FLASK_ENV=production`）
- 使用正式 WSGI 服务器（Gunicorn / uWSGI）
- 前端使用 Nginx 反向代理 + 静态文件托管

### Q: 图标显示不出来？

网站使用**内联 SVG 图标库**，无外部依赖。如果图标不显示，检查浏览器是否支持 SVG `<use>` 标签。

---

## License

MIT License

---

*HOSHINO Blog — 暗色科技风个人博客系统*

---

> 🤖 本项目由 **DeepSeek-V4-Pro** 辅助生成  
> 代码托管于 [GitCode](https://gitcode.com/hoshino5/polor_blog)
