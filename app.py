"""
HOSHINO Blog — Flask 应用入口

职责：
   创建并组装 Flask 应用实例，串联以下子系统：
   - 配置加载     （从 config.py + .env 合并）
   - 日志系统     （文件 + 终端，每日轮转）
   - 数据库       （SQLAlchemy + 自动建表 / 迁移）
   - 登录管理     （Flask-Login session 恢复）
   - 蓝图注册     （前台 blog_bp + 后台 admin_bp）
   - Gzip 压缩   （静态资源 & API 响应）
   - 请求日志     （每次 HTTP 请求的统一记录）

启动流程：
   1. 配置 / 日志 / 数据库 / Redis        — 同步（~200ms）
   2. API 客户端初始化（BestBuy/Keepa/Apify）— 同步（~10ms）
   3. Docker 浏览器池初始化               — 后台线程（~4s，不阻塞启动）
   4. 定时器 / 蓝图 / Gzip / 登录管理     — 同步（~10ms）
   → 应用在 1 秒内开始接受请求，后台初始化完成后自动就绪

使用方式：
   python app.py              # 直接开发运行
    gunicorn app:create_app()  # Linux 生产部署（需读取 .env）
    waitress-serve --port=5000 app:create_app  # Windows 生产部署
"""


import atexit
import os
import re

import time

from dotenv import load_dotenv
from flask import Flask, render_template, request
from flask_compress import Compress
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_migrate import Migrate

# ── 多密钥 session 支持 ─────────────────────────
# 默认 Flask 只用 SECRET_KEY 签名 session，
# 密钥轮换后旧 session 立即失效。
# 此接口在验签时逐一尝试所有历史密钥，保证轮换后不踢人。
from flask.sessions import SecureCookieSessionInterface
from itsdangerous import URLSafeTimedSerializer, BadSignature

class _MultiKeySessionInterface(SecureCookieSessionInterface):
    """支持 SECRET_KEY_FALLBACKS 的 session 接口。
    
    签名 → 只使用当前 SECRET_KEY（最新）
    验签 → 尝试当前密钥 + 所有历史密钥（SECRET_KEY_FALLBACKS）
    这样密钥轮换不会导致已登录用户的 session 失效。
    """

    def get_signing_serializer(self, app):
        secret_key = app.secret_key
        if not secret_key:
            return None
        fallbacks = app.config.get('SECRET_KEY_FALLBACKS', [])
        salt = self.get_cookie_salt(app)
        serializer = self.serializer
        signer_kwargs = dict(
            key_derivation=self.key_derivation,
            digest_method=self.digest_method,
        )

        primary = URLSafeTimedSerializer(
            secret_key, salt=salt, serializer=serializer, signer_kwargs=signer_kwargs
        )

        if not fallbacks:
            return primary  # 无历史密钥，退化为标准行为

        class _MultiKeyWrapper:
            """包装器：dumps 用当前密钥，loads 逐个尝试所有密钥。"""

            def dumps(self, obj):
                return primary.dumps(obj)

            def loads(self, s, max_age=None, return_timestamp=False):
                try:
                    return primary.loads(s, max_age=max_age, return_timestamp=return_timestamp)
                except BadSignature:
                    for fb_key in fallbacks:
                        try:
                            fb = URLSafeTimedSerializer(
                                fb_key,
                                salt=salt,
                                serializer=serializer,
                                signer_kwargs=signer_kwargs,
                            )
                            return fb.loads(s, max_age=max_age, return_timestamp=return_timestamp)
                        except BadSignature:
                            continue
                    raise

        return _MultiKeyWrapper()

    @staticmethod
    def get_cookie_salt(app):
        """Flask 默认 session cookie salt='cookie-session'"""
        return 'cookie-session'

# ── 环境变量加载 ──────────────────────────────
# load_dotenv() 必须在 Flask 应用创建之前执行，
# 确保所有后续 os.environ.get() 能读到 .env 文件中的值。
load_dotenv()

# Gzip 压缩实例（让静态资源和 API 响应更小）
# 在 create_app() 外部创建，确保全局唯一实例
compress = Compress()


_startup_time = time.time()


def create_app():
    """创建并配置完整的 Flask 应用实例。

    按顺序完成以下初始化步骤：
        1. 应用基础配置（config + 上传限制 + 连接池）
        2. CSRF 保护 & Gzip 参数
        3. 日志系统（文件 + 终端）
        4. 数据库（建表 + 迁移 + 默认管理员）
        5. Redis 缓存连接池
        6. 外部 API 爬虫（Amazon / B站）
        7. 定时任务（APScheduler）
        8. Flask-Login 登录管理
        9. 蓝图注册（前台 / 后台 / B站路由）
        10. 安全响应头 & 错误处理器
        11. 全局请求日志中间件

    返回:
        Flask: 配置完毕的应用实例
    """
    app = Flask(__name__, static_folder='blog/static')

    # ── 基础配置 ────────────────────────────────
    # 从 config.py 中 Config 类加载所有配置项
    app.config.from_object('config.ActiveConfig')
    # JSON 返回中文，不转义为 \\uXXXX
    app.config['JSON_AS_ASCII'] = False
    # 最大上传 200MB（支持 PDF/DOCX 导入）
    app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024
    # 表单字段内存大小上限（文章 HTML 内容经表单字段提交，默认 500KB 不够）
    app.config['MAX_FORM_MEMORY_SIZE'] = 100 * 1024 * 1024
    # 最大表单部件数
    app.config['MAX_FORM_PARTS'] = 2000
    # 静态文件缓存 — 7 天（文件内容变更时手动清浏览器缓存即可）
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 604800
    # 数据库连接池配置（Web 进程，不需要过大连接池）
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'pool_recycle': 280,
        'pool_timeout': 30,
        'pool_size': 10,
        'max_overflow': 10,
    }

    # ── CSRF 保护（全局，影响所有 POST/PUT/DELETE）──
    csrf = CSRFProtect(app)
    # Gzip 压缩哪些 MIME 类型
    app.config['COMPRESS_MIMETYPES'] = [
        'text/html',
        'text/css',
        'text/javascript',
        'application/json',
        'application/xml',
    ]
    app.config['COMPRESS_LEVEL'] = 6  # 压缩级别 1-9
    app.config['COMPRESS_MIN_SIZE'] = 500  # 小于 500 字节不压缩

    # ── 日志系统（必须在其他初始化之前） ────────────
    # 先初始化日志，后续所有模块的 logger 直接可用
    from blog.logger import log_request, setup_logging

    logger = setup_logging(app)
    logger.info('应用启动中...')

    # ── 确保上传目录存在 ──────────────────────────
    # 如果 static/uploads/ 目录不存在则自动创建
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # ── 数据库 ────────────────────────────────────
    # init_db() 内部执行：
    #   1. db.init_app(app)
    #   2. db.create_all()       —— 建表（不存在时）
    #   3. 自动迁移 v1→v2       —— 兼容旧版单分类数据
    #   4. 创建默认管理员        —— 首次启动时
    from blog import db, init_db

    # 所有进程（包括 Worker）都需要注册 db，否则数据库查询会报错
    db.init_app(app)

    # Worker 进程跳过建表和迁移（避免并发 DDL 冲突）
    if os.environ.get('WORKER_PROCESS') != '1':
        try:
            init_db(app)
        except Exception as e:
            logger.critical('数据库初始化失败: %s', e, exc_info=True)
            raise

    # Flask-Migrate（仅主进程注册，Worker 跳过）
    if 'migrate' not in app.extensions:
        migrate = Migrate(app, db)
    logger.info('数据库初始化完成')

    # ── Redis 缓存（数据库之后，蓝图之前） ────────
    # 初始化 Redis 连接池。如果 REDIS_URL 未配置，
    # 则静默降级（所有缓存操作直接返回 None，不影响业务）。
    from blog.cache import init_redis

    init_redis(app)

    # ── 任务队列初始化（复用 Redis 连接）──────────
    from blog.task_queue import init_task_queue
    init_task_queue(app)

    # ── Amazon 直爬（curl_cffi 模拟浏览器） ────
    from blog.apify_client import scraper

    # 配置爬虫代理（服务器在国内时必须使用海外代理才能访问 Amazon）
    scraper._proxy = app.config.get('SCRAPING_PROXY') or None
    logger.info(
        'Amazon 爬虫已就绪%s', '，代理: ' + scraper._proxy if scraper._proxy else '（无代理）'
    )

    # ── 加载 B站 持久化登录凭证 ──
    # 从本地文件读取 B站 cookie，确保爬虫使用已登录的账号身份
    from blog.bilibili.login import apply_cookies as _bili_apply_cookies

    _bili_apply_cookies()


    # ── 登录管理 ──────────────────────────────────
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'admin.login'  # 未登录时跳转
    login_manager.login_message = '请先登录'

    from blog.models import User

    @login_manager.user_loader
    def load_user(user_id):
        """Flask-Login 回调：从 session 中恢复用户对象。"""
        # Flask-Login 序列化时存的是 user.id，反序列化时调用此函数
        return db.session.get(User, int(user_id))

    # ── 多密钥 session 支持（SECRET_KEY 轮换不踢人） ──
    # 覆盖默认 session_interface，验签时逐一尝试所有历史密钥
    app.session_interface = _MultiKeySessionInterface()

    # ── 注册蓝图 ─────────────────────────────────
    # 前台 blueprint（URL 前缀为空，所有前台路由直接挂在 / 下）
    from blog import blog_bp

    app.register_blueprint(blog_bp)
    # 后台 blueprint（所有后台路由自动添加 /admin 前缀）
    from blog import admin_bp

    app.register_blueprint(admin_bp)
    # Bilibili 管理 blueprint
    from blog.bili_routes import bili_bp

    app.register_blueprint(bili_bp)
    # Bilibili 公开页面 blueprint
    from blog.bili_public_routes import bili_public_bp

    app.register_blueprint(bili_public_bp)
    logger.info('蓝图注册完成')

    # ── Gzip 压缩 ────────────────────────────────
    compress.init_app(app)
    logger.info('Gzip 压缩已启用')

    # ── 413 请求过大处理 ──────────────────────────
    from werkzeug.exceptions import RequestEntityTooLarge

    def _handle_413(e):
        """处理上传文件超出大小限制的请求。

        记录错误日志（含来源 IP 和路径）后返回友好的 HTML 提示页面。
        """
        logger.error(
            '413 REQUEST TOO LARGE: Content-Length=%s  Remote=%s  Path=%s',
            request.content_length,
            request.remote_addr,
            request.path,
        )
        return (
        f'<h1>413 Request Entity Too Large</h1><p>请求体过大 (Content-Length: {request.content_length})。'
        f'请减小文件或联系管理员。</p>',
        413,
        {'Content-Type': 'text/html; charset=utf-8'},
    )

    app.register_error_handler(RequestEntityTooLarge, _handle_413)

    # ── 通用错误页面 ────────────────────────────

    def _handle_404(e):
        """404 页面不存在。"""
        return render_template('errors/404.html'), 404

    def _handle_403(e):
        """403 权限不足。"""
        return render_template('errors/403.html'), 403

    def _handle_500(e):
        """500 服务器内部错误。"""
        return render_template('errors/500.html'), 500

    app.register_error_handler(404, _handle_404)
    app.register_error_handler(403, _handle_403)
    app.register_error_handler(500, _handle_500)

    # ── 全局请求日志中间件 ───────────────────────
    # 每次 HTTP 响应返回到客户端之前执行 log_request()
    app.after_request(log_request)

    # ── 安全响应头 ───────────────────────────────
    @app.after_request
    def add_security_headers(response):
        """为所有 HTTP 响应添加安全相关的响应头。

        包括：X-Content-Type-Options、X-Frame-Options、
        HSTS、Content-Security-Policy、Referrer-Policy、Permissions-Policy，
        防范常见 Web 攻击。
        """
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        # TODO: 迁移到 nonce-based CSP：将所有 inline script/style 移出为外部 .js/.css 文件，
        # 然后改用 'nonce-{nonce}' 替代 'unsafe-inline'，彻底杜绝 inline 注入风险。
        response.headers['Content-Security-Policy'] = (
            "default-src 'self';"
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net;"
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net;"
            "img-src 'self' data: https:;"
            "font-src 'self' data: https://fonts.gstatic.com;"
            "connect-src 'self' https:;"
            "frame-ancestors 'self'"
        )
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        return response

    # ── 请求结束时清理数据库 session ────────────
    from blog import db

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        """每次请求结束后自动关闭数据库 session，释放连接回连接池。"""
        db.session.remove()

    # ── Jinja 模板过滤器 ──────────────────────────
    @app.template_filter('paragraphify')
    def _jinja_paragraphify(text):
        if not text:
            return ''
        parts = re.split(r'(?<=[。！？])', text)
        parts = [p.strip() for p in parts if p.strip()]
        from markupsafe import Markup
        return Markup(''.join(f'<p style="margin:0 0 6px">{p}</p>' for p in parts))

    @app.template_filter('bleach_clean')
    def _jinja_bleach_clean(text):
        """Jinja 过滤器：对 HTML 内容进行 bleach 消毒，防止 XSS。

        用于替代 |safe，在渲染用户提交的 HTML 时确保安全。
        允许的标签和属性覆盖富文本编辑器所需的全部元素。
        """
        if not text:
            return ''
        import bleach
        allowed_tags = [
            'p', 'br', 'b', 'strong', 'i', 'em', 'u', 's', 'del',
            'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
            'ul', 'ol', 'li', 'blockquote', 'pre', 'code',
            'a', 'img', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
            'span', 'div', 'hr', 'sub', 'sup',
        ]
        allowed_attrs = {
            '*': ['class', 'id', 'style'],
            'a': ['href', 'title', 'target'],
            'img': ['src', 'alt', 'title', 'width', 'height'],
            'td': ['colspan', 'rowspan'],
            'th': ['colspan', 'rowspan'],
        }
        cleaned = bleach.clean(text, tags=allowed_tags, attributes=allowed_attrs, strip=True)
        from markupsafe import Markup
        return Markup(cleaned)

    elapsed = time.time() - _startup_time
    logger.info(
        '应用就绪 (%.2fs)  MAX_CONTENT_LENGTH=%dMB',
        elapsed,
        app.config['MAX_CONTENT_LENGTH'] / 1024 / 1024,
    )
    return app



if __name__ == '__main__':
    # ── 开发服务器启动 ──────────────────────────
    # 生产环境请使用 gunicorn (Linux) 或 waitress (Windows) 等 WSGI 服务器
    app = create_app()
    # 端口号优先从环境变量 PORT 读取，默认 5000
    port = int(os.environ.get('PORT', 5000))
    # 使用独立的 DEBUG 环境变量控制调试模式
    debug = os.environ.get('DEBUG', 'false').lower() in ('true', '1')
    host = '127.0.0.1' if debug else '0.0.0.0'
    logger = app.logger
    logger.info('=' * 50)
    logger.info('服务启动: http://%s:%d  debug=%s', host, port, debug)
    logger.info('=' * 50)

    # ── 启动后台 Worker 子进程 ──────────────────
    # Worker 进程共享同一日志文件（blog/logs/hoshino.log），
    # 终端输出通过 stderr 合并到同一控制台。
    # 使用 creationflags 确保子进程随父进程退出。
    import subprocess
    import sys as _sys

    worker_py = os.path.join(os.path.dirname(__file__), 'worker.py')
    _worker_proc = None

    def _start_worker():
        """启动 Worker 子进程，日志输出到同一 stderr。"""
        global _worker_proc
        if _worker_proc and _worker_proc.poll() is None:
            return
        kwargs = dict(
            stdout=subprocess.DEVNULL,
            stderr=_sys.stderr,
            stdin=subprocess.DEVNULL,
            cwd=os.path.dirname(__file__),
            env={**os.environ, 'WORKER_PROCESS': '1'},
        )
        # Windows: 创建子进程组，确保 Ctrl+C 能同时终止
        if os.name == 'nt':
            kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
        _worker_proc = subprocess.Popen([_sys.executable, worker_py], **kwargs)
        logger.info('后台 Worker 进程已启动 (PID: %d)', _worker_proc.pid)

    def _stop_worker():
        """安全停止 Worker 子进程。"""
        global _worker_proc
        if _worker_proc is None:
            return
        if _worker_proc.poll() is not None:
            _worker_proc = None
            return
        logger.info('正在停止 Worker 进程 (PID: %d)...', _worker_proc.pid)
        try:
            _worker_proc.terminate()
            _worker_proc.wait(timeout=10)
        except Exception:
            try:
                _worker_proc.kill()
                _worker_proc.wait(timeout=5)
            except Exception:
                pass
        logger.info('Worker 进程已停止')
        _worker_proc = None

    _start_worker()
    atexit.register(_stop_worker)

    # debug 模式下防止 Flask 热重载重复启动 Worker
    # use_reloader=False 确保主进程只启动一次
    app.run(host=host, port=port, debug=debug, use_reloader=False)
