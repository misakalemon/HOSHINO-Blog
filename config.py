# -*- coding: utf-8 -*-
"""
HOSHINO Blog — 应用配置

所有配置项通过 .env 文件管理，支持两种数据库连接方式：
1. DATABASE_URL 直接指定完整连接串（优先级最高）
2. 拆分 DB_HOST/DB_PORT/DB_USER/DB_PASS/DB_NAME 自动拼接
"""
import os
from dotenv import load_dotenv

# 项目根目录
basedir = os.path.abspath(os.path.dirname(__file__))

# 加载 .env 文件（如果存在）
load_dotenv(os.path.join(basedir, '.env'))


def _build_database_uri():
    """构造数据库连接 URI。

    优先级：
    1. DATABASE_URL 环境变量（完整连接串）
    2. 拆分变量 DB_HOST + DB_PORT + DB_USER + DB_PASS + DB_NAME 自动拼接
    """
    direct_url = os.environ.get('DATABASE_URL')
    if direct_url:
        return direct_url
    host = os.environ.get('DB_HOST', '127.0.0.1')
    port = os.environ.get('DB_PORT', '3306')
    user = os.environ.get('DB_USER', 'hoshino')
    passwd = os.environ.get('DB_PASS', 'hoshino_pass')
    dbname = os.environ.get('DB_NAME', 'hoshino_blog')
    return (f'mysql+pymysql://{user}:{passwd}@{host}:{port}/{dbname}'
            '?charset=utf8mb4&connect_timeout=10')


class Config:
    """应用配置类"""

    # Flask 密钥（用于 Session / CSRF），生产环境请设置为强随机字符串
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'hoshino-blog-secret-key'

    # ── 数据库 ────────────────────────────────────
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_DATABASE_URI = _build_database_uri()
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 2,          # 连接池大小（MySQL 5.7 conda 版不宜过大）
        'pool_recycle': 60,      # 回收空闲连接（秒）
        'pool_pre_ping': True,   # 每次借用连接前发送 ping 检测有效性
        'max_overflow': 0,       # 不允许超出 pool_size 的临时连接
    }

    # ── 上传 ──────────────────────────────────────
    UPLOAD_FOLDER = os.path.join(basedir, 'static', 'uploads')
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 16 * 1024 * 1024))

    # ── 分页 ──────────────────────────────────────
    # 每页文章数（默认 6），可通过 .env 的 POSTS_PER_PAGE 覆盖
    POSTS_PER_PAGE = int(os.environ.get('POSTS_PER_PAGE', 6))
    # 前端每页下拉选择器的可选值。
    # 自动包含 POSTS_PER_PAGE 并去重排序，例如设为 10 时选项为 [6, 10, 12, 24, 48]
    PER_PAGE_OPTIONS = sorted(set([POSTS_PER_PAGE, 6, 12, 24, 48]))

    # ── 默认主题（dark / light）────────────────
    # 首次访问时的默认主题。用户手动切换后以 localStorage 为准，不再受此值影响。
    DEFAULT_THEME = os.environ.get('DEFAULT_THEME', 'dark')

    # ── 默认管理员（首次启动自动创建）─────────────
    ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'admin@localhost')
    ADMIN_DISPLAY_NAME = os.environ.get('ADMIN_DISPLAY_NAME', 'Admin')


# 导出给 app.py 使用的活动配置
ActiveConfig = Config
