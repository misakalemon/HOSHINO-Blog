# -*- coding: utf-8 -*-
"""
HOSHINO Blog — 数据模型

四个核心模型：
  User     — 用户（管理员 + 普通用户）
  Category — 文章分类（支持多对多）
  Post     — 文章（支持多对多分类，最多 15 个）
  Comment  — 评论（需管理员审核）

关联关系：
  User ──1:N──→ Post                  一个用户有多篇文章
  Post ──M:N──→ Category             一篇文章可属于多个分类
  Post ──1:N──→ Comment               一篇文章有多条评论

技术栈：
  Flask-SQLAlchemy — ORM 映射
  Flask-Login 的 UserMixin — 提供 is_authenticated / is_active 等属性
  Werkzeug 的 security 模块 — 密码哈希（PBKDF2-SHA256）
"""
import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

# SQLAlchemy 实例，所有模型共享
# 采用延迟初始化模式：先创建 db 实例，然后在 create_app() 中 db.init_app(app)
db = SQLAlchemy()


# ── 多对多关联表 ────────────────────────────────
# 文章 ↔ 分类 的多对多关系表
# 允许一篇文章属于多个分类，一个分类包含多篇文章
# 使用 SQLAlchemy 的 Table 定义，不是 Model 类
post_categories = db.Table(
    'post_categories',
    # post_id 和 category_id 组成联合主键，确保同一对关系不重复
    db.Column('post_id', db.Integer, db.ForeignKey('posts.id'), primary_key=True),
    db.Column('category_id', db.Integer, db.ForeignKey('categories.id'), primary_key=True)
)


class User(UserMixin, db.Model):
    """用户模型。

    继承 UserMixin 以获得 Flask-Login 所需的：
      is_authenticated, is_active, is_anonymous, get_id()
    不需要显式实现这些方法。

    __tablename__ = 'users'
    """
    __tablename__ = 'users'

    # ── 基本信息 ────────────────────────────────
    id = db.Column(db.Integer, primary_key=True)                    # 主键，自增
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)  # 登录名，唯一
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)    # 邮箱，唯一
    password_hash = db.Column(db.String(256), nullable=False)       # 加密后的密码哈希值

    # ── 个人信息（可选） ─────────────────────────
    display_name = db.Column(db.String(128), default='')   # 显示昵称（页面展示用）
    bio = db.Column(db.Text, default='')                   # 个人简介
    avatar = db.Column(                                    # 头像路径（相对于 static/）
        db.String(256), default='images/avatar/main-avatar.jpg'
    )

    # ── 权限状态 ────────────────────────────────
    is_admin = db.Column(db.Boolean, default=False)   # 是否管理员（可访问后台）
    is_active = db.Column(db.Boolean, default=True)    # 是否激活（可登录）

    # ── 时间戳 ──────────────────────────────────
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    # ── 关联关系 ────────────────────────────────
    # 一对多：一个用户有多篇文章
    # backref='author' 给 Post 添加 .author 属性
    # lazy='dynamic' 返回 Query 对象而非列表，可继续链式过滤
    posts = db.relationship('Post', backref='author', lazy='dynamic')

    # ── 密码方法 ────────────────────────────────
    def set_password(self, password):
        """设置加密密码。

        使用 Werkzeug 的 generate_password_hash，
        默认使用 PBKDF2-SHA256 算法，自动加盐。
        """
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """验证密码。"""
        return check_password_hash(self.password_hash, password)

    # ── 序列化 ──────────────────────────────────
    def to_dict(self):
        """返回用户信息的字典（用于 JSON API）。"""
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'display_name': self.display_name,
            'is_admin': self.is_admin,
        }


class Category(db.Model):
    """文章分类模型。

    __tablename__ = 'categories'

    每个分类有唯一的 name 和 slug（slug 用于 URL）。
    通过 post_categories 关联表与 Post 建立多对多关系。
    """
    __tablename__ = 'categories'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)    # 分类名，唯一
    slug = db.Column(db.String(64), unique=True, nullable=False, index=True)  # URL 标识
    description = db.Column(db.Text, default='')                    # 分类描述
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    # 多对多关联：一个分类包含多篇文章
    # secondary 指向关联表 post_categories
    # back_populates='categories' 与 Post 中的 categories 对应
    # lazy='dynamic' 返回 Query 而非列表
    posts = db.relationship(
        'Post', secondary=post_categories,
        back_populates='categories', lazy='dynamic'
    )

    def post_count(self):
        """返回该分类下已发布的文章数。

        过滤 is_published=True，不统计草稿。
        """
        return self.posts.filter_by(is_published=True).count()


class Post(db.Model):
    """文章模型。

    __tablename__ = 'posts'

    文章支持 Markdown 格式的内容，支持多分类标签，
    关联的评论需要管理员审核后才能公开显示。
    slug 用于 URL 友好访问，必须唯一。
    """
    __tablename__ = 'posts'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(256), nullable=False)      # 文章标题
    slug = db.Column(db.String(256), unique=True, nullable=False, index=True)  # URL 标识
    summary = db.Column(db.Text, default='')               # 文章摘要（列表页使用）
    content = db.Column(db.Text, nullable=False)           # Markdown 正文
    cover_image = db.Column(db.String(256), default='')    # 封面图片路径
    author_id = db.Column(                                  # 作者（外键 → users.id）
        db.Integer, db.ForeignKey('users.id'), nullable=False
    )
    is_published = db.Column(db.Boolean, default=False)    # 是否已发布

    # ── 时间戳 ──────────────────────────────────
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow   # 更新时自动修改
    )

    # ── 关联关系 ────────────────────────────────
    # 多对多：一篇文章可以有多个分类（最多 15 个）
    # lazy='select' 在访问时才加载（默认行为）
    categories = db.relationship(
        'Category', secondary=post_categories,
        back_populates='posts', lazy='select'
    )
    # 一对多：一篇文章有多条评论
    # lazy='dynamic' 返回 Query，可链式过滤 is_approved=True
    comments = db.relationship(
        'Comment', backref='post', lazy='dynamic',
        order_by='Comment.created_at'
    )

    # ── 辅助方法 ────────────────────────────────
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
    """评论模型。

    __tablename__ = 'comments'

    访客评论需管理员审核（is_approved=False 时不显示在前台）。
    支持邮箱字段（选填），不强制登录即可评论。
    """
    __tablename__ = 'comments'

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(                                  # 所属文章（外键 → posts.id）
        db.Integer, db.ForeignKey('posts.id'), nullable=False
    )
    author_name = db.Column(db.String(128), nullable=False)   # 评论者昵称
    author_email = db.Column(db.String(120), nullable=True)   # 评论者邮箱（选填）
    content = db.Column(db.Text, nullable=False)              # 评论正文
    is_approved = db.Column(db.Boolean, default=False)        # 管理员审核标记
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)


# ═══════════════════════════════════════════════
# 价格追踪模型
# ═══════════════════════════════════════════════

class Product(db.Model):
    """电子产品模型。

    追踪的商品。
    __tablename__ = 'products'
    """
    __tablename__ = 'products'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(256), nullable=False, index=True)
    brand = db.Column(db.String(128), default='')
    category = db.Column(db.String(64), default='')
    image_url = db.Column(db.String(512), default='')
    specs = db.Column(db.JSON, default=dict)  # 关键规格参数（JSON格式）
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow
    )

    price_records = db.relationship(
        'PriceRecord', backref='product', lazy='dynamic',
        foreign_keys='PriceRecord.product_id',
        order_by='PriceRecord.recorded_at'
    )

    def latest_price(self):
        return self.price_records.order_by(PriceRecord.recorded_at.desc()).first()

    def price_history(self, days=30):
        since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
        return self.price_records.filter(
            PriceRecord.recorded_at >= since
        ).order_by(PriceRecord.recorded_at.asc()).all()


class ProductSource(db.Model):
    """商品来源网站配置。
    __tablename__ = 'product_sources'
    """
    __tablename__ = 'product_sources'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(
        db.Integer, db.ForeignKey('products.id'), nullable=False, index=True
    )
    site = db.Column(db.String(64), nullable=False)
    url = db.Column(db.String(1024), nullable=False)
    latest_price = db.Column(db.Float, default=0)
    is_active = db.Column(db.Boolean, default=True)
    product = db.relationship('Product', backref='sources')


class PriceRecord(db.Model):
    """单次价格记录。
    __tablename__ = 'price_records'
    """
    __tablename__ = 'price_records'

    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(
        db.Integer, db.ForeignKey('product_sources.id'), nullable=False, index=True
    )
    product_id = db.Column(
        db.Integer, db.ForeignKey('products.id'), nullable=False, index=True
    )
    price = db.Column(db.Float, nullable=False)
    recorded_at = db.Column(
        db.DateTime, default=datetime.datetime.utcnow, index=True
    )
    source = db.relationship('ProductSource', backref=db.backref('records', lazy='dynamic'))
