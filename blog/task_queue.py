"""
HOSHINO Blog — Redis 任务队列

在 Flask Web 进程与后台 Worker 进程之间传递耗时任务，
实现进程级别的解耦，避免后台任务阻塞 HTTP 请求。

使用 Redis List 作为消息队列：
  hblog:task:queue      — 待处理的任务列表（LPUSH / BRPOP）
  hblog:task:progress   — 任务进度哈希表（{mid: [log_lines...]}）
  hblog:task:running    — 运行中任务集合（{mid: timestamp}）

当 Redis 不可用时静默降级（submit_task 返回 None）。
"""

import json
import logging
import os
import time
import uuid

logger = logging.getLogger(__name__)

_KEY_PREFIX = 'hblog:task'
_TASK_QUEUE_KEY = f'{_KEY_PREFIX}:queue'
_TASK_PROGRESS_KEY = f'{_KEY_PREFIX}:progress'
_TASK_RUNNING_KEY = f'{_KEY_PREFIX}:running'

_redis_client = None


def init_task_queue(app):
    global _redis_client
    from blog.cache import _redis_client as cache_redis
    _redis_client = cache_redis
    if _redis_client is not None:
        logger.info('任务队列已就绪（使用 Redis 缓存连接）')
    else:
        logger.info('任务队列不可用（Redis 未配置），任务将降级为本地线程执行')


def _get_redis():
    return _redis_client


def submit_task(task_type, **kwargs):
    redis_client = _get_redis()
    if redis_client is None:
        logger.warning('任务队列不可用，无法提交 %s 任务', task_type)
        return None

    task_id = str(uuid.uuid4())[:8]
    task = {
        'id': task_id,
        'type': task_type,
        'data': kwargs,
        'submitted_at': time.time(),
    }
    try:
        redis_client.lpush(_TASK_QUEUE_KEY, json.dumps(task))
        logger.info('任务已提交 id=%s type=%s', task_id, task_type)
        return task_id
    except Exception as e:
        logger.warning('任务提交失败 id=%s type=%s: %s', task_id, task_type, e)
        return None


def get_task():
    redis_client = _get_redis()
    if redis_client is None:
        return None
    try:
        _, data = redis_client.brpop(_TASK_QUEUE_KEY, timeout=5)
        if data:
            return json.loads(data)
    except (TimeoutError, TypeError):
        return None
    except Exception as e:
        logger.debug('获取任务失败: %s', e)
    return None


def update_progress(mid, lines):
    redis_client = _get_redis()
    if redis_client is None:
        return
    try:
        key = f'{_TASK_PROGRESS_KEY}:{mid}'
        redis_client.setex(key, 3600, json.dumps(lines, ensure_ascii=False))
    except Exception as e:
        logger.debug('更新进度失败 mid=%d: %s', mid, e)


def get_progress(mid):
    redis_client = _get_redis()
    if redis_client is None:
        return None, False
    try:
        key = f'{_TASK_PROGRESS_KEY}:{mid}'
        data = redis_client.get(key)
        lines = json.loads(data) if data else []
    except Exception:
        lines = []
    try:
        running = redis_client.hexists(_TASK_RUNNING_KEY, str(mid))
    except Exception:
        running = False
    return lines, running


def mark_running(mid):
    redis_client = _get_redis()
    if redis_client is None:
        return
    try:
        redis_client.hset(_TASK_RUNNING_KEY, str(mid), str(time.time()))
    except Exception:
        pass


def mark_done(mid):
    redis_client = _get_redis()
    if redis_client is None:
        return
    try:
        redis_client.hdel(_TASK_RUNNING_KEY, str(mid))
    except Exception:
        pass


def is_running(mid):
    redis_client = _get_redis()
    if redis_client is None:
        return False
    try:
        return redis_client.hexists(_TASK_RUNNING_KEY, str(mid))
    except Exception:
        return False