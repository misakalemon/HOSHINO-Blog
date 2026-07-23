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
import re
import time

logger = logging.getLogger(__name__)

# Redis 客户端实例（由 app.py 的 init_redis() 初始化）
_redis_client = None

# 缓存键统一前缀，方便在 Redis 中识别和批量删除
_KEY_PREFIX = 'hblog'


def _get_redis(redis_url, max_retries=3, retry_delay=1):
    """尝试连接 Redis，失败时返回 None（快速降级）。

    使用简单重试机制，最多重试 max_retries 次，每次间隔 retry_delay 秒。

    Args:
        redis_url: Redis 连接字符串，如 redis://:password@host:6379/0
        max_retries: 最大重试次数，默认 3
        retry_delay: 每次重试的间隔秒数，默认 1

    Returns:
        redis.Redis | None: 成功返回 Redis 客户端实例，失败返回 None
    """
    import redis

    # 脱敏处理连接 URL，避免日志中泄露密码
    safe_url = re.sub(r'://[^@]+@', '://***@', redis_url) if redis_url else redis_url

    for attempt in range(max_retries):
        try:
            # 创建 Redis 连接：设置短超时（连接 2s、读写 3s）以确保快速失败
            client = redis.from_url(
                redis_url,
                decode_responses=True,       # 自动将字节响应解码为 UTF-8 字符串
                socket_connect_timeout=2,    # 连接超时 2 秒
                socket_timeout=3,            # 读写超时 3 秒
                retry_on_timeout=False,      # 不自动重试超时，由外部重试逻辑控制
            )
            client.ping()                   # 发送 PING 确认连接可用
            return client
        except Exception as e:
            # 非最后一次尝试时记录警告，最后一次记录降级信息
            if attempt < max_retries - 1:
                logger.warning('Redis 连接失败 (尝试 %d/%d): %s', attempt + 1, max_retries, safe_url)
                time.sleep(retry_delay)
            else:
                logger.warning('Redis 连接失败，缓存已降级: %s', safe_url)
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
    # 未配置 REDIS_URL 时直接降级，不尝试连接
    if not redis_url:
        logger.info('Redis 未配置（REDIS_URL 为空），缓存层已禁用')
        _redis_client = None
        return

    _redis_client = _get_redis(redis_url)
    if _redis_client is not None:
        # 使用脱敏后的 URL 记录日志（隐藏密码）
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

    将 JSON 字符串反序列化为 Python 对象后返回。
    Redis 不可用时静默降级，返回 None。

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
    使用 SETEX 命令原子性地设置值和过期时间。

    Args:
        key: 业务键名（不含前缀）
        value: 可 JSON 序列化的 Python 对象
        ttl: 过期时间（秒），默认 300 秒（5 分钟）
    """
    if _redis_client is None:
        return
    try:
        # ensure_ascii=False 确保中文等非 ASCII 字符不被转义为 \uXXXX
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
    内部使用游标迭代扫描，每次最多取 50 个键。
    例如 cache_delete_pattern('sidebar:*') 会删除所有侧边栏缓存。

    Args:
        pattern: 键名匹配模式（不含前缀），如 'sidebar:*'
    """
    if _redis_client is None:
        return
    try:
        full_pattern = _make_key(pattern)
        cursor = 0          # SCAN 游标，0 表示开始或结束
        while True:
            # SCAN 是非阻塞的键遍历命令，相比 KEYS 更适合生产环境
            cursor, keys = _redis_client.scan(cursor, match=full_pattern, count=50)
            if keys:
                # 批量删除本次扫描到的所有匹配键
                _redis_client.delete(*keys)
            if cursor == 0:
                # 游标返回 0 表示遍历完成
                break
    except Exception as e:
        logger.debug('缓存批量删除失败 pattern=%s: %s', pattern, e)
