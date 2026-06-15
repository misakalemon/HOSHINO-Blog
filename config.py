# -*- coding: utf-8 -*-
"""
HOSHINO Blog — 应用配置

职责：
  集中管理所有 Flask 配置项，支持通过 .env 文件动态覆盖。
  提供两种数据库连接方式：
    1. DATABASE_URL 直接指定完整连接串（优先级最高）
    2. 拆分 DB_HOST/DB_PORT/DB_USER/DB_PASS/DB_NAME 自动拼接

使用方式：
  app.config.from_object('config.ActiveConfig')
"""
import os
from dotenv import load_dotenv

# 项目根目录（config.py 所在目录，即项目根目录）
basedir = os.path.abspath(os.path.dirname(__file__))

# 加载 .env 文件（如果存在）
# 注意：app.py 中已调用 load_dotenv()，此处再调用一次是为了
# 其他直接 import config 的模块（如迁移脚本）也能读到 .env
load_dotenv(os.path.join(basedir, '.env'))


def _build_database_uri():
    """构造数据库连接 URI。

    优先级：
    1. DATABASE_URL 环境变量（完整连接串，如 mysql+pymysql://...）
    2. 拆分变量自动拼接（DB_HOST + DB_PORT + DB_USER + DB_PASS + DB_NAME）

    Returns:
        str: SQLAlchemy 数据库 URI
    """
    direct_url = os.environ.get('DATABASE_URL')
    if direct_url:
        return direct_url

    # ── 拆分配置（DATABASE_URL 未设置时使用） ──
    # 各字段均有默认值，适合本地开发快速启动
    host = os.environ.get('DB_HOST', '127.0.0.1')
    port = os.environ.get('DB_PORT', '3306')
    user = os.environ.get('DB_USER', 'hoshino')
    passwd = os.environ.get('DB_PASS', 'hoshino_pass')
    dbname = os.environ.get('DB_NAME', 'hoshino_blog')

    # 默认使用 pymysql 驱动连接 MySQL，UTF-8 编码 + 10 秒连接超时
    return (f'mysql+pymysql://{user}:{passwd}@{host}:{port}/{dbname}'
            '?charset=utf8mb4&connect_timeout=10')


class Config:
    """应用配置类

    所有 Flask 扩展的配置（SQLAlchemy、LoginManager、Compress 等）
    均通过此类集中管理，通过 app.config.from_object('config.ActiveConfig') 加载。
    """

    # ── Flask 核心 ──────────────────────────────
    # 密钥用于 Session 签名、CSRF token 加密。
    # 生产环境一定要在 .env 中设置强随机字符串（至少 32 字符）。
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'hoshino-blog-secret-key'

    # ── 数据库 ──────────────────────────────────
    # 关闭 SQLAlchemy 的事件追踪（减少内存开销）
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # 数据库连接 URI（由 _build_database_uri 构造）
    SQLALCHEMY_DATABASE_URI = _build_database_uri()
    # 连接池配置（适合 MySQL 5.7 conda 版本，不宜过大）
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 2,          # 连接池大小（并发不高时 2 个足够）
        'pool_recycle': 60,      # 空闲连接 60 秒后回收（MySQL 默认 8h 超时）
        'pool_pre_ping': True,   # 每次借用连接前发送 ping 检测有效性
        'max_overflow': 0,       # 不允许超出 pool_size 的临时连接
    }

    # ── 上传 ──────────────────────────────────────
    # 用户上传文件存放目录（相对于项目根目录）
    UPLOAD_FOLDER = os.path.join(basedir, 'static', 'uploads')
    # 单次上传最大字节数（默认 16MB，可通过 .env 覆盖）
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
    # 这些值只在数据库没有任何用户时生效一次。
    # 创建管理员后，修改这些值不会影响已有用户。
    ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'admin@localhost')
    ADMIN_DISPLAY_NAME = os.environ.get('ADMIN_DISPLAY_NAME', 'Admin')

    # ── Redis 缓存 ────────────────────────────────
    # 连接串格式: redis://[:password]@host:port/db
    # 留空或 None 时禁用缓存（Redis 不可用时自动降级）
    REDIS_URL = os.environ.get('REDIS_URL') or None
    # 默认缓存过期时间（秒）
    #   侧边栏数据          → 300s（5 分钟）
    #   仪表盘统计数据      → 60s（1 分钟）
    #   RSS 输出            → 600s（10 分钟）
    CACHE_TTL_SIDEBAR = int(os.environ.get('CACHE_TTL_SIDEBAR', 300))
    CACHE_TTL_DASHBOARD = int(os.environ.get('CACHE_TTL_DASHBOARD', 60))
    CACHE_TTL_RSS = int(os.environ.get('CACHE_TTL_RSS', 600))


# 导出给 app.py 使用的活动配置
# 这是一种简化写法：Config 本身可直接作为配置源，
# 无需实例化，app.config.from_object('config.ActiveConfig') 即可
ActiveConfig = Config
