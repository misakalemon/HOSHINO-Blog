"""
HOSHINO Blog — Redis 缓存层

职责：
  为应用提供统一的 Redis 缓存接口，降低数据库查询频率。
  当 Redis 不可用时自动降级（静默失败，走数据库查询）。

缓存键命名规则：
  hblog:<模块>:<key>   — 例如 hblog:sidebar:categories

支持的缓存项：
  sidebar:categories    — 侧边栏分类列表（TTL: CACHE_TTL_SIDEBAR）
  sidebar:recent_posts  — 侧边栏最新文章（TTL: CACHE_TTL_SIDEBAR）
  dashboard:stats       — 仪表盘统计数据（TTL: CACHE_TTL_DASHBOARD）
  rss:feed              — RSS XML 输出（TTL: CACHE_TTL_RSS）

使用方式：
  from blog.cache import cache_get, cache_set, cache_delete_pattern

  # 读缓存
  data = cache_get('sidebar:categories')
  if data is None:
      data = query_database()
      cache_set('sidebar:categories', data, ttl=300)

  # 清除缓存（数据变更时）
  cache_delete_pattern('sidebar:*')

依赖：
  redis==5.2.1  （pip install redis）
"""

import json
import logging
import time

logger = logging.getLogger(__name__)

# Redis 客户端实例（由 app.py 的 init_redis() 初始化）
_redis_client = None

# 缓存键统一前缀，方便在 Redis 中识别和批量删除
_KEY_PREFIX = 'hblog'


def _get_redis(redis_url, max_retries=3, retry_delay=1):
    """尝试连接 Redis，失败时返回 None（快速降级）。

    使用简单重试机制，最多重试 max_retries 次，每次间隔 retry_delay 秒。
    """
    import redis

    for attempt in range(max_retries):
        try:
            client = redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=3,
                retry_on_timeout=False,
            )
            client.ping()
            return client
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning('Redis 连接失败 (尝试 %d/%d): %s', attempt + 1, max_retries, e)
                time.sleep(retry_delay)
            else:
                logger.warning('Redis 连接失败，缓存已降级: %s', e)
                return None


def init_redis(app):
    """初始化 Redis 连接。

    在 create_app() 中调用，将全局 _redis_client 初始化为
    redis.Redis 实例。如果 REDIS_URL 未配置或连接失败，
    则标记为不可用（_redis_client = None），后续所有缓存操作静默降级。

    Args:
        app: Flask 应用实例（从 app.config 中读取 REDIS_URL）
    """
    global _redis_client

    redis_url = app.config.get('REDIS_URL')
    if not redis_url:
        logger.info('Redis 未配置（REDIS_URL 为空），缓存层已禁用')
        _redis_client = None
        return

    _redis_client = _get_redis(redis_url)
    if _redis_client is not None:
        from urllib.parse import urlparse
        parsed = urlparse(redis_url)
        safe_url = f'{parsed.scheme}://{parsed.hostname}:{parsed.port}{parsed.path}'
        logger.info('Redis 缓存已连接: %s', safe_url)


def _make_key(key):
    """构建带前缀的完整缓存键。

    Args:
        key: 业务键名，如 'sidebar:categories'

    Returns:
        str: 完整缓存键，如 'hblog:sidebar:categories'
    """
    return f'{_KEY_PREFIX}:{key}'


def cache_get(key):
    """从 Redis 获取缓存数据。

    Args:
        key: 业务键名（不含前缀）

    Returns:
        any: 反序列化后的 Python 对象，缓存不存在或 Redis 不可用时返回 None
    """
    if _redis_client is None:
        return None
    try:
        data = _redis_client.get(_make_key(key))
        if data is not None:
            return json.loads(data)
        return None
    except Exception as e:
        logger.debug('缓存读取失败 key=%s: %s', key, e)
        return None


def cache_set(key, value, ttl=300):
    """将数据写入 Redis 缓存。

    自动将 Python 对象序列化为 JSON 字符串存储。

    Args:
        key: 业务键名（不含前缀）
        value: 可 JSON 序列化的 Python 对象
        ttl: 过期时间（秒），默认 300 秒（5 分钟）
    """
    if _redis_client is None:
        return
    try:
        _redis_client.setex(_make_key(key), ttl, json.dumps(value, ensure_ascii=False))
    except Exception as e:
        logger.debug('缓存写入失败 key=%s: %s', key, e)


def cache_delete(key):
    """删除指定的缓存键。

    Args:
        key: 业务键名（不含前缀）
    """
    if _redis_client is None:
        return
    try:
        _redis_client.delete(_make_key(key))
    except Exception as e:
        logger.debug('缓存删除失败 key=%s: %s', key, e)


def cache_delete_pattern(pattern):
    """按模式批量删除缓存键。

    使用 Redis SCAN 命令匹配键名，不会阻塞服务器。
    例如 cache_delete_pattern('sidebar:*') 会删除所有侧边栏缓存。

    Args:
        pattern: 键名匹配模式（不含前缀），如 'sidebar:*'
    """
    if _redis_client is None:
        return
    try:
        full_pattern = _make_key(pattern)
        cursor = 0
        while True:
            cursor, keys = _redis_client.scan(cursor, match=full_pattern, count=50)
            if keys:
                _redis_client.delete(*keys)
            if cursor == 0:
                break
    except Exception as e:
        logger.debug('缓存批量删除失败 pattern=%s: %s', pattern, e)


def cache_scan(pattern):
    """按模式扫描并返回所有 (key, value) 对。

    Redis 不可用时返回空列表。
    例如 cache_scan('crawl:result:*') 返回所有爬取结果。

    Args:
        pattern: 键名匹配模式（不含前缀）

    Returns:
        list[tuple[str, any]]: (业务键名, 反序列化后的值) 列表
    """
    if _redis_client is None:
        return []
    try:
        full_pattern = _make_key(pattern)
        results = []
        cursor = 0
        while True:
            cursor, keys = _redis_client.scan(cursor, match=full_pattern, count=100)
            if keys:
                raws = _redis_client.mget(keys)
                for key, raw in zip(keys, raws):
                    if raw is not None:
                        biz_key = key[len(_KEY_PREFIX) + 1 :]
                        results.append((biz_key, json.loads(raw)))
            if cursor == 0:
                break
        return results
    except Exception as e:
        logger.debug('缓存扫描失败 pattern=%s: %s', pattern, e)
        return []
