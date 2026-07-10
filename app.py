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
import os
import time

from dotenv import load_dotenv
from flask import Flask, request
from flask_compress import Compress
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect

# ── 环境变量加载 ──────────────────────────────
# load_dotenv() 必须在 Flask 应用创建之前执行，
# 确保所有后续 os.environ.get() 能读到 .env 文件中的值。
load_dotenv()

# Gzip 压缩实例（让静态资源和 API 响应更小）
compress = Compress()


_startup_time = time.time()


def create_app():
    """创建并配置 Flask 应用。"""
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

    # ── CSRF 保护（全局，影响所有 POST/PUT/DELETE）──
    csrf = CSRFProtect(app)
    # Gzip 压缩哪些 MIME 类型
    app.config['COMPRESS_MIMETYPES'] = [
        'text/html', 'text/css', 'text/javascript',
        'application/json', 'application/xml'
    ]
    app.config['COMPRESS_LEVEL'] = 6       # 压缩级别 1-9
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
    init_db(app)
    logger.info('数据库初始化完成')

    # ── Redis 缓存（数据库之后，蓝图之前） ────────
    # 初始化 Redis 连接池。如果 REDIS_URL 未配置，
    # 则静默降级（所有缓存操作直接返回 None，不影响业务）。
    from blog.cache import init_redis
    init_redis(app)

    # ── Amazon 直爬（curl_cffi 模拟浏览器） ────
    from blog.apify_client import scraper
    scraper._proxy = app.config.get('SCRAPING_PROXY') or None
    logger.info('Amazon 爬虫已就绪%s',
                '，代理: ' + scraper._proxy if scraper._proxy else '（无代理）')

    # ── Exa API（海外价格搜索引擎，绕过 GFW） ──
    from blog.exa_client import ExaClient
    app.exa_client = ExaClient(app.config.get('EXA_API_KEY', ''))
    if app.exa_client._ready:
        logger.info('Exa 客户端已就绪')
        # 将启动时获取的汇率写入数据库
        from blog.models import ExchangeRate
        with app.app_context():
            for currency, rate in app.exa_client._rates.items():
                existing = ExchangeRate.query.filter_by(
                    currency=currency
                ).order_by(ExchangeRate.recorded_at.desc()).first()
                if not existing or abs(existing.rate - rate) / rate > 0.001:
                    db.session.add(ExchangeRate(
                        currency=currency, rate=rate
                    ))
            db.session.commit()
    else:
        logger.info('Exa 未配置（EXA_API_KEY 为空），跳过')

    # ── 定时任务（价格爬虫 + SECRET_KEY 轮换） ──
    _init_scheduler(app)

    # ── 登录管理 ──────────────────────────────────
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'admin.login'       # 未登录时跳转
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
    # 价格追踪 blueprint（所有价格路由自动添加 /prices 前缀）
    from blog import price_bp
    app.register_blueprint(price_bp)
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
    app.register_error_handler(RequestEntityTooLarge, lambda e: (
        logger.error('413 REQUEST TOO LARGE: Content-Length=%s  Remote=%s  Path=%s',
                     request.content_length, request.remote_addr, request.path),
        (f'<h1>413 Request Entity Too Large</h1><p>请求体过大 (Content-Length: {request.content_length})，'
         f'当前限制: {app.config["MAX_CONTENT_LENGTH"]//1024//1024}MB。'
         f'请减小文件或联系管理员。</p>', 413, {'Content-Type': 'text/html; charset=utf-8'})
    )[1])

    # ── 全局请求日志中间件 ───────────────────────
    # 每次 HTTP 响应返回到客户端之前执行 log_request()
    app.after_request(log_request)

    elapsed = time.time() - _startup_time
    logger.info('应用就绪 (%.2fs)  MAX_CONTENT_LENGTH=%dMB', elapsed, app.config['MAX_CONTENT_LENGTH'] / 1024 / 1024)
    return app


def _init_scheduler(app):
    """初始化 APScheduler 定时任务。

    - 每天 09:00 自动爬取所有启用的商品价格
    - 每天 03:00 自动轮换 SECRET_KEY
    如果 APScheduler 未安装或导入失败，静默跳过。
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler

        from config import rotate_secret_key
        scheduler = BackgroundScheduler()
        # 每天 09:00 执行
        scheduler.add_job(
            func=lambda: _run_daily_crawl(app),
            trigger='cron',
            hour=9,
            minute=0,
            id='daily_price_crawl',
            replace_existing=True,
        )
        # 每天 03:00 自动轮换 SECRET_KEY
        scheduler.add_job(
            func=lambda: rotate_secret_key(app),
            trigger='cron',
            hour=3,
            minute=0,
            id='rotate_secret_key',
            replace_existing=True,
        )
        # 每天 02:00 重新爬取所有 B站 UP 主视频
        scheduler.add_job(
            func=lambda: _run_daily_bili_refresh(app),
            trigger='cron',
            hour=2,
            minute=0,
            id='daily_bili_refresh',
            replace_existing=True,
        )
        # 每 30 分钟增量检查 B站 新视频
        scheduler.add_job(
            func=lambda: _run_bili_incremental_check(app),
            trigger='interval',
            minutes=30,
            id='bili_incremental_check',
            replace_existing=True,
        )
        scheduler.start()
        app.logger.info('定时任务: 09:00价格 / 03:00密钥 / 02:00B站全量 / 每30minB站增量')
    except Exception as e:
        app.logger.warning('定时任务启动失败（不影响运行）: %s', e)


def _run_daily_crawl(app):
    """执行每日价格爬取（在应用上下文中运行）。"""
    with app.app_context():
        from blog.crawler import crawl_all_active_sources
        count = crawl_all_active_sources()
        app.logger.info('每日价格爬取完成: %d 条记录', count)


def _run_daily_bili_refresh(app):
    """每日刷新所有 B站 UP 主视频数据（在应用上下文中运行）。"""
    with app.app_context():
        import logging
        logger = logging.getLogger(__name__)
        from blog.models import BiliUp
        from blog.bili_routes import _run_scrape as _bili_scrape

        ups = BiliUp.query.all()
        logger.info('B站 每日刷新启动: 共 %d 个 UP 主', len(ups))
        for up in ups:
            try:
                _bili_scrape(up.mid, up.space_url, app, max_videos=20)
                logger.info('B站 刷新完成: %s (mid=%d)', up.name or '?', up.mid)
            except Exception as e:
                logger.error('B站 刷新失败: mid=%d, %s', up.mid, e)
        logger.info('B站 每日刷新完成')


def _run_bili_incremental_check(app):
    """每 30 分钟增量检查所有 UP 主是否有新视频"""
    with app.app_context():
        import logging
        logger = logging.getLogger(__name__)
        from blog.models import BiliUp
        from blog.bili_routes import _check_new_videos

        ups = BiliUp.query.all()
        for up in ups:
            try:
                _check_new_videos(up.mid, app)
            except Exception as e:
                logger.error('B站 增量检查失败: mid=%d, %s', up.mid, e)


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
    app.run(host='0.0.0.0', port=port, debug=debug)
