"""
HOSHINO Blog — 前台路由

处理所有公开访问的页面路由：
  首页文章列表、文章详情、分类筛选、关于、联系、
  全文搜索、RSS 订阅、缩略图动态生成。

所有路由挂在 blog_bp（Blueprint）上，URL 前缀为空。
"""
import datetime
import logging
import os
import time

import bleach
from flask import Response, abort, current_app, redirect, render_template, request, url_for

from . import blog_bp
from .forms import CommentForm, ContactForm
from .models import Category, Comment, FeaturedCard, Post, db

logger = logging.getLogger(__name__)

# 缩略图缓存版本号（修改此值使旧缓存自动失效并清理）
THUMB_CACHE_VER = 'v2'


# ── 侧边栏数据缓存（Redis，降级友好） ─────────
def _get_sidebar_data():
    """获取侧边栏数据（分类列表 + 最新文章），带 Redis 缓存。

    分类数据量小且极少变化，直接查数据库（无需缓存）。
    最新文章缓存键：hblog:sidebar:recent_posts — TTL: CACHE_TTL_SIDEBAR

    当 Redis 不可用时，回退到数据库查询，不影响页面渲染。

    Returns:
        tuple: (categories, recent_posts)
    """
    from flask import current_app

    from .cache import cache_get, cache_set

    ttl = current_app.config.get('CACHE_TTL_SIDEBAR', 300)

    # ── 分类列表（直接查数据库，缓存收益不大） ──
    categories = Category.query.order_by(Category.name).all()

    # ── 最新文章 ──────────────────────────────
    recent_posts = cache_get('sidebar:recent_posts')
    if recent_posts is None:
        recent_posts = Post.query.filter_by(is_published=True).order_by(
            Post.created_at.desc()).limit(4).all()
        # 缓存为序列化字典，created_at 用 ISO 字符串
        cache_set('sidebar:recent_posts', [
            {
                'id': p.id, 'title': p.title, 'slug': p.slug,
                'cover_image': p.cover_image,
                'created_at': p.created_at.isoformat() if p.created_at else None
            }
            for p in recent_posts
        ], ttl)

    return categories, recent_posts


# ═══════════════════════════════════════════════
# 首页：文章瀑布流
# ═══════════════════════════════════════════════
@blog_bp.route('/')
def index():
    """首页：分页显示已发布的文章列表，支持按分类筛选。

    URL 参数：
      page      — 页码（默认 1）
      category  — 分类 slug（可选，筛选特定分类）
      per_page  — 每页条数（可选，覆盖配置默认值）

    Template: index.html
    """
    page = request.args.get('page', 1, type=int)
    category_slug = request.args.get('category', None)

    # 基础查询：只取已发布的文章，同时使用 joinedload 预加载作者信息
    # 避免 N+1 查询问题
    query = Post.query.options(db.joinedload(Post.author)).filter_by(is_published=True)
    # 按分类筛选（多对多关联）
    if category_slug:
        cat = Category.query.filter_by(slug=category_slug).first_or_404()
        query = query.filter(Post.categories.any(id=cat.id))

    # 分页（按创建时间倒序）
    # per_page 优先级：URL 查询参数 ?per_page= → 无则取 config.POSTS_PER_PAGE（.env 可配）
    per_page = request.args.get('per_page', current_app.config['POSTS_PER_PAGE'], type=int)
    posts = query.order_by(Post.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    categories, recent_posts = _get_sidebar_data()
    featured_cards = FeaturedCard.query.filter_by(is_active=True).order_by(FeaturedCard.sort_order).all()
    cat_lookup = {c.slug: c.name for c in categories}

    return render_template('index.html',
        posts=posts, categories=categories,
        recent_posts=recent_posts, current_category=category_slug,
        current_per_page=per_page,
        per_page_options=current_app.config['PER_PAGE_OPTIONS'],
        featured_cards=featured_cards,
        cat_lookup=cat_lookup,
        blog_subtitle=current_app.config['BLOG_SUBTITLE']
    )


# ═══════════════════════════════════════════════
# 文章详情页
# ═══════════════════════════════════════════════
@blog_bp.route('/post/<slug>', methods=['GET', 'POST'])
def single_post(slug):
    """文章详情：渲染 Markdown 正文 + 评论列表 + 评论表单。

    URL 参数：
      slug — 文章的唯一 URL 标识

    处理逻辑：
      GET  — 展示文章内容和评论表单
      POST — 提交评论（需审核）

    Template: single-post.html
    """
    post = Post.query.filter_by(slug=slug, is_published=True).first_or_404()
    categories, recent_posts = _get_sidebar_data()
    form = CommentForm()

    # ── 处理评论提交 ──────────────────────────
    if form.validate_on_submit():
        comment = Comment(
            post_id=post.id,
            author_name=form.author_name.data,
            author_email=form.author_email.data,
            content=form.content.data,
            is_approved=False  # 新评论默认隐藏，需管理员审核
        )
        db.session.add(comment)
        db.session.commit()
        # 提交后重定向到文章页的 #comments 锚点
        return redirect(url_for('blog.single_post', slug=slug) + '#comments')

    # ── Markdown → HTML ────────────────────────
    # 使用 Python-Markdown 库将正文渲染为 HTML
    # 支持代码块（fenced_code）、代码高亮（codehilite）、表格（tables）
    # 输出经 bleach 过滤，防止 XSS
    ALLOWED_TAGS = [
        'p', 'br', 'strong', 'em', 'a', 'code', 'pre', 'span', 'div',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li',
        'blockquote', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
        'img', 'hr', 'sup', 'sub', 'del', 'ins', 'kbd', 'samp', 'var',
        'abbr', 'dfn',
    ]
    ALLOWED_ATTRS = {
        'a': ['href', 'title', 'rel'],
        'img': ['src', 'alt', 'title'],
        'th': ['align'],
        'td': ['align'],
        'code': ['class'],
        'span': ['class'],
        'div': ['class'],
        'pre': ['class'],
        'abbr': ['title'],
    }
    from markdown import markdown
    post.content = bleach.clean(
        markdown(post.content, extensions=['fenced_code', 'codehilite', 'tables']),
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
    )

    return render_template('single-post.html',
        post=post, categories=categories,
        recent_posts=recent_posts, form=form
    )


# ═══════════════════════════════════════════════
# 分类文章列表
# ═══════════════════════════════════════════════
@blog_bp.route('/category/<slug>')
def category(slug):
    """按分类查看文章列表（多对多关联筛选）。

    URL 参数：
      slug      — 分类的唯一 URL 标识
      page      — 页码（默认 1）
      per_page  — 每页条数（可选）

    Template: category-grid.html
    """
    cat = Category.query.filter_by(slug=slug).first_or_404()
    page = request.args.get('page', 1, type=int)
    # per_page 取自 URL 参数或配置默认值，与首页一致
    per_page = request.args.get('per_page', current_app.config['POSTS_PER_PAGE'], type=int)
    posts = Post.query.filter(
        Post.categories.any(id=cat.id), Post.is_published == True
    ).order_by(Post.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    categories, recent_posts = _get_sidebar_data()
    return render_template('category-grid.html',
        category=cat, posts=posts,
        categories=categories, recent_posts=recent_posts,
        current_per_page=per_page,
        per_page_options=current_app.config['PER_PAGE_OPTIONS']
    )


# ═══════════════════════════════════════════════
# 关于页
# ═══════════════════════════════════════════════
@blog_bp.route('/about')
def about():
    """关于页面。

    展示博主信息、站点介绍等静态内容。
    Template: about.html
    """
    categories, recent_posts = _get_sidebar_data()
    return render_template('about.html', categories=categories, recent_posts=recent_posts)


# ═══════════════════════════════════════════════
# 联系页
# ═══════════════════════════════════════════════
@blog_bp.route('/contact', methods=['GET', 'POST'])
def contact():
    """联系页面：提交留言表单（带 CSRF 保护）。

    使用 ContactForm（Flask-WTF）自动处理 CSRF token，
    在表单中通过 {{ form.hidden_tag() }} 生成隐藏字段。

    Template: contact.html
    """
    form = ContactForm()
    message_sent = False
    if form.validate_on_submit():
        # 表单有效：标记为已发送（生产环境应改为发送邮件）
        message_sent = True
    categories, recent_posts = _get_sidebar_data()
    return render_template('contact.html',
        categories=categories, recent_posts=recent_posts,
        message_sent=message_sent, form=form
    )


# ═══════════════════════════════════════════════
# 工具页
# ═══════════════════════════════════════════════
@blog_bp.route('/tools')
def tools():
    """工具页面：Base64 / 字数 / 颜色 / JSON / 时间戳 / 哈希 / 图片压缩。"""
    return render_template('tools.html')


# ═══════════════════════════════════════════════
# 全文搜索
# ═══════════════════════════════════════════════
@blog_bp.route('/search')
def search():
    """搜索文章：匹配标题、摘要、正文。

    URL 参数：
      q — 搜索关键词（必填，为空时重定向到首页）

    搜索方式：使用 SQL ILIKE 模糊匹配，不区分大小写。
    结果按创建时间倒序排列，支持分页。

    Template: index.html（与首页共用）
    """
    q = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    if not q:
        return redirect(url_for('blog.index'))
    # per_page 取自 URL 参数或配置默认值，搜索结果也支持分页调整
    per_page = request.args.get('per_page', current_app.config['POSTS_PER_PAGE'], type=int)
    categories, recent_posts = _get_sidebar_data()
    # 使用 db.or_() 在标题、摘要、正文三个字段中同时搜索
    results = Post.query.filter(
        Post.is_published == True,
        db.or_(
            Post.title.ilike(f'%{q}%'),
            Post.summary.ilike(f'%{q}%'),
            Post.content.ilike(f'%{q}%')
        )
    ).order_by(Post.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return render_template('index.html',
        posts=results, categories=categories,
        recent_posts=recent_posts, search_query=q,
        current_category=None, current_per_page=per_page,
        per_page_options=current_app.config['PER_PAGE_OPTIONS']
    )


# ═══════════════════════════════════════════════
# RSS 订阅
# ═══════════════════════════════════════════════
@blog_bp.route('/feed.xml')
def rss_feed():
    """RSS/Atom 订阅源。

    返回最新 20 篇文章的 XML 订阅源，
    供 RSS 阅读器（如 Feedly、Inoreader）订阅。

    输出缓存 10 分钟（CACHE_TTL_RSS），
    发布新文章后自动失效。

    Template: rss.xml
    """
    from .cache import cache_get, cache_set
    ttl = current_app.config.get('CACHE_TTL_RSS', 600)
    cached = cache_get('rss:feed')
    if cached:
        response = Response(cached)
        response.headers['Content-Type'] = 'application/xml; charset=utf-8'
        return response
    posts = Post.query.filter_by(is_published=True).order_by(
        Post.created_at.desc()).limit(20).all()
    output = render_template('rss.xml', posts=posts)
    cache_set('rss:feed', output, ttl)
    response = Response(output)
    response.headers['Content-Type'] = 'application/xml; charset=utf-8'
    return response


# ═══════════════════════════════════════════════
# 缩略图生成
# ═══════════════════════════════════════════════
@blog_bp.route('/thumb')
def thumbnail():
    """动态生成图片缩略图并缓存到磁盘。

    URL 参数：
      path — 图片相对路径（相对于 static/，如 'uploads/abc.jpg'）
      w    — 目标宽度（px，默认 400）

    特性：
      - 保持原格式（JPEG/PNG），不转 WebP（兼容性更好）
      - 磁盘缓存 + 版本号控制（升级时自动失效）
      - 路径安全检查（禁止 ../ 遍历）
      - 出错时返回原始图片（不会中断页面渲染）

    Template: none（直接返回图片二进制数据）
    """
    path = request.args.get('path', '')
    w = request.args.get('w', 400, type=int)
    if not path:
        abort(404)
    import mimetypes

    from flask import current_app
    # 路径安全检查：禁止目录遍历（规范化后验证前缀）
    safe_path = os.path.normpath(os.path.join(current_app.root_path, 'static', path))
    static_dir = os.path.normpath(os.path.join(current_app.root_path, 'static'))
    if not safe_path.startswith(static_dir):
        logger.warning('缩略图路径非法: %s', path)
        abort(404)
    img_path = safe_path
    if not os.path.isfile(img_path):
        logger.warning('缩略图不存在: %s', path)
        # 返回 1×1 透明 GIF（避免页面布局塌陷）
        return Response(
            b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff'
            b'\x00\x00\x00!\xf9\x04\x00\x00\x00\x00\x00,\x00\x00\x00\x00'
            b'\x01\x00\x01\x00\x00\x02\x02D\x01\x00;',
            mimetype='image/gif', headers={'Cache-Control': 'no-cache'}
        )
    # 生成缓存文件路径
    ext = os.path.splitext(path)[1].lower() or '.jpg'
    cache_key = f'{THUMB_CACHE_VER}_{path.replace("/","_")}_{w}{ext}'
    cache_dir = os.path.join(current_app.root_path, 'static', '.thumb_cache')
    cache_path = os.path.join(cache_dir, cache_key)
    os.makedirs(cache_dir, exist_ok=True)

    # 清理旧版本缓存（每小时最多执行一次）
    _cleanup_old_cache(cache_dir, THUMB_CACHE_VER)

    # 缓存命中且未过时（图片源文件未修改）
    if os.path.isfile(cache_path):
        img_mtime = os.path.getmtime(img_path)
        cache_mtime = os.path.getmtime(cache_path)
        if cache_mtime >= img_mtime:
            with open(cache_path, 'rb') as f:
                return Response(f.read(),
                    mimetype=mimetypes.guess_type(cache_key)[0] or 'image/jpeg',
                    headers={'Cache-Control': 'public, max-age=2592000'}
                )
    # ── 生成缩略图 ──────────────────────────
    try:
        from PIL import Image
        img = Image.open(img_path)
        # 只缩小不放大（ratio 最大为 1.0）
        ratio = min(w / img.width, 1.0)
        if ratio < 1:
            new_w = int(img.width * ratio)
            new_h = int(img.height * ratio)
            img = img.resize((new_w, new_h), Image.LANCZOS)
        fmt = 'JPEG' if ext in ('.jpg', '.jpeg') else 'PNG'
        img.save(cache_path, fmt, quality=85, optimize=True)
        with open(cache_path, 'rb') as f:
            return Response(f.read(),
                mimetype=mimetypes.guess_type(cache_key)[0] or 'image/jpeg',
                headers={'Cache-Control': 'public, max-age=2592000'}
            )
    except Exception as e:
        # 缩略图生成失败时，返回原始图片
        logger.error('缩略图失败: %s w=%d error=%s', path, w, e)
        with open(img_path, 'rb') as f:
            return Response(f.read(),
                mimetype=mimetypes.guess_type(path)[0] or 'image/jpeg'
            )


# ── 缓存清理辅助函数 ──────────────────────────
# 记录上次清理时间，避免每次请求都遍历磁盘
_last_cache_cleanup = 0


def _cleanup_old_cache(cache_dir, current_ver):
    """清除旧版本的缩略图缓存。每小时最多执行一次。

    Args:
        cache_dir: 缓存目录路径
        current_ver: 当前版本号（如 'v2'），以此判断哪些文件是旧的
    """
    global _last_cache_cleanup
    now = time.time()
    # 频率限制：每小时最多清理一次
    if now - _last_cache_cleanup < 3600:
        return
    _last_cache_cleanup = now
    if not os.path.isdir(cache_dir):
        return
    for fname in os.listdir(cache_dir):
        # 保留当前版本和未知版本，只删除 v0_ / v1_ 开头的老文件
        if fname.startswith(current_ver + '_'):
            continue  # 当前版本保留
        if fname.startswith('v1_') or fname.startswith('v0_'):
            try:
                os.remove(os.path.join(cache_dir, fname))
            except Exception:
                pass  # 忽略删除失败（如权限问题）


# ── 模板全局函数 ──────────────────────────────
@blog_bp.app_template_global()
def format_date(dt, fmt='%Y/%m/%d'):
    """在 Jinja2 模板中格式化日期。

    注册为全局函数，模板中可直接调用：
      {{ format_date(post.created_at) }}  →  "2026/01/15"

    Args:
        dt: datetime 对象 或 ISO 格式字符串（兼容 Redis 缓存反序列化）
        fmt: 日期格式字符串（默认 '%Y/%m/%d'）

    Returns:
        str: 格式化后的日期字符串
    """
    if dt is None:
        return ''
    if isinstance(dt, str):
        # 兼容 Redis 缓存返回的 ISO 字符串
        try:
            dt = datetime.datetime.fromisoformat(dt)
        except (ValueError, TypeError):
            return dt[:10]  # 取前 10 个字符作为日期
    if hasattr(dt, 'strftime'):
        return dt.strftime(fmt)
    return ''


@blog_bp.app_template_global()
def now():
    """模板中获取当前 UTC 时间。"""
    import datetime
    return datetime.datetime.utcnow()
