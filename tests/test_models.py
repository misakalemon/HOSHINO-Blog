"""HOSHINO Blog — 数据模型测试"""
import pytest
from blog.models import User, Post, Category, ContactMessage


class TestUser:
    def test_set_and_check_password(self, app, _db):
        with app.app_context():
            user = User(username='test', email='test@test.com')
            user.set_password('mypassword')
            assert user.check_password('mypassword')
            assert not user.check_password('wrongpassword')

    def test_password_not_stored_plaintext(self, app, _db):
        with app.app_context():
            user = User(username='test2', email='test2@test.com')
            user.set_password('mypassword')
            assert user.password_hash != 'mypassword'

    def test_is_admin(self, app, _db):
        with app.app_context():
            user = User(username='admin', email='a@a.com', role='admin')
            assert user.is_admin

    def test_is_not_admin(self, app, _db):
        with app.app_context():
            user = User(username='user', email='u@u.com', role='user')
            assert not user.is_admin