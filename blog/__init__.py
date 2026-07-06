"""
HOSHINO Blog — 蓝图注册与数据库初始化

职责：
  1. 定义前台（blog_bp）和后台（admin_bp）两个 Flask Blueprint。
  2. 提供 init_db() 函数，在应用启动时执行：
     - 建表（db.create_all）
     - 自动迁移 v1（单分类）→ v2（多对多分类）
     - 创建默认管理员（首次启动）
  3. 后导入（lazy import）routes 和 admin 模块，避免循环依赖。

Blueprint 路由前缀：
  blog_bp  → / （前台，无前缀）
  admin_bp → /admin （后台，自动追加前缀）
"""
from flask import Blueprint

# ── 蓝图 ──────────────────────────────────────────
# 前台 blueprint（URL 前缀为空，所有前台路由直接挂在 / 下）
blog_bp = Blueprint('blog', __name__)
# 后台 blueprint（所有后台路由自动添加 /admin 前缀）
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')
# 价格追踪 blueprint（价格看板路由在 /prices 下）
price_bp = Blueprint('price', __name__, url_prefix='/prices')

# 先导入模型，确保 admin 和 routes 中的 from .models import ... 可用
# 这种 "先声明蓝图、再导入模型、最后导入路由" 的顺序是关键，
# 可以避免 Flask 常见的循环导入问题。
from .models import Category, Comment, ExchangeRate, FeaturedCard, Post, PriceRecord, Product, ProductSource, User, db


def init_db(app):
    """初始化数据库：建表 + 自动迁移 + 创建默认管理员。

    执行流程：
    1. db.init_app(app)         — 将 SQLAlchemy 绑定到 Flask 应用
    2. db.create_all()          — 创建所有未存在的表
    3. _migrate_category_to_many2many() — 兼容旧版单分类数据
    4. 检查 admin 用户是否已存在 → 不存在则创建默认管理员
    """
    db.init_app(app)
    with app.app_context():
        # ── 建表 ──────────────────────────────────
        # SQLAlchemy 根据 Model 定义自动 CREATE TABLE IF NOT EXISTS
        db.create_all()

        # ── 自动迁移 v1→v2 ───────────────────────
        # 检查 posts 表是否还有旧的 category_id 列，
        # 如果有则将其数据复制到新版的 post_categories 关联表
        _migrate_category_to_many2many(app)

        # ── 迁移 is_admin 布尔值 → role 字符串 ──
        # 必须在任何 User 查询之前执行，因为新字段还不存在于 MySQL 表中
        _migrate_is_admin_to_role(app)

        # ── 迁移 User 新增列（gitcode_url, github_url, about_content）──
        # 也必须在任何 User 查询之前执行
        _migrate_user_profile_fields(app)

        # ── 创建默认管理员 ────────────────────────
        # 仅当 users 表中没有任何用户名为 "admin" 的记录时执行
        if not User.query.filter_by(username='admin').first():
            import secrets
            admin_password = app.config.get('ADMIN_PASSWORD', 'CHANGE_ME')
            if admin_password == 'CHANGE_ME':
                admin_password = secrets.token_urlsafe(24)
                app.logger.warning('=' * 60)
                app.logger.warning('默认管理员密码未设置，已自动生成: %s', admin_password)
                app.logger.warning('请在 .env 中设置 ADMIN_PASSWORD，或登录后立即修改！')
                app.logger.warning('=' * 60)
            admin = User(
                username=app.config.get('ADMIN_USERNAME', 'admin'),
                email=app.config.get('ADMIN_EMAIL', 'admin@localhost'),
                display_name=app.config.get('ADMIN_DISPLAY_NAME', 'Admin'),
                is_admin=True,
                is_active=True
            )
            # set_password() 内部使用 werkzeug 的加密哈希，
            # 不会明文存储密码
            admin.set_password(admin_password)
            db.session.add(admin)
            db.session.commit()

        # ── 迁移 author 角色 → user 角色 ────────
        _migrate_author_to_user(app)

        # ── 迁移 FeaturedCard.icon 字段长度 ────
        _migrate_featured_icon(app)

        # ── 迁移 Post.content 从 TEXT 到 MEDIUMTEXT ────
        _migrate_post_content(app)

        # ── 添加示例价格追踪商品（首次启动） ─────
        from .crawler import init_sample_products
        init_sample_products()


def _migrate_category_to_many2many(app):
    """自动迁移：v1 (category_id 单分类) → v2 (post_categories 多对多)。

    迁移逻辑：
      - 如果 posts 表还有 category_id 列 → 复制数据到 post_categories
      - 如果没有该列 → 跳过（已经是 v2 或新库）
      - 兼容 MySQL（INSERT IGNORE）和 SQLite（INSERT OR IGNORE）

    为什么需要：
      项目早期版本中 Post 模型只有单个分类字段 category_id，
      v2 改为多对多关联后，旧数据需要迁移到新的关联表。
    """
    engine = db.get_engine()
    inspector = db.inspect(engine)

    # 检查 posts 表是否还有旧版 category_id 列
    cols = [c['name'] for c in inspector.get_columns('posts')]
    if 'category_id' not in cols:
        return  # 已迁移或新库，无需操作

    # 根据数据库类型选择兼容的 INSERT 语法
    #   SQLite → INSERT OR IGNORE
    #   MySQL  → INSERT IGNORE
    driver = ''
    try:
        driver = engine.url.get_driver_name()
    except AttributeError:
        pass
    ignore_keyword = 'OR IGNORE' if 'sqlite' in driver else 'IGNORE'

    # 执行迁移 SQL：将所有有分类的文章关联写入 post_categories 表
    sql = f'''
        INSERT {ignore_keyword} INTO post_categories (post_id, category_id)
        SELECT id, category_id FROM posts WHERE category_id IS NOT NULL
    '''
    result = db.session.execute(db.text(sql))
    rowcount = result.rowcount
    if rowcount > 0:
        app.logger.info(
            '迁移: 已迁移 %d 条分类关联记录 (category_id → post_categories)',
            rowcount
        )
    db.session.commit()


def _migrate_is_admin_to_role(app):
    """迁移：添加 role 字段 + 将 is_admin 布尔值转换为 role 字符串。

    1. 检查并添加 role / last_login_at / last_login_ip / login_count / website 列
    2. 将 is_admin=True 的用户设为 role='admin'
    3. 删除旧的 is_admin 列
    """
    engine = db.get_engine()
    inspector = db.inspect(engine)
    cols = {c['name'] for c in inspector.get_columns('users')}
    dialect = engine.dialect.name
    from sqlalchemy import text

    # ── 添加缺失的列（仅 MySQL） ─────────────
    if dialect == 'mysql':
        new_columns = {
            'role': "VARCHAR(16) DEFAULT 'user'",
            'last_login_at': 'DATETIME NULL',
            'last_login_ip': "VARCHAR(45) DEFAULT ''",
            'login_count': 'INT DEFAULT 0',
            'website': "VARCHAR(256) DEFAULT ''",
        }
        for col, col_type in new_columns.items():
            if col not in cols:
                try:
                    db.session.execute(text(f'ALTER TABLE users ADD COLUMN {col} {col_type}'))
                    db.session.commit()
                    app.logger.info('迁移: 已添加 users.%s 列', col)
                except Exception as e:
                    db.session.rollback()
                    app.logger.warning('迁移: 添加 users.%s 列失败: %s', col, e)

    # ── 数据迁移：is_admin → role ────────────
    if 'is_admin' in cols and 'role' in cols:
        result = db.session.execute(
            text("UPDATE users SET role = 'admin' WHERE is_admin = 1 OR is_admin = TRUE")
        )
        if result.rowcount > 0:
            app.logger.info('迁移: 已将 %d 个用户从 is_admin 迁移到 role', result.rowcount)
        db.session.commit()

        if dialect == 'mysql':
            try:
                db.session.execute(text('ALTER TABLE users DROP COLUMN is_admin'))
                db.session.commit()
                app.logger.info('迁移: 已删除 is_admin 列')
            except Exception:
                db.session.rollback()


def _migrate_featured_icon(app):
    """迁移 FeaturedCard.icon 从 VARCHAR(16) 到 VARCHAR(256)。"""
    engine = db.get_engine()
    dialect = engine.dialect.name
    if dialect == 'mysql':
        try:
            db.session.execute(db.text(
                'ALTER TABLE featured_cards MODIFY icon VARCHAR(256) DEFAULT \'✦\''
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()


def _migrate_post_content(app):
    """迁移 Post.content 从 TEXT 到 MEDIUMTEXT（支持长文）。"""
    engine = db.get_engine()
    dialect = engine.dialect.name
    if dialect == 'mysql':
        try:
            db.session.execute(db.text(
                'ALTER TABLE posts MODIFY content MEDIUMTEXT NOT NULL'
            ))
            db.session.commit()
            app.logger.info('迁移: posts.content 已扩展为 MEDIUMTEXT')
        except Exception:
            db.session.rollback()


def _migrate_author_to_user(app):
    """迁移：将已废弃的 author 角色合并到 user 角色。

    author 角色已被移除，所有权限已转移给 user。
    将数据库中 role='author' 的用户改为 role='user'。
    """
    from sqlalchemy import text
    result = db.session.execute(
        text("UPDATE users SET role = 'user' WHERE role = 'author'")
    )
    if result.rowcount > 0:
        app.logger.info('迁移: 已将 %d 个用户从 author 角色合并到 user 角色', result.rowcount)
    db.session.commit()


def _migrate_user_profile_fields(app):
    """迁移：为 User 表添加社交链接和关于页面字段（仅 MySQL 需 ALTER）。"""
    engine = db.get_engine()
    inspector = db.inspect(engine)
    cols = {c['name'] for c in inspector.get_columns('users')}
    dialect = engine.dialect.name
    if dialect != 'mysql':
        return
    from sqlalchemy import text
    new_columns = {
        'gitcode_url': "VARCHAR(256) DEFAULT ''",
        'github_url': "VARCHAR(256) DEFAULT ''",
        'gitee_url': "VARCHAR(256) DEFAULT ''",
        'bilibili_url': "VARCHAR(256) DEFAULT ''",
        'about_content': "MEDIUMTEXT",
    }
    for col, col_type in new_columns.items():
        if col not in cols:
            try:
                db.session.execute(text(f'ALTER TABLE users ADD COLUMN {col} {col_type}'))
                db.session.commit()
                app.logger.info('迁移: 已添加 users.%s 列', col)
            except Exception as e:
                db.session.rollback()
                app.logger.warning('迁移: 添加 users.%s 列失败: %s', col, e)


# ── 后导入路由（延迟导入） ─────────────────────
# 此处的 import 必须放在模型和 init_db 之后，否则会导致循环依赖：
#   __init__.py → routes.py → __init__.py
# 延迟导入打破了这个循环。
from . import admin, price_routes, routes
