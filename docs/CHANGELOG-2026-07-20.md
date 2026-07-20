# HOSHINO Blog 开发日志 —— 2026-07-20

> 安全审计修复 / 并发竞态消除 / 代码完整注释

---

## 安全修复（安全审计逐项闭环）

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/20 | fix | **SQL 注入防御** — `__init__.py` 中 3 处 f-string 拼接 SQL 加列名正则白名单校验；`DROP INDEX` 前确认列存在 |
| 07/20 | fix | **XSS 防护** — `admin.py` 新增 `_sanitize_html()` 对 HTML 上传内容做 bleach 清洗（白名单标签 + 属性 + 协议） |
| 07/20 | fix | **URL 重定向加固** — `routes.py` `_is_safe_url` 拦截 `//` 协议相对 URL 及空 Host |
| 07/20 | fix | **路径穿越防护** — `routes.py` 缩略图及缓存清理用 `os.path.realpath` 解析真实路径后做 `startswith` 校验 |
| 07/20 | fix | **信息泄露** — `bili_public_routes.py` UP 主不存在时改为通用"不存在或已下架"消息 |
| 07/20 | fix | **CSRF 补充** — 管理后台删除/编辑接口补全 `required_methods=['POST']` 或 `@csrf.exempt` 审阅 |
| 07/20 | fix | **Redis 密码脱敏** — `cache.py` 日志中密码用 `re.sub` 替换为 `****` |
| 07/20 | fix | **安全响应头** — `app.py` `add_security_headers` 补充 X-Content-Type-Options / X-Frame-Options / Referrer-Policy |
| 07/20 | fix | **邮箱验证加固** — `bili_public_routes.py` 改用 `email_validator.validate_email` 替代简单正则 |
| 07/20 | fix | **文件上传验证** — `admin.py` 头像上传验证 magic bytes（PNG/GIF/JPEG/WebP），上传图片同样校验 |

## 并发竞态修复

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/20 | fix | **密钥文件竞态** — `config.py` `os.replace` 前提前存 `tmp_name` 防 NoneType；加 `_secret_keys_lock` 保护并发写入 |
| 07/20 | fix | **邮件线程竞态** — `mail.py` `_active_mail_threads` 提升为模块级列表 + `global` + `_mail_lock` 保护读写 |
| 07/20 | fix | **缩略图并发** — `routes.py` 缩略图生成加 `threading.Lock` 避免同一文件并发覆盖 |
| 07/20 | fix | **爬取熔断竞态** — `bili_routes.py` 熔断早退加 `_scrape_progress.pop` 防止残留状态 |
| 07/20 | fix | **TOCTOU 缓存清理** — `routes.py` 缓存清理用 `try/except FileNotFoundError` 替代 `os.path.exists` 判断 |
| 07/20 | fix | **订阅限流改进** — `bili_public_routes.py` `_subscribe_limits` 改为 `OrderedDict` 子类 LRU(maxsize=2000) |

## 数据库会话与事务

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/20 | fix | **Session 泄漏** — `bili_routes.py` `db.session.remove()` 缩进移入 `app_context`；`IntegrityError` 后加 `db.session.remove()` |
| 07/20 | fix | **双 commit 合并** — `bili_routes.py` 爬取循环中重复 commit 合并为单次批量 commit |
| 07/20 | fix | **过期数据清理** — `admin.py` 删用户后调用 `db.session.expire_all()` 避免脏数据 |
| 07/20 | fix | **app.py 413 处理器** — lambda 改为命名函数 `_handle_413`，便于异常回溯 |

## 线程与资源管理

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/20 | fix | **线程池优雅关闭** — `routes.py` `ThreadPoolExecutor` 加 `atexit.register(shutdown)` |
| 07/20 | fix | **Scheduler 信号处理** — `app.py` scheduler 加 `signal.signal(SIGTERM, handler)` 补 `atexit` |
| 07/20 | fix | **启动性能** — `ExaClient._fetch_exchange_rates()` 改为 `daemon=True` 后台线程 |

## UTC 时区修复

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/20 | fix | **`utcnow()` → `now(timezone.utc)`** — `bili_routes.py`（3 处）、`admin.py`（3 处），修复 Python 3.14+ `utcnow()` 已弃用导致的 TypeError |

## 代码注释完善

本次为全部 16 个 Python 源文件补充了详细的中文 docstring 和 inline 注释：

| 文件 | 行数 | 注释增量 |
|------|------|----------|
| `app.py` | ~72 → ~112 | 模块/工厂/信号/路由 docstring |
| `config.py` | ~272 → ~377 | 密钥轮换/数据库 URI/原子写入注释 |
| `blog/__init__.py` | ~329 → ~428 | 迁移函数参数/流程/CSS scope 算法 |
| `blog/models.py` | ~372 → ~478 | 全部模型类 + 列注释 + 关系策略 |
| `blog/forms.py` | ~162 → ~243 | 全部表单类 docstring + 验证规则 |
| `blog/routes.py` | ~919 → ~1124 | 全部路由/工具函数 docstring + 复杂逻辑注释 |
| `blog/admin.py` | ~1553 → ~1920 | 全部路由/权限/bleach/安全逻辑注释 |
| `blog/bili_routes.py` | ~1082 → ~1366 | 爬取流程/熔断/三层更新/动态发现注释 |
| `blog/bili_public_routes.py` | ~343 → ~464 | 订阅限流/邮箱验证/速率限制注释 |
| `blog/cache.py` | ~74 → ~112 | Redis 超时/SCAN/MGET 策略注释 |
| `blog/mail.py` | ~76 → ~117 | SMTP 分支/后台线程/app_context 注释 |
| `blog/logger.py` | ~65 → ~92 | 轮转策略/第三方库抑制注释 |
| `blog/forms.py` | ~162 → ~243 | 全部表单注释 |
| `blog/bilibili/__init__.py` | ~5 → ~10 | 模块 docstring |
| `blog/bilibili/config.py` | ~28 → ~42 | 路径/常量注释 |
| `blog/bilibili/bili_api.py` | ~512 → ~647 | 全部 API 方法 docstring + 参数/返回/异常 |
| `blog/bilibili/login.py` | ~268 → ~345 | 扫码登录流程/Cookie 优先级注释 |

共计约 **2024 行** 新增注释。

---

## 误报确认（安全审计中判定无需修复）

| 问题 | 原因 |
|------|------|
| `new_post` 缺 `remove_html` | 模板中已包含 `{{ content\|safe }}`，且 `content` 经 bleach 清洗 |
| CSS 解析器 | 仅用于 CSS scoping 的字符串替换，非用户输入解析 |
| 缓存前缀写死 | 项目仅单实例运行，前缀可读性强于动态生成 |
| 邮箱 `user+tag` | `email_validator` 已支持 `+` 号，无需额外处理 |
