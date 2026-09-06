# HOSHINO Blog 项目结构

## 目录总览

```
hoshino-blog/
├── app.py                  # Flask 应用工厂（create_app）
├── worker.py               # Worker 进程（定时任务/爬虫/词云调度）
├── config.py               # 配置（数据库/Redis/密钥等）
├── launcher.py             # 进程启动器（Web + Worker）
├── seed_data.py            # 初始数据填充
├── start.bat / stop.bat    # Windows 启停脚本
│
├── blog/                   # 主包
│   ├── __init__.py         # 包初始化（蓝图声明/模型导入/迁移函数）
│   ├── core/               # 核心业务逻辑
│   │   ├── models.py       # SQLAlchemy ORM 模型
│+ posts_md     — 文章导出为 Markdown zip（每篇一个 .md，含 YAML front matter）
│   │   ├── admin.py        # 后台管理路由（/admin/*）
│   │   ├── routes.py       # 前台路由（首页/文章/分类/评论/联系）
│   │   ├── api.py          # 外部 API 蓝图（/api/v1/*）
│   │   ├── forms.py        # WTForms 表单定义
│   │   ├── cache.py        # Redis 缓存封装
│   │   ├── settings.py     # 站点设置（DB 驱动，运行时可改）
│   │   └── utils.py        # 通用工具函数
│   ├── bilibili/           # B站相关
│   │   ├── bili_api.py     # B站 API 客户端
│   │   ├── admin_routes.py # B站管理路由（/admin/bilibili/*）
│   │   ├── public_routes.py# B站公开路由（/bilibili/*）
│   │   ├── config.py       # B站爬取配置
│   │   └── login.py        # B站登录（QR Code）
│   ├── infra/              # 基础设施
│   │   ├── logger.py       # 日志系统（跨进程文件锁）
│   │   ├── logwatch.py     # 日志监控/告警
│   │   ├── mail.py         # 邮件发送
│   │   ├── task_queue.py   # 任务队列（Redis 驱动）
│   │   └── backup.py       # 数据备份/恢复/清理
│   ├── wordcloud/          # 词云
│   │   ├── generator.py    # 词云生成（分词/词频/渲染）
│   │   └── runner.py       # 独立词云子进程入口
│   └── logs/               # 日志文件输出目录
│
├── templates/              # Jinja2 模板
│   ├── base.html           # 前台基础布局
│   ├── index.html          # 首页
│   ├── single-post.html    # 文章详情（Markdown 模式）
│   ├── html-post.html      # 文章详情（HTML 模式）
│   ├── admin/              # 后台模板
│   │   ├── base_admin.html # 后台基础布局
│   │   ├── post-form.html  # 文章编辑
│   │   ├── backup.html     # 备份管理 + 定时设置
│   │   ├── token-list.html # API 令牌管理
│   │   ├── export.html     # 数据导出
│   │   ├── import.html     # 数据导入
│   │   └── ...
│   ├── errors/             # 错误页
│   ├── mail/               # 邮件模板
│   └── _sidebar.html       # 侧边栏
│
├── static/                 # 静态资源
│   ├── css/                # 样式表
│   ├── js/                 # JavaScript
│   ├── font/               # 字体
│   ├── images/             # 图片
│   ├── uploads/            # 用户上传文件
│   └── vendor/             # 第三方库
│
├── tests/                  # 测试套件
│   ├── conftest.py         # pytest 配置（SQLite/MySQL 双后端）
│   ├── test_api.py         # API 蓝图测试
│   ├── test_backup.py      # 备份模块测试
│   ├── test_cache.py       # 缓存模块测试
│   ├── test_models.py      # 模型测试
│   ├── test_routes.py      # 路由测试
│   ├── test_security.py    # 安全测试
│   ├── test_settings.py    # 设置模块测试
│   ├── test_task_queue.py  # 任务队列测试
│   └── test_utils.py       # 工具函数测试
│
├── tools/                  # 工具与运维脚本
│   ├── upload_post.py      # 文章上传工具（md → API → 发布）
│   ├── restructure.py      # 项目重构脚本（一次性）
│   ├── bili_daily_scrape.py # B站每日全量爬取
│   ├── bili_incremental.py  # B站增量爬取
│   ├── fix_db_schema.py     # 数据库 schema 修复
│   └── fix_timestamps.py    # 时间戳修复
│
├── docs/                   # 文档
│   ├── ARCHITECTURE.md
│   ├── TECHNICAL_DOCUMENTATION.md
│   ├── MYSQL_SETUP.md
│   └── changelog/          # 历史变更日志（归档）
│
├── migrations/             # Alembic 数据库迁移
├── src/                    # 前端源码（编辑器等）
├── .env.example            # 环境变量模板
├── requirements.txt        # Python 依赖
├── pyproject.toml          # 项目配置（pytest/lint）
└── docker-compose.yml      # Docker 编排
```

## 模块职责

### blog/core/ — 核心业务

| 模块 | 职责 |
|------|------|
| `models.py` | 所有 SQLAlchemy ORM 模型（User/Post/Category/Comment 等） |
| `admin.py` | 后台管理路由（文章/分类/评论/用户/备份/设置/媒体/导出/导入 CRUD） |
| `routes.py` | 前台路由（首页/文章详情/分类/评论/联系/关于/RSS） |
| `api.py` | 外部 API（Bearer token 认证，文章 CRUD，供 AI agent 发布博文） |
| `forms.py` | WTForms 表单定义（文章/分类/评论/用户等表单） |
| `cache.py` | Redis 缓存封装（page 缓存/侧边栏缓存/失效） |
| `settings.py` | 站点设置（DB 驱动，运行时可改，含统计脚本渲染） |
| `utils.py` | 通用工具（时间/LRU/限流/URL 校验/LIKE 转义） |

### blog/bilibili/ — B站相关

| 模块 | 职责 |
|------|------|
| `bili_api.py` | B站 API 客户端（视频/弹幕/评论/字幕抓取） |
| `admin_routes.py` | B站管理路由（UP主管理/视频抓取/增量更新） |
| `public_routes.py` | B站公开路由（视频对比/详情/词云展示） |
| `config.py` | B站爬取配置（频率/重试/UA） |
| `login.py` | B站登录（QR Code 扫码） |

### blog/infra/ — 基础设施

| 模块 | 职责 |
|------|------|
| `logger.py` | 日志系统（每日轮转/跨进程文件锁/进程标签） |
| `logwatch.py` | 日志监控（异常告警/邮件通知） |
| `mail.py` | 邮件发送（验证/通知/批量） |
| `task_queue.py` | 任务队列（Redis 驱动/签名验证/重试） |
| `backup.py` | 数据备份/恢复/清理（JSON 导出/zip 打包/定时清理） |

### blog/wordcloud/ — 词云

| 模块 | 职责 |
|------|------|
| `generator.py` | 词云生成（jieba 分词/词频统计/权重计算/渲染） |
| `runner.py` | 独立词云子进程入口（与 Worker 隔离 GIL） |

## 进程架构

```
launcher.py
├── Web 进程 (app.py)
│   └── 处理 HTTP 请求（前台 + 后台 + API）
└── Worker 进程 (worker.py)
    ├── APScheduler 定时任务
    │   ├── 密钥轮换（03:00）
    │   ├── 数据备份（可配置，默认 01:00）
    │   ├── B站每日深扫（02:00）
    │   └── 词云预计算（04:00/04:30）
    └── 任务队列消费者（爬虫/评论/弹幕/词云）
```

## 部署流程

```bash
# 本地
git add -A && git commit -m "..." && git push

# 服务器
git pull && 重启 Web + Worker 进程
```