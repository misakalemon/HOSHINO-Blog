import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    display_name = db.Column(db.String(128), default='')
    bio = db.Column(db.Text, default='')
    avatar = db.Column(db.String(256), default='images/avatar/main-avatar.jpg')
    is_admin = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    posts = db.relationship('Post', backref='author', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'display_name': self.display_name,
            'is_admin': self.is_admin,
        }


class Category(db.Model):
    __tablename__ = 'categories'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    slug = db.Column(db.String(64), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    posts = db.relationship('Post', backref='category', lazy='dynamic')

    def post_count(self):
        return self.posts.filter_by(is_published=True).count()


class Post(db.Model):
    __tablename__ = 'posts'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(256), nullable=False)
    slug = db.Column(db.String(256), unique=True, nullable=False, index=True)
    summary = db.Column(db.Text, default='')
    content = db.Column(db.Text, nullable=False)
    cover_image = db.Column(db.String(256), default='')
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=True)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    is_published = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    comments = db.relationship('Comment', backref='post', lazy='dynamic', order_by='Comment.created_at')

    def published_comments(self):
        return self.comments.filter_by(is_approved=True).count()


class Comment(db.Model):
    __tablename__ = 'comments'

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False)
    author_name = db.Column(db.String(128), nullable=False)
    author_email = db.Column(db.String(120), nullable=True)
    content = db.Column(db.Text, nullable=False)
    is_approved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)