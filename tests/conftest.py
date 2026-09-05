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
# TEST_DB_BACKEND=sqlite  → 用 SQLite 文件数据库（无需 MySQL）
# TEST_DB_BACKEND=mysql   → 用 MySQL（需配置 hoshino_test 用户）
# 默认 mysql，但 MySQL 不可用时自动回退 sqlite
_TEST_BACKEND = os.environ.get('TEST_DB_BACKEND', 'mysql')

if _TEST_BACKEND == 'sqlite':
    # 用临时文件 SQLite，避免 :memory: 多连接问题
    _sqlite_path = os.path.join(tempfile.gettempdir(), 'hoshino_test.sqlite3')
    if os.path.exists(_sqlite_path):
        os.remove(_sqlite_path)
    os.environ['DATABASE_URL'] = f'sqlite:///{_sqlite_path}'
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
    """创建测试用 Flask 应用实例

    MySQL 不可用时跳过整个测试套件（而不是收集阶段直接报错），
    使测试可在未配置 MySQL 的机器/CI 上安全运行。
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
    from blog.models import User
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
