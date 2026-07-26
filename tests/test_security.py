"""HOSHINO Blog — 安全测试"""
import pytest


class TestCSRF:
    def test_csrf_token_in_forms(self, client):
        rv = client.get('/admin/login')
        assert b'csrf_token' in rv.data


class TestSecurityHeaders:
    def test_x_content_type_options(self, client):
        rv = client.get('/')
        assert rv.headers.get('X-Content-Type-Options') == 'nosniff'

    def test_x_frame_options(self, client):
        rv = client.get('/')
        assert rv.headers.get('X-Frame-Options') == 'SAMEORIGIN'

    def test_hsts(self, client):
        rv = client.get('/')
        assert 'Strict-Transport-Security' in rv.headers

    def test_referrer_policy(self, client):
        rv = client.get('/')
        assert 'Referrer-Policy' in rv.headers

    def test_csp_header(self, client):
        rv = client.get('/')
        csp = rv.headers.get('Content-Security-Policy', '')
        assert "default-src 'self'" in csp
        assert 'unsafe-eval' not in csp