"""HOSHINO Blog — 权限与访问控制

从 blog/core/admin.py 抽出的权限层。原先权限装饰器被困在 2700+ 行的视图
模块里，被 blog/bilibili/admin_routes.py、blog/core/api.py 等多个包反向
导入（跨层依赖 + 导入巨型模块的副作用）。

本模块只依赖 flask / flask_login / models，不导入任何蓝图或视图模块，
因此可被任意层安全引用。

提供：
    admin_required      — 仅管理员
    editor_required     — 管理员 + 编辑
    author_required     — 管理员 + 编辑 + 作者
    registration_enabled — 注册开关（DB 站点设置优先，回退环境变量配置）
"""

from functools import wraps

from flask import abort, current_app
from flask_login import current_user, login_required

from .models import SiteSetting

__all__ = [
    'admin_required',
    'author_required',
    'check_active',
    'editor_required',
    'registration_enabled',
]


def check_active():
    """检查当前用户是否被禁用，禁用则 403。"""
    if not current_user.is_active:
        abort(403)


def registration_enabled():
    """注册是否开放：DB 站点设置优先，回退 ENABLE_REGISTRATION 环境变量配置。

    注意：回退分支必须读取 Flask 配置，**绝不能调用自身**——否则在
    site_settings 表缺少 enable_registration 行时（SiteSetting.get 返回
    None）会无限递归 RecursionError，导致 /admin/login 与 /admin/register
    直接 500（该函数在登录页每次 GET 的渲染路径上被调用）。
    """
    db_val = SiteSetting.get('enable_registration', None)
    if db_val is not None:
        return str(db_val).lower() in ('true', '1')
    try:
        return bool(current_app.config.get('ENABLE_REGISTRATION', False))
    except RuntimeError:
        # 无应用上下文（脚本/离线调用）时按"关闭注册"处理
        return False


def admin_required(f):
    """装饰器：仅允许管理员访问（同时检查用户未被禁用）。"""

    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        check_active()
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)

    return decorated_function


def editor_required(f):
    """装饰器：允许管理员和编辑访问（同时检查用户未被禁用）。"""

    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        check_active()
        if not current_user.is_editor:
            abort(403)
        return f(*args, **kwargs)

    return decorated_function


def author_required(f):
    """装饰器：允许管理员、编辑和作者访问（同时检查用户未被禁用）。"""

    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        check_active()
        if not current_user.is_author:
            abort(403)
        return f(*args, **kwargs)

    return decorated_function
