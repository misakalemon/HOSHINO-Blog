"""HOSHINO Blog — Redis 任务队列测试（纯单元测试，不依赖真实 Redis/MySQL）

使用 mock 替身模拟 Redis 客户端，覆盖 task_queue.py 的全部公开函数：
签名/验签、提交/获取/确认/重投/恢复、进度、运行锁、降级路径。
"""
# ruff: noqa: PLR2004, PLC0415
import json
from unittest.mock import MagicMock

import pytest

import blog.cache as cache_mod
import blog.task_queue as tq

pytestmark = pytest.mark.pure


@pytest.fixture
def mock_redis(monkeypatch):
    """注入 mock Redis 客户端到 task_queue 模块。"""
    client = MagicMock()
    monkeypatch.setattr(tq, '_redis_client', client)
    return client


@pytest.fixture
def secret_key(monkeypatch):
    """设置任务签名密钥。"""
    monkeypatch.setattr(tq, '_secret_key', 'test-secret-key')
    return 'test-secret-key'


# ── _canonical / _sign ─────────────────────────────────────
class TestCanonical:
    def test_sorted_keys(self):
        out = tq._canonical({'b': 2, 'a': 1})
        assert out == '{"a":1,"b":2}'

    def test_compact_separators(self):
        out = tq._canonical({'a': 1})
        assert out == '{"a":1}'  # 无空格

    def test_unicode_preserved(self):
        out = tq._canonical({'k': '中文'})
        assert '中文' in out


class TestSign:
    def test_empty_key_returns_empty(self, monkeypatch):
        monkeypatch.setattr(tq, '_secret_key', '')
        assert tq._sign('payload') == ''

    def test_with_key_returns_hex(self, secret_key):
        s = tq._sign('payload')
        assert isinstance(s, str)
        assert len(s) == 64  # SHA256 hex
        assert all(c in '0123456789abcdef' for c in s)

    def test_deterministic(self, secret_key):
        assert tq._sign('x') == tq._sign('x')

    def test_different_payload_different_sig(self, secret_key):
        assert tq._sign('x') != tq._sign('y')


# ── is_queue_available ─────────────────────────────────────
class TestIsQueueAvailable:
    def test_available(self, mock_redis):
        assert tq.is_queue_available() is True

    def test_unavailable(self, monkeypatch):
        monkeypatch.setattr(tq, '_redis_client', None)
        assert tq.is_queue_available() is False


# ── submit_task ────────────────────────────────────────────
class TestSubmitTask:
    def test_no_redis_returns_none(self, monkeypatch):
        monkeypatch.setattr(tq, '_redis_client', None)
        assert tq.submit_task('bili', aid=1) is None

    def test_success_returns_id(self, mock_redis, secret_key):
        mock_redis.llen.return_value = 0
        tid = tq.submit_task('bili', aid=123)
        assert tid is not None
        assert len(tid) == 12
        mock_redis.lpush.assert_called_once()

    def test_task_structure(self, mock_redis, secret_key):
        mock_redis.llen.return_value = 0
        tq.submit_task('bili', aid=123, title='测试')
        raw = mock_redis.lpush.call_args.args[1]
        task = json.loads(raw)
        assert task['type'] == 'bili'
        assert task['data'] == {'aid': 123, 'title': '测试'}
        assert 'submitted_at' in task
        assert 'sig' in task and task['sig']

    def test_queue_full_returns_none(self, mock_redis, secret_key):
        mock_redis.llen.return_value = tq._MAX_QUEUE_SIZE
        assert tq.submit_task('bili', aid=1) is None
        mock_redis.lpush.assert_not_called()

    def test_exception_returns_none(self, mock_redis, secret_key):
        mock_redis.llen.return_value = 0
        mock_redis.lpush.side_effect = RuntimeError
        assert tq.submit_task('bili', aid=1) is None

    def test_no_secret_still_submits(self, mock_redis, monkeypatch):
        monkeypatch.setattr(tq, '_secret_key', '')
        mock_redis.llen.return_value = 0
        tid = tq.submit_task('bili', aid=1)
        assert tid is not None
        raw = mock_redis.lpush.call_args.args[1]
        task = json.loads(raw)
        assert task['sig'] == ''  # 无密钥时签名为空


# ── verify_task_signature ──────────────────────────────────
class TestVerifyTaskSignature:
    def test_no_secret_allows(self, monkeypatch):
        monkeypatch.setattr(tq, '_secret_key', '')
        assert tq.verify_task_signature({'sig': 'x'}) is True

    def test_valid_signature(self, mock_redis, secret_key):
        mock_redis.llen.return_value = 0
        tq.submit_task('bili', aid=1)
        task = json.loads(mock_redis.lpush.call_args.args[1])
        assert tq.verify_task_signature(task) is True

    def test_tampered_signature_rejected(self, secret_key):
        task = {'id': 'x', 'type': 'bili', 'data': {}, 'submitted_at': 1, 'sig': 'bad'}
        assert tq.verify_task_signature(task) is False

    def test_missing_signature_rejected(self, secret_key):
        assert tq.verify_task_signature({'id': 'x', 'type': 't'}) is False

    def test_tampered_data_rejected(self, mock_redis, secret_key):
        mock_redis.llen.return_value = 0
        tq.submit_task('bili', aid=1)
        task = json.loads(mock_redis.lpush.call_args.args[1])
        task['data'] = {'aid': 999}  # 篡改数据但保留旧 sig
        assert tq.verify_task_signature(task) is False


# ── get_task ───────────────────────────────────────────────
class TestGetTask:
    def test_no_redis_returns_none(self, monkeypatch):
        monkeypatch.setattr(tq, '_redis_client', None)
        assert tq.get_task() is None

    def test_returns_task(self, mock_redis):
        task = {'id': 'x', 'type': 'bili'}
        mock_redis.brpoplpush.return_value = json.dumps(task)
        assert tq.get_task() == task

    def test_empty_queue_returns_none(self, mock_redis):
        mock_redis.brpoplpush.return_value = None
        assert tq.get_task() is None

    def test_exception_returns_none(self, mock_redis):
        mock_redis.brpoplpush.side_effect = RuntimeError
        assert tq.get_task() is None


# ── ack_task ───────────────────────────────────────────────
class TestAckTask:
    def test_no_redis_is_noop(self, monkeypatch):
        monkeypatch.setattr(tq, '_redis_client', None)
        tq.ack_task({'id': 'x'})

    def test_empty_task_is_noop(self, mock_redis):
        tq.ack_task({})
        mock_redis.lrem.assert_not_called()

    def test_no_id_is_noop(self, mock_redis):
        tq.ack_task({'data': 1})
        mock_redis.lrem.assert_not_called()

    def test_ack_removes_from_backup(self, mock_redis):
        task = {'id': 'x', 'type': 'bili'}
        tq.ack_task(task)
        mock_redis.lrem.assert_called_once()
        assert mock_redis.lrem.call_args.args[0] == tq._TASK_BACKUP_KEY
        assert mock_redis.lrem.call_args.args[1] == 1

    def test_exception_silent(self, mock_redis):
        mock_redis.lrem.side_effect = RuntimeError
        tq.ack_task({'id': 'x'})  # 不应抛异常


# ── requeue_task ───────────────────────────────────────────
class TestRequeueTask:
    def test_no_redis_returns_false(self, monkeypatch):
        monkeypatch.setattr(tq, '_redis_client', None)
        assert tq.requeue_task({'id': 'x'}, 'raw') is False

    def test_success_returns_true(self, mock_redis, secret_key):
        task = {'id': 'x', 'type': 'bili', 'data': {}}
        assert tq.requeue_task(task, 'orig') is True
        mock_redis.lrem.assert_called_once_with(tq._TASK_BACKUP_KEY, 1, 'orig')
        mock_redis.lpush.assert_called_once()

    def test_resigns_on_requeue(self, mock_redis, secret_key):
        task = {'id': 'x', 'type': 'bili', 'data': {'_retries': 1}, 'sig': 'old'}
        tq.requeue_task(task, 'orig')
        new_raw = mock_redis.lpush.call_args.args[1]
        new_task = json.loads(new_raw)
        assert new_task['sig'] != 'old'  # 已重签名
        assert tq.verify_task_signature(new_task) is True

    def test_empty_original_skips_lrem(self, mock_redis, secret_key):
        assert tq.requeue_task({'id': 'x'}, '') is True
        mock_redis.lrem.assert_not_called()

    def test_exception_returns_false(self, mock_redis, secret_key):
        mock_redis.lpush.side_effect = RuntimeError
        assert tq.requeue_task({'id': 'x'}, '') is False


# ── recover_backup_tasks ───────────────────────────────────
class TestRecoverBackupTasks:
    def test_no_redis_is_noop(self, monkeypatch):
        monkeypatch.setattr(tq, '_redis_client', None)
        tq.recover_backup_tasks()

    def test_empty_backup(self, mock_redis):
        mock_redis.lrange.return_value = []
        tq.recover_backup_tasks()
        mock_redis.lpush.assert_not_called()
        mock_redis.delete.assert_not_called()

    def test_requeue_all(self, mock_redis):
        tasks = [json.dumps({'id': 'a'}), json.dumps({'id': 'b'})]
        mock_redis.lrange.return_value = tasks
        tq.recover_backup_tasks()
        assert mock_redis.lpush.call_count == 2
        mock_redis.delete.assert_called_once_with(tq._TASK_BACKUP_KEY)

    def test_dedup_by_id(self, mock_redis):
        tasks = [json.dumps({'id': 'a'}), json.dumps({'id': 'a'}), json.dumps({'id': 'b'})]
        mock_redis.lrange.return_value = tasks
        tq.recover_backup_tasks()
        assert mock_redis.lpush.call_count == 2  # a 去重，仅 a、b 入队

    def test_malformed_entry_skipped(self, mock_redis):
        tasks = ['not-json', json.dumps({'id': 'a'})]
        mock_redis.lrange.return_value = tasks
        tq.recover_backup_tasks()
        assert mock_redis.lpush.call_count == 1

    def test_exception_silent(self, mock_redis):
        mock_redis.lrange.side_effect = RuntimeError
        tq.recover_backup_tasks()  # 不应抛异常


# ── update_progress / get_progress ─────────────────────────
class TestProgress:
    def test_update_no_redis_is_noop(self, monkeypatch):
        monkeypatch.setattr(tq, '_redis_client', None)
        tq.update_progress(1, ['line'])

    def test_update_writes_setex(self, mock_redis):
        tq.update_progress(1, ['line1', 'line2'])
        mock_redis.setex.assert_called_once()
        key = mock_redis.setex.call_args.args[0]
        assert key == f'{tq._TASK_PROGRESS_KEY}:1'
        assert mock_redis.setex.call_args.args[1] == 3600

    def test_update_exception_silent(self, mock_redis):
        mock_redis.setex.side_effect = RuntimeError
        tq.update_progress(1, ['line'])  # 不应抛异常

    def test_get_no_redis_returns_none_false(self, monkeypatch):
        monkeypatch.setattr(tq, '_redis_client', None)
        lines, running = tq.get_progress(1)
        assert lines is None
        assert running is False

    def test_get_with_data(self, mock_redis):
        mock_redis.get.return_value = json.dumps(['l1', 'l2'])
        mock_redis.exists.return_value = 1
        lines, running = tq.get_progress(1)
        assert lines == ['l1', 'l2']
        assert running is True

    def test_get_empty_progress(self, mock_redis):
        mock_redis.get.return_value = None
        mock_redis.exists.return_value = 0
        lines, running = tq.get_progress(1)
        assert lines == []
        assert running is False

    def test_get_exception_returns_empty(self, mock_redis):
        mock_redis.get.side_effect = RuntimeError
        mock_redis.exists.return_value = 0
        lines, running = tq.get_progress(1)
        assert lines == []
        assert running is False


# ── try_acquire / mark_running / mark_done / is_running ────
class TestRunningLock:
    def test_try_acquire_no_redis_returns_true(self, monkeypatch):
        monkeypatch.setattr(tq, '_redis_client', None)
        assert tq.try_acquire(1) is True  # 降级放行

    def test_try_acquire_success(self, mock_redis):
        mock_redis.set.return_value = True
        assert tq.try_acquire(1) is True
        key = mock_redis.set.call_args.args[0]
        assert key == f'{tq._TASK_LOCK_KEY_PREFIX}:1'
        assert mock_redis.set.call_args.kwargs['nx'] is True

    def test_try_acquire_busy_returns_false(self, mock_redis):
        mock_redis.set.return_value = None
        assert tq.try_acquire(1) is False

    def test_try_acquire_exception_degrades_true(self, mock_redis):
        mock_redis.set.side_effect = RuntimeError
        assert tq.try_acquire(1) is True  # 异常时降级放行

    def test_mark_running_no_redis_is_noop(self, monkeypatch):
        monkeypatch.setattr(tq, '_redis_client', None)
        tq.mark_running(1)

    def test_mark_running_setex(self, mock_redis):
        tq.mark_running(1)
        mock_redis.setex.assert_called_once()
        key = mock_redis.setex.call_args.args[0]
        assert key == f'{tq._TASK_LOCK_KEY_PREFIX}:1'

    def test_mark_running_exception_silent(self, mock_redis):
        mock_redis.setex.side_effect = RuntimeError
        tq.mark_running(1)  # 不应抛异常

    def test_mark_done_no_redis_is_noop(self, monkeypatch):
        monkeypatch.setattr(tq, '_redis_client', None)
        tq.mark_done(1)

    def test_mark_done_deletes(self, mock_redis):
        tq.mark_done(1)
        mock_redis.delete.assert_called_once()
        key = mock_redis.delete.call_args.args[0]
        assert key == f'{tq._TASK_LOCK_KEY_PREFIX}:1'

    def test_mark_done_exception_silent(self, mock_redis):
        mock_redis.delete.side_effect = RuntimeError
        tq.mark_done(1)  # 不应抛异常

    def test_is_running_no_redis_returns_false(self, monkeypatch):
        monkeypatch.setattr(tq, '_redis_client', None)
        assert tq.is_running(1) is False

    def test_is_running_true(self, mock_redis):
        mock_redis.exists.return_value = 1
        assert tq.is_running(1) is True

    def test_is_running_false(self, mock_redis):
        mock_redis.exists.return_value = 0
        assert tq.is_running(1) is False

    def test_is_running_exception_returns_false(self, mock_redis):
        mock_redis.exists.side_effect = RuntimeError
        assert tq.is_running(1) is False


# ── init_task_queue ────────────────────────────────────────
class TestInitTaskQueue:
    def test_init_with_redis(self, monkeypatch):
        app = MagicMock()
        app.config.get.return_value = 'my-secret'
        client = MagicMock()
        monkeypatch.setattr(cache_mod, '_redis_client', client)
        tq.init_task_queue(app)
        assert tq._redis_client is client
        assert tq._secret_key == 'my-secret'

    def test_init_without_redis(self, monkeypatch):
        app = MagicMock()
        app.config.get.return_value = 'my-secret'
        monkeypatch.setattr(cache_mod, '_redis_client', None)
        tq.init_task_queue(app)
        assert tq._redis_client is None
        assert tq._secret_key == 'my-secret'

    def test_init_empty_secret(self, monkeypatch):
        app = MagicMock()
        app.config.get.return_value = None
        monkeypatch.setattr(cache_mod, '_redis_client', None)
        tq.init_task_queue(app)
        assert tq._secret_key == ''
