"""
HOSHINO Blog — 前台路由

处理所有公开访问的页面路由：
   首页文章列表、文章详情、分类筛选、关于、联系、
   全文搜索、RSS 订阅、缩略图动态生成、工具页面。

所有路由挂在 blog_bp（Blueprint）上，URL 前缀为空。

函数列表：
   _get_sidebar_data()     — 侧边栏数据（分类+最新文章），带 Redis 缓存
   index()                 — 首页文章瀑布流（分页+分类筛选）
   single_post(slug)       — 文章详情页（Markdown 渲染+评论表单）
   category(slug)          — 按分类查看文章列表
   about()                 — 关于页面
   contact()               — 联系页面（留言表单）
   tools()                 — 工具页面（Base64/字数/颜色/JSON/时间戳等）
   search()                — 全文搜索（ILIKE 模糊匹配）
   rss_feed()              — RSS/Atom 订阅源
   thumbnail()             — 动态缩略图生成（磁盘缓存）
   _cleanup_old_cache()    — 清理旧版本缩略图缓存
   format_date()           — 模板全局函数：日期格式化
   now()                   — 模板全局函数：当前 UTC 时间
"""

import datetime
import logging
import os
import threading
import time

import bleach
from flask import Response, abort, current_app, redirect, render_template, request, url_for

from sqlalchemy import func
from sqlalchemy.orm import load_only

from . import blog_bp
from .forms import CommentForm, ContactForm
from .models import Category, Comment, FeaturedCard, Post, db, post_categories

logger = logging.getLogger(__name__)

# 共享 XSS 过滤白名单（多路由复用）
ALLOWED_TAGS = [
    'p',
    'br',
    'strong',
    'em',
    'a',
    'code',
    'pre',
    'span',
    'div',
    'h1',
    'h2',
    'h3',
    'h4',
    'h5',
    'h6',
    'ul',
    'ol',
    'li',
    'blockquote',
    'table',
    'thead',
    'tbody',
    'tr',
    'th',
    'td',
    'img',
    'hr',
    'sup',
    'sub',
    'del',
    'ins',
    'kbd',
    'samp',
    'var',
    'abbr',
    'dfn',
    'u',
    's',
]
ALLOWED_ATTRS = {
    'a': ['href', 'title', 'rel'],
    'img': ['src', 'alt', 'title', 'style'],
    'th': ['align'],
    'td': ['align'],
    'code': ['class'],
    'span': ['class', 'style'],
    'div': ['class'],
    'pre': ['class'],
    'abbr': ['title'],
}

# 缩略图缓存版本号（修改此值使旧缓存自动失效并清理）
THUMB_CACHE_VER = 'v3'


# ── 侧边栏数据缓存（Redis，降级友好） ─────────
# 共享线程池，避免每次请求创建/销毁
_sidebar_executor = None
_sidebar_executor_lock = threading.Lock()


def _get_sidebar_data():
    """获取侧边栏数据（分类列表 + 最新文章），带 Redis 缓存。

    使用 ThreadPoolExecutor 并行执行 3 个独立的数据获取操作：
      1. 分类列表查询
      2. 分类文章数聚合查询
      3. 最新文章（Redis 缓存命中则跳过 DB）

    当 Redis 不可用时，回退到数据库查询，不影响页面渲染。

    Returns:
        tuple: (categories, recent_posts, cat_post_counts)
    """
    from concurrent.futures import ThreadPoolExecutor

    from flask import current_app

    from .cache import cache_get, cache_set

    global _sidebar_executor
    if _sidebar_executor is None:
        with _sidebar_executor_lock:
            if _sidebar_executor is None:
                _sidebar_executor = ThreadPoolExecutor(max_workers=3)

    ttl = current_app.config.get('CACHE_TTL_SIDEBAR', 300)
    app = current_app._get_current_object()

    def _fetch_categories():
        with app.app_context():
            return Category.query.order_by(Category.name).all()

    def _fetch_cat_post_counts():
        with app.app_context():
            return dict(
                db.session.query(
                    post_categories.c.category_id, func.count(post_categories.c.post_id)
                )
                .join(Post, Post.id == post_categories.c.post_id)
                .filter(Post.is_published == True)
                .group_by(post_categories.c.category_id)
                .all()
            )

    def _fetch_recent_posts():
        with app.app_context():
            cached = cache_get('sidebar:recent_posts')
            if cached is not None:
                return cached
            posts = (
                Post.query.filter_by(is_published=True)
                .options(
                    load_only(Post.id, Post.title, Post.slug, Post.cover_image, Post.created_at)
                )
                .order_by(Post.created_at.desc())
                .limit(4)
                .all()
            )
            result = [
                {
                    'id': p.id,
                    'title': p.title,
                    'slug': p.slug,
                    'cover_image': p.cover_image,
                    'created_at': p.created_at.isoformat() if p.created_at else None,
                }
                for p in posts
            ]
            cache_set('sidebar:recent_posts', result, ttl)
            return result

    fut_cat = _sidebar_executor.submit(_fetch_categories)
    fut_counts = _sidebar_executor.submit(_fetch_cat_post_counts)
    fut_recent = _sidebar_executor.submit(_fetch_recent_posts)
    categories = fut_cat.result()
    cat_post_counts = fut_counts.result()
    recent_posts = fut_recent.result()

    return categories, recent_posts, cat_post_counts


def _cached_featured_cards():
    from .cache import cache_get, cache_set

    cached = cache_get('home:featured_cards')
    if cached is not None:
        return cached
    cards = FeaturedCard.query.filter_by(is_active=True).order_by(FeaturedCard.sort_order).all()
    cards_data = [
        {
            'title': c.title,
            'description': c.description,
            'icon': c.icon,
            'tag': c.tag,
            'link': c.link,
            'image_url': c.image_url,
        }
        for c in cards
    ]
    cache_set('home:featured_cards', cards_data, 300)
    return cards_data


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
    query = Post.query.options(
        db.joinedload(Post.author),
        db.joinedload(Post.categories),
        load_only(Post.id, Post.title, Post.slug, Post.summary, Post.cover_image, Post.created_at),
    ).filter_by(is_published=True)
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
    categories, recent_posts, cat_post_counts = _get_sidebar_data()
    featured_cards = _cached_featured_cards()
    cat_lookup = {c.slug: c.name for c in categories}

    import random
    from blog.models import HeroImage

    # 从激活的 Hero 画像中随机选一张，供粒子引擎渲染
    # 无画像时 hero_image=None，模板降级为纯文字 hero
    hero_images = HeroImage.query.filter_by(is_active=True).order_by(HeroImage.sort_order).all()
    hero_image = random.choice(hero_images).image_url if hero_images else None

    return render_template(
        'index.html',
        posts=posts,
        categories=categories,
        recent_posts=recent_posts,
        cat_post_counts=cat_post_counts,
        current_category=category_slug,
        current_per_page=per_page,
        per_page_options=current_app.config['PER_PAGE_OPTIONS'],
        featured_cards=featured_cards,
        cat_lookup=cat_lookup,
        blog_subtitle=current_app.config['BLOG_SUBTITLE'],
        hero_image=hero_image,
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
    post = (
        Post.query.options(db.joinedload(Post.author), db.joinedload(Post.categories))
        .filter_by(slug=slug, is_published=True)
        .first_or_404()
    )
    categories, recent_posts, cat_post_counts = _get_sidebar_data()
    form = CommentForm()

    # ── 处理评论提交 ──────────────────────────
    if form.validate_on_submit():
        comment = Comment(
            post_id=post.id,
            author_name=form.author_name.data,
            author_email=form.author_email.data,
            content=bleach.clean(form.content.data or '', tags=[], strip=True),
            is_approved=False,  # 新评论默认隐藏，需管理员审核
        )
        db.session.add(comment)
        db.session.commit()
        # 提交后重定向到文章页的 #comments 锚点
        return redirect(url_for('blog.single_post', slug=slug) + '#comments')

    # ── 渲染缓存（内容不变时跳过 markdown + bleach）──
    from .cache import cache_get, cache_set

    cache_key = f'post:rendered:{post.id}:{post.updated_at.timestamp() if post.updated_at else ""}'
    rendered_content = cache_get(cache_key)
    if rendered_content is None:
        from markdown import markdown

        rendered_content = bleach.clean(
            markdown(post.content, extensions=['fenced_code', 'codehilite', 'tables']),
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRS,
        )
        cache_set(cache_key, rendered_content, 3600)

    comment_count = post.published_comments()

    template = 'html-post.html' if post.html_content else 'single-post.html'

    return render_template(
        template,
        post=post,
        rendered_content=rendered_content,
        categories=categories,
        recent_posts=recent_posts,
        cat_post_counts=cat_post_counts,
        form=form,
        comment_count=comment_count,
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
    posts = (
        Post.query.options(
            load_only(Post.id, Post.title, Post.slug, Post.cover_image, Post.created_at),
            db.joinedload(Post.categories),
        )
        .filter(Post.categories.any(id=cat.id), Post.is_published == True)
        .order_by(Post.created_at.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )
    categories, recent_posts, cat_post_counts = _get_sidebar_data()
    return render_template(
        'category-grid.html',
        category=cat,
        posts=posts,
        categories=categories,
        recent_posts=recent_posts,
        cat_post_counts=cat_post_counts,
        current_per_page=per_page,
        per_page_options=current_app.config['PER_PAGE_OPTIONS'],
    )


# ═══════════════════════════════════════════════
# 关于页
# ═══════════════════════════════════════════════
@blog_bp.route('/about')
def about():
    """关于页面。

    展示博主信息、站点介绍等静态内容。
    内容取自管理员账号的 about_content 字段（富文本 HTML）。
    Template: about.html
    """
    categories, recent_posts, cat_post_counts = _get_sidebar_data()
    from .models import User

    admin = User.query.filter_by(role='admin').order_by(User.id).first()
    about_content = (
        admin.about_content if admin and admin.about_content else '<p>欢迎来到 Hoshino Blog</p>'
    )
    about_content = bleach.clean(about_content, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS)
    return render_template(
        'about.html',
        about_content=about_content,
        categories=categories,
        recent_posts=recent_posts,
        cat_post_counts=cat_post_counts,
    )


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
        # 表单有效：留存留言至 session 供页面显示（未来可改为发邮件）
        from .models import ContactMessage

        msg = ContactMessage(
            name=form.name.data,
            email=form.email.data,
            subject=form.subject.data or '',
            content=form.content.data,
        )
        db.session.add(msg)
        db.session.commit()
        message_sent = True
    categories, recent_posts, cat_post_counts = _get_sidebar_data()
    return render_template(
        'contact.html',
        categories=categories,
        recent_posts=recent_posts,
        cat_post_counts=cat_post_counts,
        message_sent=message_sent,
        form=form,
    )


# ═══════════════════════════════════════════════
# 工具页
# ═══════════════════════════════════════════════
@blog_bp.route('/tools')
def tools():
    """工具页面：提供多种在线小工具。

    包含功能：
      - Base64 编码/解码
      - 字数统计
      - 颜色选择器与格式转换
      - JSON 格式化与校验
      - 时间戳与日期互转
      - 哈希计算（MD5/SHA1/SHA256）
      - 图片压缩

    Template: tools.html
    """
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
    # 转义 SQL 通配符，防止 DoS
    safe_q = q.replace('%', '\\%').replace('_', '\\_')
    per_page = request.args.get('per_page', current_app.config['POSTS_PER_PAGE'], type=int)
    categories, recent_posts, cat_post_counts = _get_sidebar_data()
    # 使用 MATCH AGAINST 全文搜索（需 FULLTEXT 索引）
    results = (
        Post.query.options(
            db.joinedload(Post.categories),
            load_only(
                Post.id, Post.title, Post.slug, Post.summary, Post.cover_image, Post.created_at
            ),
        )
        .filter(
            Post.is_published == True,
            db.or_(
                Post.title.match(q, postgresql_regconfig='simple'),
                Post.summary.match(q, postgresql_regconfig='simple'),
                Post.content.match(q, postgresql_regconfig='simple'),
            ),
        )
        .order_by(Post.created_at.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )
    # 若全文搜索无结果，回退到 ILIKE 模糊匹配（转义后的安全版本）
    if results.total == 0:
        results = (
            Post.query.options(
                db.joinedload(Post.categories),
                load_only(
                    Post.id, Post.title, Post.slug, Post.summary, Post.cover_image, Post.created_at
                ),
            )
            .filter(
                Post.is_published == True,
                db.or_(
                    Post.title.ilike(f'%{safe_q}%'),
                    Post.summary.ilike(f'%{safe_q}%'),
                    Post.content.ilike(f'%{safe_q}%'),
                ),
            )
            .order_by(Post.created_at.desc())
            .paginate(page=page, per_page=per_page, error_out=False)
        )
    return render_template(
        'index.html',
        posts=results,
        categories=categories,
        recent_posts=recent_posts,
        cat_post_counts=cat_post_counts,
        search_query=q,
        current_category=None,
        current_per_page=per_page,
        per_page_options=current_app.config['PER_PAGE_OPTIONS'],
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
    posts = Post.query.filter_by(is_published=True).order_by(Post.created_at.desc()).limit(20).all()
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
      fmt  — 输出格式（webp/jpg/png，默认 webp）

    特性：
      - 默认输出 WebP（体积比 JPEG 小 30-50%），保持原宽高比
      - 支持格式覆盖（?fmt=jpg 用于兼容旧浏览器）
      - 磁盘缓存 + 版本号控制（升级时自动失效）
      - 路径安全检查（禁止 ../ 遍历）
      - RGBA 图片自动转换为 RGB 再存 JPEG
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
            mimetype='image/gif',
            headers={'Cache-Control': 'no-cache'},
        )

    # ── 输出格式 ──────────────────────────────
    fmt_param = request.args.get('fmt', '').upper()
    if fmt_param in ('JPEG', 'JPG'):
        output_fmt, ext, save_kwargs, mime_type = (
            'JPEG',
            '.jpg',
            {'quality': 85, 'optimize': True},
            'image/jpeg',
        )
    elif fmt_param == 'PNG':
        output_fmt, ext, save_kwargs, mime_type = (
            'PNG',
            '.png',
            {'quality': 85, 'optimize': True},
            'image/png',
        )
    else:
        output_fmt, ext, save_kwargs, mime_type = (
            'WEBP',
            '.webp',
            {'quality': 80, 'method': 6},
            'image/webp',
        )

    # 生成缓存文件路径
    cache_key = f'{THUMB_CACHE_VER}_{path.replace("/", "_")}_{w}{ext}'
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
                return Response(
                    f.read(),
                    mimetype=mime_type,
                    headers={'Cache-Control': 'public, max-age=2592000'},
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
        # JPEG 不支持 RGBA，先转换
        if output_fmt == 'JPEG' and img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        img.save(cache_path, output_fmt, **save_kwargs)
        with open(cache_path, 'rb') as f:
            return Response(
                f.read(), mimetype=mime_type, headers={'Cache-Control': 'public, max-age=2592000'}
            )
    except Exception as e:
        # 缩略图生成失败时，返回原始图片
        logger.error('缩略图失败: %s w=%d error=%s', path, w, e)
        with open(img_path, 'rb') as f:
            return Response(f.read(), mimetype=mimetypes.guess_type(path)[0] or 'image/jpeg')


# ── 缓存清理辅助函数 ──────────────────────────
# 记录上次清理时间，避免每次请求都遍历磁盘
_last_cache_cleanup = 0
_cache_cleanup_lock = threading.Lock()


def _cleanup_old_cache(cache_dir, current_ver):
    """清除旧版本的缩略图缓存。每小时最多执行一次。

    Args:
        cache_dir: 缓存目录路径
        current_ver: 当前版本号（如 'v2'），以此判断哪些文件是旧的
    """
    global _last_cache_cleanup
    with _cache_cleanup_lock:
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
                continue
            if fname.startswith('v1_') or fname.startswith('v0_'):
                try:
                    os.remove(os.path.join(cache_dir, fname))
                except Exception:
                    pass


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
    logger.warning('format_date 收到意外类型: %s', type(dt).__name__)
    return ''


@blog_bp.app_template_global()
def now():
    """模板中获取当前 UTC 时间。

    注册为全局函数，模板中可直接调用：
      {{ now() }}  →  datetime.datetime(2026, 1, 15, 12, 30, 0)

    Returns:
        datetime: 当前 UTC 时间
    """
    return datetime.datetime.now(datetime.UTC)


@blog_bp.app_template_global()
def admin_social():
    """获取管理员社交链接，供页脚显示。

    返回 dict: { website, gitcode_url, github_url, gitee_url, bilibili_url }
    """
    from .cache import cache_get, cache_set

    cached = cache_get('admin:social_links')
    if cached:
        return cached
    from .models import User

    admin = User.query.filter_by(role='admin').order_by(User.id).first()
    result = (
        {
            'website': admin.website or '',
            'gitcode_url': admin.gitcode_url or '',
            'github_url': admin.github_url or '',
            'gitee_url': admin.gitee_url or '',
            'bilibili_url': admin.bilibili_url or '',
        }
        if admin
        else {
            'website': '',
            'gitcode_url': '',
            'github_url': '',
            'gitee_url': '',
            'bilibili_url': '',
        }
    )
    cache_set('admin:social_links', result, 300)
    return result
