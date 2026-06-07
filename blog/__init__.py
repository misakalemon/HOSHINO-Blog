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

# Import routes AFTER models
from . import routes
from . import admin
