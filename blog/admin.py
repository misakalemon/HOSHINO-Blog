import datetime, os, uuid, logging
from flask import render_template, redirect, url_for, request, flash, abort, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from . import admin_bp
from .models import db, User, Post, Category, Comment
from .forms import LoginForm, PostForm, CategoryForm, UserForm, ProfileForm

logger = logging.getLogger(__name__)


@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data) and user.is_active:
            login_user(user)
            next_page = request.args.get('next')
            logger.info('管理员登录成功: username=%s ip=%s', form.username.data, request.remote_addr)
            return redirect(next_page or url_for('admin.dashboard'))
        logger.warning('管理员登录失败: username=%s ip=%s', form.username.data, request.remote_addr)
        flash('\u7528\u6237\u540d\u6216\u5bc6\u7801\u9519\u8bef', 'error')
    return render_template('login.html', form=form)


@admin_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('blog.index'))


@admin_bp.route('/')
@login_required
def dashboard():
    post_count = Post.query.count()
    published_count = Post.query.filter_by(is_published=True).count()
    comment_count = Comment.query.filter_by(is_approved=False).count()
    user_count = User.query.count()
    recent_posts = Post.query.order_by(Post.created_at.desc()).limit(5).all()
    recent_comments = Comment.query.filter_by(is_approved=False).order_by(
        Comment.created_at.desc()).limit(5).all()
    return render_template('admin/dashboard.html',
        post_count=post_count,
        published_count=published_count,
        comment_count=comment_count,
        user_count=user_count,
        recent_posts=recent_posts,
        recent_comments=recent_comments
    )


# ===== Posts =====

@admin_bp.route('/posts')
@login_required
def post_list():
    page = request.args.get('page', 1, type=int)
    posts = Post.query.order_by(Post.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False)
    return render_template('admin/post-list.html', posts=posts)


@admin_bp.route('/posts/new', methods=['GET', 'POST'])
@login_required
def new_post():
    form = PostForm()
    form.category.choices = [(0, '\u65e0')] + [
        (c.id, c.name) for c in Category.query.order_by(Category.name).all()]
    if form.validate_on_submit():
        # 检查 slug 是否已存在
        existing = Post.query.filter_by(slug=form.slug.data).first()
        if existing:
            flash('\u94fe\u63a5\u6807\u8bc6\u5df2\u88ab\u5176\u4ed6\u6587\u7ae0\u4f7f\u7528\uFF0C\u8bf7\u66f4\u6362\u4e00\u4e2a', 'error')
            return render_template('admin/post-form.html', form=form, editing=False)
        post = Post(
            title=form.title.data,
            slug=form.slug.data,
            summary=form.summary.data,
            content=form.content.data,
            cover_image=form.cover_image.data or '',
            category_id=form.category.data if form.category.data > 0 else None,
            author_id=current_user.id,
            is_published=form.is_published.data
        )
        db.session.add(post)
        db.session.commit()
        logger.info('创建文章: id=%d title="%s" slug=%s author=%s', post.id, post.title, post.slug, current_user.username)
        flash('\u6587\u7ae0\u5df2\u53d1\u5e03', 'success')
        return redirect(url_for('admin.post_list'))
    return render_template('admin/post-form.html', form=form, editing=False)


@admin_bp.route('/posts/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_post(id):
    post = Post.query.get_or_404(id)
    form = PostForm(obj=post)
    form.category.choices = [(0, '\u65e0')] + [
        (c.id, c.name) for c in Category.query.order_by(Category.name).all()]
    if form.validate_on_submit():
        post.title = form.title.data
        post.slug = form.slug.data
        post.summary = form.summary.data
        post.content = form.content.data
        post.cover_image = form.cover_image.data or ''
        post.category_id = form.category.data if form.category.data > 0 else None
        post.is_published = form.is_published.data
        post.updated_at = datetime.datetime.utcnow()
        db.session.commit()
        flash('\u6587\u7ae0\u5df2\u66f4\u65b0', 'success')
        return redirect(url_for('admin.post_list'))
    form.category.data = post.category_id or 0
    return render_template('admin/post-form.html', form=form, editing=True, post=post)


@admin_bp.route('/posts/<int:id>/delete', methods=['POST'])
@login_required
def delete_post(id):
    post = Post.query.get_or_404(id)
    db.session.delete(post)
    db.session.commit()
    flash('\u6587\u7ae0\u5df2\u5220\u9664', 'success')
    return redirect(url_for('admin.post_list'))


# ===== Categories =====

@admin_bp.route('/categories')
@login_required
def category_list():
    categories = Category.query.order_by(Category.name).all()
    return render_template('admin/category-list.html', categories=categories)


@admin_bp.route('/categories/new', methods=['GET', 'POST'])
@login_required
def new_category():
    form = CategoryForm()
    if form.validate_on_submit():
        cat = Category(name=form.name.data, slug=form.slug.data,
                       description=form.description.data)
        db.session.add(cat)
        db.session.commit()
        flash('\u5206\u7c7b\u5df2\u521b\u5efa', 'success')
        return redirect(url_for('admin.category_list'))
    return render_template('admin/category-form.html', form=form, editing=False)


@admin_bp.route('/categories/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_category(id):
    cat = Category.query.get_or_404(id)
    form = CategoryForm(obj=cat)
    if form.validate_on_submit():
        cat.name = form.name.data
        cat.slug = form.slug.data
        cat.description = form.description.data
        db.session.commit()
        flash('\u5206\u7c7b\u5df2\u66f4\u65b0', 'success')
        return redirect(url_for('admin.category_list'))
    return render_template('admin/category-form.html', form=form, editing=True, cat=cat)


@admin_bp.route('/categories/<int:id>/delete', methods=['POST'])
@login_required
def delete_category(id):
    cat = Category.query.get_or_404(id)
    # Set posts to uncategorized
    Post.query.filter_by(category_id=id).update({'category_id': None})
    db.session.delete(cat)
    db.session.commit()
    flash('\u5206\u7c7b\u5df2\u5220\u9664', 'success')
    return redirect(url_for('admin.category_list'))


# ===== Comments =====

@admin_bp.route('/comments')
@login_required
def comment_list():
    pending = Comment.query.filter_by(is_approved=False).order_by(
        Comment.created_at.desc()).all()
    approved = Comment.query.filter_by(is_approved=True).order_by(
        Comment.created_at.desc()).all()
    return render_template('admin/comment-list.html', pending=pending, approved=approved)


@admin_bp.route('/comments/<int:id>/approve', methods=['POST'])
@login_required
def approve_comment(id):
    comment = Comment.query.get_or_404(id)
    comment.is_approved = True
    db.session.commit()
    flash('\u8bc4\u8bba\u5df2\u901a\u8fc7', 'success')
    return redirect(url_for('admin.comment_list'))


@admin_bp.route('/comments/<int:id>/delete', methods=['POST'])
@login_required
def delete_comment(id):
    comment = Comment.query.get_or_404(id)
    db.session.delete(comment)
    db.session.commit()
    flash('\u8bc4\u8bba\u5df2\u5220\u9664', 'success')
    return redirect(url_for('admin.comment_list'))


# ===== Users =====

@admin_bp.route('/users')
@login_required
def user_list():
    if not current_user.is_admin:
        abort(403)
    users = User.query.order_by(User.created_at).all()
    return render_template('admin/user-list.html', users=users)


@admin_bp.route('/users/new', methods=['GET', 'POST'])
@login_required
def new_user():
    if not current_user.is_admin:
        abort(403)
    form = UserForm()
    if form.validate_on_submit():
        if User.query.filter_by(username=form.username.data).first():
            flash('\u7528\u6237\u540d\u5df2\u5b58\u5728', 'error')
            return render_template('admin/user-form.html', form=form, editing=False)
        user = User(
            username=form.username.data,
            email=form.email.data,
            display_name=form.display_name.data,
            bio=form.bio.data,
            is_admin=form.is_admin.data
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('\u7528\u6237\u5df2\u521b\u5efa', 'success')
        return redirect(url_for('admin.user_list'))
    return render_template('admin/user-form.html', form=form, editing=False)


# ===== Profile =====

@admin_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    form = ProfileForm(obj=current_user)
    if form.validate_on_submit():
        current_user.display_name = form.display_name.data
        current_user.bio = form.bio.data
        # 头像上传
        if 'avatar' in request.files:
            file = request.files['avatar']
            if file and file.filename:
                ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'png'
                if ext in ('png', 'jpg', 'jpeg', 'gif', 'webp'):
                    from PIL import Image
                    import io as _io
                    img = Image.open(file)
                    # 头像缩放到 200px 宽
                    ratio = min(200 / img.width, 1.0)
                    if ratio < 1:
                        new_w = int(img.width * ratio)
                        new_h = int(img.height * ratio)
                        img = img.resize((new_w, new_h), Image.LANCZOS)
                    buf = _io.BytesIO()
                    fmt = 'JPEG' if ext in ('jpg', 'jpeg') else 'PNG'
                    img.save(buf, fmt, quality=85, optimize=True)
                    buf.seek(0)
                    filename = 'avatar_' + str(uuid.uuid4()) + '.' + ext
                    from flask import current_app
                    upload_dir = os.path.join(current_app.root_path, 'static', 'uploads')
                    os.makedirs(upload_dir, exist_ok=True)
                    with open(os.path.join(upload_dir, filename), 'wb') as f:
                        f.write(buf.getvalue())
                    old_avatar = current_user.avatar
                    current_user.avatar = 'uploads/' + filename
                    logger.info('更新头像: user=%s old=%s new=%s (%dx%d, %dKB)', current_user.username, old_avatar, current_user.avatar, img.width, img.height, buf.tell()//1024)
        # 邮箱：有修改时才更新，并检查唯一性
        if form.email.data and form.email.data != current_user.email:
            existing = User.query.filter_by(email=form.email.data).first()
            if existing:
                logger.warning('邮箱已被占用: user=%s email=%s', current_user.username, form.email.data)
                return render_template('admin/profile.html', form=form)
            current_user.email = form.email.data
        if form.password.data:
            current_user.set_password(form.password.data)
        db.session.commit()
        flash('\u4e2a\u4eba\u8d44\u6599\u5df2\u66f4\u65b0', 'success')
        return redirect(url_for('admin.profile'))
    return render_template('admin/profile.html', form=form)


# ===== Image Upload =====

@admin_bp.route('/upload-image', methods=['POST'])
@login_required
def upload_image():
    if 'image' not in request.files:
        return jsonify({'error': '未选择文件'}), 400
    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': '未选择文件'}), 400
    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'png'
    if ext not in ('png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'):
        return jsonify({'error': '不支持的图片格式'}), 400
    
    from PIL import Image
    import io as _io
    # 读取图片并压缩
    img = Image.open(file)
    # 限制最大尺寸（宽1920，高1080），保持宽高比
    max_w, max_h = 1920, 1080
    if img.width > max_w or img.height > max_h:
        ratio = min(max_w / img.width, max_h / img.height, 1.0)
        new_w = int(img.width * ratio)
        new_h = int(img.height * ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)
    
    # 保存到 BytesIO 再写入磁盘
    buf = _io.BytesIO()
    fmt = 'JPEG' if ext in ('jpg', 'jpeg') else 'PNG'
    if ext == 'webp': fmt = 'WEBP'
    if ext == 'gif': fmt = 'GIF'
    img.save(buf, fmt, quality=85, optimize=True)
    buf.seek(0)
    
    filename = str(uuid.uuid4()) + '.' + ext
    from flask import current_app
    upload_dir = os.path.join(current_app.root_path, 'static', 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    with open(os.path.join(upload_dir, filename), 'wb') as f:
        f.write(buf.getvalue())
    
    logger.info('图片上传: %s → uploads/%s (%dx%d, %dKB)', file.filename, filename, img.width, img.height, buf.tell()//1024)
    url = url_for('static', filename='uploads/' + filename)
    return jsonify({'url': url})
