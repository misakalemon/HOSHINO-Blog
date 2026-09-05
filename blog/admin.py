"""
HOSHINO Blog — 管理后台路由

所有 /admin/* 路由（除 login 外），需要登录才能访问，
其中管理操作（文章/分类/评论/用户 CRUD）还额外需要 is_admin 权限。

功能模块：
  - 认证       ─ 登录 / 登出
  - 仪表盘     ─ 后台首页统计概览
  - 文章管理   ─ 文章 CRUD（支持多分类）
  - 分类管理   ─ 分类 CRUD（多对多）
  - 评论管理   ─ 评论列表 / 审核 / 删除
  - 用户管理   ─ 用户 CRUD（仅管理员）
  - 个人资料   ─ 当前用户编辑头像 / 邮箱 / 密码
  - 图片上传   ─ 富文本编辑器图片上传 API
  - 特色卡片   ─ 首页特色卡片 CRUD

函数列表：
  _invalidate_sidebar_cache()  — 使侧边栏和 RSS 缓存失效
  admin_required(f)            — 权限控制装饰器（@login_required + is_admin 检查）
  login()                      — 管理员登录
  logout()                     — 退出登录
  dashboard()                  — 仪表盘统计概览
  post_list()                  — 文章列表（分页）
  new_post()                   — 新建文章
  edit_post(id)                — 编辑文章
  delete_post(id)              — 删除文章（含关联评论）
  category_list()              — 分类列表
  new_category()               — 新建分类
  edit_category(id)            — 编辑分类
  delete_category(id)          — 删除分类（含解除文章关联）
  comment_list()               — 评论列表
  approve_comment(id)          — 审核通过评论
  delete_comment(id)           — 删除评论
  user_list()                  — 用户列表
  new_user()                   — 新建用户
  edit_user(id)                — 编辑用户
  delete_user(id)              — 删除用户（含级联操作）
  profile()                    — 个人资料编辑（含头像上传）
  upload_image()               — 图片上传 API（供编辑器调用）
  featured_card_list()         — 特色卡片列表
  new_featured_card()          — 新建特色卡片
  edit_featured_card(id)       — 编辑特色卡片
  delete_featured_card(id)     — 删除特色卡片
"""

import datetime
import logging
import os
import threading
import time
import uuid
from functools import wraps

from flask import (
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user

import bleach

from . import admin_bp
from .routes import ALLOWED_TAGS, ALLOWED_ATTRS
from .utils import LRUDict, now_cst, get_client_ip, validate_url_protocol, is_safe_image_url, escape_like


# iframe 允许嵌入的视频平台域名白名单（防止嵌入钓鱼/恶意页面）
_ALLOWED_IFRAME_HOSTS = (
    'player.bilibili.com', 'www.bilibili.com',
    'www.youtube.com', 'www.youtube-nocookie.com',
    'player.youku.com', 'v.qq.com',
    'open.163.com', 'music.163.com',
)


def _allow_attr(tag: str, name: str, value: str) -> bool:
    """bleach 属性白名单回调：按标签+属性名+值三重校验。

    安全规则：
      - 仅允许已知安全属性名
      - URL 类属性（href/src/poster/action）：拒绝 javascript:/data:/vbscript:/file: 协议、
        拒绝协议相对 URL（//evil.com）、拒绝含 '..' 穿越段的值
      - iframe[src] 额外限制为视频平台域名白名单
    """
    if value is None:
        return True
    name = (name or '').lower()
    url_attrs = ('href', 'src', 'poster', 'action', 'cite', 'formaction', 'longdesc')
    if name in url_attrs:
        v = (value or '').strip()
        if not v:
            return True
        low = v.lower()
        if low.startswith(('javascript:', 'data:', 'vbscript:', 'file:')):
            return False
        if low.startswith('//'):  # 协议相对 URL 会跳到外部站点
            return False
        if low.startswith(('http://', 'https://')):
            if tag == 'iframe' and name == 'src':
                from urllib.parse import urlparse
                host = (urlparse(v).hostname or '').lower()
                return any(host == h or host.endswith('.' + h) for h in _ALLOWED_IFRAME_HOSTS)
            return True
        # 站内相对路径：拒绝路径穿越段
        if '..' in v.split('/'):
            return False
        return True

    # 非 URL 属性：按 (标签, 属性名) 白名单
    allowed = {
        '*': {'id', 'class', 'style', 'title', 'lang', 'dir', 'width', 'height', 'align'},
        'a': {'title', 'rel', 'target'},
        'img': {'alt', 'title', 'style', 'loading'},
        'video': {'controls', 'autoplay', 'loop', 'muted', 'poster'},
        'audio': {'controls', 'autoplay', 'loop'},
        'source': {'type'},
        'iframe': {'width', 'height', 'allowfullscreen', 'frameborder', 'allow', 'title'},
        'td': {'colspan', 'rowspan'},
        'th': {'colspan', 'rowspan'},
        'col': {'span'},
        'ol': {'start', 'type'},
        'li': {'value'},
        'svg': {'viewbox', 'fill', 'stroke', 'stroke-width', 'stroke-linecap',
                'stroke-linejoin', 'fill-opacity', 'stroke-opacity', 'opacity',
                'transform', 'preserveaspectratio'},
        'path': {'d', 'fill', 'stroke', 'stroke-width', 'stroke-linecap',
                 'stroke-linejoin', 'fill-opacity', 'stroke-opacity', 'opacity',
                 'transform'},
        'circle': {'cx', 'cy', 'r', 'fill', 'stroke', 'stroke-width', 'opacity'},
        'rect': {'x', 'y', 'width', 'height', 'rx', 'ry', 'fill', 'stroke',
                 'stroke-width', 'opacity'},
        'line': {'x1', 'y1', 'x2', 'y2', 'stroke', 'stroke-width'},
        'polyline': {'points', 'fill', 'stroke', 'stroke-width'},
        'polygon': {'points', 'fill', 'stroke', 'stroke-width'},
        'text': {'x', 'y', 'dx', 'dy', 'fill', 'font-size', 'font-family',
                 'text-anchor', 'transform', 'opacity'},
        'g': {'fill', 'stroke', 'stroke-width', 'opacity', 'transform'},
        'defs': set(),
        'use': {'href', 'xlink:href', 'x', 'y', 'width', 'height'},
        'clippath': {'clippathunits'},
        'mask': {'maskunits', 'x', 'y', 'width', 'height'},
        'lineargradient': {'gradientunits', 'x1', 'y1', 'x2', 'y2', 'spreadmethod'},
        'radialgradient': {'gradientunits', 'cx', 'cy', 'r', 'spreadmethod'},
        'stop': {'offset', 'stop-color', 'stop-opacity'},
    }
    per_tag = allowed.get(tag, set())
    return name in per_tag or name in allowed['*']


# bleach HTML 白名单：允许保留的 HTML 标签。
# 安全说明：script/form/input/button/select/option/textarea/meta/link/noscript
# 等可执行/表单/外部加载标签一律不允许（防止存储型 XSS 与钓鱼表单）。
# iframe 仅允许白名单视频平台；style 允许（仅作用于文档自身样式）。
_HTML_CLEAN_TAGS = [
    'div', 'span', 'section', 'header', 'footer', 'nav', 'main', 'article',
    'aside', 'figure', 'figcaption', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'p', 'br', 'hr', 'ul', 'ol', 'li', 'dl', 'dt', 'dd', 'blockquote',
    'pre', 'code', 'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td',
    'caption', 'colgroup', 'col', 'img', 'a', 'video', 'audio', 'source',
    'iframe', 'style', 'u', 's', 'em', 'strong', 'i', 'b', 'small', 'sub',
    'sup', 'mark',
    'svg', 'path', 'circle', 'rect', 'line', 'polyline', 'polygon',
    'text', 'g', 'defs', 'use', 'clipPath', 'mask', 'linearGradient',
    'radialGradient', 'stop',
]


def _sanitize_html(html: str) -> str:
    """净化用户提交的 HTML 内容，移除不安全的标签、属性和协议。

    使用 bleach 库对 HTML 进行白名单过滤：
      - _HTML_CLEAN_TAGS: 允许保留的标签列表（不含 script/form 等危险标签）
      - _allow_attr 回调: 属性名 + URL 协议 + iframe 域名三重校验
      - strip=True: 移除不在白名单中的标签及其内容

    Args:
        html: 原始 HTML 字符串

    Returns:
        净化后的安全 HTML 字符串
    """
    if not html:
        return html
    return bleach.clean(html, tags=_HTML_CLEAN_TAGS, attributes=_allow_attr, strip=True)


from .forms import (CategoryForm,
             
    FeaturedCardForm,
    HeroImageForm,
    LoginForm,
    PostForm,
    ProfileForm,
    RegisterForm,
    UserForm,
)
from .models import ApiToken, BackupRecord, BiliSubscription, BiliUp, Category, Comment, FeaturedCard, HeroImage, Post, SiteSetting, User, db

logger = logging.getLogger(__name__)


def _redirect_list(endpoint):
    """重定向到列表页并透传当前查询参数（保留页码/搜索词，避免操作后丢失上下文）。

    依据目标列表自动携带对应参数：
      - admin.post_list / category_list / user_list: page, q
      - admin.comment_list: pending_page, approved_page, q
    """
    args = {}
    q = request.args.get('q', '')
    if endpoint == 'admin.comment_list':
        for key in ('pending_page', 'approved_page'):
            val = request.args.get(key)
            if val:
                args[key] = val
        if q:
            args['q'] = q
    else:
        page = request.args.get('page')
        if page:
            args['page'] = page
        if q:
            args['q'] = q
    return redirect(url_for(endpoint, **args))


# ── 缓存失效辅助函数 ─────────────────────────
def _invalidate_sidebar_cache():
    """使侧边栏、RSS 和前台整页缓存失效。

    在文章或分类发生变更时调用，确保前台能及时看到最新内容。
    删除旧文章时 max(updated_at) 可能不变，整页缓存键不会自动失效，
    因此这里同时显式清除 page:* 前缀的前台页面缓存。
    """
    from .cache import cache_delete_pattern

    cache_delete_pattern('sidebar:*')
    cache_delete_pattern('rss:*')
    cache_delete_pattern('page:index:*')
    cache_delete_pattern('page:category:*')
    cache_delete_pattern('page:about:*')


def _invalidate_page_cache(*prefixes):
    """使前台整页缓存失效（如 'page:index' / 'page:about'）。

    前台只读页面缓存键为 page:<路由>:<参数>:<版本签名>，
    使用前缀模式批量删除即可使相关页面失效。
    """
    from .cache import cache_delete_pattern

    patterns = prefixes or ('page:index', 'page:category', 'page:about')
    for prefix in patterns:
        cache_delete_pattern(f'{prefix}:*')


# ═══════════════════════════════════════════════
# 权限控制装饰器
# ═══════════════════════════════════════════════
def _check_active():
    """检查当前用户是否被禁用，禁用则 403。"""
    if not current_user.is_active:
        abort(403)


def _registration_enabled():
    """注册是否开放：DB 站点设置优先，回退 ENABLE_REGISTRATION 环境变量。"""
    db_val = SiteSetting.get('enable_registration', None)
    if db_val is not None:
        return db_val.lower() in ('true', '1')
    return _registration_enabled()


def admin_required(f):
    """装饰器：仅允许管理员访问（同时检查用户未被禁用）。"""

    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        _check_active()
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)

    return decorated_function


def editor_required(f):
    """装饰器：允许管理员和编辑访问（同时检查用户未被禁用）。"""

    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        _check_active()
        if not current_user.is_editor:
            abort(403)
        return f(*args, **kwargs)

    return decorated_function


def author_required(f):
    """装饰器：允许管理员、编辑和作者访问（同时检查用户未被禁用）。"""

    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        _check_active()
        if not current_user.is_author:
            abort(403)
        return f(*args, **kwargs)

    return decorated_function


# ═══════════════════════════════════════════════
# 诊断
# ═══════════════════════════════════════════════


@admin_bp.route('/_bili_debug/<int:mid>')
@admin_required
def bili_debug(mid):
    """诊断端点：查看 B站 API 对指定 mid 的返回数据"""
    from flask import jsonify
    from blog.bilibili.bili_api import get_user_info, get_video_list
    import traceback

    result = {}
    try:
        ui = get_user_info(mid)
        result['user_info'] = {
            'name': ui.get('name'),
            'video_count': ui.get('video_count'),
            'follower_count': ui.get('follower_count'),
        }
    except Exception as e:
        result['user_info'] = {'error': str(e), 'traceback': traceback.format_exc()}
    try:
        first10 = []
        for i, v in enumerate(get_video_list(mid, max_pages=2)):
            first10.append(
                {
                    'bvid': v['bvid'],
                    'aid': v['aid'],
                    'title': v['title'][:40],
                    'pubdate': v['pubdate'],
                }
            )
            if i >= 9:
                break
        result['videos_sample'] = first10
    except Exception as e:
        result['videos_sample'] = {'error': str(e), 'traceback': traceback.format_exc()}
    return jsonify(result)


@admin_bp.route('/_debug')
@admin_required
def debug_info():
    """诊断端点：查看当前请求的 session、cookie、请求头等信息。

    帮助排查 CSRF 403 等远程访问问题。仅管理员可访问。
    """
    from flask import jsonify

    headers = dict(request.headers)
    headers.pop('Cookie', None)
    safe_session = {
        k: v for k, v in session.items()
        if k not in ('csrf_token', '_fresh', '_id', '_user_id', '_permanent')
    }
    return jsonify(
        {
            'session': safe_session,
            'session_permanent': session.permanent,
            'remote_addr': request.remote_addr,
            'host': request.host,
            'origin': request.headers.get('Origin', ''),
            'referrer': request.headers.get('Referer', ''),
            'x_forwarded_for': request.headers.get('X-Forwarded-For', ''),
            'x_forwarded_proto': request.headers.get('X-Forwarded-Proto', ''),
            'has_csrf_token': 'csrf_token' in session,
            'is_authenticated': current_user.is_authenticated,
            'user': current_user.username if current_user.is_authenticated else None,
        }
    )


# ═══════════════════════════════════════════════
# 认证
# ═══════════════════════════════════════════════

# 登录频率限制（简易内存实现：每 IP 每分钟最多 10 次）
# 使用固定大小的 LRU 字典避免内存泄漏



_login_attempts = LRUDict(maxsize=10000)      # IP → [尝试时间戳列表]，记录每个 IP 的登录尝试
_login_attempts_lock = threading.Lock()        # 保护 _login_attempts 的并发访问
LOGIN_RATE_LIMIT = 10                          # 每个时间窗口内允许的最大尝试次数
LOGIN_RATE_WINDOW = 60                         # 时间窗口长度（秒）


@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    """管理员登录页面。

    GET  — 显示登录表单
    POST — 验证用户名和密码，成功则创建 session

    注意：此路由不检查 is_admin，任何已注册用户均可登录。
    但非管理员用户登录后只能访问 /profile 和 /logout，
    其他管理路由会因 @admin_required 返回 403。

    Template: admin/login.html
    """
    from flask import get_flashed_messages

    get_flashed_messages()

    if current_user.is_authenticated:
        if current_user.is_editor:
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('admin.profile'))

    import ipaddress

    # ── 获取客户端真实 IP（支持反向代理，取 access_route 第一跳） ─
    ip = get_client_ip()
    try:
        ip = ipaddress.ip_address(ip).compressed  # 标准化 IPv6 格式
    except ValueError:
        pass
    now = time.time()
    # ── 滑动窗口频率限制：清理超出窗口的旧记录，检查是否超限 ─
    with _login_attempts_lock:
        # 保留当前时间窗口内的尝试记录
        _login_attempts[ip] = [
            t for t in _login_attempts.get(ip, []) if now - t < LOGIN_RATE_WINDOW
        ]
        if len(_login_attempts[ip]) >= LOGIN_RATE_LIMIT:
            flash('登录尝试过于频繁，请稍后再试', 'error')
            return render_template('admin/login.html', form=LoginForm(), register_enabled=_registration_enabled())

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            if not user.is_active:
                flash('账号已被禁用，请联系管理员', 'error')
                return render_template('admin/login.html', form=form, register_enabled=_registration_enabled())
            # ── 登录成功：清除该 IP 的失败记录，更新用户统计信息 ─
            with _login_attempts_lock:
                _login_attempts[ip] = []
            user.last_login_at = now_cst()
            user.last_login_ip = ip
            user.login_count = (user.login_count or 0) + 1
            db.session.commit()
            session.permanent = True  # 会话持久化（关闭浏览器不清除）
            login_user(user)
            # 编辑及以上角色跳转仪表盘，普通用户跳转个人资料页
            if user.is_editor:
                return redirect(url_for('admin.dashboard'))
            return redirect(url_for('admin.profile'))
        # ── 登录失败：记录本次尝试时间戳 ─
        with _login_attempts_lock:
            _login_attempts[ip].append(now)
        flash('用户名或密码错误', 'error')
    return render_template('admin/login.html', form=form, register_enabled=_registration_enabled())


@admin_bp.route('/register', methods=['GET', 'POST'])
def register():
    """用户注册页面。

    GET  — 显示注册表单
    POST — 创建新用户（默认 role='user'，需要密码二次确认）

    注意：
      - 注册功能受 ENABLE_REGISTRATION 配置开关控制，默认关闭
      - 生产环境建议由管理员在后台创建用户
      - 每个 IP 每天最多注册 3 次，防止批量注册
    """
    if current_user.is_authenticated:
        return redirect(url_for('admin.profile'))

    if not _registration_enabled():
        abort(404)  # 注册功能默认关闭，返回 404 避免暴露注册入口

    form = RegisterForm()
    if form.validate_on_submit():
        # ── 注册频率限制：每 IP 每小时最多注册 3 次 ─
        import ipaddress
        import time

        ip = get_client_ip()
        try:
            ip = ipaddress.ip_address(ip).compressed
        except ValueError:
            pass

        REGISTER_KEY = f'reg_{ip}'
        REGISTER_LIMIT = 3          # 每时间窗口允许的注册次数
        REGISTER_WINDOW = 3600      # 时间窗口（秒）

        now = time.time()
        with _login_attempts_lock:
            _login_attempts[REGISTER_KEY] = [
                t for t in _login_attempts.get(REGISTER_KEY, []) if now - t < REGISTER_WINDOW
            ]
            if len(_login_attempts[REGISTER_KEY]) >= REGISTER_LIMIT:
                flash('注册过于频繁，请稍后再试', 'error')
                return render_template('admin/register.html', form=form, register_enabled=True)

            # 记录本次注册尝试
            _login_attempts[REGISTER_KEY].append(now)

        # 双重检查：防止在表单提交窗口期内配置被关闭
        if not _registration_enabled():
            flash('注册功能已关闭', 'error')
            return render_template('admin/register.html', form=form)
        if User.query.filter_by(username=form.username.data).first():
            flash('用户名已存在', 'error')
            return render_template('admin/register.html', form=form)
        if User.query.filter_by(email=form.email.data).first():
            flash('邮箱已被注册', 'error')
            return render_template('admin/register.html', form=form)

        user = User(
            username=form.username.data,
            email=form.email.data,
            display_name=form.display_name.data or form.username.data,
            role='user',
            is_active=True,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()

        flash('注册成功，请登录', 'success')
        return redirect(url_for('admin.login'))

    return render_template('admin/register.html', form=form)


@admin_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    """退出登录。

    清除当前用户的 session，重定向到前台首页。
    仅接受 POST（含 CSRF token），防止 GET 型 CSRF 强制登出。
    """
    logout_user()
    return redirect(url_for('blog.index'))


# ═══════════════════════════════════════════════
# 仪表盘
# ═══════════════════════════════════════════════


@admin_bp.route('/')
@editor_required
def dashboard():
    """管理后台首页：显示统计数据概览。

    统计数据缓存 60 秒（CACHE_TTL_DASHBOARD），
    避免每次刷新页面都查询数据库。

    使用 ThreadPoolExecutor 并行执行 6 个独立统计查询：
      文章总数、已发布数、待审核评论数、用户数、
      最近 5 篇文章、最近 5 条待审核评论（含 joinedload 预加载）。

    Template: admin/dashboard.html
    """
    from .cache import cache_get, cache_set

    ttl = current_app.config.get('CACHE_TTL_DASHBOARD', 60)
    stats = cache_get('dashboard:stats')
    if stats:
        return render_template('admin/dashboard.html', **stats)

    post_count = Post.query.count()
    published_count = Post.query.filter_by(is_published=True).count()
    comment_count = Comment.query.filter_by(is_approved=False).count()
    user_count = User.query.count()
    recent_posts_raw = Post.query.order_by(Post.created_at.desc()).limit(5).all()
    recent_comments_raw = (
        Comment.query.options(db.joinedload(Comment.post))
        .filter_by(is_approved=False)
        .order_by(Comment.created_at.desc())
        .limit(5)
        .all()
    )

    stats = {
        'post_count': post_count,
        'published_count': published_count,
        'comment_count': comment_count,
        'user_count': user_count,
        'recent_posts': [
            {
                'id': p.id,
                'title': p.title,
                'is_published': p.is_published,
                'created_at': p.created_at.isoformat() if p.created_at else None,
            }
            for p in recent_posts_raw
        ],
        'recent_comments': [
            {
                'id': c.id,
                'content': c.content,
                'post': {'id': c.post.id, 'title': c.post.title},
                'created_at': c.created_at.isoformat() if c.created_at else None,
            }
            for c in recent_comments_raw
        ],
    }
    cache_set('dashboard:stats', stats, ttl)
    return render_template('admin/dashboard.html', **stats)


# ═══════════════════════════════════════════════
# 文章管理
# ═══════════════════════════════════════════════


@admin_bp.route('/posts')
@author_required
def post_list():
    """文章列表页（分页 + 搜索，每页 20 条）。

    管理员和编辑可见全部文章，作者仅见自己的文章。
    Template: admin/post-list.html
    """
    from sqlalchemy.orm import joinedload

    page = request.args.get('page', 1, type=int)
    q = request.args.get('q', '').strip()
    query = Post.query.options(
        joinedload(Post.categories),
        joinedload(Post.author),
    )
    if q:
        # 转义 LIKE 通配符，防止用户通过 % 或 _ 触发非预期的模糊匹配
        safe_q = escape_like(q)
        query = query.filter(Post.title.ilike(f'%{safe_q}%', escape='\\'))
    if not current_user.is_editor:
        query = query.filter(Post.author_id == current_user.id)
    posts = query.order_by(Post.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template('admin/post-list.html', posts=posts)


@admin_bp.route('/posts/new', methods=['GET', 'POST'])
@author_required
def new_post():
    """新建文章。支持多分类选择（最多 15 个）。

    表单验证：
      - slug 必须全局唯一
      - categories 最多选择 15 个
      - 封面图片 URL 可选

    Template: admin/post-form.html (editing=False)
    """
    form = PostForm()
    # 动态填充分类多选下拉框的选项
    form.categories.choices = [(c.id, c.name) for c in Category.query.order_by(Category.name).all()]
    if form.validate_on_submit():
        # ── slug 唯一性检查 ─────────────────────
        existing = Post.query.filter_by(slug=form.slug.data).first()
        if existing:
            flash('链接标识已被其他文章使用，请更换一个', 'error')
            return render_template('admin/post-form.html', form=form, editing=False)
        # ── 分类数量限制 ──────────────────────
        if len(form.categories.data) > 15:
            flash('最多选择15个分类', 'error')
            return render_template('admin/post-form.html', form=form, editing=False)
        # ── XSS 过滤：净化富文本编辑器内容 ─────
        form.content.data = bleach.clean(
            form.content.data or '', tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS
        )
        # ── HTML 源码处理策略（按优先级）：
        #   1. 优先取 form 中提交的 textarea 内容（富文本编辑器直接编辑）
        #   2. 回退到上传的 .html/.htm 文件内容
        #   3. 原始 HTML 存储后通过沙箱 iframe 隔离展示，避免样式冲突 ─
        html_content = request.form.get('html_content', '')
        if not html_content:
            html_file = form.html_file.data
            if html_file and html_file.filename and (html_file.filename.endswith('.html') or html_file.filename.endswith('.htm')):
                raw = html_file.read()
                # 尝试 UTF-8 → GBK → 容错 UTF-8 的编码探测
                try:
                    raw = raw.decode('utf-8')
                except UnicodeDecodeError:
                    try:
                        raw = raw.decode('gbk')
                    except UnicodeDecodeError:
                        raw = raw.decode('utf-8', errors='replace')
                html_content = raw

        html_content = _sanitize_html(html_content)

        post = Post(
            title=form.title.data,
            slug=form.slug.data,
            summary=form.summary.data,
            content=form.content.data,
            cover_image=form.cover_image.data or '',
            html_content=html_content,
            html_file_url='',
            author_id=current_user.id,
            is_published=form.is_published.data,
        )
        post.categories = Category.query.filter(Category.id.in_(form.categories.data)).all()
        db.session.add(post)
        db.session.commit()
        _invalidate_sidebar_cache()
        logger.info('创建文章: id=%d title="%s"', post.id, post.title)
        # 后台异步计算单篇词云
        from .wordcloud import submit_task
        submit_task('post', post_id=post.id)
        flash('文章已发布', 'success')
        return _redirect_list('admin.post_list')
    return render_template('admin/post-form.html', form=form, editing=False)


@admin_bp.route('/posts/<int:id>/edit', methods=['GET', 'POST'])
@author_required
def edit_post(id):
    """编辑文章。

    与 new_post 共用 PostForm，差别在于：
      - slug 唯一性检查要排除自身（Post.id != id）
      - 编辑时回填已有的分类选中状态

    Args:
        id: 文章 ID

    Template: admin/post-form.html (editing=True)

    权限：作者只能编辑自己的文章，编辑/管理员可编辑任何文章。
    """
    post = Post.query.get_or_404(id)
    if not current_user.is_editor and post.author_id != current_user.id:
        abort(403)
    # obj=post 让表单自动填充现有字段值
    form = PostForm(obj=post)
    form.categories.choices = [(c.id, c.name) for c in Category.query.order_by(Category.name).all()]
    if form.validate_on_submit():
        # ── slug 唯一性检查（排除自身） ─────
        existing = Post.query.filter(Post.slug == form.slug.data, Post.id != id).first()
        if existing:
            flash('链接标识已被其他文章使用，请更换一个', 'error')
            return render_template('admin/post-form.html', form=form, editing=True, post=post)
        if len(form.categories.data) > 15:
            flash('最多选择15个分类', 'error')
            return render_template('admin/post-form.html', form=form, editing=True, post=post)
        # ── XSS 过滤：净化富文本编辑器内容 ─────
        form.content.data = bleach.clean(
            form.content.data or '', tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS
        )
        # ── HTML 源码处理策略（编辑时）：
        #   1. 优先取 textarea 提交的 HTML 内容（覆盖旧内容）
        #   2. 如果标记了 remove_html，清空 HTML 字段
        #   3. 回退到上传的 .html/.htm 文件内容
        #   4. 未提供新内容时保留 post 已有 html_content ─
        html_content = request.form.get('html_content', '')
        if html_content:
            post.html_content = _sanitize_html(html_content)
        elif request.form.get('remove_html'):
            post.html_content = ''
        else:
            html_file = form.html_file.data
            if html_file and html_file.filename and (html_file.filename.endswith('.html') or html_file.filename.endswith('.htm')):
                raw = html_file.read()
                try:
                    raw = raw.decode('utf-8')
                except UnicodeDecodeError:
                    try:
                        raw = raw.decode('gbk')
                    except UnicodeDecodeError:
                        raw = raw.decode('utf-8', errors='replace')
                post.html_content = _sanitize_html(raw)
        if post.html_file_url:
            old_path = os.path.join(current_app.static_folder, post.html_file_url)
            if os.path.isfile(old_path):
                os.remove(old_path)
            post.html_file_url = ''

        post.title = form.title.data
        post.slug = form.slug.data
        post.summary = form.summary.data
        post.content = form.content.data
        post.cover_image = form.cover_image.data or ''
        post.is_published = form.is_published.data
        post.updated_at = now_cst()
        post.categories = Category.query.filter(Category.id.in_(form.categories.data)).all()
        db.session.commit()
        _invalidate_sidebar_cache()
        from .wordcloud import submit_task
        submit_task('post', post_id=post.id)
        flash('文章已更新', 'success')
        return _redirect_list('admin.post_list')
    # ── 编辑时回填已选的分类 ─────────────────
    form.categories.data = [c.id for c in post.categories]
    return render_template('admin/post-form.html', form=form, editing=True, post=post)


@admin_bp.route('/posts/<int:id>/delete', methods=['POST'])
@author_required
def delete_post(id):
    """删除文章（同时删除关联评论）。

    先删除所有关联的评论，再删除文章本身，
    避免数据库外键约束冲突。

    Args:
        id: 文章 ID

    POST 请求（通过表单按钮触发），删除后重定向到文章列表。

    权限：作者只能删除自己的文章，编辑/管理员可删除任何文章。
    """
    post = Post.query.get_or_404(id)
    if not current_user.is_editor and post.author_id != current_user.id:
        abort(403)
    # 删除关联的 HTML 文件（如有）
    if post.html_file_url:
        html_path = os.path.join(current_app.static_folder, post.html_file_url)
        if os.path.isfile(html_path):
            os.remove(html_path)
    # 先删除关联评论再删文章，避免外键约束冲突
    Comment.query.filter_by(post_id=post.id).delete()
    db.session.delete(post)
    db.session.commit()
    _invalidate_sidebar_cache()
    from .cache import cache_delete

    cache_delete('dashboard:stats')
    # 异步投递全站词云重算（删除一篇文章后需刷新全站 + 按月切片）
    from .wordcloud import submit_task
    submit_task('site')
    flash('文章已删除', 'success')
    return _redirect_list('admin.post_list')


# ═══════════════════════════════════════════════
# API 令牌管理
# ═══════════════════════════════════════════════


@admin_bp.route('/tokens')
@author_required
def token_list():
    """API 令牌列表 + 创建表单。

    普通用户只能看到自己的令牌；管理员可看到全部令牌。
    创建后明文令牌通过一次性 session 变量传递到模板，仅显示一次。
    """
    if current_user.is_admin:
        tokens = ApiToken.query.order_by(ApiToken.created_at.desc()).all()
    else:
        tokens = (
            ApiToken.query.filter_by(user_id=current_user.id)
            .order_by(ApiToken.created_at.desc())
            .all()
        )
    new_token = session.pop('_new_api_token', None)
    return render_template('admin/token-list.html', tokens=tokens, new_token=new_token, now_cst=now_cst)


@admin_bp.route('/tokens/new', methods=['POST'])
@author_required
def new_token():
    """创建 API 令牌。

    表单字段：
      name      — 令牌名称（必填）
      expire_days — 过期天数（选填，留空=永不过期）
    """
    name = (request.form.get('name') or '').strip()
    if not name or len(name) > 128:
        flash('请填写有效的令牌名称（1-128 字符）', 'error')
        return redirect(url_for('admin.token_list'))
    expire_days = request.form.get('expire_days', '').strip()
    expires_at = None
    if expire_days:
        try:
            days = int(expire_days)
            if days > 0:
                expires_at = now_cst() + datetime.timedelta(days=days)
        except ValueError:
            flash('过期天数必须是正整数', 'error')
            return redirect(url_for('admin.token_list'))
    raw, token = ApiToken.generate(user_id=current_user.id, name=name, expires_at=expires_at)
    session['_new_api_token'] = raw
    logger.info('用户 %d 创建 API 令牌: id=%d name="%s"', current_user.id, token.id, name)
    flash('令牌已创建，请立即复制保存（仅显示一次）', 'success')
    return redirect(url_for('admin.token_list'))


@admin_bp.route('/tokens/<int:id>/revoke', methods=['POST'])
@author_required
def revoke_token(id):
    """禁用令牌（保留记录便于审计）。"""
    token = db.session.get(ApiToken, id)
    if token is None:
        abort(404)
    if token.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    token.is_active = False
    db.session.commit()
    logger.info('禁用 API 令牌: id=%d name="%s"', token.id, token.name)
    flash('令牌已禁用', 'success')
    return redirect(url_for('admin.token_list'))


@admin_bp.route('/tokens/<int:id>/delete', methods=['POST'])
@author_required
def delete_token(id):
    """彻底删除令牌。"""
    token = db.session.get(ApiToken, id)
    if token is None:
        abort(404)
    if token.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    db.session.delete(token)
    db.session.commit()
    logger.info('删除 API 令牌: id=%d name="%s"', token.id, token.name)
    flash('令牌已删除', 'success')
    return redirect(url_for('admin.token_list'))


# ═══════════════════════════════════════════════
# 数据备份
# ═══════════════════════════════════════════════


@admin_bp.route('/backup')
@admin_required
def backup_list():
    """备份记录列表 + 触发按钮。"""
    records = BackupRecord.query.order_by(BackupRecord.created_at.desc()).limit(100).all()
    return render_template('admin/backup.html', records=records)


@admin_bp.route('/backup/run', methods=['POST'])
@admin_required
def backup_run():
    """触发一次备份。表单字段 kind: full/db/uploads。"""
    from . import backup as backup_mod

    kind = request.form.get('kind', 'full')
    record = backup_mod.run_backup(kind=kind)
    if record.status == 'ok':
        flash(f'备份完成（{record.kind}）：{record.filename}', 'success')
    else:
        flash(f'备份失败：{record.error_msg}', 'error')
    return redirect(url_for('admin.backup_list'))


@admin_bp.route('/backup/download/<int:id>')
@admin_required
def backup_download(id):
    """下载备份文件。"""
    record = db.session.get(BackupRecord, id)
    if record is None or record.status != 'ok':
        abort(404)
    from . import backup as backup_mod

    path = os.path.join(backup_mod._backup_dir(), record.filename)
    if not os.path.isfile(path):
        flash('备份文件已丢失', 'error')
        return redirect(url_for('admin.backup_list'))
    return send_file(path, as_attachment=True, download_name=record.filename)


@admin_bp.route('/backup/delete/<int:id>', methods=['POST'])
@admin_required
def backup_delete(id):
    """删除备份记录与文件。"""
    record = db.session.get(BackupRecord, id)
    if record is None:
        abort(404)
    from . import backup as backup_mod

    try:
        backup_mod.delete_backup(record)
        flash('备份已删除', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'删除失败：{e}', 'error')
    return redirect(url_for('admin.backup_list'))


@admin_bp.route('/backup/restore/<int:id>', methods=['POST'])
@admin_required
def backup_restore(id):
    """从备份恢复数据库（高危，仅管理员）。

    恢复会清空现有数据再灌入备份内容，恢复后需重启服务刷新缓存。
    """
    record = db.session.get(BackupRecord, id)
    if record is None:
        abort(404)
    if record.kind not in ('db', 'full'):
        flash('仅 DB 或 full 备份可恢复', 'error')
        return redirect(url_for('admin.backup_list'))
    from . import backup as backup_mod

    try:
        info = backup_mod.restore_db_from_record(record)
        _invalidate_sidebar_cache()
        flash(
            f'恢复完成：{info["tables"]} 张表 / {info["rows"]} 行。请尽快重启服务以刷新缓存。',
            'success',
        )
        logger.warning('管理员从备份恢复数据库: backup_id=%d', id)
    except Exception as e:
        db.session.rollback()
        flash(f'恢复失败：{e}', 'error')
        logger.error('恢复失败: backup_id=%d err=%s', id, e, exc_info=True)
    return redirect(url_for('admin.backup_list'))


# ═══════════════════════════════════════════════
# 站点设置
# ═══════════════════════════════════════════════


@admin_bp.route('/settings', methods=['GET', 'POST'])
@admin_required
def site_settings():
    """站点设置（运行时可改，存数据库）。"""
    from . import settings as settings_mod

    if request.method == 'POST':
        for group in settings_mod.GROUPS:
            for field in group['fields']:
                key = field['key']
                if field['type'] == 'bool':
                    val = 'true' if request.form.get(key) else 'false'
                else:
                    val = request.form.get(key, '')
                settings_mod.set_setting(key, val)
        flash('设置已保存', 'success')
        return redirect(url_for('admin.site_settings'))
    return render_template(
        'admin/settings.html',
        groups=settings_mod.GROUPS,
        settings=settings_mod.get_all_settings(),
    )


# ═══════════════════════════════════════════════
# 媒体库
# ═══════════════════════════════════════════════


@admin_bp.route('/media')
@editor_required
def media_list():
    """媒体库：浏览 uploads 文件，支持搜索与分页。"""
    upload_dir = current_app.config['UPLOAD_FOLDER']
    q = (request.args.get('q') or '').strip().lower()
    page = max(1, request.args.get('page', 1, type=int))
    per_page = 24

    files = []
    if os.path.isdir(upload_dir):
        for fn in os.listdir(upload_dir):
            full = os.path.join(upload_dir, fn)
            if not os.path.isfile(full):
                continue
            if q and q not in fn.lower():
                continue
            st = os.stat(full)
            files.append(
                {
                    'name': fn,
                    'size': st.st_size,
                    'mtime': datetime.datetime.fromtimestamp(st.st_mtime),
                    'url': f'/static/uploads/{fn}',
                    'thumb': f'/thumb?path=uploads/{fn}&w=300&fmt=webp',
                }
            )
    files.sort(key=lambda x: x['mtime'], reverse=True)
    total = len(files)
    items = files[(page - 1) * per_page : page * per_page]
    return render_template(
        'admin/media.html', files=items, total=total, page=page, per_page=per_page, q=q
    )


@admin_bp.route('/media/delete', methods=['POST'])
@editor_required
def media_delete():
    """删除媒体文件（删除前检查文章引用并提示）。"""
    name = (request.form.get('name') or '').strip()
    if not name or '/' in name or '\\' in name or '..' in name:
        flash('无效的文件名', 'error')
        return redirect(url_for('admin.media_list'))
    upload_dir = current_app.config['UPLOAD_FOLDER']
    path = os.path.join(upload_dir, name)
    if not os.path.isfile(path):
        flash('文件不存在', 'error')
        return redirect(url_for('admin.media_list'))
    safe_name = name.replace('%', '\\%')
    refs = (
        Post.query.filter(
            db.or_(
                Post.cover_image.like(f'%{safe_name}%', escape='\\'),
                Post.content.like(f'%{safe_name}%', escape='\\'),
                Post.html_content.like(f'%{safe_name}%', escape='\\'),
            )
        ).all()
    )
    try:
        os.remove(path)
    except OSError as e:
        flash(f'删除失败：{e}', 'error')
        return redirect(url_for('admin.media_list'))
    if refs:
        titles = '、'.join(p.title for p in refs[:5])
        flash(f'已删除 {name}（被 {len(refs)} 篇文章引用：{titles}…，建议更新相关文章）', 'success')
    else:
        flash(f'已删除 {name}', 'success')
    return redirect(url_for('admin.media_list'))


# ═══════════════════════════════════════════════
# 分类管理
# ═══════════════════════════════════════════════


@admin_bp.route('/categories')
@editor_required
def category_list():
    """分类列表页。

    Template: admin/category-list.html
    """
    categories = Category.query.order_by(Category.name).all()
    # 一次性 GROUP BY 聚合各分类已发布文章数，避免模板逐行 COUNT（N+1）
    from sqlalchemy import func as _sa_func
    from .models import post_categories

    post_counts: dict[int, int] = {}
    try:
        rows = (
            db.session.query(post_categories.c.category_id, _sa_func.count(post_categories.c.post_id))
            .join(Post, Post.id == post_categories.c.post_id)
            .filter(Post.is_published.is_(True))
            .group_by(post_categories.c.category_id)
            .all()
        )
        post_counts = {cid: cnt for cid, cnt in rows}
    except Exception:
        pass
    return render_template(
        'admin/category-list.html', categories=categories, post_counts=post_counts
    )


@admin_bp.route('/categories/new', methods=['GET', 'POST'])
@editor_required
def new_category():
    """新建分类。

    name 和 slug 都有唯一约束，不能重复。

    Template: admin/category-form.html (editing=False)
    """
    form = CategoryForm()
    if form.validate_on_submit():
        if Category.query.filter_by(slug=form.slug.data).first():
            flash('该链接标识已存在', 'error')
            return render_template('admin/category-form.html', form=form, editing=False)
        if Category.query.filter_by(name=form.name.data).first():
            flash('该分类名称已存在', 'error')
            return render_template('admin/category-form.html', form=form, editing=False)
        cat = Category(name=form.name.data, slug=form.slug.data, description=form.description.data)
        db.session.add(cat)
        db.session.commit()
        _invalidate_sidebar_cache()
        flash('分类已创建', 'success')
        return _redirect_list('admin.category_list')
    return render_template('admin/category-form.html', form=form, editing=False)


@admin_bp.route('/categories/<int:id>/edit', methods=['GET', 'POST'])
@editor_required
def edit_category(id):
    """编辑分类。

    Args:
        id: 分类 ID

    Template: admin/category-form.html (editing=True)
    """
    cat = Category.query.get_or_404(id)
    form = CategoryForm(obj=cat)
    if form.validate_on_submit():
        # 唯一性预检（排除自身）：slug/name 重复直接提交会 IntegrityError → 500
        dup = Category.query.filter(
            Category.id != cat.id,
            db.or_(
                Category.slug == form.slug.data,
                Category.name == form.name.data,
            ),
        ).first()
        if dup:
            flash('分类名称或链接标识已存在', 'error')
            return render_template('admin/category-form.html', form=form, editing=True, cat=cat)
        cat.name = form.name.data
        cat.slug = form.slug.data
        cat.description = form.description.data
        db.session.commit()
        _invalidate_sidebar_cache()
        flash('分类已更新', 'success')
        return _redirect_list('admin.category_list')
    return render_template('admin/category-form.html', form=form, editing=True, cat=cat)


@admin_bp.route('/categories/<int:id>/delete', methods=['POST'])
@editor_required
def delete_category(id):
    """删除分类。同时从所有文章中移除该分类（多对多关联）。

    删除前遍历所有包含此分类的文章，手动解除关联关系，
    确保多对多关联表也被清理。

    Args:
        id: 分类 ID
    """
    cat = Category.query.get_or_404(id)
    # 遍历所有包含此分类的文章，解除关联
    from sqlalchemy.orm import joinedload

    # 遍历所有关联了该分类的文章，使用列表推导式移除目标分类
    # 注意：joinedload 确保 post.categories 已预加载，避免 N+1 查询
    for post in (
        Post.query.options(joinedload(Post.categories)).filter(Post.categories.any(id=id)).all()
    ):
        post.categories = [c for c in post.categories if c.id != id]
    db.session.delete(cat)
    db.session.commit()
    _invalidate_sidebar_cache()
    flash('分类已删除', 'success')
    return _redirect_list('admin.category_list')


# ═══════════════════════════════════════════════
# 评论管理
# ═══════════════════════════════════════════════


@admin_bp.route('/comments')
@editor_required
def comment_list():
    """评论列表页（已分页，独立翻页）。

    显示所有评论，按审核状态分两个表格：
      - 待审核（pending）：is_approved=False
      - 已通过（approved）：is_approved=True

    使用 joinedload(Comment.post) 预加载关联文章，避免 N+1。
    默认每页 20 条，支持 ?pending_page= 和 ?approved_page= 独立翻页。

    Template: admin/comment-list.html
    """
    from sqlalchemy.orm import joinedload

    # 待审核和已通过评论使用独立的翻页参数，可在同一页面分别翻页
    pending_page = request.args.get('pending_page', 1, type=int)
    approved_page = request.args.get('approved_page', 1, type=int)
    pending = (
        Comment.query.options(joinedload(Comment.post))
        .filter_by(is_approved=False)
        .order_by(Comment.created_at.desc())
        .paginate(page=pending_page, per_page=20, error_out=False)
    )
    approved = (
        Comment.query.options(joinedload(Comment.post))
        .filter_by(is_approved=True)
        .order_by(Comment.created_at.desc())
        .paginate(page=approved_page, per_page=20, error_out=False)
    )
    return render_template('admin/comment-list.html', pending=pending, approved=approved)


@admin_bp.route('/comments/<int:id>/approve', methods=['POST'])
@editor_required
def approve_comment(id):
    """审核通过评论。

    将评论的 is_approved 设为 True，使其在前台可见。

    Args:
        id: 评论 ID
    """
    comment = Comment.query.get_or_404(id)
    comment.is_approved = True
    db.session.commit()
    flash('评论已审核通过', 'success')
    return _redirect_list('admin.comment_list')


@admin_bp.route('/comments/<int:id>/delete', methods=['POST'])
@editor_required
def delete_comment(id):
    """删除评论。

    Args:
        id: 评论 ID
    """
    comment = Comment.query.get_or_404(id)
    db.session.delete(comment)
    db.session.commit()
    flash('评论已删除', 'success')
    return _redirect_list('admin.comment_list')


# ═══════════════════════════════════════════════
# 用户管理
# ═══════════════════════════════════════════════


@admin_bp.route('/users')
@admin_required
def user_list():
    """用户列表页（分页，每页 20 条）。

    Template: admin/user-list.html
    """
    page = request.args.get('page', 1, type=int)
    users = User.query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    return render_template('admin/user-list.html', users=users)


@admin_bp.route('/users/new', methods=['GET', 'POST'])
@admin_required
def new_user():
    """新建用户。

    可为新用户设置用户名、邮箱、密码、显示名、简介、是否为管理员。

    Template: admin/user-form.html (user=None)
    """
    form = UserForm()
    if form.validate_on_submit():
        # 唯一性预检：用户名/邮箱重复直接提交会触发 DB IntegrityError → 500
        if User.query.filter_by(username=form.username.data).first():
            flash('用户名已存在', 'error')
            return render_template('admin/user-form.html', form=form, user=None)
        if User.query.filter_by(email=form.email.data).first():
            flash('邮箱已被注册', 'error')
            return render_template('admin/user-form.html', form=form, user=None)
        # 新建用户必须设置初始密码（UserForm.password 为 Optional，编辑时可留空）
        if not form.password.data:
            flash('必须为新用户设置初始密码', 'error')
            return render_template('admin/user-form.html', form=form, user=None)
        user = User(
            username=form.username.data,
            email=form.email.data,
            display_name=form.display_name.data,
            bio=form.bio.data,
            website=form.website.data,
            role=form.role.data,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('用户已创建', 'success')
        return _redirect_list('admin.user_list')
    return render_template('admin/user-form.html', form=form, user=None)


@admin_bp.route('/users/<int:id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_user(id):
    """编辑用户角色。

    编辑模式下仅可修改角色，其他字段只读且不会保存到数据库。
    如需修改用户名/邮箱等信息，请删除后重建用户。

    Args:
        id: 用户 ID

    Template: admin/user-form.html (editing)
    """
    user = User.query.get_or_404(id)
    form = UserForm(obj=user)
    if form.validate_on_submit():
        if user.id == current_user.id and user.role != form.role.data:
            flash('⚠️ 警告：您正在修改自己的角色！降级后可能立即失去管理权限。如果角色不再为 admin/editor，当前会话的管理功能将不可用。', 'warning')
        # 编辑模式：仅更新角色，其他字段只读不写
        user.role = form.role.data
        db.session.commit()
        flash('用户角色已更新', 'success')
        return _redirect_list('admin.user_list')
    return render_template('admin/user-form.html', form=form, user=user, editing=True)


@admin_bp.route('/users/<int:id>/delete', methods=['POST'])
@admin_required
def delete_user(id):
    """删除用户（不能删除自己，同时删除该用户的文章和评论）。

    安全限制：
      - 不能删除当前登录的管理员自己
      - 级联删除该用户的所有文章（以及文章的评论）

    Args:
        id: 用户 ID
    """
    user = User.query.get_or_404(id)
    if user.id == current_user.id:
        flash('不能删除自己', 'error')
        return _redirect_list('admin.user_list')
    # 删除该用户的所有文章（及关联评论）
    post_ids = [p.id for p in user.posts.all()]
    if post_ids:
        Comment.query.filter(Comment.post_id.in_(post_ids)).delete(synchronize_session=False)
        Post.query.filter(Post.id.in_(post_ids)).delete(synchronize_session=False)
    db.session.delete(user)
    db.session.commit()
    db.session.expire_all()
    flash('用户已删除', 'success')
    return _redirect_list('admin.user_list')


@admin_bp.route('/users/<int:id>/toggle-active', methods=['POST'])
@admin_required
def toggle_user_active(id):
    """切换用户的激活/禁用状态。

    不能禁用自己。
    """
    user = User.query.get_or_404(id)
    if user.id == current_user.id:
        flash('不能禁用自己', 'error')
        return _redirect_list('admin.user_list')
    user.is_active = not user.is_active
    db.session.commit()
    status = '已启用' if user.is_active else '已禁用'
    flash(f'用户 {user.username} {status}', 'success')
    return _redirect_list('admin.user_list')


# ═══════════════════════════════════════════════
# 个人资料
# ═══════════════════════════════════════════════


@admin_bp.route('/profile', methods=['GET', 'POST'])
@author_required
def profile():
    """个人资料编辑页，支持头像上传。

    功能：
      - 修改显示名、简介、个人网站、社交链接（GitCode/GitHub）
      - 上传新头像（自动缩放至 200px 宽，PNG/JPEG）
      - 修改邮箱（检查唯一性）
      - 修改密码（需验证当前密码，且两次新密码一致）
      - 编辑关于页面内容（仅管理员，富文本编辑器）

    注意：此路由使用 @login_required 而非 @admin_required，
    任何已登录用户均可编辑自己的资料。

    Template: admin/profile.html
    """
    _check_active()
    form = ProfileForm(obj=current_user)
    if form.validate_on_submit():
        current_user.display_name = form.display_name.data
        current_user.bio = form.bio.data
        current_user.website = form.website.data
        current_user.gitcode_url = form.gitcode_url.data
        current_user.github_url = form.github_url.data
        current_user.gitee_url = form.gitee_url.data
        current_user.bilibili_url = form.bilibili_url.data

        # ── 头像上传 ──────────────────────────
        # 优先级：avatar_url（外部URL）> avatar 文件上传
        avatar_url = request.form.get('avatar_url', '').strip()
        if avatar_url:
            # 协议校验：接受站内路径（/static/、uploads/）或 http/https，
            # 防止 javascript:/data: 等恶意协议注入。
            # 注意：前端裁剪上传回填的是 data.url.replace('/static/','')
            # 即 'uploads/xxx.webp' 相对路径，必须放行。
            from .utils import is_safe_image_url
            if not is_safe_image_url(avatar_url):
                flash('头像 URL 协议不安全（仅支持站内路径或 http/https）', 'error')
                return render_template('admin/profile.html', form=form)
            current_user.avatar = avatar_url
        elif 'avatar' in request.files:
            file = request.files['avatar']
            if file and file.filename:
                # 从文件名提取扩展名，用于后续格式判断和保存
                ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'png'
                if ext in ('png', 'jpg', 'jpeg', 'gif', 'webp'):
                    import io as _io

                    from PIL import Image

                    # Magic Bytes 校验：防止改名绕过扩展名上传非图片文件
                    _magic = file.read(12)
                    file.seek(0)
                    _valid_magic = (
                        _magic.startswith(b'\x89PNG')
                        or _magic.startswith(b'\xff\xd8')
                        or _magic.startswith(b'GIF87a')
                        or _magic.startswith(b'GIF89a')
                        or (len(_magic) >= 12 and _magic.startswith(b'RIFF') and _magic[8:12] == b'WEBP')
                    )
                    if not _valid_magic:
                        flash('头像文件不是有效的图片', 'error')
                        return render_template('admin/profile.html', form=form)
                    try:
                        # 解压炸弹防护：限制最大像素数
                        if not hasattr(Image, 'MAX_IMAGE_PIXELS'):
                            Image.MAX_IMAGE_PIXELS = 50_000_000
                        Image.MAX_IMAGE_PIXELS = 50_000_000
                        img = Image.open(file)
                        img.verify()
                        file.seek(0)
                        img = Image.open(file)
                        # 缩放到 200px 宽（保持宽高比），仅缩小不放大
                        ratio = min(200 / img.width, 1.0)
                        if ratio < 1:
                            h = int(img.height * ratio)
                            img = img.resize((200, h), Image.LANCZOS)
                        buf = _io.BytesIO()
                        # GIF 保持 GIF（保留动画）；JPEG 用 JPEG；其他统一转 WebP
                        if ext == 'gif':
                            img.save(buf, 'GIF')
                            save_ext = 'gif'
                        elif ext in ('jpg', 'jpeg'):
                            img.save(buf, 'JPEG', quality=85, optimize=True)
                            save_ext = 'jpg'
                        else:
                            img.save(buf, 'WEBP', quality=85, method=6)
                            save_ext = 'webp'
                        buf.seek(0)
                        # 生成 UUID 文件名，避免用户间头像覆盖
                        filename = 'avatar_' + str(uuid.uuid4()) + '.' + save_ext
                        from flask import current_app

                        upload_dir = os.path.join(current_app.root_path, 'static', 'uploads')
                        os.makedirs(upload_dir, exist_ok=True)
                        # 删除旧头像文件（本地上传的头像），避免磁盘文件累积
                        # 安全：realpath 规范化后校验必须位于 static/uploads/ 内，
                        # 防止历史遗留/构造的 avatar 值含 '..' 穿越删除任意文件
                        if current_user.avatar and current_user.avatar.startswith('uploads/avatar_'):
                            old_path = os.path.realpath(
                                os.path.join(current_app.root_path, 'static', current_user.avatar)
                            )
                            uploads_real = os.path.realpath(upload_dir)
                            if old_path.startswith(uploads_real + os.sep) and os.path.isfile(old_path):
                                try:
                                    os.remove(old_path)
                                except OSError:
                                    pass
                        with open(os.path.join(upload_dir, filename), 'wb') as f:
                            f.write(buf.getvalue())
                        current_user.avatar = 'uploads/' + filename
                        logger.info('更新头像: user=%s new=%s', current_user.username, filename)
                    except Exception:
                        # 解码/处理失败（如 magic bytes 通过但 PIL 无法解码的损坏图片）
                        logger.warning('头像处理失败: user=%s file=%s',
                                       current_user.username, file.filename, exc_info=True)
                        flash('头像处理失败，请更换图片文件', 'error')
                        return render_template('admin/profile.html', form=form)
                else:
                    flash('不支持的头像格式（支持 png/jpg/jpeg/gif/webp）', 'error')
                    return render_template('admin/profile.html', form=form)

        # ── 邮箱：检查唯一性 ──────────────────
        if form.email.data and form.email.data != current_user.email:
            existing = User.query.filter_by(email=form.email.data).first()
            if existing:
                flash('邮箱已被占用', 'error')
                return render_template('admin/profile.html', form=form)
            current_user.email = form.email.data

        # ── 修改密码 ──────────────────────────
        if form.password.data:
            if not form.current_password.data:
                flash('请输入当前密码以修改密码', 'error')
                return render_template('admin/profile.html', form=form)
            if not current_user.check_password(form.current_password.data):
                flash('当前密码错误', 'error')
                return render_template('admin/profile.html', form=form)
            current_user.set_password(form.password.data)

        # ── 关于页面内容 ──────────────────────
        current_user.about_content = bleach.clean(
            form.about_content.data or '', tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS
        )

        db.session.commit()
        from .cache import cache_delete
        cache_delete('admin:social_links')
        _invalidate_page_cache('page:about')
        flash('个人资料已更新', 'success')
        return redirect(url_for('admin.profile'))
    return render_template('admin/profile.html', form=form)


# ═══════════════════════════════════════════════
# 图片上传 API
# ═══════════════════════════════════════════════


@admin_bp.route('/upload-image', methods=['POST'])
@author_required
def upload_image():
    """图片上传接口（供富文本编辑器调用）。

    接收 multipart/form-data，字段名 'file'。
    返回 JSON: {"url": "/static/uploads/xxx.jpg"}

    支持的格式：png, jpg, jpeg, gif, webp
    上传后存入 static/uploads/，文件名使用 UUID 避免冲突。

    注意：
      - 此路由使用 @login_required（不要求 admin），
        方便所有登录用户编辑文章时上传图片。
      - 前端编辑器中插入图片通过此 API 返回的 URL 实现。

    Returns:
        JSON: 成功 → {"url": "/static/uploads/xxx.jpg"}
              失败 → {"error": "错误信息"}, 400
    """
    if 'file' not in request.files:
        return jsonify({'error': '没有文件'}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({'error': '空文件'}), 400
    # 校验文件扩展名白名单
    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'png'
    if ext not in ('png', 'jpg', 'jpeg', 'gif', 'webp'):
        return jsonify({'error': '不支持的格式'}), 400
    # 校验 Magic Bytes（文件头签名），防止通过改名绕过后缀检查
    import io as _io

    magic = file.read(12)
    file.seek(0)
    # 各格式魔数签名：PNG(‰PNG), JPEG(ÿØ), GIF87a/GIF89a, WEBP(RIFF....WEBP)
    is_valid_magic = (
        magic.startswith(b'\x89PNG')
        or magic.startswith(b'\xff\xd8')
        or magic.startswith(b'GIF87a')
        or magic.startswith(b'GIF89a')
        or (len(magic) >= 12 and magic.startswith(b'RIFF') and magic[8:12] == b'WEBP')
    )
    if not is_valid_magic:
        return jsonify({'error': '文件内容不是有效的图片'}), 400
    # 使用 PIL 重新编码图片（统一质量控制，同时阻断二次构造的恶意图片）
    try:
        from PIL import Image

        # 解压炸弹防护：与 /thumb 路由一致，拒绝超大像素图片
        # （防止恶意构造的 PNG/JPEG 声明海量像素耗尽内存）
        if not hasattr(Image, 'MAX_IMAGE_PIXELS'):
            Image.MAX_IMAGE_PIXELS = 50_000_000
        Image.MAX_IMAGE_PIXELS = 50_000_000

        img = Image.open(file)
        img.verify()
        file.seek(0)
        img = Image.open(file)
    except Exception:
        return jsonify({'error': '无法解析图片文件'}), 400
    # 限制上传图片的最大边长（富文本内嵌图片，超大原图会导致页面加载缓慢）
    # 超出则等比缩小（仅缩小不放大）
    try:
        max_side = int(os.environ.get('UPLOAD_MAX_SIDE', '4096'))
    except (ValueError, TypeError):
        max_side = 4096
    if max_side > 0 and max(img.width, img.height) > max_side:
        ratio = max_side / max(img.width, img.height)
        img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
    try:
        buf = _io.BytesIO()
        if ext == 'gif':
            img.save(buf, 'GIF')  # GIF 保持原格式（保留动画）
        else:
            img.save(buf, 'WEBP', quality=85, method=6)  # 非 GIF 统一转 WebP，减小体积
        buf.seek(0)
    except Exception:
        return jsonify({'error': '图片处理失败'}), 400
    # 生成 UUID 文件名，避免路径冲突和文件名猜测
    filename = str(uuid.uuid4()) + ('.webp' if ext != 'gif' else '.gif')
    from flask import current_app

    upload_dir = os.path.join(current_app.root_path, 'static', 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    with open(os.path.join(upload_dir, filename), 'wb') as f:
        f.write(buf.getvalue())
    logger.info(
        '图片上传: %s → uploads/%s (%dx%d, %dKB)',
        file.filename,
        filename,
        img.width,
        img.height,
        buf.tell() // 1024,
    )
    url = url_for('static', filename='uploads/' + filename)
    return jsonify({'url': url})


# ═══════════════════════════════════════════════
# 特色卡片管理
# ═══════════════════════════════════════════════


@admin_bp.route('/featured-cards')
@admin_required
def featured_card_list():
    """特色卡片列表页。

    特色卡片展示在首页的精选区域，每张卡片关联一个分类。
    显示卡片标题、图标、排序权重、启禁用状态等。

    Template: admin/featured-card-list.html
    """
    cards = FeaturedCard.query.order_by(FeaturedCard.sort_order).all()
    categories = Category.query.all()
    cat_lookup = {c.slug: c.name for c in categories}
    return render_template('admin/featured-card-list.html', cards=cards, cat_lookup=cat_lookup)


@admin_bp.route('/featured-cards/new', methods=['GET', 'POST'])
@admin_required
def new_featured_card():
    """新建特色卡片。

    需要先有分类才能创建卡片（卡片必须关联一个分类）。

    Template: admin/featured-card-form.html (editing=False)
    """
    categories = Category.query.order_by(Category.name).all()
    if not categories:
        flash('请先创建分类，再添加特色卡片', 'error')
        return _redirect_list('admin.category_list')
    form = FeaturedCardForm()
    form.tag.choices = [(c.slug, c.name) for c in categories]
    def _validate_url_protocol_local(val):
        if not validate_url_protocol(val):
            flash(f'不安全的 URL 协议: {val}', 'error')
            return False
        return True

    def _validate_image_url_local(val):
        if val and not is_safe_image_url(val):
            flash(f'不安全的图片 URL: {val}', 'error')
            return False
        return True

    if form.validate_on_submit():
        if not _validate_url_protocol_local(form.link.data) or not _validate_image_url_local(form.image_url.data):
            return render_template('admin/featured-card-form.html', form=form, editing=False)
        card = FeaturedCard(
            title=form.title.data,
            description=form.description.data or '',
            icon=form.icon.data or '✦',
            tag=form.tag.data,
            link=form.link.data or '',
            image_url=form.image_url.data or '',
            sort_order=form.sort_order.data or 0,
            is_active=form.is_active.data,
        )
        db.session.add(card)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash(f'创建失败: {e}', 'error')
            return render_template('admin/featured-card-form.html', form=form, editing=False)
        from .cache import cache_delete
        cache_delete('home:featured_cards')
        _invalidate_page_cache('page:index')
        flash('特色卡片已创建', 'success')
        return redirect(url_for('admin.featured_card_list'))
    for field, errors in form.errors.items():
        label = field
        f = getattr(form, field, None)
        if f and hasattr(f, 'label') and f.label:
            label = f.label.text
        for err in errors:
            flash(f'{label}: {err}', 'error')
    return render_template('admin/featured-card-form.html', form=form, editing=False)


@admin_bp.route('/featured-cards/<int:id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_featured_card(id):
    """编辑特色卡片。

    Args:
        id: 卡片 ID

    Template: admin/featured-card-form.html (editing=True)
    """
    card = FeaturedCard.query.get_or_404(id)
    form = FeaturedCardForm(obj=card)
    form.tag.choices = [(c.slug, c.name) for c in Category.query.order_by(Category.name).all()]
    def _validate_url_protocol_local(val):
        if not validate_url_protocol(val):
            flash(f'不安全的 URL 协议: {val}', 'error')
            return False
        return True

    def _validate_image_url_local(val):
        if val and not is_safe_image_url(val):
            flash(f'不安全的图片 URL: {val}', 'error')
            return False
        return True

    if form.validate_on_submit():
        if not _validate_url_protocol_local(form.link.data) or not _validate_image_url_local(form.image_url.data):
            return render_template('admin/featured-card-form.html', form=form, editing=True)
        card.title = form.title.data
        card.description = form.description.data or ''
        card.icon = form.icon.data or '✦'
        card.tag = form.tag.data
        card.link = form.link.data or ''
        card.image_url = form.image_url.data or ''
        card.sort_order = form.sort_order.data or 0
        card.is_active = form.is_active.data
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash(f'更新失败: {e}', 'error')
            return render_template('admin/featured-card-form.html', form=form, editing=True)
        from .cache import cache_delete
        cache_delete('home:featured_cards')
        _invalidate_page_cache('page:index')
        flash('特色卡片已更新', 'success')
        return redirect(url_for('admin.featured_card_list'))
    for field, errors in form.errors.items():
        label = field
        f = getattr(form, field, None)
        if f and hasattr(f, 'label') and f.label:
            label = f.label.text
        for err in errors:
            flash(f'{label}: {err}', 'error')
    return render_template('admin/featured-card-form.html', form=form, editing=True, card=card)


@admin_bp.route('/featured-cards/<int:id>/delete', methods=['POST'])
@admin_required
def delete_featured_card(id):
    """删除特色卡片。

    Args:
        id: 卡片 ID
    """
    card = FeaturedCard.query.get_or_404(id)
    db.session.delete(card)
    db.session.commit()
    from .cache import cache_delete
    cache_delete('home:featured_cards')
    _invalidate_page_cache('page:index')
    flash('特色卡片已删除', 'success')
    return redirect(url_for('admin.featured_card_list'))


# ═══════════════════════════════════════════════
# B站 订阅管理
# ═══════════════════════════════════════════════


@admin_bp.route('/bili-subscriptions')
@admin_required
def bili_subscriptions():
    """B站 邮件订阅管理列表（分页 + 搜索）。

    支持按邮箱或 UP 主名称模糊搜索。
    Template: admin/bili_subscriptions.html
    """
    page = request.args.get('page', 1, type=int)
    per_page = 20
    q = request.args.get('q', '').strip()

    query = BiliSubscription.query.join(BiliUp, BiliSubscription.up_id == BiliUp.id)
    if q:
        safe_q = escape_like(q)
        query = query.filter(
            db.or_(
                BiliSubscription.email.ilike(f'%{safe_q}%', escape='\\'),
                BiliUp.name.ilike(f'%{safe_q}%', escape='\\'),
            )
        )
    pagination = query.order_by(BiliSubscription.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template('admin/bili_subscriptions.html', pagination=pagination, q=q)


@admin_bp.route('/bili-subscriptions/<int:id>/delete', methods=['POST'])
@admin_required
def delete_bili_subscription(id):
    """删除单条订阅记录。

    Args:
        id: 订阅记录 ID
    """
    sub = BiliSubscription.query.get_or_404(id)
    db.session.delete(sub)
    db.session.commit()
    flash('订阅记录已删除', 'success')
    return redirect(url_for('admin.bili_subscriptions'))


@admin_bp.route('/bili-subscriptions/batch', methods=['POST'])
@admin_required
def batch_bili_subscriptions():
    """批量管理订阅记录（删除 / 标记已验证 / 取消验证）。

    通过表单字段 action 指定操作类型，ids 为选中的订阅 ID 列表。
    """
    action = request.form.get('action', '')
    ids = request.form.getlist('ids', type=int)
    if not ids:
        flash('请至少选择一条订阅记录', 'warning')
        return redirect(url_for('admin.bili_subscriptions'))

    subs = BiliSubscription.query.filter(BiliSubscription.id.in_(ids)).all()
    count = len(subs)

    if action == 'delete':
        for sub in subs:
            db.session.delete(sub)
        db.session.commit()
        flash(f'已删除 {count} 条订阅记录', 'success')
    elif action == 'verify':
        for sub in subs:
            sub.verified = True
        db.session.commit()
        flash(f'已标记 {count} 条订阅为已验证', 'success')
    elif action == 'unverify':
        for sub in subs:
            sub.verified = False
        db.session.commit()
        flash(f'已取消 {count} 条订阅的验证状态', 'success')
    else:
        flash(f'未知操作: {action}', 'warning')  # 兜底处理：表单提交了无效的 action 值
    return redirect(url_for('admin.bili_subscriptions'))


@admin_bp.route('/bili-subscriptions/cleanup-unverified', methods=['POST'])
@admin_required
def cleanup_unverified_subscriptions():
    """清理超过 24 小时仍未验证的订阅记录。

    删除 created_at 早于当前时间 24 小时前且 verified=False 的订阅，
    避免数据库中积累大量未验证的过期订阅数据。
    """

    cutoff = now_cst() - datetime.timedelta(hours=24)
    deleted = BiliSubscription.query.filter(
        BiliSubscription.verified == False, BiliSubscription.created_at < cutoff
    ).delete()
    db.session.commit()
    flash(f'已清理 {deleted} 条未验证的过期订阅', 'success')
    return redirect(url_for('admin.bili_subscriptions'))


@admin_bp.route('/bili-history-cleanup', methods=['GET', 'POST'])
@admin_required
def bili_history_cleanup():
    """B站视频历史记录清理（配置自动清理 + 手动执行）。

    GET  — 显示清理配置页面（自动清理开关、保留天数、手动清理表单）
    POST — 处理两种操作：
       action=manual:  手动执行清理（指定保留天数）
       action=config:  更新自动清理配置（启用/禁用 + 保留天数）

    自动清理通过定时任务调用 cleanup_old_history() 实现。
    Template: admin/bili_history_cleanup.html
    """
    from blog.bili_routes import cleanup_old_history
    from blog.models import BiliCleanupConfig, BiliVideoHistory

    # 获取或创建配置
    cfg = BiliCleanupConfig.query.first()
    if not cfg:
        cfg = BiliCleanupConfig()
        db.session.add(cfg)
        db.session.commit()

    deleted = None
    days_used = None
    total = None

    if request.method == 'POST':
        action = request.form.get('action', 'manual')

        if action == 'manual':
            days_used = request.form.get('days', 90, type=int)
            if days_used < 1:
                flash('天数必须大于 0', 'error')
            else:
                total = BiliVideoHistory.query.count()
                deleted = cleanup_old_history(days=days_used)  # 执行清理，返回删除条数
                flash(
                    f'已清理 {deleted} 条 {days_used} 天前的记录（剩余 {total - deleted} 条）',
                    'success',
                )

        elif action == 'config':
            cfg.days = request.form.get('days', 90, type=int)
            if cfg.days < 1:
                flash('天数必须大于 0', 'error')
            else:
                cfg.enabled = request.form.get('enabled') == '1'  # 表单值为 '1' 时启用
                db.session.commit()
                flash(
                    f'自动清理已{"启用" if cfg.enabled else "禁用"}，保留最近 {cfg.days} 天数据',
                    'success',
                )

    return render_template(
        'admin/bili_history_cleanup.html',
        cfg=cfg,
        deleted=deleted,
        days=days_used,
        total=total,
    )


# ── Hero 粒子画像管理 ────────────────────────────


@admin_bp.route('/hero-images')
@admin_required
def hero_image_list():
    """Hero 粒子画像列表页。

    展示所有上传的 PNG 画像，包含排序、启用状态、预览缩略图。
    画像按 sort_order 升序排列。

    Template: admin/hero_image_list.html
    """
    images = HeroImage.query.order_by(HeroImage.sort_order).all()
    return render_template('admin/hero_image_list.html', images=images)


@admin_bp.route('/hero-images/new', methods=['GET', 'POST'])
@admin_required
def new_hero_image():
    """新建 Hero 粒子画像。

    图片通过前端裁剪 → upload_image API 处理后传入 URL，
    此路由仅负责入库，不处理文件。

    Template: admin/hero_image_form.html (editing=False)
    """
    form = HeroImageForm()
    if form.validate_on_submit():
        raw_url = (form.image_url.data or '').strip()
        if raw_url:
            # 协议校验：接受站内路径或 http/https，防止恶意协议注入
            from .utils import is_safe_image_url
            if not is_safe_image_url(raw_url):
                flash('图片 URL 协议不安全（仅支持站内路径或 http/https）', 'error')
                return render_template('admin/hero_image_form.html', form=form, editing=False)
        if raw_url and not raw_url.startswith('/static/'):
            image_url = url_for('static', filename=raw_url)
        else:
            image_url = raw_url
        image = HeroImage(
            title=form.title.data or '',
            image_url=image_url,
            sort_order=form.sort_order.data or 0,
            is_active=form.is_active.data,
        )
        db.session.add(image)
        db.session.commit()
        _invalidate_page_cache('page:index')
        flash('Hero 画像已添加', 'success')
        return redirect(url_for('admin.hero_image_list'))
    for field, errors in form.errors.items():
        label = field
        f = getattr(form, field, None)
        if f and hasattr(f, 'label') and f.label:
            label = f.label.text
        for err in errors:
            flash(f'{label}: {err}', 'error')
    return render_template('admin/hero_image_form.html', form=form, editing=False)


@admin_bp.route('/hero-images/<int:id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_hero_image(id):
    """编辑 Hero 粒子画像。

    可修改标题、排序、启用状态、图片。
    图片通过前端裁剪 → upload_image API 处理后传入 URL，
    此处仅读取 image_url 字段更新记录，有值则替换，无值保留原图。

    Args:
        id: HeroImage ID

    Template: admin/hero_image_form.html (editing=True)
    """
    image = HeroImage.query.get_or_404(id)
    form = HeroImageForm(obj=image)
    form.image_url.validators = []
    if form.validate_on_submit():
        image.title = form.title.data or ''
        image.sort_order = form.sort_order.data or 0
        image.is_active = form.is_active.data
        if form.image_url.data:
            raw_url = (form.image_url.data or '').strip()
            from .utils import is_safe_image_url
            if raw_url and not is_safe_image_url(raw_url):
                flash('图片 URL 协议不安全（仅支持站内路径或 http/https）', 'error')
                return render_template('admin/hero_image_form.html', form=form, editing=True)
            if raw_url and not raw_url.startswith('/static/'):
                image.image_url = url_for('static', filename=raw_url)
            else:
                image.image_url = raw_url
        db.session.commit()
        _invalidate_page_cache('page:index')
        flash('Hero 画像已更新', 'success')
        return redirect(url_for('admin.hero_image_list'))
    for field, errors in form.errors.items():
        label = field
        f = getattr(form, field, None)
        if f and hasattr(f, 'label') and f.label:
            label = f.label.text
        for err in errors:
            flash(f'{label}: {err}', 'error')
    return render_template('admin/hero_image_form.html', form=form, editing=True)


@admin_bp.route('/hero-images/<int:id>/delete', methods=['POST'])
@admin_required
def delete_hero_image(id):
    """删除 Hero 粒子画像。

    从数据库中删除记录（不删除物理文件，避免其他记录引用同一文件）。

    Args:
        id: HeroImage ID
    """
    image = HeroImage.query.get_or_404(id)
    db.session.delete(image)
    db.session.commit()
    _invalidate_page_cache('page:index')
    flash('Hero 画像已删除', 'success')
    return redirect(url_for('admin.hero_image_list'))


# ═══════════════════════════════════════════════
# 词云配置
# ═══════════════════════════════════════════════
@admin_bp.route('/wordcloud-config', methods=['GET', 'POST'])
@admin_required
def wordcloud_config():
    """词云配置页面。

    管理员可调整词云渲染参数（形状、字号、词数、配色等）。
    首次访问时自动创建默认配置行。

    Template: admin/wordcloud_config.html
    """
    from .forms import WordCloudConfigForm
    from .models import WordCloudConfig

    config = WordCloudConfig.get_or_create()
    form = WordCloudConfigForm(obj=config)

    if form.validate_on_submit():
        # 处理自定义形状图片上传
        if request.form.get('delete_shape_image') == '1':
            config.shape_image = ''
        elif 'shape_image' in request.files:
            file = request.files['shape_image']
            if file and file.filename:
                ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'png'
                if ext not in ('png', 'webp', 'jpg', 'jpeg'):
                    flash('仅支持 PNG / WebP / JPEG 格式的形状图片', 'danger')
                    return render_template('admin/wordcloud_config.html', form=form, config=config)
                try:
                    from PIL import Image
                    import io as _io
                    magic = file.read(12)
                    file.seek(0)
                    if magic[:8] != b'\x89PNG\r\n\x1a\n' and magic[:4] not in (b'\xff\xd8', b'RIFF'):
                        flash('不是有效的图片文件', 'danger')
                        return render_template('admin/wordcloud_config.html', form=form, config=config)
                    # 解压炸弹防护：与其他上传入口一致，限制最大像素数
                    if not hasattr(Image, 'MAX_IMAGE_PIXELS'):
                        Image.MAX_IMAGE_PIXELS = 50_000_000
                    Image.MAX_IMAGE_PIXELS = 50_000_000
                    img = Image.open(file)
                    img.verify()
                    file.seek(0)
                    img = Image.open(file)
                    w, h_ = img.size
                    if max(w, h_) > 512:
                        scale = 512 / max(w, h_)
                        img = img.resize((int(w * scale), int(h_ * scale)), Image.LANCZOS)
                    buf = _io.BytesIO()
                    img.save(buf, 'WEBP', quality=80)
                    filename = 'shape_' + str(uuid.uuid4()) + '.webp'
                    upload_dir = os.path.join(current_app.root_path, 'static', 'uploads')
                    os.makedirs(upload_dir, exist_ok=True)
                    path = os.path.join(upload_dir, filename)
                    with open(path, 'wb') as f:
                        f.write(buf.getvalue())
# 删除旧形状图片
                    if config.shape_image:
                        old_path = os.path.join(current_app.root_path, 'static', config.shape_image)
                        if os.path.isfile(old_path):
                            try: os.remove(old_path)
                            except OSError: pass
                    config.shape_image = 'uploads/' + filename
                    # 标记图片已上传，populate_obj 后强制切 custom
                    request._shape_uploaded = True
                    flash('形状图片已上传', 'success')
                except Exception as e:
                    flash(f'形状图片处理失败: {e}', 'danger')
                    return render_template('admin/wordcloud_config.html', form=form, config=config)

        form.populate_obj(config)
        # 如果上传了自定义形状图片，强制 shape 为 custom（覆盖表单提交值）
        if getattr(request, '_shape_uploaded', False):
            config.shape = 'custom'
        config.updated_at = now_cst()
        db.session.commit()
        _invalidate_page_cache()
        flash('词云配置已保存', 'success')
        # 自动投递全量词云重算（使屏蔽词等立即生效）
        from .wordcloud import submit_task
        submit_task('all')
        return redirect(url_for('admin.wordcloud_config'))

    return render_template('admin/wordcloud_config.html', form=form, config=config)


@admin_bp.route('/wordcloud/refresh')
@admin_required
def refresh_wordcloud():
    """手动触发博客+ B站词云重新计算（异步后台执行）。"""
    from .wordcloud import submit_task

    submit_task('all')
    _invalidate_page_cache()
    flash('词云数据已投递到后台计算（博客 + B站）', 'success')
    return redirect(url_for('admin.wordcloud_config'))
