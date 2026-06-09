# -*- coding: utf-8 -*-
"""
HOSHINO Blog — 前台路由

处理所有公开访问的页面：
首页文章列表、文章详情、分类筛选、关于、联系、
全文搜索、RSS 订阅、缩略图生成。
"""
import datetime
import os
import time
import logging
from flask import render_template, request, redirect, url_for, abort, Response, current_app
from . import blog_bp
from .models import db, Post, Category, Comment
from .forms import CommentForm, ContactForm

logger = logging.getLogger(__name__)

# 缩略图缓存版本号（修改此值使旧缓存自动失效并清理）
THUMB_CACHE_VER = 'v2'


# ── 首页：文章瀑布流 ──────────────────────────
@blog_bp.route('/')
def index():
    """首页：分页显示已发布的文章列表，支持按分类筛选。"""
    page = request.args.get('page', 1, type=int)
    category_slug = request.args.get('category', None)

    # 基础查询：只取已发布的文章，同时加载作者信息
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
    categories = Category.query.order_by(Category.name).all()
    recent_posts = Post.query.filter_by(is_published=True).order_by(
        Post.created_at.desc()).limit(4).all()

    return render_template('index.html',
        posts=posts, categories=categories,
        recent_posts=recent_posts, current_category=category_slug,
        current_per_page=per_page,
        per_page_options=current_app.config['PER_PAGE_OPTIONS']
    )


# ── 文章详情页 ─────────────────────────────────
@blog_bp.route('/post/<slug>', methods=['GET', 'POST'])
def single_post(slug):
    """文章详情：渲染 Markdown 正文 + 评论列表 + 评论表单。"""
    post = Post.query.filter_by(slug=slug, is_published=True).first_or_404()
    categories = Category.query.order_by(Category.name).all()
    recent_posts = Post.query.filter_by(is_published=True).order_by(
        Post.created_at.desc()).limit(4).all()
    form = CommentForm()

    # 处理评论提交
    if form.validate_on_submit():
        comment = Comment(
            post_id=post.id,
            author_name=form.author_name.data,
            author_email=form.author_email.data,
            content=form.content.data,
            is_approved=False  # 需要管理员审核
        )
        db.session.add(comment)
        db.session.commit()
        return redirect(url_for('blog.single_post', slug=slug) + '#comments')

    # 将 Markdown 渲染为 HTML（支持代码高亮、表格）
    from markdown import markdown
    post.content = markdown(post.content, extensions=[
        'fenced_code', 'codehilite', 'tables'
    ])

    return render_template('single-post.html',
        post=post, categories=categories,
        recent_posts=recent_posts, form=form
    )


# ── 分类文章列表 ───────────────────────────────
@blog_bp.route('/category/<slug>')
def category(slug):
    """按分类查看文章列表（多对多关联筛选）。"""
    cat = Category.query.filter_by(slug=slug).first_or_404()
    page = request.args.get('page', 1, type=int)
    # per_page 取自 URL 参数或配置默认值，与首页一致
    per_page = request.args.get('per_page', current_app.config['POSTS_PER_PAGE'], type=int)
    posts = Post.query.filter(
        Post.categories.any(id=cat.id), Post.is_published == True
    ).order_by(Post.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    categories = Category.query.order_by(Category.name).all()
    recent_posts = Post.query.filter_by(is_published=True).order_by(
        Post.created_at.desc()).limit(4).all()
    return render_template('category-grid.html',
        category=cat, posts=posts,
        categories=categories, recent_posts=recent_posts,
        current_per_page=per_page,
        per_page_options=current_app.config['PER_PAGE_OPTIONS']
    )


# ── 关于页 ─────────────────────────────────────
@blog_bp.route('/about')
def about():
    """关于页面。"""
    categories = Category.query.order_by(Category.name).all()
    recent_posts = Post.query.filter_by(is_published=True).order_by(
        Post.created_at.desc()).limit(4).all()
    return render_template('about.html', categories=categories, recent_posts=recent_posts)


# ── 联系页 ─────────────────────────────────────
@blog_bp.route('/contact', methods=['GET', 'POST'])
def contact():
    """联系页面：提交留言表单（带 CSRF 保护）。"""
    categories = Category.query.order_by(Category.name).all()
    recent_posts = Post.query.filter_by(is_published=True).order_by(
        Post.created_at.desc()).limit(4).all()
    form = ContactForm()
    message_sent = False
    if form.validate_on_submit():
        message_sent = True  # 生产环境应改为发送邮件
    return render_template('contact.html',
        categories=categories, recent_posts=recent_posts,
        message_sent=message_sent, form=form
    )


# ── 全文搜索 ───────────────────────────────────
@blog_bp.route('/search')
def search():
    """搜索文章：匹配标题、摘要、正文。"""
    q = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    if not q:
        return redirect(url_for('blog.index'))
    # per_page 取自 URL 参数或配置默认值，搜索结果也支持分页调整
    per_page = request.args.get('per_page', current_app.config['POSTS_PER_PAGE'], type=int)
    categories = Category.query.order_by(Category.name).all()
    recent_posts = Post.query.filter_by(is_published=True).order_by(
        Post.created_at.desc()).limit(4).all()
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


# ── RSS 订阅 ───────────────────────────────────
@blog_bp.route('/feed.xml')
def rss_feed():
    """RSS/Atom 订阅源。"""
    posts = Post.query.filter_by(is_published=True).order_by(
        Post.created_at.desc()).limit(20).all()
    response = Response(render_template('rss.xml', posts=posts))
    response.headers['Content-Type'] = 'application/xml; charset=utf-8'
    return response


# ── 缩略图生成 ─────────────────────────────────
@blog_bp.route('/thumb')
def thumbnail():
    """动态生成图片缩略图并缓存到磁盘。

    参数：
        path - 图片相对路径（相对于 static/）
        w    - 目标宽度（px）

    特性：
        - 保持原格式（JPEG/PNG），不转 WebP（兼容性更好）
        - 磁盘缓存 + 版本号控制（升级时自动失效）
        - 出错时返回原始图片
    """
    path = request.args.get('path', '')
    w = request.args.get('w', 400, type=int)
    if not path:
        abort(404)
    from flask import current_app
    import mimetypes
    # 路径安全检查：禁止 ../ 遍历
    if '..' in path or path.startswith('/'):
        logger.warning('缩略图路径非法: %s', path)
        abort(404)
    img_path = os.path.join(current_app.root_path, 'static', path)
    if not os.path.isfile(img_path):
        logger.warning('缩略图不存在: %s', path)
        # 返回 1×1 透明 GIF
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

    # 缓存命中且未过时
    if os.path.isfile(cache_path):
        img_mtime = os.path.getmtime(img_path)
        cache_mtime = os.path.getmtime(cache_path)
        if cache_mtime >= img_mtime:
            with open(cache_path, 'rb') as f:
                return Response(f.read(),
                    mimetype=mimetypes.guess_type(cache_key)[0] or 'image/jpeg',
                    headers={'Cache-Control': 'public, max-age=2592000'}
                )
    # 生成缩略图
    try:
        from PIL import Image
        img = Image.open(img_path)
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
        logger.error('缩略图失败: %s w=%d error=%s', path, w, e)
        with open(img_path, 'rb') as f:
            return Response(f.read(),
                mimetype=mimetypes.guess_type(path)[0] or 'image/jpeg'
            )


# ── 缓存清理辅助函数 ──────────────────────────
_last_cache_cleanup = 0


def _cleanup_old_cache(cache_dir, current_ver):
    """清除旧版本的缩略图缓存。每小时最多执行一次。"""
    global _last_cache_cleanup
    now = time.time()
    if now - _last_cache_cleanup < 3600:
        return
    _last_cache_cleanup = now
    if not os.path.isdir(cache_dir):
        return
    for fname in os.listdir(cache_dir):
        if fname.startswith(current_ver + '_'):
            continue  # 当前版本保留
        if fname.startswith('v1_') or fname.startswith('v0_'):
            try:
                os.remove(os.path.join(cache_dir, fname))
            except Exception:
                pass


# ── 模板全局函数 ──────────────────────────────
@blog_bp.app_template_global()
def format_date(dt, fmt='%Y/%m/%d'):
    """模板中格式化日期。"""
    if dt:
        return dt.strftime(fmt)
    return ''
