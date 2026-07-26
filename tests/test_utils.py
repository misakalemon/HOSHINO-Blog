"""HOSHINO Blog — 公共工具模块测试"""
import datetime
import pytest
from blog.utils import LRUDict, RateLimiter, now_cst, get_client_ip, validate_url_protocol, escape_like, CST


class TestLRUDict:
    def test_maxsize_eviction(self):
        d = LRUDict(maxsize=3)
        d['a'] = 1
        d['b'] = 2
        d['c'] = 3
        d['d'] = 4
        assert 'a' not in d
        assert d['d'] == 4

    def test_update_existing(self):
        d = LRUDict(maxsize=3)
        d['a'] = 1
        d['a'] = 2
        assert d['a'] == 2
        assert len(d) == 1


class TestRateLimiter:
    def test_under_limit(self):
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        assert not limiter.is_limited('key1')
        assert not limiter.is_limited('key1')
        assert not limiter.is_limited('key1')

    def test_over_limit(self):
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        limiter.is_limited('key1')
        limiter.is_limited('key1')
        assert limiter.is_limited('key1')

    def test_window_reset(self):
        limiter = RateLimiter(max_requests=2, window_seconds=0)
        limiter.is_limited('key1')
        limiter.is_limited('key1')
        assert not limiter.is_limited('key1')


class TestNowCst:
    def test_returns_cst(self):
        result = now_cst()
        assert result.tzinfo == CST

    def test_is_recent(self):
        result = now_cst()
        diff = datetime.datetime.now(CST) - result
        assert abs(diff.total_seconds()) < 1


class TestValidateUrlProtocol:
    def test_http(self):
        assert validate_url_protocol('http://example.com')

    def test_https(self):
        assert validate_url_protocol('https://example.com')

    def test_mailto(self):
        assert validate_url_protocol('mailto:test@test.com')

    def test_relative(self):
        assert validate_url_protocol('/path/to/page')

    def test_javascript_blocked(self):
        assert not validate_url_protocol('javascript:alert(1)')

    def test_data_blocked(self):
        assert not validate_url_protocol('data:text/html,<h1>test</h1>')

    def test_empty(self):
        assert not validate_url_protocol('')


class TestEscapeLike:
    def test_percent(self):
        assert escape_like('100%') == r'100\%'

    def test_underscore(self):
        assert escape_like('a_b') == r'a\_b'

    def test_combined(self):
        assert escape_like('%_test') == r'\%\_test'

    def test_normal(self):
        assert escape_like('normal') == 'normal'