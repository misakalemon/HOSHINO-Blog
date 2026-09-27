"""P0 缺陷回归测试（2026-09 全项目审计发现并修复）

每个测试对应一个已修复的真实缺陷，防止再次回归：

  1. ``_registration_enabled`` 无限自我递归 → ``/admin/login`` 500
  2. 词云子进程 ``-m`` 模块名拼错 → 每日 04:00 预计算静默失败
  3. worker 心跳/PID 路径与看门狗读取端不一致 → 看门狗误判僵死
  4. 公开调试端点无鉴权 → 原文泄露 + 缓存击穿
"""

import ast
import pathlib
import re
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding='utf-8')


# ── 1. 注册开关回退不得自我递归 ──────────────────────────
@pytest.mark.pure
def test_registration_enabled_has_no_self_recursion():
    """静态断言：回退分支不得调用自身。

    修复前 ``return _registration_enabled()`` 在 site_settings 缺
    enable_registration 行时无限递归 → RecursionError → 登录页 500。
    权限层已抽至 blog/core/security.py（函数名 registration_enabled）。
    """
    tree = ast.parse(_read('blog/core/security.py'))
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == 'registration_enabled':
            found = True
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Name)
                    and sub.func.id == 'registration_enabled'
                ):
                    raise AssertionError(
                        'registration_enabled 内仍有自我递归调用：'
                        'site_settings 缺少 enable_registration 行时会 RecursionError'
                    )
    assert found, '未找到 registration_enabled 定义'


@pytest.mark.pure
def test_admin_reexports_security_layer():
    """admin.py 必须再导出权限层，保证既有导入路径与调用点不破。"""
    src = _read('blog/core/admin.py')
    assert 'from .security import' in src
    for alias in ('admin_required', 'author_required', 'editor_required'):
        assert alias in src
    assert 'registration_enabled as _registration_enabled' in src
    assert 'check_active as _check_active' in src


@pytest.mark.pure
def test_security_layer_does_not_import_views():
    """权限层不得反向导入视图模块（这是抽取它的目的）。"""
    src = _read('blog/core/security.py')
    assert 'from .admin import' not in src
    assert 'from .routes import' not in src
    assert 'import admin' not in src


@pytest.mark.pure
def test_registration_enabled_falls_back_to_config(monkeypatch):
    """无 DB 设置行时回退到 Flask 配置（而不是递归崩溃）。"""
    sec = pytest.importorskip('blog.core.security')
    from flask import Flask

    monkeypatch.setattr(
        sec.SiteSetting, 'get', classmethod(lambda cls, key, default=None: None)
    )
    app = Flask(__name__)

    app.config['ENABLE_REGISTRATION'] = True
    with app.app_context():
        assert sec.registration_enabled() is True

    app.config['ENABLE_REGISTRATION'] = False
    with app.app_context():
        assert sec.registration_enabled() is False


@pytest.mark.pure
def test_registration_enabled_prefers_db_value(monkeypatch):
    """DB 有设置行时以 DB 值为准。"""
    sec = pytest.importorskip('blog.core.security')
    from flask import Flask

    monkeypatch.setattr(
        sec.SiteSetting, 'get', classmethod(lambda cls, key, default=None: 'true')
    )
    app = Flask(__name__)
    app.config['ENABLE_REGISTRATION'] = False
    with app.app_context():
        assert sec.registration_enabled() is True


# ── 2. 词云子进程模块名必须真实存在 ──────────────────────
@pytest.mark.pure
def test_subprocess_module_names_exist():
    """worker.py 里所有 ``-m <module>`` 调用的模块必须真实存在。

    修复前是 ``blog.wordcloud.generator_runner``（不存在，实际文件为
    blog/wordcloud/runner.py）→ 每日/每周词云预计算每次启动即
    ModuleNotFoundError，且输出被丢弃 → 长期静默失败。
    """
    src = _read('worker.py')
    mods = set(re.findall(r"""['"]-m['"]\s*,\s*['"]([\w.]+)['"]""", src))
    assert mods, 'worker.py 中未找到 -m 子进程调用（正则或代码结构已变）'
    for mod in mods:
        parts = mod.split('.')
        as_file = _ROOT.joinpath(*parts).with_suffix('.py')
        as_pkg = _ROOT.joinpath(*parts, '__init__.py')
        assert as_file.exists() or as_pkg.exists(), f'-m {mod} 对应的模块文件不存在'


@pytest.mark.pure
def test_wordcloud_runner_module_path_is_correct():
    """词云子进程必须指向 blog.wordcloud.runner。

    用 AST 提取代码中的字符串常量（``#`` 注释里的历史说明不计），
    既保证代码正确，又保留"曾误写 generator_runner"的溯源注释。
    """
    src = _read('worker.py')
    string_literals = [
        node.value
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    assert "'blog.wordcloud.runner'" in src, '词云子进程模块名应为 blog.wordcloud.runner'
    assert not any('generator_runner' in s for s in string_literals), (
        '代码中仍引用不存在的 generator_runner 模块'
    )
    assert _ROOT.joinpath('blog', 'wordcloud', 'runner.py').exists()


# ── 3. 心跳/PID 路径契约（worker 写入端 == 看门狗读取端）──
@pytest.mark.pure
def test_watchdog_activity_path_matches_worker():
    """心跳文件路径必须两端一致。

    修复前 worker 写 <root>/blog/logs/.activity，看门狗读 <root>/logs/.activity，
    文件永不重合 → mtime 恒为 0 → 宽限期后必然告警"业务僵死"，
    且 restart 模式会再拉起一个 Worker（双 Worker 并发爬取）。
    """
    logwatch = pytest.importorskip('blog.infra.logwatch')
    worker = pytest.importorskip('worker')

    assert pathlib.Path(worker._ACTIVITY_FILE) == pathlib.Path(logwatch.ACTIVITY_FILE), (
        'worker 写入的心跳路径与看门狗读取路径不一致'
    )
    assert pathlib.Path(worker._LOG_DIR, 'worker.pid') == pathlib.Path(
        logwatch.WORKER_PID_FILE
    ), 'worker PID 文件路径与看门狗读取路径不一致'


@pytest.mark.pure
def test_watchdog_paths_derive_from_logger_logdir():
    """两端路径都应基于 blog.infra.logger.LOG_DIR（单一真相）。"""
    logwatch = pytest.importorskip('blog.infra.logwatch')
    from blog.infra.logger import LOG_DIR

    assert pathlib.Path(logwatch.LOG_DIR) == pathlib.Path(LOG_DIR)
    assert pathlib.Path(logwatch.ACTIVITY_FILE).parent == pathlib.Path(LOG_DIR)


# ── 4. 调试端点必须鉴权 ──────────────────────────────────
def test_debug_endpoints_require_admin(client):
    """匿名访问调试/清缓存端点应被拒绝（401/403/404），不得回显内容。"""
    for path in ('/post/any-slug/debug-render', '/post/any-slug/clear-cache'):
        resp = client.get(path)
        assert resp.status_code in (401, 403, 404), (
            f'{path} 未鉴权即可访问（status={resp.status_code}）'
        )
        assert b'raw_content_head' not in resp.data, f'{path} 泄露了原文内容'
