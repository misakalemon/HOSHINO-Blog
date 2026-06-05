# -*- coding: utf-8 -*-
import os

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    """基础配置 —— 所有数据库共用"""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'hoshino-blog-secret-key'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(basedir, 'static', 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB
    POSTS_PER_PAGE = 6


class SQLiteConfig(Config):
    """SQLite 配置"""
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'blog.db')


class MySQLConfig(Config):
    """MySQL 配置 — 优先从环境变量读取，否则使用默认值"""
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'mysql+pymysql://hoshino:hoshino_pass@localhost:3306/hoshino_blog?charset=utf8mb4'
    # 连接池设置（MySQL 专用）
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 10,
        'pool_recycle': 3600,
        'pool_pre_ping': True,
        'max_overflow': 5,
        'connect_args': {'charset': 'utf8mb4'},
    }


# ============================================================
# 数据库选择器 —— 通过环境变量 DB_TYPE 切换
#   export DB_TYPE=mysql   → 使用 MySQL
#   export DB_TYPE=sqlite  → 使用 SQLite（默认）
#   也可直接设置 DATABASE_URL 完全自定义
# ============================================================
_db_type = os.environ.get('DB_TYPE', 'sqlite').strip().lower()

if _db_type == 'mysql':
    ActiveConfig = MySQLConfig
elif _db_type == 'sqlite':
    ActiveConfig = SQLiteConfig
else:
    raise ValueError(f'不支持的 DB_TYPE: {_db_type}，请使用 sqlite 或 mysql')

