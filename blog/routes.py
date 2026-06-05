# -*- coding: utf-8 -*-
import datetime, os, io, logging
from flask import render_template, request, redirect, url_for, abort, jsonify, send_file
from . import blog_bp
from .models import db, Post, Category, Comment
from .forms import CommentForm

logger = logging.getLogger(__name__)


@blog_bp.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    category_slug = request.args.get('category', None)

    query = Post.query.filter_by(is_published=True)
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
    img_path = os.path.join(current_app.root_path, 'static', path.lstrip('/'))
    if not os.path.isfile(img_path):
        logger.warning('缩略图文件不存在: path=%s full=%s', path, img_path)
        # 使用默认占位图
        if 'avatar' in path:
            fallback = os.path.join(current_app.root_path, 'static', 'images', 'avatar', 'main-avatar.jpg')
        else:
            fallback = os.path.join(current_app.root_path, 'static', 'images', 'categories', 'category-item-1.jpg')
        if os.path.isfile(fallback):
            img_path = fallback
        else:
            abort(404)
    try:
        from PIL import Image
        img = Image.open(img_path)
        ratio = min(w / img.width, 1.0)
        new_w = int(img.width * ratio)
        new_h = int(img.height * ratio)
        if ratio < 1:
            img = img.resize((new_w, new_h), Image.LANCZOS)
        buf = io.BytesIO()
        ext = os.path.splitext(path)[1].lower()
        fmt = 'JPEG' if ext in ('.jpg', '.jpeg') else 'PNG' if ext == '.png' else 'WEBP'
        img.save(buf, fmt, quality=85, optimize=True)
        buf.seek(0)
        logger.debug('缩略图: path=%s w=%d %dx%d -> %dx%d', path, w, img.width, img.height, new_w, new_h)
        return send_file(buf, mimetype=f'image/{fmt.lower()}')
    except Exception as e:
        logger.error('缩略图生成失败: path=%s error=%s', path, str(e))
        abort(500)


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
