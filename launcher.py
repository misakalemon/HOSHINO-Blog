"""
HOSHINO Launcher — Conda 环境管理 & Python 应用启动器 (WebView)

基于 pywebview 构建，界面使用 HTML/CSS/JS，复用项目暗色粉紫主题。

打包为 EXE：
  pip install pywebview pyinstaller
  pyinstaller --onefile --windowed --name "HoshinoLauncher" launcher.py
"""

import json
import os
import subprocess
import sys
import threading
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── 应用配置 ──────────────────────────────────────
APPS = [
    {'name': '博客服务', 'icon': '🚀', 'desc': 'Flask 博客主服务 (http://0.0.0.0:5000)',
     'cmd': lambda env: f'conda run -n {env} python {os.path.join(BASE_DIR, "app.py")}'},
    {'name': 'B站 增量检查', 'icon': '🔄', 'desc': '检查所有 UP 主的新视频并入库',
     'cmd': lambda env: f'conda run -n {env} python -c "import sys; sys.path.insert(0, {repr(BASE_DIR)}); from blog.bili_routes import _check_new_videos; from blog.models import BiliUp; from app import create_app; app = create_app(); ups = BiliUp.query.all(); [print(f\'Checking {u.name}\') or _check_new_videos(u.mid, app) for u in ups]"'},
    {'name': 'B站 全量刷新', 'icon': '📊', 'desc': '对所有 UP 主执行完整爬取',
     'cmd': lambda env: f'conda run -n {env} python -c "import sys; sys.path.insert(0, {repr(BASE_DIR)}); from blog.bili_routes import _run_scrape; from blog.models import BiliUp; from app import create_app; app = create_app(); ups = BiliUp.query.all(); [print(f\'Scraping {u.name}\') or _run_scrape(u.mid, u.space_url, app) for u in ups]"'},
    {'name': '价格爬虫', 'icon': '💰', 'desc': '手动触发价格数据爬取',
     'cmd': lambda env: f'conda run -n {env} python -c "import sys; sys.path.insert(0, {repr(BASE_DIR)}); from blog.crawler import crawl_all_active_sources; from app import create_app; create_app(); crawl_all_active_sources()"'},
]

# ── 进程管理 ──────────────────────────────────────
_processes: dict[str, subprocess.Popen] = {}
_log_callbacks: list = []
_envs: list[str] = []


def _detect_envs() -> list[str]:
    try:
        r = subprocess.run(['conda', 'env', 'list', '--json'],
                           capture_output=True, text=True, timeout=10)
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
        states = {}
        for name in [a['name'] for a in APPS]:
            proc = _processes.get(name)
            if proc is None:
                states[name] = 'stopped'
            elif proc.poll() is None:
                states[name] = 'running'
            else:
                states[name] = 'exited'
        return states

    def start_app(self, name: str) -> str:
        cfg = next((a for a in APPS if a['name'] == name), None)
        if not cfg:
            return 'error: 未找到应用'
        if name in _processes and _processes[name].poll() is None:
            return 'error: 已在运行中'

        env = _envs[0] if _envs else 'base'
        cmd = cfg['cmd'](env)
        _log(f'[{name}] 启动中...')
        _log(f'  → {cmd[:120]}...' if len(cmd) > 120 else f'  →  {cmd}')

        def run():
            try:
                proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True,
                                        encoding='utf-8', errors='replace',
                                        cwd=BASE_DIR)
                _processes[name] = proc
                _log(f'[{name}] 已启动 (PID: {proc.pid})')
                _notify_status()
                for line in proc.stdout:
                    if line:
                        _log(f'[{name}] {line.rstrip()}')
                proc.wait()
                _log(f'[{name}] {"正常退出" if proc.returncode == 0 else f"异常退出 (code={proc.returncode})"}')
                _processes.pop(name, None)
                _notify_status()
            except Exception as e:
                _log(f'[{name}] 启动失败: {e}')
                _notify_status()

        threading.Thread(target=run, daemon=True).start()
        return 'ok'

    def stop_app(self, name: str) -> str:
        proc = _processes.get(name)
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            _log(f'[{name}] 已停止')
            _processes.pop(name, None)
            _notify_status()
            return 'ok'
        return 'error: 未在运行'

    def stop_all(self):
        for name, proc in list(_processes.items()):
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                _log(f'[{name}] 已停止')
        _processes.clear()
        _notify_status()
        return 'ok'


def _log(msg: str):
    ts = datetime.now().strftime('%H:%M:%S')
    line = f'[{ts}] {msg}'
    for cb in _log_callbacks:
        try:
            cb(line)
        except Exception:
            pass


def _notify_status():
    try:
        import webview
        states = {}
        for name in [a['name'] for a in APPS]:
            proc = _processes.get(name)
            if proc is None:
                states[name] = 'stopped'
            elif proc.poll() is None:
                states[name] = 'running'
            else:
                states[name] = 'exited'
        webview.windows[0].evaluate_js(f'updateStatus({json.dumps(states)})')
    except Exception:
        pass


HTML = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hoshino Launcher</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', sans-serif;
  background: #0b0e17; color: #e8edf5; height: 100vh; overflow: hidden;
  display: flex; flex-direction: column;
}
.header {
  display: flex; align-items: center; gap: 12px; padding: 16px 24px;
  background: rgba(255,255,255,0.02); border-bottom: 1px solid rgba(255,255,255,0.06);
  flex-shrink: 0;
}
.header h1 { font-size: 16px; font-weight: 600; color: #d0c8f0; }
.header select {
  margin-left: auto; padding: 6px 12px; border-radius: 8px;
  background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08);
  color: #e8edf5; font-size: 13px; outline: none; font-family: inherit;
}
.cards { padding: 16px 24px; display: flex; flex-direction: column; gap: 8px; flex-shrink: 0; }
.card {
  display: flex; align-items: center; gap: 12px; padding: 12px 16px;
  background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.04);
  border-radius: 12px; transition: border-color 0.2s;
}
.card:hover { border-color: rgba(255,255,255,0.12); }
.card-icon { font-size: 24px; flex-shrink: 0; }
.card-body { flex: 1; min-width: 0; }
.card-name { font-size: 14px; font-weight: 500; color: #d0c8f0; }
.card-desc { font-size: 12px; color: rgba(255,255,255,0.35); margin-top: 2px; }
.card-status { font-size: 12px; padding: 3px 10px; border-radius: 20px; flex-shrink: 0; }
.card-status.stopped { background: rgba(255,255,255,0.04); color: rgba(255,255,255,0.3); }
.card-status.running { background: rgba(61,214,140,0.12); color: #3dd68c; }
.card-status.exited { background: rgba(242,90,90,0.12); color: #f25a5a; }
.card-btn {
  padding: 6px 14px; border-radius: 8px; border: none; font-size: 12px;
  cursor: pointer; font-family: inherit; transition: all 0.2s; flex-shrink: 0;
}
.card-btn.start { background: rgba(108,66,209,0.2); color: #a78bfa; border: 1px solid rgba(108,66,209,0.2); }
.card-btn.start:hover { background: rgba(108,66,209,0.35); }
.card-btn.stop { background: rgba(242,90,90,0.15); color: #f25a5a; border: 1px solid rgba(242,90,90,0.2); }
.card-btn.stop:hover { background: rgba(242,90,90,0.3); }
.log-area {
  flex: 1; margin: 0 24px 16px; padding: 12px 16px;
  background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.04);
  border-radius: 12px; overflow-y: auto; font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 12px; line-height: 1.6; color: rgba(255,255,255,0.5);
}
.log-area::-webkit-scrollbar { width: 4px; }
.log-area::-webkit-scrollbar-track { background: transparent; }
.log-area::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 4px; }
.footer {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 24px; border-top: 1px solid rgba(255,255,255,0.04);
  font-size: 12px; color: rgba(255,255,255,0.25); flex-shrink: 0;
}
.footer button {
  padding: 4px 14px; border-radius: 6px; border: 1px solid rgba(242,90,90,0.2);
  background: rgba(242,90,90,0.1); color: #f25a5a; font-size: 11px;
  cursor: pointer; font-family: inherit;
}
.footer button:hover { background: rgba(242,90,90,0.2); }
</style>
</head>
<body>
<div class="header">
  <span style="font-size:20px">✦</span>
  <h1>Hoshino Launcher</h1>
  <select id="envSelect"><option>加载中...</option></select>
</div>
<div class="cards" id="cardList"></div>
<div class="log-area" id="logArea"></div>
<div class="footer">
  <span id="statusText">就绪</span>
  <button onclick="stopAll()">全部停止</button>
</div>
<script>
var apps = [];
function init() {
  pywebview.api.get_envs().then(function(envs) {
    var sel = document.getElementById('envSelect');
    sel.innerHTML = envs.map(function(e) { return '<option>' + e + '</option>'; }).join('');
  });
  pywebview.api.get_apps().then(function(data) {
    apps = data;
    renderCards();
  });
  pywebview.api.get_status().then(updateStatus);
}
function renderCards() {
  var html = '';
  apps.forEach(function(a) {
    html += '<div class="card" id="card-' + a.name + '">' +
      '<div class="card-icon">' + a.icon + '</div>' +
      '<div class="card-body">' +
        '<div class="card-name">' + a.name + '</div>' +
        '<div class="card-desc">' + a.desc + '</div>' +
      '</div>' +
      '<div class="card-status stopped" id="status-' + a.name + '">⏸ 未启动</div>' +
      '<button class="card-btn start" id="btn-' + a.name + '" onclick="startApp(\'' + a.name + '\')">启动</button>' +
    '</div>';
  });
  document.getElementById('cardList').innerHTML = html;
}
function updateStatus(states) {
  for (var name in states) {
    var s = states[name];
    var el = document.getElementById('status-' + name);
    var btn = document.getElementById('btn-' + name);
    if (!el || !btn) continue;
    if (s === 'running') {
      el.className = 'card-status running'; el.textContent = '🟢 运行中';
      btn.className = 'card-btn stop'; btn.textContent = '停止';
      btn.setAttribute('onclick', "stopApp('" + name + "')");
    } else if (s === 'exited') {
      el.className = 'card-status exited'; el.textContent = '🔴 已退出';
      btn.className = 'card-btn start'; btn.textContent = '启动';
      btn.setAttribute('onclick', "startApp('" + name + "')");
    } else {
      el.className = 'card-status stopped'; el.textContent = '⏸ 未启动';
      btn.className = 'card-btn start'; btn.textContent = '启动';
      btn.setAttribute('onclick', "startApp('" + name + "')");
    }
  }
}
function appendLog(line) {
  var el = document.getElementById('logArea');
  el.innerHTML += '<div>' + escapeHtml(line) + '</div>';
  el.scrollTop = el.scrollHeight;
}
function escapeHtml(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function startApp(name) { pywebview.api.start_app(name).then(function(r) { if (r !== 'ok') appendLog(r); }); }
function stopApp(name) { pywebview.api.stop_app(name); }
function stopAll() { pywebview.api.stop_all(); }
document.addEventListener('DOMContentLoaded', init);
</script>
</body>
</html>'''


def main():
    import webview

    # 注册日志回调
    def on_log(line):
        try:
            webview.windows[0].evaluate_js(f'appendLog({json.dumps(line)})')
        except Exception:
            pass
    _log_callbacks.append(on_log)

    api = API()
    # 预加载环境列表
    api.get_envs()

    _log('Hoshino Launcher 已启动')
    _log(f'工作目录: {BASE_DIR}')

    window = webview.create_window(
        '✦ Hoshino Launcher',
        html=HTML,
        js_api=api,
        width=720,
        height=620,
        min_size=(560, 480),
        text_select=True,
    )
    webview.start(debug=False, private_mode=False)


if __name__ == '__main__':
    main()