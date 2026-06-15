# -*- coding: utf-8 -*-
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

使用方式：
  python app.py              # 直接开发运行
  gunicorn app:create_app()  # 生产部署（需读取 .env）
"""
import os
from flask import Flask
from flask_login import LoginManager
from flask_compress import Compress
from dotenv import load_dotenv

# ── 环境变量加载 ──────────────────────────────
# load_dotenv() 必须在 Flask 应用创建之前执行，
# 确保所有后续 os.environ.get() 能读到 .env 文件中的值。
load_dotenv()

# Gzip 压缩实例（让静态资源和 API 响应更小）
compress = Compress()


def create_app():
    """创建并配置 Flask 应用。"""
    app = Flask(__name__)

    # ── 基础配置 ────────────────────────────────
    # 从 config.py 中 Config 类加载所有配置项
    app.config.from_object('config.ActiveConfig')
    # JSON 返回中文，不转义为 \\uXXXX
    app.config['JSON_AS_ASCII'] = False
    # 最大上传 16MB
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
    # Gzip 压缩哪些 MIME 类型
    app.config['COMPRESS_MIMETYPES'] = [
        'text/html', 'text/css', 'text/javascript',
        'application/json', 'application/xml'
    ]
    app.config['COMPRESS_LEVEL'] = 6       # 压缩级别 1-9
    app.config['COMPRESS_MIN_SIZE'] = 500  # 小于 500 字节不压缩

    # ── 日志系统（必须在其他初始化之前） ────────────
    # 先初始化日志，后续所有模块的 logger 直接可用
    from blog.logger import setup_logging, log_request
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
    from blog import init_db, db
    init_db(app)
    logger.info('数据库初始化完成')

    # ── Redis 缓存（数据库之后，蓝图之前） ────────
    # 初始化 Redis 连接池。如果 REDIS_URL 未配置，
    # 则静默降级（所有缓存操作直接返回 None，不影响业务）。
    from blog.cache import init_redis
    init_redis(app)

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
    logger.info('蓝图注册完成')

    # ── Gzip 压缩 ────────────────────────────────
    compress.init_app(app)
    logger.info('Gzip 压缩已启用')

    # ── 全局请求日志中间件 ───────────────────────
    # 每次 HTTP 响应返回到客户端之前执行 log_request()
    app.after_request(log_request)

    return app


if __name__ == '__main__':
    # ── 开发服务器启动 ──────────────────────────
    # 生产环境请使用 gunicorn / uwsgi 等 WSGI 服务器
    app = create_app()
    # 端口号优先从环境变量 PORT 读取，默认 5000
    port = int(os.environ.get('PORT', 5000))
    # FLASK_ENV=development 时开启 debug 模式（热重载 + 详细错误页）
    debug = os.environ.get('FLASK_ENV') == 'development'
    logger = app.logger
    logger.info('=' * 50)
    logger.info('服务启动: http://0.0.0.0:%d  debug=%s', port, debug)
    logger.info('=' * 50)
    app.run(host='0.0.0.0', port=port, debug=debug)
