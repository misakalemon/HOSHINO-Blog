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
# 任务备份列表：get_task 用 brpoplpush 把任务原子移到这里，
# Worker 完成后 ack_task 移除；若 Worker 崩溃，任务留在备份列表可重新入队。
_TASK_BACKUP_KEY = f'{_KEY_PREFIX}:backup'

_redis_client = None
# 任务运行超时时间（秒）：超过此时间仍未完成的任务视为卡死
_MAX_RUNNING_TIME = int(os.environ.get('BILI_MAX_RUNNING', '1800'))  # 30 分钟


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


def is_queue_available():
    """检查任务队列是否可用（Redis 已连接）。"""
    return _redis_client is not None


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
        # brpoplpush 原子地把队尾任务弹出并压入备份列表，
        # 避免 BRPOP 取出即删导致 Worker 崩溃时任务永久丢失。
        data = redis_client.brpoplpush(_TASK_QUEUE_KEY, _TASK_BACKUP_KEY, timeout=5)
        if data:
            return json.loads(data)
    except Exception:
        pass
    return None


def ack_task(task):
    """确认任务已完成：从备份列表移除该任务。

    若 Worker 在处理中崩溃（任务仍在备份列表），下次启动 worker 时
    可扫描备份列表重新入队。
    """
    redis_client = _get_redis()
    if redis_client is None or not task:
        return
    task_id = task.get('id')
    if not task_id:
        return
    try:
        raw = json.dumps(task)
        # LREM 精确删除该任务；若已被超时重投，忽略即可
        redis_client.lrem(_TASK_BACKUP_KEY, 1, raw)
    except Exception:
        pass


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
        if running:
            ts = redis_client.hget(_TASK_RUNNING_KEY, str(mid))
            if ts and time.time() - float(ts) > _MAX_RUNNING_TIME:
                redis_client.hdel(_TASK_RUNNING_KEY, str(mid))
                running = False
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
        running = redis_client.hexists(_TASK_RUNNING_KEY, str(mid))
        if running:
            ts = redis_client.hget(_TASK_RUNNING_KEY, str(mid))
            if ts and time.time() - float(ts) > _MAX_RUNNING_TIME:
                redis_client.hdel(_TASK_RUNNING_KEY, str(mid))
                return False
        return running
    except Exception:
        return False