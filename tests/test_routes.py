"""HOSHINO Blog — 路由测试"""
import pytest


class TestPublicRoutes:
    def test_home_page(self, client):
        rv = client.get('/')
        assert rv.status_code == 200

    def test_about_page(self, client):
        rv = client.get('/about')
        assert rv.status_code == 200

    def test_contact_page(self, client):
        rv = client.get('/contact')
        assert rv.status_code == 200

    def test_tools_page(self, client):
        rv = client.get('/tools')
        assert rv.status_code == 200

    def test_404_page(self, client):
        rv = client.get('/nonexistent-page')
        assert rv.status_code == 404


class TestAdminRoutes:
    def test_login_page(self, client):
        rv = client.get('/admin/login')
        assert rv.status_code == 200

    def test_admin_requires_login(self, client):
        rv = client.get('/admin/')
        assert rv.status_code in (302, 401)