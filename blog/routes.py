# -*- coding: utf-8 -*-
import datetime, os, io, logging
from flask import render_template, request, redirect, url_for, abort, jsonify, send_file, Response
from . import blog_bp
from .models import db, Post, Category, Comment
from .forms import CommentForm

logger = logging.getLogger(__name__)


@blog_bp.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    category_slug = request.args.get('category', None)

    query = Post.query.options(db.joinedload(Post.author)).filter_by(is_published=True)
    if category_slug:
        cat = Category.query.filter_by(slug=category_slug).first_or_404()
        query = query.filter_by(category_id=cat.id)

    posts = query.order_by(Post.created_at.desc()).paginate(
        page=page, per_page=6, error_out=False
    )
    categories = Category.query.order_by(Category.name).all()
    recent_posts = Post.query.filter_by(is_published=True).order_by(
        Post.created_at.desc()).limit(4).all()

    return render_template('index.html',
        posts=posts,
        categories=categories,
        recent_posts=recent_posts,
        current_category=category_slug,
        now=datetime.datetime.now
    )


@blog_bp.route('/post/<slug>')
def single_post(slug):
    post = Post.query.filter_by(slug=slug, is_published=True).first_or_404()
    categories = Category.query.order_by(Category.name).all()
    recent_posts = Post.query.filter_by(is_published=True).order_by(
        Post.created_at.desc()).limit(4).all()
    form = CommentForm()

    if form.validate_on_submit():
        comment = Comment(
            post_id=post.id,
            author_name=form.author_name.data,
            author_email=form.author_email.data,
            content=form.content.data,
            is_approved=False  # Requires admin approval
        )
        db.session.add(comment)
        db.session.commit()
        return redirect(url_for('blog.single_post', slug=slug) + '#comments')

    return render_template('single-post.html',
        post=post,
        categories=categories,
        recent_posts=recent_posts,
        form=form
    )


@blog_bp.route('/category/<slug>')
def category(slug):
    cat = Category.query.filter_by(slug=slug).first_or_404()
    page = request.args.get('page', 1, type=int)
    posts = Post.query.filter_by(
        category_id=cat.id, is_published=True
    ).order_by(Post.created_at.desc()).paginate(
        page=page, per_page=6, error_out=False
    )
    categories = Category.query.order_by(Category.name).all()
    recent_posts = Post.query.filter_by(is_published=True).order_by(
        Post.created_at.desc()).limit(4).all()

    return render_template('category-grid.html',
        category=cat,
        posts=posts,
        categories=categories,
        recent_posts=recent_posts
    )


@blog_bp.route('/about')
def about():
    categories = Category.query.order_by(Category.name).all()
    recent_posts = Post.query.filter_by(is_published=True).order_by(
        Post.created_at.desc()).limit(4).all()
    return render_template('about.html', categories=categories, recent_posts=recent_posts)


@blog_bp.route('/contact', methods=['GET', 'POST'])
def contact():
    categories = Category.query.order_by(Category.name).all()
    recent_posts = Post.query.filter_by(is_published=True).order_by(
        Post.created_at.desc()).limit(4).all()
    message_sent = False

    if request.method == 'POST':
        # Basic contact form handling
        name = request.form.get('name', '')
        email = request.form.get('email', '')
        message = request.form.get('message', '')
        if name and email and message:
            # In production: send email here
            message_sent = True

    return render_template('contact.html',
        categories=categories,
        recent_posts=recent_posts,
        message_sent=message_sent
    )


@blog_bp.route('/search')
def search():
    q = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)

    if not q:
        return redirect(url_for('blog.index'))

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
        page=page, per_page=6, error_out=False
    )

    return render_template('index.html',
        posts=results,
        categories=categories,
        recent_posts=recent_posts,
        search_query=q,
        current_category=None
    )


@blog_bp.route('/feed.xml')
def rss_feed():
    posts = Post.query.filter_by(is_published=True).order_by(
        Post.created_at.desc()).limit(20).all()
    from flask import make_response
    response = make_response(render_template('rss.xml', posts=posts))
    response.headers['Content-Type'] = 'application/xml; charset=utf-8'
    return response


@blog_bp.route('/thumb')
def thumbnail():
    path = request.args.get('path', '')
    w = request.args.get('w', 400, type=int)
    if not path:
        abort(404)
    from flask import current_app
    import mimetypes
    img_path = os.path.join(current_app.root_path, 'static', path.lstrip('/'))
    
    if not os.path.isfile(img_path):
        logger.warning('缩略图文件不存在: path=%s full=%s', path, img_path)
        abort(404)
    
    # 缩略图缓存（使用原格式，避免 WebP 兼容问题）
    ext = os.path.splitext(path)[1].lower() or '.jpg'
    cache_key = f'{path.replace("/","_")}_{w}{ext}'
    cache_dir = os.path.join(current_app.root_path, 'static', '.thumb_cache')
    cache_path = os.path.join(cache_dir, cache_key)
    os.makedirs(cache_dir, exist_ok=True)
    
    # 缓存命中
    if os.path.isfile(cache_path):
        img_mtime = os.path.getmtime(img_path)
        cache_mtime = os.path.getmtime(cache_path)
        if cache_mtime >= img_mtime:
            with open(cache_path, 'rb') as f:
                return Response(f.read(), mimetype=mimetypes.guess_type(cache_key)[0] or 'image/jpeg',
                              headers={'Cache-Control': 'public, max-age=2592000'})
    
    try:
        from PIL import Image
        img = Image.open(img_path)
        ratio = min(w / img.width, 1.0)
        if ratio < 1:
            new_w = int(img.width * ratio)
            new_h = int(img.height * ratio)
            img = img.resize((new_w, new_h), Image.LANCZOS)
        # 保持原格式（不用 WebP，Windows 兼容更好）
        fmt = 'JPEG' if ext in ('.jpg', '.jpeg') else 'PNG'
        img.save(cache_path, fmt, quality=85, optimize=True)
        with open(cache_path, 'rb') as f:
            return Response(f.read(), mimetype=mimetypes.guess_type(cache_key)[0] or 'image/jpeg',
                          headers={'Cache-Control': 'public, max-age=2592000'})
    except Exception as e:
        logger.error('缩略图失败: path=%s w=%d error=%s', path, w, str(e), exc_info=True)
        # 出错时返回原始图片
        with open(img_path, 'rb') as f:
            return Response(f.read(), mimetype=mimetypes.guess_type(path)[0] or 'image/jpeg')


@blog_bp.app_template_global()
def format_date(dt, fmt='%B %d, %Y'):
    if dt:
        return dt.strftime(fmt)
    return ''


@blog_bp.app_template_global()
def truncate_text(text, length=200):
    if not text:
        return ''
    if len(text) <= length:
        return text
    return text[:length].rsplit(' ', 1)[0] + '...'
