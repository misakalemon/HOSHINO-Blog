"""HOSHINO Blog — 测试配置和 fixtures"""
import os
import pytest
import tempfile

# 设置测试环境变量（在 import app 之前）
os.environ['WORKER_PROCESS'] = '1'  # 跳过 DB 迁移
os.environ['FLASK_ENV'] = 'testing'
os.environ['DB_HOST'] = '127.0.0.1'
os.environ['DB_USER'] = 'hoshino_test'
os.environ['DB_PASS'] = 'hoshino_test_pass'
os.environ['DB_NAME'] = 'hoshino_blog_test'


@pytest.fixture(scope='session')
def app():
    """创建测试用 Flask 应用实例

    MySQL 不可用时跳过整个测试套件（而不是收集阶段直接报错），
    使测试可在未配置 MySQL 的机器/CI 上安全运行。
    """
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
def _setup_db(app, _db):
    """每个测试前后清理数据库"""
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