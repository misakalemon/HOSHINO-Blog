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
import json
import secrets
from datetime import timedelta
from dotenv import load_dotenv

# 项目根目录（config.py 所在目录，即项目根目录）
basedir = os.path.abspath(os.path.dirname(__file__))

# 加载 .env 文件（如果存在）
# 注意：app.py 中已调用 load_dotenv()，此处再调用一次是为了
# 其他直接 import config 的模块（如迁移脚本）也能读到 .env
load_dotenv(os.path.join(basedir, '.env'))

# ── SECRET_KEY 轮换 ──────────────────────────────
# .secret_keys 文件存储多个历史密钥（JSON 数组，最新在前），
# 用于支持运行时定期轮换 SECRET_KEY，同时保留旧密钥让已签发 session 不失效。
SECRET_KEYS_FILE = os.path.join(basedir, '.secret_keys')
SECRET_KEY_MAX_HISTORY = 10  # 最多保留 10 个历史密钥


def _load_secret_keys():
    """从文件加载所有历史密钥，返回列表（最新在前）。"""
    if os.path.exists(SECRET_KEYS_FILE):
        with open(SECRET_KEYS_FILE) as f:
            keys = json.load(f)
            if isinstance(keys, list) and all(isinstance(k, str) for k in keys):
                return keys
    return []


def _save_secret_keys(keys):
    """将密钥列表持久化到文件。"""
    with open(SECRET_KEYS_FILE, 'w') as f:
        json.dump(keys, f)


def _ensure_initial_key():
    """确保至少有一个密钥存在，没有则自动生成。"""
    keys = _load_secret_keys()
    if not keys:
        keys = [secrets.token_hex(32)]
        _save_secret_keys(keys)
    return keys


def rotate_secret_key(app):
    """生成新密钥轮换当前 SECRET_KEY，旧密钥移入 SECRET_KEY_FALLBACKS。

    如果 .env 中显式设置了 SECRET_KEY，则不执行轮换。
    """
    if os.environ.get('SECRET_KEY'):
        return
    new_key = secrets.token_hex(32)
    keys = _load_secret_keys()
    keys.insert(0, new_key)
    keys = keys[:SECRET_KEY_MAX_HISTORY]
    _save_secret_keys(keys)

    app.config['SECRET_KEY'] = new_key
    app.config['SECRET_KEY_FALLBACKS'] = keys[1:]
    app.logger.info('SECRET_KEY 已轮换（共 %d 个历史密钥）', len(keys))


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
    # 优先级：.env 中的 SECRET_KEY > .secret_keys 文件（自动轮换）
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if SECRET_KEY:
        SECRET_KEY_FALLBACKS = []
    else:
        keys = _ensure_initial_key()
        SECRET_KEY = keys[0]
        SECRET_KEY_FALLBACKS = keys[1:]

    # ── Session 安全 ────────────────────────────────
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    # 生产环境默认强制 HTTPS，可通过 .env 中 SESSION_COOKIE_SECURE=false 关闭
    _default_secure = os.environ.get('FLASK_ENV') != 'development'
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', str(_default_secure)).lower() in ('true', '1')
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

    # ── CSRF 保护 ──────────────────────────────────
    # 关闭 SSL 严格检查（HTTP 环境下误报率低）
    WTF_CSRF_SSL_STRICT = False
    # 不设 CSRF token 过期时间（由 session 7 天过期兜底）
    WTF_CSRF_TIME_LIMIT = None

    # ── Flask-Login 记住我 cookie ─────────────────
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'

    # ── 数据库 ──────────────────────────────────
    # 关闭 SQLAlchemy 的事件追踪（减少内存开销）
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # 数据库连接 URI（由 _build_database_uri 构造）
    SQLALCHEMY_DATABASE_URI = _build_database_uri()
    # 连接池配置（适合 MySQL 5.7 conda 版本，不宜过大）
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 5,          # 连接池大小（应对并发访问）
        'pool_recycle': 3600,    # 空闲连接 1 小时后回收（MySQL 默认 8h 超时）
        'pool_pre_ping': True,   # 每次借用连接前发送 ping 检测有效性
        'max_overflow': 5,       # 突发流量时允许的临时连接数
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

    # ── 博客副标题（首页英雄区显示）─────────────
    BLOG_SUBTITLE = os.environ.get('BLOG_SUBTITLE',
        '碧蓝档案 · 手办 · 键盘 · 耳机 · 桌面 · 圣地巡礼 · 虎式坦克 · 迷彩历史')

    # ── 默认主题（dark / light）────────────────
    # 首次访问时的默认主题。用户手动切换后以 localStorage 为准，不再受此值影响。
    DEFAULT_THEME = os.environ.get('DEFAULT_THEME', 'dark')

    # ── 默认管理员（首次启动自动创建）─────────────
    # 这些值只在数据库没有任何用户时生效一次。
    # 创建管理员后，修改这些值不会影响已有用户。
    ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'CHANGE_ME')
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'admin@localhost')
    ADMIN_DISPLAY_NAME = os.environ.get('ADMIN_DISPLAY_NAME', 'Admin')

    # ── 用户注册开关 ───────────────────────────────
    # 关闭后 /admin/register 路由返回禁止注册提示。
    # 生产环境建议关闭，需要新用户时由管理员在后台创建。
    ENABLE_REGISTRATION = os.environ.get('ENABLE_REGISTRATION', 'false').lower() in ('true', '1')

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

    # ── Amazon 直爬代理（可选）─────────────────────
    # curl_cffi 直爬 Amazon 时使用的 HTTP 代理。
    # 服务器在国内时必须设置海外代理才能访问 Amazon。
    # 格式: http://user:pass@host:port
    SCRAPING_PROXY = os.environ.get('SCRAPING_PROXY') or ''

    # ── Exa API（搜索引擎，绕过 GFW 获取海外价格）──
    # 从 https://exa.ai 注册获取 API Key
    # 通过搜索获取电商页面内容，解析价格信息
    EXA_API_KEY = os.environ.get('EXA_API_KEY') or ''


# 导出给 app.py 使用的活动配置
# 这是一种简化写法：Config 本身可直接作为配置源，
# 无需实例化，app.config.from_object('config.ActiveConfig') 即可
ActiveConfig = Config
