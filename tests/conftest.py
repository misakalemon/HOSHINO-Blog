"""HOSHINO Blog — 测试配置和 fixtures"""
# ruff: noqa: PLC0415
import os
import tempfile

import pytest

# 设置测试环境变量（在 import app 之前）
os.environ['WORKER_PROCESS'] = '1'  # 跳过 DB 迁移
os.environ['FLASK_ENV'] = 'testing'
os.environ['SECRET_KEY'] = 'test-secret-key-for-unit-tests'

# ── 数据库后端选择 ──────────────────────────────
# TEST_DB_BACKEND=sqlite  → 用 SQLite 文件数据库（无需 MySQL，默认）
# TEST_DB_BACKEND=mysql   → 用 MySQL（需配置 hoshino_test 用户；CI 的 integration job 使用）
#
# 默认改为 sqlite：此前默认 mysql 且无回退，未装 MySQL 的环境会静默 skip
# 约 43% 的测试（160/369），导致"测试通过"名不副实。
_TEST_BACKEND = os.environ.get('TEST_DB_BACKEND', 'sqlite')

if _TEST_BACKEND == 'sqlite':
    # 用临时文件 SQLite，避免 :memory: 多连接问题
    _sqlite_path = os.path.join(tempfile.gettempdir(), 'hoshino_test.sqlite3')
    if os.path.exists(_sqlite_path):
        os.remove(_sqlite_path)
    os.environ['DATABASE_URL'] = f'sqlite:///{_sqlite_path}'

    # ── SQLite 兼容 shim ─────────────────────────────
    # 生产代码含 MySQL 专有函数，SQLite 下会报 "no such function"：
    #   - 首页加权随机排序（blog/core/routes.py:_render_index）用
    #     unix_timestamp() + rand() —— 这是无条件执行的请求路径，
    #     不注册 shim 会让 / 在 SQLite 下直接报错（test_home_page 与
    #     test_security 的响应头测试都会失败）。
    #   - 词云按月分组用 date_format()。
    # 注意：shim 只保证 SQL 可执行，排序权重的具体数值与 MySQL 不逐一
    #       等价（测试只断言状态码与结构，不受影响）。
    #       词云的 ON DUPLICATE KEY UPDATE 无法 shim（MySQL 方言 insert），
    #       该路径由 CI 的 mysql-integration job 覆盖，SQLite job 不覆盖。
    import random as _random
    import sqlite3 as _sqlite3
    from datetime import datetime as _dt

    from sqlalchemy import event as _sa_event
    from sqlalchemy.engine import Engine as _Engine

    def _sqlite_unix_timestamp(value):
        """MySQL UNIX_TIMESTAMP(datetime) 的等价实现（秒级整数）。"""
        if value is None:
            return 0
        if isinstance(value, (int, float)):
            return int(value)
        text = str(value).strip()
        for parser in (
            _dt.fromisoformat,
            lambda s: _dt.strptime(s, '%Y-%m-%d %H:%M:%S'),
            lambda s: _dt.strptime(s, '%Y-%m-%d'),
        ):
            try:
                return int(parser(text).timestamp())
            except (ValueError, TypeError):
                continue
        return 0

    def _sqlite_date_format(value, fmt):
        """MySQL DATE_FORMAT(datetime, '%Y-%m') 的等价实现。

        MySQL 与 Python strftime 的占位符对 %Y/%m/%d/%H/%M/%S 一致。
        """
        if value is None:
            return None
        text = str(value).strip()
        try:
            parsed = _dt.fromisoformat(text)
        except ValueError:
            try:
                parsed = _dt.strptime(text, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                return None
        try:
            return parsed.strftime(fmt)
        except (ValueError, TypeError):
            return None

    @_sa_event.listens_for(_Engine, 'connect')
    def _register_sqlite_shims(dbapi_connection, connection_record):
        """为 SQLite 连接注册 MySQL 函数 shim（可选启用外键约束）。"""
        if not isinstance(dbapi_connection, _sqlite3.Connection):
            return
        dbapi_connection.create_function('unix_timestamp', 1, _sqlite_unix_timestamp)
        dbapi_connection.create_function('rand', 0, _random.random)
        dbapi_connection.create_function('rand', 1, lambda seed: _random.random())
        dbapi_connection.create_function('date_format', 2, _sqlite_date_format)
        # 外键约束默认保持 SQLite 原生行为（foreign_keys=OFF）。
        # 原因：生产 MySQL 的外键是开启的，但 SQLite 开启后会严格校验插入顺序
        # （不通过 relationship 关联、直接写外键列的测试数据会 IntegrityError）。
        # 需要验证级联删除等外键语义时，显式设置 TEST_SQLITE_FK=1 再跑测试。
        if os.environ.get('TEST_SQLITE_FK') == '1':
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute('PRAGMA foreign_keys=ON')
            finally:
                cursor.close()
else:
    os.environ.setdefault('DB_HOST', '127.0.0.1')
    os.environ.setdefault('DB_USER', 'hoshino_test')
    os.environ.setdefault('DB_PASS', 'hoshino_test_pass')
    os.environ.setdefault('DB_NAME', 'hoshino_blog_test')

# ── SQLAlchemy.init_app monkey-patch ────────────
# SQLite 不兼容 MySQL 的 pool_size/max_overflow/connect_timeout 等参数，
# 在 init_app 前自动清理，使同一套测试代码可在两种后端运行。
from flask_sqlalchemy import SQLAlchemy as _SA

_orig_init_app = _SA.init_app


def _patched_init_app(self, app):
    uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if uri.startswith('sqlite'):
        opts = app.config.get('SQLALCHEMY_ENGINE_OPTIONS', {})
        for k in ('pool_size', 'max_overflow', 'pool_timeout'):
            opts.pop(k, None)
        ca = opts.get('connect_args', {})
        for k in ('connect_timeout', 'read_timeout', 'write_timeout'):
            ca.pop(k, None)
        if not ca:
            opts.pop('connect_args', None)
    _orig_init_app(self, app)


_SA.init_app = _patched_init_app

# ── MEDIUMTEXT → TEXT 编译映射（SQLite 兼容）─────
from sqlalchemy.ext.compiler import compiles as _compiles
from sqlalchemy.dialects.mysql import MEDIUMTEXT as _MEDIUMTEXT


@_compiles(_MEDIUMTEXT, 'sqlite')
def _compile_mediumtext_sqlite(element, compiler, **kw):
    return 'TEXT'


@pytest.fixture(scope='session')
def app():
    """创建测试用 Flask 应用实例。

    TEST_DB_BACKEND=mysql 时先预检 MySQL 连接，不可用则跳过整个测试套件
    （便于在没有 MySQL 的机器上安全运行）；sqlite 后端无需预检。
    """
    if _TEST_BACKEND != 'sqlite':
        try:
            # 预检 MySQL 连接
            from sqlalchemy import create_engine
            from config import _build_database_uri
            probe = create_engine(
                _build_database_uri(),
                connect_args={'connect_timeout': 3},
            )
            with probe.connect():
                pass
            probe.dispose()
        except Exception as e:
            pytest.skip(f'MySQL 不可用，跳过测试套件: {e}')

    from app import create_app
    app = create_app()
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SERVER_NAME'] = 'localhost'
    return app


@pytest.fixture(scope='session')
def _db(app):
    """数据库 fixture（session 级别，整个测试套件共享）"""
    from blog import db as _db
    with app.app_context():
        _db.create_all()
        yield _db
        _db.drop_all()


@pytest.fixture(autouse=True)
def _setup_db(request):
    """每个测试前后清理数据库

    带 `pure` marker 的纯单元测试不依赖数据库，跳过 DB 初始化，
    避免触发 MySQL 预检（MySQL 不可用时纯测试仍可运行）。
    """
    if request.node.get_closest_marker('pure'):
        yield
        return
    app = request.getfixturevalue('app')
    _db = request.getfixturevalue('_db')
    with app.app_context():
        _db.create_all()
        yield
        for table in reversed(_db.metadata.sorted_tables):
            _db.session.execute(table.delete())
        _db.session.commit()


@pytest.fixture
def client(app):
    """Flask 测试客户端"""
    return app.test_client()


@pytest.fixture
def admin_user(app, _db):
    """创建测试管理员用户"""
    from blog.core.models import User
    with app.app_context():
        user = User(
            username='testadmin',
            email='testadmin@test.com',
            display_name='Test Admin',
            role='admin',
            is_active=True,
        )
        user.set_password('testpass123')
        _db.session.add(user)
        _db.session.commit()
        return user.id


@pytest.fixture
def logged_in_client(client, app, admin_user):
    """已登录管理员的测试客户端"""
    client.post('/admin/login', data={
        'username': 'testadmin',
        'password': 'testpass123',
    })
    return client
