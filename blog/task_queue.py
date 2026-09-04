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

import hashlib
import hmac
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
# 单 UP 运行占位键前缀（string + TTL，SETNX 原子占位）
_TASK_LOCK_KEY_PREFIX = f'{_KEY_PREFIX}:lock'
# 队列长度上限（防止 Worker 停机期间任务无限堆积）
_MAX_QUEUE_SIZE = int(os.environ.get('TASK_QUEUE_MAX', '500'))

_redis_client = None
# 任务签名密钥（init_task_queue 时从 app.config['SECRET_KEY'] 获取，
# Web 与 Worker 进程使用同一密钥文件，可互相验签）
_secret_key = ''
# 任务运行超时时间（秒）：超过此时间仍未完成的任务视为卡死
_MAX_RUNNING_TIME = int(os.environ.get('BILI_MAX_RUNNING', '1800'))  # 30 分钟


def init_task_queue(app):
    global _redis_client, _secret_key
    from blog.cache import _redis_client as cache_redis
    _redis_client = cache_redis
    _secret_key = app.config.get('SECRET_KEY') or ''
    if _redis_client is not None:
        logger.info('任务队列已就绪（使用 Redis 缓存连接）')
    else:
        logger.info('任务队列不可用（Redis 未配置），任务将降级为本地线程执行')


def _get_redis():
    return _redis_client


def _sign(payload: str) -> str:
    """HMAC-SHA256 签名（防 Redis 投毒：伪造任务需持有 SECRET_KEY）。"""
    if not _secret_key:
        return ''
    return hmac.new(_secret_key.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()


def _canonical(task: dict) -> str:
    """任务规范序列化（键排序），用于签名与验签。"""
    return json.dumps(task, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def is_queue_available():
    """检查任务队列是否可用（Redis 已连接）。"""
    return _redis_client is not None


def submit_task(task_type, **kwargs):
    redis_client = _get_redis()
    if redis_client is None:
        logger.warning('任务队列不可用，无法提交 %s 任务', task_type)
        return None

    task_id = str(uuid.uuid4())[:12]
    task = {
        'id': task_id,
        'type': task_type,
        'data': kwargs,
        'submitted_at': time.time(),
    }
    # 对不含 sig 的规范载荷签名；verify 时用同样方式重建
    task['sig'] = _sign(_canonical({k: v for k, v in task.items() if k != 'sig'}))
    raw = json.dumps(task)
    try:
        # 队列长度上限保护：Worker 停机期间避免无限堆积
        if redis_client.llen(_TASK_QUEUE_KEY) >= _MAX_QUEUE_SIZE:
            logger.warning('任务队列已满（>%d），拒绝提交 %s', _MAX_QUEUE_SIZE, task_type)
            return None
        redis_client.lpush(_TASK_QUEUE_KEY, raw)
        logger.info('任务已提交 id=%s type=%s', task_id, task_type)
        return task_id
    except Exception as e:
        logger.warning('任务提交失败 id=%s type=%s: %s', task_id, task_type, e)
        return None


def verify_task_signature(task: dict) -> bool:
    """校验任务 HMAC 签名。无密钥配置时（降级模式）放行。"""
    if not _secret_key:
        return True
    sig = task.get('sig')
    if not sig:
        return False
    payload = _canonical({k: v for k, v in task.items() if k != 'sig'})
    return hmac.compare_digest(_sign(payload), sig)


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
    可扫描备份列表重新入队（见 recover_backup_tasks）。
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


def requeue_task(task, original_raw):
    """将失败任务重新入队（重试）：先从备份列表移除原串，再入队新串。

    Args:
        task: 修改过（含重试计数）的任务 dict
        original_raw: 修改前的原始 JSON 串（与备份列表中的一致）
    """
    redis_client = _get_redis()
    if redis_client is None:
        return False
    try:
        if original_raw:
            redis_client.lrem(_TASK_BACKUP_KEY, 1, original_raw)
        # 重签名：retry 时 Worker 会修改 data（如 _retries），payload 已变，
        # 旧 sig 失效 → 重新入队后 verify_task_signature 校验失败导致丢弃。
        # 用修正后的载荷重算 HMAC 再入队。
        task['sig'] = _sign(_canonical({k: v for k, v in task.items() if k != 'sig'}))
        redis_client.lpush(_TASK_QUEUE_KEY, json.dumps(task))
        return True
    except Exception as e:
        logger.warning('任务重新入队失败 id=%s: %s', task.get('id'), e)
        return False


def recover_backup_tasks():
    """Worker 启动时扫描备份列表，把上次崩溃遗留的任务重新入队。

    去重依据 task id：同一任务只恢复一次，避免崩溃后重复消费。
    任务幂等性（视频 aid 判重 / 词云覆盖写）兜底重复执行场景。
    """
    redis_client = _get_redis()
    if redis_client is None:
        return
    try:
        items = redis_client.lrange(_TASK_BACKUP_KEY, 0, -1)
        if not items:
            return
        seen = set()
        requeued = 0
        for raw in items:
            try:
                task = json.loads(raw)
                tid = task.get('id')
                if tid:
                    if tid in seen:
                        continue
                    seen.add(tid)
                redis_client.lpush(_TASK_QUEUE_KEY, raw)
                requeued += 1
            except Exception:
                continue
        redis_client.delete(_TASK_BACKUP_KEY)
        logger.warning('已从备份列表恢复 %d 个遗留任务重新入队', requeued)
    except Exception as e:
        logger.warning('备份任务恢复失败: %s', e)


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
    return lines, is_running(mid)


def try_acquire(mid):
    """原子占位：为 mid 抢占运行锁（SETNX + TTL）。

    替代原先"is_running 检查 + mark_running"的非原子组合——
    并发请求同时通过检查、重复提交同一 UP 任务的问题由此消除。
    Redis 不可用时退化放行（进程内 _scrape_running 互斥仍生效）。
    """
    redis_client = _get_redis()
    if redis_client is None:
        return True
    key = f'{_TASK_LOCK_KEY_PREFIX}:{mid}'
    try:
        ok = redis_client.set(key, str(time.time()), nx=True, ex=_MAX_RUNNING_TIME)
        return bool(ok)
    except Exception as e:
        logger.debug('运行锁获取失败 mid=%d: %s', mid, e)
        return True


def mark_running(mid):
    """标记运行中（幂等续期，供兼容旧调用）。"""
    redis_client = _get_redis()
    if redis_client is None:
        return
    key = f'{_TASK_LOCK_KEY_PREFIX}:{mid}'
    try:
        redis_client.setex(key, _MAX_RUNNING_TIME, str(time.time()))
    except Exception:
        pass


def mark_done(mid):
    """清除运行标记。"""
    redis_client = _get_redis()
    if redis_client is None:
        return
    key = f'{_TASK_LOCK_KEY_PREFIX}:{mid}'
    try:
        redis_client.delete(key)
    except Exception:
        pass


def is_running(mid):
    """检查 mid 是否在运行中（key 存在即运行中，TTL 自动过期兜底卡死）。"""
    redis_client = _get_redis()
    if redis_client is None:
        return False
    key = f'{_TASK_LOCK_KEY_PREFIX}:{mid}'
    try:
        return bool(redis_client.exists(key))
    except Exception:
        return False