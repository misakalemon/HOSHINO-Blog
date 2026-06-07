# -*- coding: utf-8 -*-
"""
HOSHINO Blog — Flask 应用入口

创建 Flask 应用实例，配置数据库、登录管理、
蓝图注册、Gzip 压缩和请求日志中间件。
"""
import os
from flask import Flask
from flask_login import LoginManager
from flask_compress import Compress
from dotenv import load_dotenv

# 加载 .env 环境变量（必须最先执行）
load_dotenv()

# Gzip 压缩实例（让静态资源和 API 响应更小）
compress = Compress()


def create_app():
    """创建并配置 Flask 应用。"""
    app = Flask(__name__)
    # 从 config.py 加载配置
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
    from blog.logger import setup_logging, log_request
    logger = setup_logging(app)
    logger.info('应用启动中...')

    # ── 确保上传目录存在 ──────────────────────────
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # ── 数据库 ────────────────────────────────────
    from blog import init_db, db
    init_db(app)        # 建表 + 自动迁移（v1→v2）
    logger.info('数据库初始化完成')

    # ── 登录管理 ──────────────────────────────────
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'admin.login'       # 未登录时跳转
    login_manager.login_message = '请先登录'

    from blog.models import User

    @login_manager.user_loader
    def load_user(user_id):
        """Flask-Login 回调：从 session 中恢复用户对象。"""
        return db.session.get(User, int(user_id))

    # ── 注册蓝图 ─────────────────────────────────
    from blog import blog_bp, admin_bp
    app.register_blueprint(blog_bp)       # 前台路由（首页、文章等）
    app.register_blueprint(admin_bp)      # 后台路由（管理面板）
    logger.info('蓝图注册完成')

    # ── Gzip 压缩 ────────────────────────────────
    compress.init_app(app)
    logger.info('Gzip 压缩已启用')

    # ── 全局请求日志中间件 ───────────────────────
    app.after_request(log_request)

    return app


if __name__ == '__main__':
    app = create_app()
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    logger = app.logger
    logger.info('=' * 50)
    logger.info('服务启动: http://0.0.0.0:%d  debug=%s', port, debug)
    logger.info('=' * 50)
    app.run(host='0.0.0.0', port=port, debug=debug)
