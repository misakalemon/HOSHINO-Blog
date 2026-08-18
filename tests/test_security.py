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


class TestHTMLSanitizer:
    """回归测试：_sanitize_html 白名单不得放行可执行/表单标签"""

    def _sanitize(self, html):
        from blog.admin import _sanitize_html
        return _sanitize_html(html)

    def test_script_tag_removed(self, app):
        out = self._sanitize('<script src="https://evil.com/x.js"></script><p>hi</p>')
        assert '<script' not in out.lower()
        assert 'evil.com' not in out
        assert '<p>hi</p>' in out

    def test_inline_script_removed(self, app):
        out = self._sanitize('<p>a</p><script>alert(1)</script><p>b</p>')
        assert '<script' not in out.lower()

    def test_javascript_href_stripped(self, app):
        out = self._sanitize('<a href="javascript:alert(1)">click</a>')
        assert 'javascript:' not in out.lower()
        assert 'click' in out  # 文本保留

    def test_form_and_input_removed(self, app):
        out = self._sanitize('<form action="https://evil.com"><input name="x"></form><p>t</p>')
        assert '<form' not in out.lower()
        assert '<input' not in out.lower()

    def test_meta_and_link_removed(self, app):
        out = self._sanitize('<meta http-equiv="refresh"><link rel="stylesheet" href="https://evil.com/x.css"><p>t</p>')
        assert '<meta' not in out.lower()
        assert '<link' not in out.lower()

    def test_evil_iframe_removed(self, app):
        out = self._sanitize('<iframe src="https://evil.com/phishing"></iframe><p>t</p>')
        assert '<iframe' not in out.lower()

    def test_bilibili_iframe_kept(self, app):
        out = self._sanitize('<iframe src="https://player.bilibili.com/player.html?bvid=BV1xx"></iframe>')
        assert 'player.bilibili.com' in out

    def test_protocol_relative_url_rejected(self, app):
        out = self._sanitize('<a href="//evil.com/x">link</a>')
        assert 'evil.com' not in out


class TestImageUrlSafety:
    """回归测试：is_safe_image_url 拒绝路径穿越"""

    def test_traversal_rejected(self, app):
        from blog.utils import is_safe_image_url
        assert not is_safe_image_url('uploads/avatar_../../../app.py')
        assert not is_safe_image_url('/static/../../config.py')
        assert not is_safe_image_url('uploads/../.env')

    def test_normal_paths_accepted(self, app):
        from blog.utils import is_safe_image_url
        assert is_safe_image_url('uploads/avatar_123.webp')
        assert is_safe_image_url('/static/uploads/x.png')
        assert is_safe_image_url('https://example.com/a.png')

    def test_javascript_rejected(self, app):
        from blog.utils import is_safe_image_url
        assert not is_safe_image_url('javascript:alert(1)')


class TestEscapeLike:
    """回归测试：escape_like 必须转义反斜杠本身"""

    def test_backslash_escaped(self, app):
        from blog.utils import escape_like
        assert escape_like('100\\%') == '100\\\\\\%'
        assert '\\\\' in escape_like('a\\b')

    def test_wildcards_escaped(self, app):
        from blog.utils import escape_like
        assert escape_like('50%_off') == '50\\%\\_off'