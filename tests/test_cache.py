"""HOSHINO Blog — Redis 缓存层测试（纯单元测试，不依赖真实 Redis/MySQL）

使用 mock 替身模拟 Redis 客户端，覆盖 cache.py 的全部公开函数与降级路径。
"""
# ruff: noqa: PLR2004, PLC0415
import json
from unittest.mock import MagicMock

import pytest

import blog.cache as cache_mod

pytestmark = pytest.mark.pure


# ── _make_key ──────────────────────────────────────────────
class TestMakeKey:
    def test_prefix(self):
        assert cache_mod._make_key('sidebar:categories') == 'hblog:sidebar:categories'

    def test_empty_key(self):
        assert cache_mod._make_key('') == 'hblog:'

    def test_arbitrary(self):
        assert cache_mod._make_key('dashboard:stats') == 'hblog:dashboard:stats'


# ── cache_get ──────────────────────────────────────────────
class TestCacheGet:
    def test_no_redis_returns_none(self, monkeypatch):
        monkeypatch.setattr(cache_mod, '_redis_client', None)
        assert cache_mod.cache_get('any') is None

    def test_hit(self, monkeypatch):
        client = MagicMock()
        client.get.return_value = json.dumps({'a': 1})
        monkeypatch.setattr(cache_mod, '_redis_client', client)
        assert cache_mod.cache_get('k') == {'a': 1}
        client.get.assert_called_once_with('hblog:k')

    def test_miss(self, monkeypatch):
        client = MagicMock()
        client.get.return_value = None
        monkeypatch.setattr(cache_mod, '_redis_client', client)
        assert cache_mod.cache_get('k') is None

    def test_exception_returns_none(self, monkeypatch):
        client = MagicMock()
        client.get.side_effect = RuntimeError('boom')
        monkeypatch.setattr(cache_mod, '_redis_client', client)
        assert cache_mod.cache_get('k') is None

    def test_unicode_value(self, monkeypatch):
        client = MagicMock()
        client.get.return_value = json.dumps({'title': '中文标题'}, ensure_ascii=False)
        monkeypatch.setattr(cache_mod, '_redis_client', client)
        assert cache_mod.cache_get('k') == {'title': '中文标题'}


# ── cache_set ──────────────────────────────────────────────
class TestCacheSet:
    def test_no_redis_is_noop(self, monkeypatch):
        monkeypatch.setattr(cache_mod, '_redis_client', None)
        cache_mod.cache_set('k', {'a': 1})  # 不应抛异常

    def test_setex_with_ttl(self, monkeypatch):
        client = MagicMock()
        monkeypatch.setattr(cache_mod, '_redis_client', client)
        cache_mod.cache_set('k', {'a': 1}, ttl=120)
        client.setex.assert_called_once_with('hblog:k', 120, json.dumps({'a': 1}, ensure_ascii=False))

    def test_default_ttl_300(self, monkeypatch):
        client = MagicMock()
        monkeypatch.setattr(cache_mod, '_redis_client', client)
        cache_mod.cache_set('k', 1)
        assert client.setex.call_args.args[1] == 300

    def test_non_serializable_warns_not_throws(self, monkeypatch):
        client = MagicMock()
        monkeypatch.setattr(cache_mod, '_redis_client', client)
        cache_mod.cache_set('k', object())  # object() 不可 JSON 序列化
        client.setex.assert_not_called()  # 序列化失败，未写入

    def test_unicode_not_escaped(self, monkeypatch):
        client = MagicMock()
        monkeypatch.setattr(cache_mod, '_redis_client', client)
        cache_mod.cache_set('k', '中文')
        raw = client.setex.call_args.args[2]
        assert '中文' in raw  # ensure_ascii=False 保留原文
        assert '\\u' not in raw

    def test_redis_error_silent(self, monkeypatch):
        client = MagicMock()
        client.setex.side_effect = RuntimeError('redis down')
        monkeypatch.setattr(cache_mod, '_redis_client', client)
        cache_mod.cache_set('k', 1)  # 不应抛异常


# ── cache_delete ───────────────────────────────────────────
class TestCacheDelete:
    def test_no_redis_is_noop(self, monkeypatch):
        monkeypatch.setattr(cache_mod, '_redis_client', None)
        cache_mod.cache_delete('k')

    def test_delete(self, monkeypatch):
        client = MagicMock()
        monkeypatch.setattr(cache_mod, '_redis_client', client)
        cache_mod.cache_delete('k')
        client.delete.assert_called_once_with('hblog:k')

    def test_exception_silent(self, monkeypatch):
        client = MagicMock()
        client.delete.side_effect = RuntimeError
        monkeypatch.setattr(cache_mod, '_redis_client', client)
        cache_mod.cache_delete('k')  # 不应抛异常


# ── cache_delete_pattern ───────────────────────────────────
class TestCacheDeletePattern:
    def test_no_redis_is_noop(self, monkeypatch):
        monkeypatch.setattr(cache_mod, '_redis_client', None)
        cache_mod.cache_delete_pattern('sidebar:*')

    def test_scan_and_delete(self, monkeypatch):
        client = MagicMock()
        # 第一次扫描返回 2 个键且游标非 0（继续），第二次游标 0（结束）
        client.scan.side_effect = [(1, ['hblog:sidebar:a', 'hblog:sidebar:b']), (0, [])]
        monkeypatch.setattr(cache_mod, '_redis_client', client)
        cache_mod.cache_delete_pattern('sidebar:*')
        client.delete.assert_called_once_with('hblog:sidebar:a', 'hblog:sidebar:b')

    def test_multiple_batches(self, monkeypatch):
        client = MagicMock()
        client.scan.side_effect = [
            (1, ['k1']),
            (2, ['k2', 'k3']),
            (0, []),
        ]
        monkeypatch.setattr(cache_mod, '_redis_client', client)
        cache_mod.cache_delete_pattern('sidebar:*')
        assert client.delete.call_count == 2

    def test_empty_result(self, monkeypatch):
        client = MagicMock()
        client.scan.return_value = (0, [])
        monkeypatch.setattr(cache_mod, '_redis_client', client)
        cache_mod.cache_delete_pattern('sidebar:*')
        client.delete.assert_not_called()

    def test_exception_silent(self, monkeypatch):
        client = MagicMock()
        client.scan.side_effect = RuntimeError
        monkeypatch.setattr(cache_mod, '_redis_client', client)
        cache_mod.cache_delete_pattern('sidebar:*')  # 不应抛异常


# ── init_redis ─────────────────────────────────────────────
class TestInitRedis:
    def test_no_url_disables(self, monkeypatch):
        app = MagicMock()
        app.config.get.return_value = None
        monkeypatch.setattr(cache_mod, '_redis_client', 'stale')
        cache_mod.init_redis(app)
        assert cache_mod._redis_client is None

    def test_with_url_connects(self, monkeypatch):
        app = MagicMock()
        app.config.get.return_value = 'redis://localhost:6379/0'
        client = MagicMock()
        monkeypatch.setattr(cache_mod, '_get_redis', lambda url, **kw: client)
        cache_mod.init_redis(app)
        assert cache_mod._redis_client is client

    def test_with_url_but_connect_fails(self, monkeypatch):
        app = MagicMock()
        app.config.get.return_value = 'redis://localhost:6379/0'
        monkeypatch.setattr(cache_mod, '_get_redis', lambda url, **kw: None)
        cache_mod.init_redis(app)
        assert cache_mod._redis_client is None


# ── _get_redis ─────────────────────────────────────────────
class TestGetRedis:
    def test_success(self, monkeypatch):
        import redis
        client = MagicMock()
        client.ping.return_value = True
        monkeypatch.setattr(redis, 'from_url', lambda *a, **kw: client)
        result = cache_mod._get_redis('redis://localhost:6379/0')
        assert result is client

    def test_ping_failure_returns_none(self, monkeypatch):
        import redis

        def fail(*a, **kw):
            c = MagicMock()
            c.ping.side_effect = RuntimeError('no redis')
            return c

        monkeypatch.setattr(redis, 'from_url', fail)
        result = cache_mod._get_redis('redis://localhost:6379/0', max_retries=2, retry_delay=0)
        assert result is None

    def test_retries_then_gives_up(self, monkeypatch):
        import redis
        attempts = {'n': 0}

        def fail(*a, **kw):
            attempts['n'] += 1
            c = MagicMock()
            c.ping.side_effect = RuntimeError
            return c

        monkeypatch.setattr(redis, 'from_url', fail)
        result = cache_mod._get_redis('redis://localhost:6379/0', max_retries=3, retry_delay=0)
        assert result is None
        assert attempts['n'] == 3
