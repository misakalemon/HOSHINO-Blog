"""
HOSHINO Launcher — Conda 环境管理 & Python 应用启动器

功能：
  - 自动检测 Conda 环境
  - 一键启动/停止博客服务、爬虫等 Python 应用
  - 实时日志输出窗口
  - 进程管理（PID 追踪、全部停止）

打包为 EXE：
  pip install pyinstaller
  pyinstaller --onefile --windowed --name "HoshinoLauncher" launcher.py
"""

import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from tkinter import ttk, messagebox
import tkinter as tk

# ── 应用配置 ──────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

APPS = [
    {
        'name': '博客服务',
        'script': 'app.py',
        'desc': 'Flask 博客主服务 (http://0.0.0.0:5000)',
        'icon': '🟢',
    },
    {
        'name': 'B站 增量检查',
        'script': '-c "from blog.bili_routes import _check_new_videos; from blog import db; ..."',
        'desc': '手动触发一次 B站 新视频检查',
        'cmd': lambda env: f'conda run -n {env} python -c "import sys; sys.path.insert(0, {repr(BASE_DIR)}); from blog.bili_routes import _check_new_videos; from blog.models import BiliUp; from app import create_app; app = create_app(); ups = BiliUp.query.all(); [print(f\'Checking {u.name}\') or _check_new_videos(u.mid, app) for u in ups]"',
    },
    {
        'name': 'B站 全量刷新',
        'script': '-c "手动触发全量 B站 数据刷新"',
        'desc': '对所有 UP 主执行完整爬取',
        'cmd': lambda env: f'conda run -n {env} python -c "import sys; sys.path.insert(0, {repr(BASE_DIR)}); from blog.bili_routes import _run_scrape; from blog.models import BiliUp; from app import create_app; app = create_app(); ups = BiliUp.query.all(); [print(f\'Scraping {u.name}\') or _run_scrape(u.mid, u.space_url, app) for u in ups]"',
    },
    {
        'name': '价格爬虫',
        'script': '-c "from blog.crawler import crawl_all_active_sources"',
        'desc': '手动触发价格数据爬取',
        'cmd': lambda env: f'conda run -n {env} python -c "import sys; sys.path.insert(0, {repr(BASE_DIR)}); from blog.crawler import crawl_all_active_sources; from app import create_app; create_app(); crawl_all_active_sources()"',
    },
]


class LauncherApp:
    """主窗口"""

    def __init__(self, root):
        self.root = root
        self.root.title('✦ Hoshino Launcher  v1.0')
        self.root.geometry('780x620')
        self.root.minsize(600, 480)

        # 进程管理
        self.processes: dict[str, subprocess.Popen] = {}
        self.status_vars: dict[str, tk.StringVar] = {}

        # 检测 Conda 环境
        self.envs = self._detect_envs()
        self._build_ui()

    # ── UI 构建 ──────────────────────────────────────

    def _build_ui(self):
        # 顶部：环境选择
        header = ttk.Frame(self.root, padding=12)
        header.pack(fill='x')

        ttk.Label(header, text='Conda 环境:', font=('Segoe UI', 10)).pack(side='left')
        self.env_var = tk.StringVar(value=self.envs[0] if self.envs else '')
        env_menu = ttk.Combobox(header, textvariable=self.env_var, values=self.envs,
                                state='readonly', width=20, font=('Segoe UI', 10))
        env_menu.pack(side='left', padx=(8, 0))

        # 应用卡片区域
        cards = ttk.Frame(self.root, padding=12)
        cards.pack(fill='both', expand=True)

        for app_cfg in APPS:
            self._add_app_card(cards, app_cfg)

        # 日志输出
        log_frame = ttk.Frame(self.root, padding=(12, 0, 12, 8))
        log_frame.pack(fill='both', expand=True)

        ttk.Label(log_frame, text='日志输出:', font=('Segoe UI', 9)).pack(anchor='w')
        self.log_text = tk.Text(log_frame, height=10, font=('Consolas', 9),
                                bg='#1e1e2e', fg='#cdd6f4', insertbackground='white',
                                relief='flat', borderwidth=4)
        self.log_text.pack(fill='both', expand=True, pady=(4, 0))

        # 底部状态栏
        status_frame = ttk.Frame(self.root, padding=8)
        status_frame.pack(fill='x')
        self.status_label = ttk.Label(status_frame, text='就绪', font=('Segoe UI', 9))
        self.status_label.pack(side='left')
        ttk.Button(status_frame, text='全部停止', command=self._stop_all).pack(side='right')

    def _add_app_card(self, parent, cfg):
        card = ttk.LabelFrame(parent, text=f'  {cfg["icon"]}  {cfg["name"]}  ', padding=8)
        card.pack(fill='x', pady=(0, 6))

        row = ttk.Frame(card)
        row.pack(fill='x')

        ttk.Label(row, text=cfg['desc'], font=('Segoe UI', 9)).pack(side='left', fill='x', expand=True)

        status_var = tk.StringVar(value='⏸ 未启动')
        self.status_vars[cfg['name']] = status_var
        status_label = ttk.Label(row, textvariable=status_var, font=('Segoe UI', 9), width=12)
        status_label.pack(side='right', padx=(4, 0))

        start_btn = ttk.Button(row, text='启动', width=6,
                               command=lambda c=cfg: self._start_app(c))
        start_btn.pack(side='right', padx=(4, 0))

        stop_btn = ttk.Button(row, text='停止', width=6,
                              command=lambda c=cfg: self._stop_app(c))
        stop_btn.pack(side='right')

    # ── 核心功能 ──────────────────────────────────────

    def _detect_envs(self) -> list[str]:
        """检测 Conda 环境"""
        try:
            r = subprocess.run(['conda', 'env', 'list', '--json'],
                               capture_output=True, text=True, timeout=10)
            import json
            data = json.loads(r.stdout)
            envs = [os.path.basename(p) for p in data.get('envs', [])]
            return [e for e in envs if e != 'base'] or ['base']
        except Exception:
            return ['base']

    def _start_app(self, cfg):
        """启动应用"""
        env = self.env_var.get()
        if not env:
            messagebox.showwarning('提示', '请先选择 Conda 环境')
            return

        if cfg['name'] in self.processes and self.processes[cfg['name']].poll() is None:
            self._log(f'[{cfg["name"]}] 已在运行中，请勿重复启动')
            return

        # 构建命令
        if 'cmd' in cfg:
            cmd = cfg['cmd'](env)
        else:
            script = cfg['script']
            cmd = f'conda run -n {env} python {os.path.join(BASE_DIR, script)}'

        self._log(f'[{cfg["name"]}] 启动中...')
        self._log(f'  → {cmd[:120]}...' if len(cmd) > 120 else f'  → {cmd}')
        self.status_vars[cfg['name']].set('🟡 启动中')

        def run():
            try:
                proc = subprocess.Popen(
                    cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding='utf-8', errors='replace',
                    cwd=BASE_DIR
                )
                self.processes[cfg['name']] = proc
                self.status_vars[cfg['name']].set('🟢 运行中')
                self._log(f'[{cfg["name"]}] 已启动 (PID: {proc.pid})')

                for line in proc.stdout:
                    if line:
                        self._log(f'[{cfg["name"]}] {line.rstrip()}')

                proc.wait()
                if proc.returncode == 0:
                    self._log(f'[{cfg["name"]}] 正常退出')
                else:
                    self._log(f'[{cfg["name"]}] 异常退出 (code={proc.returncode})')
                self.status_vars[cfg['name']].set('⏸ 已停止')
                self.processes.pop(cfg['name'], None)
            except Exception as e:
                self._log(f'[{cfg["name"]}] 启动失败: {e}')
                self.status_vars[cfg['name']].set('🔴 失败')

        threading.Thread(target=run, daemon=True).start()

    def _stop_app(self, cfg):
        """停止应用"""
        proc = self.processes.get(cfg['name'])
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            self._log(f'[{cfg["name"]}] 已停止')
            self.status_vars[cfg['name']].set('⏸ 未启动')
            self.processes.pop(cfg['name'], None)
        else:
            self._log(f'[{cfg["name"]}] 未在运行')

    def _stop_all(self):
        """停止所有应用"""
        for name, proc in list(self.processes.items()):
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                self.status_vars[name].set('⏸ 未启动')
                self._log(f'[{name}] 已停止')
        self.processes.clear()
        self._log('已全部停止')

    def _log(self, msg: str):
        """输出日志到窗口"""
        ts = datetime.now().strftime('%H:%M:%S')
        self.log_text.insert('end', f'[{ts}] {msg}\n')
        self.log_text.see('end')
        self.root.update_idletasks()


def main():
    root = tk.Tk()
    LauncherApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()