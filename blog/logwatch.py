"""HOSHINO Blog — 独立日志看门狗子进程 (logwatch)

随 app.py 启动的独立守护进程，监听 Worker 的业务心跳文件
（blog/logs/.activity，内容为「Unix时间戳 + 最近业务活动类型」），
判定「无业务活动超阈值」是否意味着僵死，然后执行告警与可选自愈重启。

心跳写入方：worker.py
  - 增量 / 深扫 / 词云 / 任务完成 任一业务活动即时更新心跳文件；
  - Worker 主循环每 BILI_ACTIVITY_INTERVAL（默认 5 分钟）兜底刷新一次。
  - 心跳只写文件，不写日志（与「移除刷屏心跳日志」的决策兼容）。

判定口径：
  - 心跳文件 mtime 距今超过 BILI_WATCHDOG_MINUTES（默认 30）分钟，
    且期间没有任何业务心跳更新 → 判定僵死。

告警动作：
  - 写 ERROR 日志（多进程安全的 error-YYYY-MM-DD.log）；
  - send_email 发告警邮件。收件人 BILI_WATCHDOG_EMAILS（留空用 ADMIN_EMAIL），
    主题 [BILI Watchdog] 业务无活动超 XXX 分钟，正文含最近心跳时间戳。

重启策略（BILI_WATCHDOG_RESTART，默认 1）：
  0：仅告警（邮件 + ERROR 日志）
  1：kill 旧 Worker（PID 记录于 blog/logs/worker.pid）+ 重新 Popen 拉起
  2：重启整个进程组（Web + Worker 一并 SIGTERM，退出码交由外部守护接管）

自愈容错：
  - 自身主循环每个迭代独立 try/except，任一异常不会终止本守门进程；
  - 告警邮件懒加载 create_app（WORKER_PROCESS=1）复用 blog.mail.send_email，
    初始化/发送失败只记日志，不影响判定循环。

用法：python -m blog.logwatch
"""

import logging
import os
import signal
import subprocess
import sys
import time

# 兼容直接执行 python blog/logwatch.py：把项目根目录注入 sys.path，
# 否则 sys.path[0]=blog/ 目录，import blog.logger 会 ModuleNotFoundError。
# 官方启动路径是 python -m blog.logwatch（app.py 已保证 cwd=项目根）。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))   # .../blog
PROJECT_ROOT = os.path.dirname(BASE_DIR)                 # 项目根目录
LOG_DIR = os.path.join(BASE_DIR, 'logs')
ACTIVITY_FILE = os.path.join(LOG_DIR, '.activity')
WORKER_PID_FILE = os.path.join(LOG_DIR, 'worker.pid')
WORKER_PY = os.path.join(PROJECT_ROOT, 'worker.py')


def _setup_logging():
    """配置与主进程一致的多进程安全日志（文件 + 错误文件 + 终端）。"""
    import blog.logger as _logger_mod
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for h in root.handlers[:]:
        root.removeHandler(h)
    fh = _logger_mod.DailyFileHandler(_logger_mod.LOG_DIR, prefix='hoshino', level=logging.DEBUG)
    fh.setFormatter(logging.Formatter(_logger_mod.DETAILED_FORMAT, _logger_mod.DATE_FORMAT))
    root.addHandler(fh)
    efh = _logger_mod.DailyFileHandler(_logger_mod.LOG_DIR, prefix='error', level=logging.ERROR)
    efh.setFormatter(logging.Formatter(_logger_mod.DETAILED_FORMAT, _logger_mod.DATE_FORMAT))
    root.addHandler(efh)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(_logger_mod.CONSOLE_FORMAT, _logger_mod.CONSOLE_DATE_FORMAT))
    root.addHandler(ch)
    return logging.getLogger('logwatch')


logger = _setup_logging()


def _env_int(key: str, default: int) -> int:
    try:
        return int(float(os.environ.get(key, default)))
    except (TypeError, ValueError):
        return default


def _read_activity():
    """返回 (mtime, 内容)。文件不存在时 mtime 返回 0（视为无心跳）。"""
    try:
        st = os.stat(ACTIVITY_FILE)
        with open(ACTIVITY_FILE) as f:
            content = f.read().strip()
        return st.st_mtime, content
    except OSError:
        return 0.0, ''


def _read_worker_pid() -> int:
    try:
        with open(WORKER_PID_FILE) as f:
            return int(f.read().strip() or 0)
    except (OSError, ValueError):
        return 0


def _watchdog_emails() -> list:
    raw = (os.environ.get('BILI_WATCHDOG_EMAILS') or '').strip()
    if raw:
        return [e.strip() for e in raw.split(',') if e.strip()]
    return [os.environ.get('ADMIN_EMAIL', 'admin@localhost')]


def _send_alert(subject: str, html_body: str):
    """发送告警邮件（懒加载 create_app，复用 blog.mail.send_email）。"""
    try:
        from app import create_app
        app = create_app()
        with app.app_context():
            from blog.mail import send_email
            for addr in _watchdog_emails():
                try:
                    send_email(addr, subject, html_body)
                    logger.info('看门狗告警邮件已投递 → %s', addr)
                except Exception as e:
                    logger.error('看门狗告警邮件发送失败 → %s: %s', addr, e)
    except Exception as e:
        logger.error('看门狗告警邮件初始化失败: %s', e)


def _terminate_process(pid: int, wait_seconds: int = 30) -> bool:
    """SIGTERM → 等待 → SIGKILL 兜底。返回进程是否已退出。"""
    if pid <= 0:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    for _ in range(wait_seconds):
        time.sleep(1)
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            return True
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    return True


def _restart_worker():
    """kill 旧 Worker + 重新拉起（BILI_WATCHDOG_RESTART=1）。"""
    pid = _read_worker_pid()
    if pid:
        _terminate_process(pid)
        logger.warning('看门狗已终止旧 Worker (PID=%d)', pid)
    proc = subprocess.Popen(
        [sys.executable, WORKER_PY],
        cwd=PROJECT_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=sys.stderr,
        env={**os.environ, 'WORKER_PROCESS': '1'},
    )
    logger.warning('看门狗已重新拉起 Worker (PID=%d)', proc.pid)
    return proc


def _restart_process_group():
    """重启整个进程组（Web + Worker + 本进程，SIGTERM 交由外部守护接管）。"""
    try:
        pgid = os.getpgid(os.getppid())
    except (OSError, ProcessLookupError):
        pgid = None
    if pgid:
        try:
            os.killpg(pgid, signal.SIGTERM)
            logger.warning('看门狗已向进程组 pgid=%d 发送 SIGTERM', pgid)
        except (OSError, ProcessLookupError) as e:
            logger.error('看门狗进程组 SIGTERM 失败: %s', e)
    else:
        try:
            os.kill(os.getppid(), signal.SIGTERM)
        except OSError as e:
            logger.error('看门狗父进程 SIGTERM 失败: %s', e)
    # 等组内进程收尾后退出自身（若自身也被信号终止，则直接由守护接管）
    for _ in range(30):
        time.sleep(1)
        try:
            os.kill(os.getppid(), 0)
        except OSError:
            os._exit(0)
    os._exit(2)


def _check_once(state: dict) -> bool:
    """执行一轮僵死判定；返回 True 表示本轮触发了告警/重启动作。"""
    watchdog_minutes = _env_int('BILI_WATCHDOG_MINUTES', 30)
    restart_mode = _env_int('BILI_WATCHDOG_RESTART', 1)
    state.setdefault('startup_ts', time.monotonic())

    # 启动宽限：Worker 心跳刚写入还需时间，避免启动初期误报
    if time.monotonic() - state['startup_ts'] < watchdog_minutes * 60:
        return False

    now = time.time()
    mtime, content = _read_activity()
    stale = mtime <= 0 or (now - mtime) > watchdog_minutes * 60
    if not stale:
        # 心跳已恢复：重置告警 / 重启状态
        state.pop('alerted_mtime', None)
        state.pop('restarted_at', None)
        return False

    # 告警冷却：同一心跳 mtime 只告警一次；心跳始终不恢复时至少隔 1h 复查
    if state.get('alerted_mtime') == mtime and now - state.get('alerted_at', 0) < 3600:
        return False

    last_stamp = content.split()[0] if content else '?'
    subject = f'[BILI Watchdog] 业务无活动超 {watchdog_minutes} 分钟'
    html = (
        f'<p>业务心跳已超过 <b>{watchdog_minutes}</b> 分钟未更新，判定业务僵死。</p>'
        f'<p>最近一次心跳时间戳: <code>{last_stamp}</code>（Unix 秒）</p>'
        f'<p>心跳文件: <code>{ACTIVITY_FILE}</code></p>'
        f'<p>建议检查 Worker 进程是否存活，以及日志中是否存在"静默"空窗。</p>'
    )
    logger.error('%s — 最近心跳时间戳: %s', subject, last_stamp)
    try:
        _send_alert(subject, html)
    except Exception as e:
        logger.error('看门狗告警动作异常（不影响循环）: %s', e)
    state['alerted_mtime'] = mtime
    state['alerted_at'] = now

    if restart_mode == 0:
        return True

    # 重启冷却：至少间隔 max(2*watchdog 分钟, 30 分钟) 才再次重启
    if state.get('restarted_at') and now - state.get('restarted_at', 0) < max(watchdog_minutes * 120, 1800):
        return True
    try:
        if restart_mode == 1:
            _restart_worker()
        elif restart_mode == 2:
            _restart_process_group()
        state['restarted_at'] = time.time()
    except Exception as e:
        logger.error('看门狗重启动作异常: %s', e)
    return True


def main():
    check_interval = max(10, _env_int('BILI_WATCHDOG_CHECK', 60))
    logger.info('日志看门狗启动（心跳=%s 判定阈值=%d 分钟 重启模式=%d）',
                ACTIVITY_FILE,
                _env_int('BILI_WATCHDOG_MINUTES', 30),
                _env_int('BILI_WATCHDOG_RESTART', 1))
    state: dict = {}
    while True:
        try:
            _check_once(state)
        except Exception as e:
            # 自愈容错：自身循环异常不终止本守门进程
            logger.error('看门狗判定循环异常（已忽略，继续监控）: %s', e)
        time.sleep(check_interval)


if __name__ == '__main__':
    main()