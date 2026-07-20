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
import signal
import time

from dotenv import load_dotenv
from flask import Flask, request
from flask_compress import Compress
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_migrate import Migrate

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
    app = Flask(__name__)

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
    os.environ['MAX_CONTENT_LENGTH'] = str(200 * 1024 * 1024)
    # 静态文件缓存 — 7 天（文件内容变更时手动清浏览器缓存即可）
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 604800
    # 数据库连接池配置（B站爬取并发高，池子设大些）
    # 保留 config.py 中的 pool_pre_ping 设置
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'pool_recycle': 280,
        'pool_timeout': 30,
        'pool_size': 20,
        'max_overflow': 20,
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

    try:
        init_db(app)
    except Exception as e:
        logger.critical('数据库初始化失败: %s', e, exc_info=True)
        raise
    migrate = Migrate(app, db)
    logger.info('数据库初始化完成')

    # ── Redis 缓存（数据库之后，蓝图之前） ────────
    # 初始化 Redis 连接池。如果 REDIS_URL 未配置，
    # 则静默降级（所有缓存操作直接返回 None，不影响业务）。
    from blog.cache import init_redis

    init_redis(app)

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

    # ── 定时任务（价格爬虫 + SECRET_KEY 轮换） ──
    _init_scheduler(app)

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
            f'<h1>413 Request Entity Too Large</h1><p>请求体过大 (Content-Length: {request.content_length})，'
            f'当前限制: {app.config["MAX_CONTENT_LENGTH"] // 1024 // 1024}MB。'
            f'请减小文件或联系管理员。</p>',
            413,
            {'Content-Type': 'text/html; charset=utf-8'},
        )

    app.register_error_handler(RequestEntityTooLarge, _handle_413)

    # ── 全局请求日志中间件 ───────────────────────
    # 每次 HTTP 响应返回到客户端之前执行 log_request()
    app.after_request(log_request)

    # ── 安全响应头 ───────────────────────────────
    @app.after_request
    def add_security_headers(response):
        """为所有 HTTP 响应添加安全相关的响应头。

        包括：X-Content-Type-Options、X-Frame-Options、
        HSTS、Content-Security-Policy，防范常见 Web 攻击。
        """
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self';"
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net;"
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net;"
            "img-src 'self' data: https:;"
            "font-src 'self' https://fonts.gstatic.com;"
            "connect-src 'self';"
            "frame-ancestors 'self'"
        )
        return response

    # ── 请求结束时清理数据库 session ────────────
    from blog import db

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        """每次请求结束后自动关闭数据库 session，释放连接回连接池。"""
        db.session.remove()

    elapsed = time.time() - _startup_time
    logger.info(
        '应用就绪 (%.2fs)  MAX_CONTENT_LENGTH=%dMB',
        elapsed,
        app.config['MAX_CONTENT_LENGTH'] / 1024 / 1024,
    )
    return app


def _init_scheduler(app):
    """初始化 APScheduler 定时任务。

    定时任务清单：
      - 每天 02:00  深扫所有 B站 UP 主视频（补全 + 三层统计更新）
      - 每天 03:00  自动轮换 SECRET_KEY
      - 增量检查     B站 新视频（跑完一轮等 30 分钟再跑下一轮）
      - 每天 03:00  自动清理 B站 视频历史快照

    同时在进程退出和 SIGTERM 信号时执行安全关闭，避免挂起任务被杀死。
    """
    try:
        from datetime import datetime, timedelta
        from apscheduler.schedulers.background import BackgroundScheduler

        from config import rotate_secret_key

        scheduler = BackgroundScheduler()
        # 每天 03:00 自动轮换 SECRET_KEY
        scheduler.add_job(
            func=lambda: rotate_secret_key(app),
            trigger='cron',
            hour=3,
            minute=0,
            id='rotate_secret_key',
            replace_existing=True,
        )
        # 每天 02:00 深扫所有 UP 主 Hot/Warm/Cold 三层数据
        from blog.bili_routes import run_daily_scrape

        scheduler.add_job(
            func=lambda: run_daily_scrape(app),
            trigger='cron',
            hour=2,
            minute=0,
            id='daily_bili_refresh',
            replace_existing=True,
        )
        # B站 增量检查（首次 10 秒后触发，之后每轮跑完自调度 40 分钟）
        scheduler.add_job(
            func=lambda: _run_bili_incremental_check(app),
            trigger='date',
            run_date=datetime.now() + timedelta(seconds=10),
            id='bili_incremental_check',
            replace_existing=True,
        )
        # 每天 03:00 自动清理 B站视频历史快照（按 BiliCleanupConfig 配置）
        from blog.bili_routes import auto_cleanup_history

        scheduler.add_job(
            func=lambda: auto_cleanup_history(app),
            trigger='cron',
            hour=3,
            minute=0,
            id='bili_auto_cleanup',
            replace_existing=True,
        )
        scheduler.start()
        app.scheduler = scheduler

        # 注册进程退出时的清理函数
        # 在 Python 解释器正常退出时调用 scheduler.shutdown()
        def _shutdown_scheduler():
            """安全关闭调度器（忽略关闭过程中的异常）。"""
            try:
                scheduler.shutdown(wait=False)
            except Exception:
                pass
        atexit.register(_shutdown_scheduler)

        import signal
        import sys

        def _scheduler_sigterm(signum, frame):
            """SIGTERM 信号处理：关闭调度器后退出进程。"""
            _shutdown_scheduler()
            sys.exit(0)

        signal.signal(signal.SIGTERM, _scheduler_sigterm)

        app.logger.info('定时任务: 03:00密钥/清理 / 每30minB站增量 / 02:00B站深扫')
    except Exception as e:
        app.logger.warning('定时任务启动失败（不影响运行）: %s', e)


def _run_bili_incremental_check(app):
    """增量检查所有 B站 UP 主是否有新视频发布。

    分批并发执行，每批 _BATCH_SIZE 个 UP 主同时检查。
    线程之间通过 _scrape_lock 互斥，避免同一个 UP 主被重复检查。
    如果全局熔断（_circuit_open_until）未到期，则跳过本轮检查。

    跑完一轮后自动调度下一轮（间隔 30 分钟），形成持续的增量检查循环。
    """
    from datetime import datetime, timedelta

    with app.app_context():
        import logging
        import random
        import threading
        import time

        logger = logging.getLogger(__name__)
        from blog.models import BiliUp
        from blog.bili_routes import (
            _BATCH_SIZE,
            _check_new_videos,
            _scrape_progress,
            _incremental_running,
            _scrape_running,
            _scrape_lock,
            _circuit_open_until,
        )

        if time.time() < _circuit_open_until:
            remaining = int(_circuit_open_until - time.time()) // 60
            logger.warning('B站 增量检查取消: 全局熔断中，剩余 %d 分钟', remaining)
            return

        THREAD_TIMEOUT = 10 * 60

        ups = BiliUp.query.all()
        active: list = []
        for up in ups:
            mid = up.mid
            with _scrape_lock:
                if mid in _incremental_running or mid in _scrape_running:
                    continue
                _scrape_progress[mid] = []
                _incremental_running.add(mid)
            active.append(up)

        for i in range(0, len(active), _BATCH_SIZE):
            batch = active[i : i + _BATCH_SIZE]
            threads = []
            for up in batch:
                t = threading.Thread(
                    target=_check_new_videos,
                    args=(up.mid, app),
                    daemon=True,
                )
                t.start()
                threads.append(t)
                time.sleep(random.uniform(0.5, 2.0))
            for t in threads:
                t.join(timeout=THREAD_TIMEOUT)
                if t.is_alive():
                    logger.warning(
                        'B站 增量检查: 线程 %s 超时 (>%ds)，跳过', t.name, THREAD_TIMEOUT
                    )

    # 全部跑完 → 40 分钟后调度下一轮
    app.scheduler.add_job(
        func=lambda: _run_bili_incremental_check(app),
        trigger='date',
        run_date=datetime.now() + timedelta(minutes=30),
        id='bili_incremental_check',
        replace_existing=True,
    )
    app.logger.info('B站 增量检查完成，30 分钟后开始下一轮')


if __name__ == '__main__':
    # ── 开发服务器启动 ──────────────────────────
    # 生产环境请使用 gunicorn (Linux) 或 waitress (Windows) 等 WSGI 服务器
    app = create_app()
    # 端口号优先从环境变量 PORT 读取，默认 5000
    port = int(os.environ.get('PORT', 5000))
    # FLASK_ENV=development 时开启 debug 模式（热重载 + 详细错误页）
    debug = os.environ.get('FLASK_ENV') == 'development'
    host = '127.0.0.1' if debug else '0.0.0.0'
    logger = app.logger
    logger.info('=' * 50)
    logger.info('服务启动: http://%s:%d  debug=%s', host, port, debug)
    logger.info('=' * 50)
    app.run(host=host, port=port, debug=debug)
