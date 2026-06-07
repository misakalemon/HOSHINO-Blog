# -*- coding: utf-8 -*-
"""
HOSHINO Blog — 蓝图注册与数据库初始化

定义前台（blog_bp）和后台（admin_bp）两个蓝图。
init_db() 在应用启动时执行：建表、自动迁移 v1→v2、创建默认管理员。
"""
from flask import Blueprint

# ── 蓝图 ──────────────────────────────────────────
# 前台 blueprint（URL 前缀为空，所有前台路由直接挂在 / 下）
blog_bp = Blueprint('blog', __name__)
# 后台 blueprint（所有后台路由自动添加 /admin 前缀）
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# 先导入模型，确保 admin 和 routes 中的 from .models import ... 可用
from .models import db, User, Post, Category, Comment


def init_db(app):
    """初始化数据库：建表 + 自动迁移 + 创建默认管理员。"""
    db.init_app(app)
    with app.app_context():
        # 创建所有表（如果不存在）
        db.create_all()
        # 自动检测并迁移：v1（单分类）→ v2（多对多分类）
        _migrate_category_to_many2many(app)
        # 首次启动时创建默认管理员
        if not User.query.filter_by(username='admin').first():
            admin = User(
                username=app.config.get('ADMIN_USERNAME', 'admin'),
                email=app.config.get('ADMIN_EMAIL', 'admin@localhost'),
                display_name=app.config.get('ADMIN_DISPLAY_NAME', 'Admin'),
                is_admin=True,
                is_active=True
            )
            admin.set_password(app.config.get('ADMIN_PASSWORD', 'admin123'))
            db.session.add(admin)
            db.session.commit()


def _migrate_category_to_many2many(app):
    """自动迁移：v1 (category_id 单分类) → v2 (post_categories 多对多)。

    检测逻辑：
    - 如果 posts 表还有 category_id 列 → 复制数据到 post_categories
    - 如果没有该列 → 跳过（已经是 v2 或新库）
    - 兼容 MySQL（INSERT IGNORE）和 SQLite（INSERT OR IGNORE）
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


# 后导入路由（必须放在模型和 init_db 之后，否则循环依赖）
from . import routes
from . import admin
