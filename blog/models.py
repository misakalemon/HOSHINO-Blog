# -*- coding: utf-8 -*-
"""
HOSHINO Blog — 数据模型

User      用户（管理员 + 普通用户）
Category  分类（支持多对多）
Post      文章（支持多对多分类，最多 15 个）
Comment   评论（需管理员审核）
"""
import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

# SQLAlchemy 实例，所有模型共享
db = SQLAlchemy()


# ── 多对多关联表 ────────────────────────────────
# 文章 ↔ 分类 的多对多关系表
# 允许一篇文章属于多个分类，一个分类包含多篇文章
post_categories = db.Table(
    'post_categories',
    db.Column('post_id', db.Integer, db.ForeignKey('posts.id'), primary_key=True),
    db.Column('category_id', db.Integer, db.ForeignKey('categories.id'), primary_key=True)
)


class User(UserMixin, db.Model):
    """用户模型。"""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    display_name = db.Column(db.String(128), default='')       # 显示昵称
    bio = db.Column(db.Text, default='')                        # 个人简介
    avatar = db.Column(db.String(256), default='images/avatar/main-avatar.jpg')
    is_admin = db.Column(db.Boolean, default=False)             # 是否管理员
    is_active = db.Column(db.Boolean, default=True)             # 是否激活
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    # 关联：一个用户有多篇文章
    posts = db.relationship('Post', backref='author', lazy='dynamic')

    def set_password(self, password):
        """设置加密密码。"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """验证密码。"""
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        """返回用户信息的字典（用于 API）。"""
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'display_name': self.display_name,
            'is_admin': self.is_admin,
        }


class Category(db.Model):
    """文章分类模型。"""
    __tablename__ = 'categories'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    slug = db.Column(db.String(64), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    # 多对多关联：一个分类包含多篇文章
    posts = db.relationship(
        'Post', secondary=post_categories,
        back_populates='categories', lazy='dynamic'
    )

    def post_count(self):
        """返回该分类下已发布的文章数。"""
        return self.posts.filter_by(is_published=True).count()


class Post(db.Model):
    """文章模型。"""
    __tablename__ = 'posts'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(256), nullable=False)
    slug = db.Column(db.String(256), unique=True, nullable=False, index=True)
    summary = db.Column(db.Text, default='')            # 文章摘要
    content = db.Column(db.Text, nullable=False)         # Markdown 正文
    cover_image = db.Column(db.String(256), default='')  # 封面图片
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    is_published = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow
    )

    # 多对多关联：一篇文章可以有多个分类（最多 15 个）
    categories = db.relationship(
        'Category', secondary=post_categories,
        back_populates='posts', lazy='select'
    )
    # 一对多关联：一篇文章有多条评论
    comments = db.relationship(
        'Comment', backref='post', lazy='dynamic',
        order_by='Comment.created_at'
    )

    def published_comments(self):
        """返回已审核通过的评论数。"""
        return self.comments.filter_by(is_approved=True).count()

    def category_names(self):
        """返回所有分类名称列表。"""
        return [c.name for c in self.categories]

    def category_slugs(self):
        """返回所有分类 slug 列表。"""
        return [c.slug for c in self.categories]


class Comment(db.Model):
    """评论模型。"""
    __tablename__ = 'comments'

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False)
    author_name = db.Column(db.String(128), nullable=False)
    author_email = db.Column(db.String(120), nullable=True)
    content = db.Column(db.Text, nullable=False)
    is_approved = db.Column(db.Boolean, default=False)   # 管理员审核
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
