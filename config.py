# -*- coding: utf-8 -*-
import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))

# 加载 .env 文件（如果存在）
load_dotenv(os.path.join(basedir, '.env'))


def _build_database_uri():
    """从拆分配置自动拼接数据库连接串。
    
    如果设置了 DATABASE_URL 环境变量，则直接使用它（优先级最高）。
    """
    direct_url = os.environ.get('DATABASE_URL')
    if direct_url:
        return direct_url
    host = os.environ.get('DB_HOST', '127.0.0.1')
    port = os.environ.get('DB_PORT', '3307')
    user = os.environ.get('DB_USER', 'hoshino')
    passwd = os.environ.get('DB_PASS', 'hoshino_pass')
    dbname = os.environ.get('DB_NAME', 'hoshino_blog')
    return (f'mysql+pymysql://{user}:{passwd}@{host}:{port}/{dbname}'
            '?charset=utf8mb4&connect_timeout=10')


class Config:
    """应用配置"""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'hoshino-blog-secret-key'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_DATABASE_URI = _build_database_uri()
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 2,
        'pool_recycle': 60,
        'pool_pre_ping': True,
        'max_overflow': 0,
    }
    UPLOAD_FOLDER = os.path.join(basedir, 'static', 'uploads')
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 16 * 1024 * 1024))
    POSTS_PER_PAGE = 6

    # 默认管理员
    ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'admin@localhost')
    ADMIN_DISPLAY_NAME = os.environ.get('ADMIN_DISPLAY_NAME', 'Admin')


ActiveConfig = Config
