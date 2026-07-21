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
import random
import threading
import time

import atexit

import bleach
from flask import Response, abort, current_app, make_response, redirect, render_template, request, url_for

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
def _is_safe_url(url):
    """检查 URL 是否为安全的 HTTP/HTTPS 链接，阻止危险协议注入。

    用于过滤用户提交的链接（如评论中的 URL），
    防止 javascript:/data:/vbscript: 等协议被注入到 <a href> 中。

    Args:
        url: 待检查的 URL 字符串

    Returns:
        bool: True 表示安全可用，False 表示包含危险协议
    """
    if not url:
        return False
    # 跳过以 // 开头的协议相对 URL
    if url.startswith('//'):
        return False
    # 去除空白后检查是否以危险协议开头
    url_lower = ''.join(url.strip().lower().split())
    for scheme in ('javascript:', 'data:', 'vbscript:', 'file:', 'blob:'):
        if url_lower.startswith(scheme):
            return False
    return True


# 标签→允许属性映射表，bleach 清理 HTML 时据此保留安全的属性
_ATTRS_BY_TAG = {
    'a': ('href', 'title', 'rel'),
    'img': ('src', 'alt', 'title', 'style'),
    'th': ('align',),
    'td': ('align',),
    'code': ('class',),
    'span': ('class', 'style'),
    'div': ('class',),
    'pre': ('class',),
    'abbr': ('title',),
}


def _allow_attrs(tag, name, value):
    """bleach 属性白名单回调：判断指定标签的某个属性是否允许保留。

    Args:
        tag: HTML 标签名
        name: 属性名
        value: 属性值

    Returns:
        bool: True 表示该属性允许保留
    """
    allowed = _ATTRS_BY_TAG.get(tag)
    if not allowed:
        return False
    # 对 <a href> 做额外安全校验
    if tag == 'a' and name == 'href':
        return _is_safe_url(value)
    return name in allowed


ALLOWED_ATTRS = _allow_attrs

# 缩略图缓存版本号（修改此值使旧缓存自动失效并清理）
THUMB_CACHE_VER = 'v3'


# ── 侧边栏数据缓存（Redis，降级友好） ─────────
# 共享线程池，避免每次请求创建/销毁
_sidebar_executor = None
_sidebar_executor_lock = threading.Lock()

# 缩略图生成并发写锁
_thumbnail_locks: dict[str, threading.Lock] = {}
_thumbnail_locks_lock = threading.Lock()


def _get_thumbnail_lock(cache_path: str) -> threading.Lock:
    """获取或创建与缓存路径关联的线程锁，防止同一缩略图的并发写入。

    Args:
        cache_path: 缩略图缓存文件的绝对路径

    Returns:
        与 cache_path 一一对应的 threading.Lock 对象
    """
    with _thumbnail_locks_lock:
        if cache_path not in _thumbnail_locks:
            _thumbnail_locks[cache_path] = threading.Lock()
        return _thumbnail_locks[cache_path]


def _get_sidebar_data():
    """获取侧边栏数据（分类列表 + 最新文章），带 Redis 缓存。

    使用 ThreadPoolExecutor 并行执行 3 个独立的数据获取操作：
      1. 分类列表查询
      2. 分类文章数聚合查询
      3. 最新文章（Redis 缓存命中则跳过 DB）

    当 Redis 不可用时，回退到数据库查询，不影响页面渲染。

    Returns:
        tuple: (categories, recent_posts, cat_post_counts)
            categories       — 全部分类列表（按名称排序）
            recent_posts     — 最新 4 篇已发布文章的摘要信息
            cat_post_counts  — dict { category_id: 已发布文章数 }
    """
    from concurrent.futures import ThreadPoolExecutor

    from flask import current_app

    from .cache import cache_get, cache_set

    global _sidebar_executor
    if _sidebar_executor is None:
        with _sidebar_executor_lock:
            if _sidebar_executor is None:
                _sidebar_executor = ThreadPoolExecutor(max_workers=3)
                # 进程退出时自动关闭线程池，避免资源泄漏
                atexit.register(lambda: _sidebar_executor.shutdown(wait=False))

    ttl = current_app.config.get('CACHE_TTL_SIDEBAR', 300)
    app = current_app._get_current_object()

    def _fetch_categories():
        """子任务 1：获取所有分类（按名称排序）。"""
        with app.app_context():
            return Category.query.order_by(Category.name).all()

    def _fetch_cat_post_counts():
        """子任务 2：统计每个分类下已发布文章的数量。"""
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
        """子任务 3：获取最新 4 篇已发布文章（优先走 Redis 缓存）。"""
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
            # 序列化为纯 Python 结构以兼容 Redis 存储
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

    # 并行提交三个独立查询任务
    fut_cat = _sidebar_executor.submit(_fetch_categories)
    fut_counts = _sidebar_executor.submit(_fetch_cat_post_counts)
    fut_recent = _sidebar_executor.submit(_fetch_recent_posts)
    categories = fut_cat.result()
    cat_post_counts = fut_counts.result()
    recent_posts = fut_recent.result()

    return categories, recent_posts, cat_post_counts


def _cached_featured_cards():
    """获取首页展示的特色卡片列表，带 Redis 缓存（5 分钟 TTL）。

    从 FeaturedCard 表中读取所有激活的卡片，按 sort_order 排序，
    结果序列化后缓存在 Redis 中，减少数据库查询。

    Returns:
        list[dict]: 每个元素包含 title / description / icon / tag / link / image_url
    """
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

def _get_site_wordcloud():
    """获取全站词云数据（从预计算数据库读取）。

    Returns:
        dict: {period: data, ...} 如 {'all': [...], '2026-01': [...], ...}
    """
    from .models import WordCloudData

    try:
        records = WordCloudData.query.filter_by(post_id=None, source='blog').order_by(WordCloudData.period).all()
    except Exception:
        # 兼容旧表缺少 source/period 列
        try:
            records = WordCloudData.query.filter_by(post_id=None).order_by(WordCloudData.period).all()
        except Exception:
            records = WordCloudData.query.filter_by(post_id=None).all()
    if not records:
        return None
    return {r.period: r.data for r in records if r.data}


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

    # 基础查询：只取已发布的文章，同时使用 joinedload 预加载作者和分类信息
    # 避免 N+1 查询问题（遍历文章时不再逐条查询关联表）
    query = Post.query.options(
        db.joinedload(Post.author),
        db.joinedload(Post.categories),
        load_only(Post.id, Post.title, Post.slug, Post.summary, Post.cover_image, Post.created_at),
    ).filter_by(is_published=True)
    # 按分类筛选（多对多关联：通过中间表 post_categories 关联）
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

    from blog.models import HeroImage

    # 从激活的 Hero 画像中随机选一张，供粒子引擎渲染
    # 无画像时 hero_image=None，模板降级为纯文字 hero
    hero_images = HeroImage.query.filter_by(is_active=True).order_by(HeroImage.sort_order).all()
    hero_image = random.choice(hero_images).image_url if hero_images else None

    # 读取词云配置（单行，惰性初始化）
    from .models import WordCloudConfig
    wc_config = WordCloudConfig.get_or_create().to_dict()
    wordcloud_periods = _get_site_wordcloud() if wc_config.get('enabled_site', True) else None

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
        wordcloud_periods=wordcloud_periods,
        wc_config=wc_config,
    )


# ═══════════════════════════════════════════════
# 文章详情页
# ═══════════════════════════════════════════════
@blog_bp.route('/post/<slug>/html-frame')
def post_html_frame(slug):
    """HTML 报告独立帧路由：返回原始 html_content，无父页面上下文。

    专为 sandboxed iframe 设计，返回纯 HTML + 严格安全头。
    不包含 allow-same-origin，iframe 内脚本无法访问父页面 DOM/Cookie。

    Args:
        slug: 文章的唯一 URL 标识

    Returns:
        Response: 包含完整 HTML 的响应，带有严格 CSP 安全头
    """
    post = (
        Post.query.options(db.joinedload(Post.author), db.joinedload(Post.categories))
        .filter_by(slug=slug, is_published=True)
        .first_or_404()
    )
    if not post.html_content:
        abort(404)

    # 注入 iframe 自适应高度的 JavaScript 脚本
    # 通过 postMessage 通知父页面调整 iframe 高度
    AUTO_HEIGHT_SCRIPT = '''<script>
(function(){function h(){parent.postMessage({type:'hoshino-iframe-resize',height:document.documentElement.scrollHeight},'*')}
window.addEventListener('load',h);window.addEventListener('resize',h);
new ResizeObserver(h).observe(document.body);})();
</script>'''

    content = post.html_content
    # 在 </body> 前注入自适应高度脚本（浏览器忽略 </html> 后的内容）
    if '</body>' in content:
        content = content.replace('</body>', AUTO_HEIGHT_SCRIPT + '</body>', 1)
    elif '</html>' in content:
        content = content.replace('</html>', AUTO_HEIGHT_SCRIPT + '</html>', 1)
    else:
        content += AUTO_HEIGHT_SCRIPT

    return Response(
        content,
        mimetype='text/html',
        headers={
            'Content-Security-Policy': (
                "default-src 'self'; "
                "script-src 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
                "style-src 'unsafe-inline' 'self' https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
                "img-src 'self' data: https:; "
                "font-src 'self' https://fonts.gstatic.com; "
                "connect-src 'self'; "
                "frame-src 'none'; "
                "object-src 'none'"
            ),
            'X-Content-Type-Options': 'nosniff',
        }
    )


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

    # ── 渲染缓存（内容不变时跳过 markdown + bleach 重复渲染）──
    from .cache import cache_get, cache_set

    # 缓存键包含 updated_at 时间戳，文章更新后自动失效
    cache_key = f'post:rendered:{post.id}:{post.updated_at.timestamp() if post.updated_at else ""}'
    rendered_content = cache_get(cache_key)
    if rendered_content is None:
        from markdown import markdown

        # Markdown → HTML → 清理 XSS（三步流水线）
        rendered_content = bleach.clean(
            markdown(post.content, extensions=['fenced_code', 'codehilite', 'tables']),
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRS,
        )
        cache_set(cache_key, rendered_content, 3600)

    comment_count = post.published_comments()

    # ── 词云数据（从预计算数据库读取，不再实时分词）──
    wordcloud_data = None
    wc_config = None
    from .models import WordCloudConfig, WordCloudData
    wc_config = WordCloudConfig.get_or_create().to_dict()
    wc_record = WordCloudData.query.filter_by(post_id=post.id).first()
    if wc_record and wc_record.data:
        wordcloud_data = wc_record.data

    # 优先使用手动编写的 html_content（如报告），否则渲染 Markdown
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
        wordcloud_data=wordcloud_data,
        wc_config=wc_config,
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
        # 表单有效：将留言写入 ContactMessage 表（未来可改为发邮件通知）
        from .models import ContactMessage

        msg = ContactMessage(
            name=form.name.data,
            email=form.email.data,
            subject='',
            content=form.message.data or '',
        )
        db.session.add(msg)
        try:
            db.session.commit()
        except Exception:
            # 数据库写入失败时回滚，保持 message_sent = False
            db.session.rollback()
            message_sent = False
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

    搜索方式：
      1. 优先使用数据库全文索引（PostgreSQL tsvector 或 SQLite FTS）
      2. 全文搜索无结果时，回退到 ILIKE 模糊匹配（不区分大小写）

    结果按创建时间倒序排列，支持分页。

    Template: index.html（与首页共用）
    """
    q = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    if not q:
        return redirect(url_for('blog.index'))
    # 转义 SQL 通配符（% 和 _），防止恶意构造的搜索词导致 DoS
    safe_q = q.replace('%', '\\%').replace('_', '\\_')
    per_page = request.args.get('per_page', current_app.config['POSTS_PER_PAGE'], type=int)
    categories, recent_posts, cat_post_counts = _get_sidebar_data()
    # 根据数据库方言选择不同的全文搜索语法
    engine = db.get_engine()
    dialect = engine.dialect.name
    if dialect == 'postgresql':
        # PostgreSQL: 使用 to_tsvector + plainto_tsquery（防 tsquery 语法错误）
        match_exprs = [
            func.to_tsvector('simple', Post.title).op('@@')(func.plainto_tsquery('simple', q)),
            func.to_tsvector('simple', Post.summary).op('@@')(func.plainto_tsquery('simple', q)),
            func.to_tsvector('simple', Post.content).op('@@')(func.plainto_tsquery('simple', q)),
        ]
    else:
        # MySQL: 使用原生 MATCH ... AGAINST 语法匹配复合 FULLTEXT 索引
        # SQLite: 使用 FTS match 谓词
        if dialect == 'mysql':
            from sqlalchemy import text
            match_expr = text("MATCH (title, content) AGAINST (:q IN BOOLEAN MODE)").bindparams(q=q)
        else:
            match_expr = Post.title.match(q) | Post.content.match(q)
        match_exprs = [match_expr]
    results = (
        Post.query.options(
            db.joinedload(Post.categories),
            load_only(
                Post.id, Post.title, Post.slug, Post.summary, Post.cover_image, Post.created_at
            ),
        )
        .filter(
            Post.is_published == True,
            db.or_(*match_exprs),
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

    # 路径安全检查：禁止目录遍历（规范化后验证前缀是否为 static_dir）
    safe_path = os.path.realpath(os.path.normpath(os.path.join(current_app.root_path, 'static', path)))
    static_dir = os.path.realpath(os.path.normpath(os.path.join(current_app.root_path, 'static')))
    if not safe_path.startswith(static_dir):
        logger.warning('缩略图路径非法: %s', path)
        abort(404)
    img_path = safe_path
    if not os.path.isfile(img_path):
        logger.warning('缩略图不存在: %s', path)
        # 返回 1×1 透明 GIF（避免页面布局塌陷）而非 404 错误页
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
        # 默认输出 WebP（体积小，质量高）
        output_fmt, ext, save_kwargs, mime_type = (
            'WEBP',
            '.webp',
            {'quality': 80, 'method': 6},
            'image/webp',
        )

    # 生成缓存文件路径（包含版本号，升级时自动失效）
    cache_key = f'{THUMB_CACHE_VER}_{path.replace("/", "_")}_{w}{ext}'
    cache_dir = os.path.join(current_app.root_path, 'static', '.thumb_cache')
    cache_path = os.path.join(cache_dir, cache_key)
    os.makedirs(cache_dir, exist_ok=True)

    # 清理旧版本缓存（每小时最多执行一次）
    _cleanup_old_cache(cache_dir, THUMB_CACHE_VER)

    # 缓存命中且未过时（图片源文件未修改）— 直接返回缓存文件
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

        # 使用线程锁防止同一缩略图的并发写入
        lock = _get_thumbnail_lock(cache_path)
        with lock:
            # 双重检查：获取锁后再次检查缓存是否已被其他线程写入
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
            img = Image.open(img_path)
            # 只缩小不放大（ratio 最大为 1.0），保持原始宽高比
            ratio = min(w / img.width, 1.0)
            if ratio < 1:
                new_w = int(img.width * ratio)
                new_h = int(img.height * ratio)
                img = img.resize((new_w, new_h), Image.LANCZOS)
            # JPEG 不支持 RGBA 模式，先转换为 RGB
            if output_fmt == 'JPEG' and img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            img.save(cache_path, output_fmt, **save_kwargs)
            with open(cache_path, 'rb') as f:
                return Response(
                    f.read(), mimetype=mime_type, headers={'Cache-Control': 'public, max-age=2592000'}
                )
    except Exception as e:
        # 缩略图生成失败时，降级返回原始图片（避免页面图片缺失）
        logger.error('缩略图失败: %s w=%d error=%s', path, w, e)
        with open(img_path, 'rb') as f:
            return Response(f.read(), mimetype=mimetypes.guess_type(path)[0] or 'image/jpeg')


# ── 缓存清理辅助函数 ──────────────────────────
# 记录上次清理时间，避免每次请求都遍历磁盘
_last_cache_cleanup = 0
_cache_cleanup_lock = threading.Lock()


def _cleanup_old_cache(cache_dir, current_ver):
    """清除旧版本的缩略图缓存。每小时最多执行一次。

    遍历缓存目录，删除文件名以 `v0_`、`v1_`、`v2_` 开头的旧缓存文件，
    保留当前版本（current_ver）前缀的文件。

    Args:
        cache_dir: 缓存目录路径
        current_ver: 当前版本号（如 'v2'），以此判断哪些文件是旧的
    """
    global _last_cache_cleanup
    with _cache_cleanup_lock:
        now = time.time()
        # 频率限制：每小时最多清理一次，避免每次请求都遍历磁盘
        if now - _last_cache_cleanup < 3600:
            return
        _last_cache_cleanup = now
        if not os.path.isdir(cache_dir):
            return
        try:
            entries = os.listdir(cache_dir)
        except FileNotFoundError:
            return
        for fname in entries:
            # 保留当前版本和未知版本的文件，只删除已知旧版本前缀的文件
            if fname.startswith(current_ver + '_'):
                continue
            if fname.startswith('v2_') or fname.startswith('v1_') or fname.startswith('v0_'):
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
        # 兼容 Redis 缓存返回的 ISO 格式字符串
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

    从 User 表中读取第一个管理员账号的社交媒体 URL，
    结果缓存在 Redis 中 5 分钟（避免每次渲染页脚都查库）。

    返回 dict: { website, gitcode_url, github_url, gitee_url, bilibili_url }
    每个值为字符串，无对应数据时为空字符串。

    Returns:
        dict: 包含所有社交链接 URL 的字典
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
