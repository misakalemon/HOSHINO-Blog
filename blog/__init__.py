# -*- coding: utf-8 -*-
from flask import Blueprint

blog_bp = Blueprint('blog', __name__)
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# Import models FIRST so admin/routes can use them
from .models import db, User, Post, Category, Comment

def init_db(app):
    """Initialize database and create tables."""
    db.init_app(app)
    with app.app_context():
        db.create_all()
        _migrate_category_to_many2many(app)
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
    """自动迁移：v1 (category_id) → v2 (post_categories 多对多)。"""
    engine = db.get_engine()
    inspector = db.inspect(engine)

    # 检查旧版 posts 表是否有 category_id 列
    cols = [c['name'] for c in inspector.get_columns('posts')]
    if 'category_id' not in cols:
        return  # 已经是 v2 了

    # 迁移数据：将 category_id 复制到关联表
    driver = engine.url.get_driver_name() if hasattr(engine.url, 'get_driver_name') else ''
    ignore_keyword = 'OR IGNORE' if 'sqlite' in driver else 'IGNORE'
    sql = f'''
        INSERT {ignore_keyword} INTO post_categories (post_id, category_id)
        SELECT id, category_id FROM posts WHERE category_id IS NOT NULL
    '''
    result = db.session.execute(db.text(sql))
    rowcount = result.rowcount
    if rowcount > 0:
        app.logger.info('迁移: 已迁移 %d 条分类关联记录 (category_id → post_categories)', rowcount)
    db.session.commit()

# Import routes AFTER models
from . import routes
from . import admin
