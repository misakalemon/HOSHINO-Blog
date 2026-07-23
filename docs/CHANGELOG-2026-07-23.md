# HOSHINO Blog 开发日志 —— 2026-07-23

> 词云系统架构重铸 — 异步队列 + ZLIB 压缩 + UP 主页聚合词云 + 全站代码注释

---

## 词云异步改造

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/23 | feat | **新增 `submit_task()` 后台任务队列** — `blog/wordcloud.py` 新增 `_task_queue` + `_worker_loop` 单线程消费者 |
| 07/23 | refactor | **所有用户触发词云计算改为异步投递** — 发布/编辑/删除文章、手动重算、刷新UP评论/字幕后，不再同步执行 jieba 分词，HTTP 请求即时返回 |
| 07/23 | feat | `admin.py` 4 处同步调用 → `submit_task('post')` / `submit_task('site')` / `submit_task('all')` |
| 07/23 | feat | `bili_routes.py` 2 处同步调用 → `submit_task('bili_up', up_id=...)` |

### 队列设计

```
                submit_task('post', post_id=x)
                submit_task('site')
                submit_task('all')                ┌─────────────────┐
                submit_task('bili_up', up_id=x)   │  _worker_loop   │
                  ↓                               │  单线程守护线程  │
              _task_queue ──────────────────────→ │  with app_ctx:  │
                (Queue)                           │   分发到预计算函数│
                                                  └─────────────────┘
```

- 定时任务（02:10 / 02:15）不走队列，仍直接调用预计算函数
- `_wc_queue`（新视频入库词云）保持不变，仍由 `_wc_worker` 直接消费

## ZLIB 压缩存储

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/23 | feat | **新增 `CompressedJSON` TypeDecorator** — `blog/models.py`，写入自动 `zlib.compress()`，读取自动 `zlib.decompress()`，对业务代码完全透明 |
| 07/23 | feat | **自动迁移** — `blog/__init__.py` `_migrate_wordcloud_data_compress()`，启动时检查并压缩已有数据（MySQL COMPRESS → 标准 zlib 格式） |

## UP 主页聚合词云修复

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/23 | fix | **`precompute_up_wordclouds` 新增 UP 主聚合词云** — 刷新评论/字幕时，不仅更新单视频词云 (`source='bili_video'`)，还汇总全部文本刷新 UP 主页聚合词云 (`source='bili', period='up_{id}'`) |

此前刷新评论/字幕后，UP 主页词云仅在全量定时任务 02:15 更新，评论刷新不生效。

## 词云架构全貌

```
文本来源权重：字幕×5 > 标题×3 > 评论×2 > 标签×2 > 简介×1
存储格式：zlib 压缩 BLOB，每条 1~3KB
聚合维度：视频 → UP 主 → 月度 → 全站
计算入口：
  ├─ 定时 02:10  precompute_all_wordclouds()         博客全站+单篇
  ├─ 定时 02:15  precompute_bili_wordclouds()         B站全站+按月+按UP+单视频
  ├─ 后台队列    submit_task(type, **kwargs)          用户触发（4 种类型）
  └─ 视频队列    _wc_queue → _wc_worker              新视频入库增量
```

---

## 全站代码注释

为项目所有核心源码添加了详细的中文注释，包括模块级文档字符串、函数级 docstring、关键逻辑行内注释。

### 注释范围

| 文件 | 注释内容 |
|------|------|
| `app.py` | 模块文档（启动流程/职责/使用方式）、`create_app()` 步骤说明、`_init_scheduler()` 定时任务清单、安全响应头说明、413 错误处理器 |
| `config.py` | 模块文档（配置加载优先级）、SECRET_KEY 轮换机制详解、`_build_database_uri()` 连接串构造逻辑、`Config` 类各配置项分组注释 |
| `blog/__init__.py` | 模块文档（蓝图注册/导入顺序约定）、`inline_html` 模板过滤器 CSS 作用域化三步流程、`init_db()` 迁移函数链说明 |
| `blog/models.py` | 模块文档（模型分组/关联关系摘要）、每个 Model 的字段级注释、`CompressedJSON` TypeDecorator 读写逻辑、角色常量/属性说明 |
| `blog/routes.py` | 模块文档（函数列表）、XSS 过滤白名单、`_get_sidebar_data()` 并行查询说明、缩略图生成流程、全文搜索降级策略 |
| `blog/admin.py` | 模块文档（功能模块/函数列表）、HTML 净化白名单、权限装饰器说明、登录频率限制实现、图片上传安全校验（Magic Bytes） |
| `blog/bili_routes.py` | 模块文档（爬取架构/线程安全/防封机制）、共享状态变量注释、`_insert_or_update_video()` 入库逻辑、`_crawl_video_comments()` 分页爬取 |
| `blog/bili_public_routes.py` | 模块文档（公开路由/速率限制）、`_RateLimitDict` 淘汰策略、订阅验证/取消流程 |
| `blog/mail.py` | 模块文档（配置项/使用方式）、RFC 5322 Header 编码、异步发送线程池管理 |
| `blog/cache.py` | 模块文档（缓存键命名/支持项/使用方式/依赖）、`_get_redis()` 重试机制、SCAN 非阻塞遍历 |
| `blog/wordcloud.py` | 模块文档、`submit_task()` 任务类型说明、停用词表分类注释、`_bili_texts_from_videos()` 权重逻辑、GC 内存管理 |
| `blog/forms.py` | 模块文档（WTForms 技术要点）、每个表单的字段级注释、验证器说明 |

### 注释风格

- **模块级文档字符串**：职责、使用方式、技术要点
- **函数级 docstring**：Args/Returns/Raises（Google 风格）
- **行内注释**：关键业务逻辑、安全考量、性能优化原因
- **分隔线**：`# ──` 标记配置分组，`# ══` 标记路由分区

---

## README 更新

| 更新项 | 说明 |
|------|------|
| 技术栈表格 | 补充 Flask-Migrate、APScheduler、Flask-Compress、bilibili-api-python、jieba、Docker Compose、Ruff 等 |
| 项目结构 | 补充 `blog/wordcloud.py`、`blog/logger.py`、`blog/apify_client.py`、`scripts/`、`docs/`、`migrations/` |
| 数据库模型 | 补充 BiliVideoComment、WordCloudConfig、WordCloudData、CompressedJSON |
| 词云系统 | 新增完整章节：架构总览/存储模型/计算入口/前端渲染/异步安全 |
| 环境要求 | 更新为 Python 3.11+ |
| 开发日志 | 新增本条记录 |

---

## 涉及文件

| 文件 | 改动 |
|------|------|
| `blog/models.py` | +CompressedJSON TypeDecorator（zlib 透明压缩）+ 全量字段注释 |
| `blog/wordcloud.py` | +_task_queue / _ensure_worker / _worker_loop / submit_task；precompute_up_wordclouds 末尾追加 UP 聚合词云 + 模块文档 |
| `blog/__init__.py` | +_migrate_wordcloud_data_compress 迁移函数 + inline_html 过滤器注释 |
| `blog/admin.py` | 4 处 submit_task 替换同步调用 + 全量函数注释 |
| `blog/bili_routes.py` | 2 处 submit_task 替换同步调用 + 爬取架构注释 |
| `blog/bili_public_routes.py` | + 速率限制/订阅流程注释 |
| `blog/mail.py` | + RFC 5322/异步发送注释 |
| `blog/cache.py` | + Redis 降级/SCAN 遍历注释 |
| `blog/forms.py` | + 表单字段级注释 |
| `blog/routes.py` | + XSS 过滤/搜索降级/缩略图注释 |
| `app.py` | + 启动流程/定时任务/安全头注释 |
| `config.py` | + 配置优先级/SECRET_KEY 轮换注释 |
| `README.md` | 技术栈/结构/模型/词云章节更新 |

---

## 文档与注释完善（第二轮）

在第一轮注释基础上，进一步补充前端 JS/CSS 注释、Python 模块深度注释、README 修正。

### 前端注释

| 文件 | 注释内容 |
|------|------|
| `static/js/base.js` | 模块级 JSDoc、导航渐显逻辑、抽屉菜单交互、灯箱组件、glow-select 自定义下拉框完整交互流程 |
| `static/js/admin.js` | Toast 提示系统、侧边栏切换、图片裁剪工具（浮动裁剪框模式）完整流程、富文本编辑器命令说明 |
| `static/js/tools.js` | 各工具函数（Base64/字数统计/颜色转换/JSON 格式化/哈希计算/时间戳转换/密码生成器）JSDoc |
| `static/js/cookie-banner.js` | Cookie 横幅交互逻辑、localStorage 持久化、自动接受超时 |
| `static/js/wordcloud.js` | 螺旋布局算法、碰撞检测、形状裁剪、配色方案、交互事件 |
| `static/js/particle-hero.js` | WebGL 着色器说明、粒子物理模拟、鼠标交互、滚动散开、散开/汇聚切换 |
| `static/css/glow-design.css` | CSS 变量分组注释、组件样式块注释、响应式断点说明 |

### Python 深度注释

| 文件 | 注释内容 |
|------|------|
| `blog/wordcloud.py` | `precompute_post_wordcloud` / `precompute_site_wordcloud` / `precompute_bili_wordclouds` / `precompute_up_wordclouds` 完整 docstring + 权重逻辑行内注释 |
| `blog/bili_routes.py` | `_run_scrape` 三层更新策略、`_insert_or_update_video` 入库逻辑、`_crawl_video_comments` 分页爬取、`_check_new_videos` 双路径发现 |
| `blog/bilibili/bili_api.py` | `get_video_list` / `get_video_stat` / `get_user_info` / `get_dynamics_new` / `check_relation` 完整参数返回注释 |
| `blog/bilibili/login.py` | V2 扫码登录完整流程、Cookie/Credential 双持久化、`apply_cookies` 优先级链 |
| `blog/__init__.py` | 20+ 迁移函数逐行注释、`init_db` 完整流程说明 |

### README 修正

| 修正项 | 说明 |
|------|------|
| 重复段落 | 移除项目结构中 `bilibili/` 目录的重复条目 |
| 脚本目录 | 补充 `scripts/` 目录说明 |
| 文档目录 | 更新 CHANGELOG 数量为 12 个 |
| 开发辅助 | 补充 DeepSeek-V4-Pro + AtomCode 辅助开发说明 |

---

## 涉及文件（第二轮）

| 文件 | 改动 |
|------|------|
| `static/js/base.js` | + 模块级 JSDoc + 函数注释 |
| `static/js/admin.js` | + Toast/裁剪/编辑器函数注释 |
| `static/js/tools.js` | + 各工具函数 JSDoc |
| `static/js/cookie-banner.js` | + 交互逻辑注释 |
| `static/js/wordcloud.js` | + 布局/碰撞/形状/配色注释 |
| `static/js/particle-hero.js` | + WebGL/物理/交互注释 |
| `static/css/glow-design.css` | + 变量分组/组件块注释 |
| `blog/wordcloud.py` | + 预计算函数完整 docstring |
| `blog/bili_routes.py` | + 爬取逻辑深度注释 |
| `blog/bilibili/bili_api.py` | + API 方法参数/返回注释 |
| `blog/bilibili/login.py` | + 扫码登录流程注释 |
| `blog/__init__.py` | + 迁移函数逐行注释 |
| `README.md` | 修复重复段落 + 补充缺失信息 |

---

## 文档与注释完善（第三轮）

在前两轮基础上，补齐剩余模板文件头注释、JS 引擎文件内部函数 JSDoc。

### 模板注释补齐

| 文件 | 注释内容 |
|------|------|
| `templates/mail/verify_subscription.html` | 邮件模板 — 订阅确认页文件头注释（上下文变量说明） |
| `templates/mail/new_video_notify.html` | 邮件模板 — 新视频通知页文件头注释（上下文变量说明） |
| `templates/admin/_cookie_banner.html` | 组件片段 — Cookie 同意横幅文件头注释 |

### JS 引擎函数级 JSDoc

| 文件 | 注释内容 |
|------|------|
| `static/js/particle-hero.js` | 12 个函数完整 JSDoc：compileShader / resize / sampleImage / computeRect / buildParticles / remapHomes / makeSprite / buildMotes / draw / step / loop / setMode / toggleScatter |
| `static/js/wordcloud.js` | 14 个函数完整 JSDoc：getPalette / randomColor / mapFontSize / rectsOverlap / measureText / isInsideShape / _loadShapeImage / _isInsideCustom / _isInsideCircle / _isInsideStar / _isInsideHeart / _isInsideCloud / _renderWordCloud |

### 涉及文件（第三轮）

| 文件 | 改动 |
|------|------|
| `templates/mail/verify_subscription.html` | + 文件头注释 |
| `templates/mail/new_video_notify.html` | + 文件头注释 |
| `templates/admin/_cookie_banner.html` | + 文件头注释 |
| `static/js/particle-hero.js` | + 12 个函数 JSDoc |
| `static/js/wordcloud.js` | + 14 个函数 JSDoc |
