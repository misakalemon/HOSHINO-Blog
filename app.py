# -*- coding: utf-8 -*-
import os
from flask import Flask
from flask_login import LoginManager
from flask_compress import Compress
from dotenv import load_dotenv

load_dotenv()

compress = Compress()


def create_app():
    app = Flask(__name__)
    app.config.from_object('config.ActiveConfig')
    # 跨平台编码配置
    app.config['JSON_AS_ASCII'] = False       # JSON 返回中文而非 \\u 转义
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
    # 压缩配置
    app.config['COMPRESS_MIMETYPES'] = ['text/html', 'text/css', 'text/javascript', 
                                        'application/json', 'application/xml']
    app.config['COMPRESS_LEVEL'] = 6
    app.config['COMPRESS_MIN_SIZE'] = 500

    # 初始化日志（必须先于其他初始化）
    from blog.logger import setup_logging, log_request
    logger = setup_logging(app)
    logger.info('应用启动中...')

    # Ensure upload directory exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Initialize database
    from blog import init_db, db
    init_db(app)
    logger.info('数据库初始化完成')

    # Initialize login manager
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'admin.login'
    login_manager.login_message = '\u8bf7\u5148\u767b\u5f55'

    from blog.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # Register blueprints
    from blog import blog_bp, admin_bp
    app.register_blueprint(blog_bp)
    app.register_blueprint(admin_bp)
    logger.info('蓝图注册完成')
    
    # 初始化压缩
    compress.init_app(app)
    logger.info('Gzip 压缩已启用')

    # Request 日志中间件（在所有请求之后记录）
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
