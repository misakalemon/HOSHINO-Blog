"""
HOSHINO Launcher — Conda 环境管理 & Python 应用启动器 (Eel)

基于 Eel 构建，使用系统浏览器渲染界面，无需额外安装 WebView2。

日志文件：logs/launcher.log（每日轮转，保留 30 天）
日志级别：DEBUG / INFO / WARNING / ERROR

使用方式：
  pip install eel
  python launcher.py

打包为 EXE：
  pip install eel pyinstaller
  pyinstaller --onefile --windowed --name "HoshinoLauncher" launcher.py
"""

import json
import logging
import logging.handlers
import os
import signal
import subprocess
import sys
import threading
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── 日志系统 ──────────────────────────────────────
LOG_DIR = os.path.join(BASE_DIR, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, 'launcher.log')

LOG_FORMAT = '[%(asctime)s] %(levelname)-7s [%(threadName)s] %(message)s'
LOG_DATE = '%m/%d %H:%M:%S'

_logger = logging.getLogger('launcher')
_logger.setLevel(logging.DEBUG)

# 文件 handler（每日轮转，保留 30 天）
_file_handler = logging.handlers.TimedRotatingFileHandler(
    LOG_FILE, when='midnight', interval=1, backupCount=30,
    encoding='utf-8'
)
_file_handler.setLevel(logging.DEBUG)
_file_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE))
_logger.addHandler(_file_handler)

# 终端 handler（控制台输出）
_console_handler = logging.StreamHandler()
_console_handler.setLevel(logging.INFO)
_console_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE))
_logger.addHandler(_console_handler)

# ── 应用配置 ──────────────────────────────────────
APPS = [
    {'name': '博客服务', 'icon': '🚀', 'desc': 'Flask 博客主服务 (http://0.0.0.0:5000)',
     'cmd': lambda env: f'conda run -n {env} python {os.path.join(BASE_DIR, "app.py")}'},
    {'name': 'B站 增量检查', 'icon': '🔄', 'desc': '检查所有 UP 主的新视频并入库',
     'cmd': lambda env: f'conda run -n {env} python {os.path.join(BASE_DIR, "scripts", "bili_incremental.py")}'},
    {'name': 'B站 全量刷新', 'icon': '📊', 'desc': '对所有 UP 主执行完整爬取',
     'cmd': lambda env: f'conda run -n {env} python {os.path.join(BASE_DIR, "scripts", "bili_daily_scrape.py")}'},
]

# ── 进程管理 ──────────────────────────────────────
_processes: dict[str, subprocess.Popen] = {}
_proc_lock = threading.Lock()
_log_callbacks: list = []
_envs: list[str] = []


def _detect_envs() -> list[str]:
    try:
        # 先检查 conda 是否存在
        import shutil
        if not shutil.which('conda'):
            return ['base']
        r = subprocess.run(['conda', 'env', 'list', '--json'],
                           capture_output=True, text=True, timeout=5)
        data = json.loads(r.stdout)
        envs = [os.path.basename(p) for p in data.get('envs', [])]
        return [e for e in envs if e != 'base'] or ['base']
    except Exception:
        return ['base']


class API:
    """暴露给前端的 JS API"""

    def get_envs(self) -> list[str]:
        global _envs
        if not _envs:
            _envs = _detect_envs()
        return _envs

    def get_apps(self) -> list[dict]:
        return [{'name': a['name'], 'icon': a['icon'], 'desc': a['desc']} for a in APPS]

    def get_status(self) -> dict:
        with _proc_lock:
            snap = dict(_processes)
        states = {}
        for name in [a['name'] for a in APPS]:
            proc = snap.get(name)
            if proc is None:
                states[name] = 'stopped'
            elif proc.poll() is None:
                states[name] = 'running'
            else:
                states[name] = 'exited'
        return states

    def get_next_schedule(self) -> dict:
        """计算下次爬取时间"""
        now = datetime.now()
        # 每天 02:00 全量刷新
        daily = now.replace(hour=2, minute=0, second=0, microsecond=0)
        if now >= daily:
            daily += timedelta(days=1)
        daily_remaining = int((daily - now).total_seconds())
        # 每 30 分钟增量检查
        next_inc = now + timedelta(minutes=30)
        return {
            'daily_next': daily.strftime('%m/%d %H:%M'),
            'daily_remaining': daily_remaining,
            'incremental_next': next_inc.strftime('%m/%d %H:%M'),
            'incremental_remaining': 1800,
        }

    def start_app(self, name: str) -> str:
        cfg = next((a for a in APPS if a['name'] == name), None)
        if not cfg:
            return 'error: 未找到应用'
        with _proc_lock:
            if name in _processes and _processes[name].poll() is None:
                return 'error: 已在运行中'

        env = _envs[0] if _envs else 'base'
        cmd = cfg['cmd'](env)
        _log(f'[{name}] 启动中...')
        _log(f'  -> {cmd[:120]}...' if len(cmd) > 120 else f'  -> {cmd}')

        def run():
            try:
                proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True,
                                        encoding='utf-8', errors='replace',
                                        cwd=BASE_DIR, start_new_session=True)
                with _proc_lock:
                    _processes[name] = proc
                _log(f'[{name}] 已启动 (PID: {proc.pid})')
                _notify_status()
                for line in proc.stdout:
                    if line:
                        _log(f'[{name}] {line.rstrip()}')
                proc.wait()
                with _proc_lock:
                    _processes.pop(name, None)
                _log(f'[{name}] {"正常退出" if proc.returncode == 0 else f"异常退出 (code={proc.returncode})"}')
                _notify_status()
            except Exception as e:
                _log(f'[{name}] 启动失败: {e}')
                _notify_status()

        threading.Thread(target=run, daemon=True).start()
        return 'ok'

    def stop_app(self, name: str) -> str:
        with _proc_lock:
            proc = _processes.get(name)
            if not proc or proc.poll() is not None:
                return 'error: 未在运行'
        # 先杀进程组（shell=True 会创建 shell 子进程）
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
        with _proc_lock:
            _processes.pop(name, None)
        _log(f'[{name}] 已停止')
        _notify_status()
        return 'ok'

    def stop_all(self):
        with _proc_lock:
            items = list(_processes.items())
        for name, proc in items:
            if proc.poll() is None:
                try:
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    try:
                        pgid = os.getpgid(proc.pid)
                        os.killpg(pgid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        proc.kill()
                _log(f'[{name}] 已停止')
        with _proc_lock:
            _processes.clear()
        _notify_status()
        return 'ok'


def _log(msg: str, level: str = 'INFO'):
    """统一日志输出：写入文件 + 控制台 + WebView 界面"""
    ts = datetime.now().strftime('%H:%M:%S')
    line = f'[{ts}] {msg}'
    # 写入日志文件和控制台
    getattr(_logger, level.lower(), _logger.info)('%s', msg)
    # 推送到 WebView
    for cb in _log_callbacks:
        try:
            cb(line)
        except Exception:
            pass


def _notify_status():
    try:
        import eel
        with _proc_lock:
            snap = dict(_processes)
        states = {}
        for name in [a['name'] for a in APPS]:
            proc = snap.get(name)
            if proc is None:
                states[name] = 'stopped'
            elif proc.poll() is None:
                states[name] = 'running'
            else:
                states[name] = 'exited'
        eel.updateStatus(states)
    except Exception:
        pass


def main():
    import eel

    def on_log(line):
        try:
            eel.appendLog(line)
        except Exception:
            pass
    _log_callbacks.append(on_log)

    eel.init(os.path.join(BASE_DIR, 'web'))
    _log('Hoshino Launcher 已启动')
    _log(f'工作目录: {BASE_DIR}')

    try:
        eel.start('index.html', size=(720, 620), port=0, block=True)
    except Exception as e:
        _log(f'启动失败: {e}', 'ERROR')
        _log('请确保已安装 eel: pip install eel', 'ERROR')
        input('按 Enter 键退出...')


if __name__ == '__main__':
    main()