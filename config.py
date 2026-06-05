# -*- coding: utf-8 -*-
import os

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    """应用配置"""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'hoshino-blog-secret-key'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'mysql+pymysql://hoshino:hoshino_pass@localhost:3306/hoshino_blog?charset=utf8mb4'
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 10,
        'pool_recycle': 3600,
        'pool_pre_ping': True,
        'max_overflow': 5,
        'connect_args': {'charset': 'utf8mb4'},
    }
    UPLOAD_FOLDER = os.path.join(basedir, 'static', 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB
    POSTS_PER_PAGE = 6


ActiveConfig = Config
