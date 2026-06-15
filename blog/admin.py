# -*- coding: utf-8 -*-
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
"""
import os
import uuid
import datetime
import logging
from flask import render_template, request, redirect, url_for, abort, flash, jsonify, current_app
from flask_login import login_user, logout_user, login_required, current_user
from functools import wraps
from . import admin_bp
from .models import db, User, Category, Post, Comment
from .forms import LoginForm, PostForm, CategoryForm, UserForm, ProfileForm

logger = logging.getLogger(__name__)


# ── 缓存失效辅助函数 ─────────────────────────
def _invalidate_sidebar_cache():
    """使侧边栏和 RSS 缓存失效。

    在文章或分类发生变更时调用，确保前台能及时看到最新内容。
    """
    from .cache import cache_delete_pattern
    cache_delete_pattern('sidebar:*')
    cache_delete_pattern('rss:*')


# ═══════════════════════════════════════════════
# 权限控制装饰器
# ═══════════════════════════════════════════════
def admin_required(f):
    """装饰器：仅允许管理员访问。

    组合了 @login_required（必须登录）和 is_admin 检查。
    非管理员用户访问会返回 403 Forbidden。

    用法：
        @admin_bp.route('/posts')
        @admin_required
        def post_list():
            ...
    """
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


# ═══════════════════════════════════════════════
# 认证
# ═══════════════════════════════════════════════

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
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            return redirect(url_for('admin.dashboard'))
        flash('用户名或密码错误', 'error')
    return render_template('admin/login.html', form=form)


@admin_bp.route('/logout')
@login_required
def logout():
    """退出登录。

    清除当前用户的 session，重定向到前台首页。
    """
    logout_user()
    return redirect(url_for('blog.index'))


# ═══════════════════════════════════════════════
# 仪表盘
# ═══════════════════════════════════════════════

@admin_bp.route('/')
@admin_required
def dashboard():
    """管理后台首页：显示统计数据概览。

    统计数据缓存 60 秒（CACHE_TTL_DASHBOARD），
    避免每次刷新页面都查询数据库。

    展示：文章总数、已发布数、待审核评论数、用户数、
    最近 5 篇文章、最近 5 条待审核评论。

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
    recent_posts = Post.query.order_by(Post.created_at.desc()).limit(5).all()
    recent_comments = Comment.query.filter_by(is_approved=False).order_by(
        Comment.created_at.desc()).limit(5).all()

    stats = {
        'post_count': post_count,
        'published_count': published_count,
        'comment_count': comment_count,
        'user_count': user_count,
        'recent_posts': recent_posts,
        'recent_comments': recent_comments,
    }
    cache_set('dashboard:stats', stats, ttl)
    return render_template('admin/dashboard.html', **stats)


# ═══════════════════════════════════════════════
# 文章管理
# ═══════════════════════════════════════════════

@admin_bp.route('/posts')
@admin_required
def post_list():
    """文章列表页（分页，每页 20 条）。

    Template: admin/post-list.html
    """
    page = request.args.get('page', 1, type=int)
    posts = Post.query.order_by(Post.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    return render_template('admin/post-list.html', posts=posts)


@admin_bp.route('/posts/new', methods=['GET', 'POST'])
@admin_required
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
    form.categories.choices = [
        (c.id, c.name) for c in Category.query.order_by(Category.name).all()
    ]
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
        post = Post(
            title=form.title.data,
            slug=form.slug.data,
            summary=form.summary.data,
            content=form.content.data,
            cover_image=form.cover_image.data or '',
            author_id=current_user.id,       # 当前登录的管理员为作者
            is_published=form.is_published.data
        )
        # ── 多对多关联：设置分类 ─────────────
        post.categories = Category.query.filter(
            Category.id.in_(form.categories.data)
        ).all()
        db.session.add(post)
        db.session.commit()
        _invalidate_sidebar_cache()
        logger.info('创建文章: id=%d title="%s"', post.id, post.title)
        flash('文章已发布', 'success')
        return redirect(url_for('admin.post_list'))
    return render_template('admin/post-form.html', form=form, editing=False)


@admin_bp.route('/posts/<int:id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_post(id):
    """编辑文章。

    与 new_post 共用 PostForm，差别在于：
      - slug 唯一性检查要排除自身（Post.id != id）
      - 编辑时回填已有的分类选中状态

    Template: admin/post-form.html (editing=True)
    """
    post = Post.query.get_or_404(id)
    # obj=post 让表单自动填充现有字段值
    form = PostForm(obj=post)
    form.categories.choices = [
        (c.id, c.name) for c in Category.query.order_by(Category.name).all()
    ]
    if form.validate_on_submit():
        # ── slug 唯一性检查（排除自身） ─────
        existing = Post.query.filter(
            Post.slug == form.slug.data,
            Post.id != id
        ).first()
        if existing:
            flash('链接标识已被其他文章使用，请更换一个', 'error')
            return render_template('admin/post-form.html', form=form, editing=True, post=post)
        if len(form.categories.data) > 15:
            flash('最多选择15个分类', 'error')
            return render_template('admin/post-form.html', form=form, editing=True, post=post)
        # ── 更新字段 ────────────────────────
        post.title = form.title.data
        post.slug = form.slug.data
        post.summary = form.summary.data
        post.content = form.content.data
        post.cover_image = form.cover_image.data or ''
        post.is_published = form.is_published.data
        post.updated_at = datetime.datetime.utcnow()
        # ── 更新多对多分类关联 ───────────────
        post.categories = Category.query.filter(
            Category.id.in_(form.categories.data)
        ).all()
        db.session.commit()
        _invalidate_sidebar_cache()
        flash('文章已更新', 'success')
        return redirect(url_for('admin.post_list'))
    # ── 编辑时回填已选的分类 ─────────────────
    form.categories.data = [c.id for c in post.categories]
    return render_template('admin/post-form.html', form=form, editing=True, post=post)


@admin_bp.route('/posts/<int:id>/delete', methods=['POST'])
@admin_required
def delete_post(id):
    """删除文章（同时删除关联评论）。

    先删除所有关联的评论，再删除文章本身，
    避免数据库外键约束冲突。

    POST 请求（通过表单按钮触发），删除后重定向到文章列表。
    """
    post = Post.query.get_or_404(id)
    # 先删除关联评论，避免外键约束
    Comment.query.filter_by(post_id=post.id).delete()
    db.session.delete(post)
    db.session.commit()
    _invalidate_sidebar_cache()
    from .cache import cache_delete
    cache_delete('dashboard:stats')
    flash('文章已删除', 'success')
    return redirect(url_for('admin.post_list'))


# ═══════════════════════════════════════════════
# 分类管理
# ═══════════════════════════════════════════════

@admin_bp.route('/categories')
@admin_required
def category_list():
    """分类列表页。

    Template: admin/category-list.html
    """
    categories = Category.query.order_by(Category.name).all()
    return render_template('admin/category-list.html', categories=categories)


@admin_bp.route('/categories/new', methods=['GET', 'POST'])
@admin_required
def new_category():
    """新建分类。

    name 和 slug 都有唯一约束，不能重复。

    Template: admin/category-form.html (editing=False)
    """
    form = CategoryForm()
    if form.validate_on_submit():
        cat = Category(
            name=form.name.data,
            slug=form.slug.data,
            description=form.description.data
        )
        db.session.add(cat)
        db.session.commit()
        _invalidate_sidebar_cache()
        flash('分类已创建', 'success')
        return redirect(url_for('admin.category_list'))
    return render_template('admin/category-form.html', form=form, editing=False)


@admin_bp.route('/categories/<int:id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_category(id):
    """编辑分类。

    Template: admin/category-form.html (editing=True)
    """
    cat = Category.query.get_or_404(id)
    form = CategoryForm(obj=cat)
    if form.validate_on_submit():
        cat.name = form.name.data
        cat.slug = form.slug.data
        cat.description = form.description.data
        db.session.commit()
        _invalidate_sidebar_cache()
        flash('分类已更新', 'success')
        return redirect(url_for('admin.category_list'))
    return render_template('admin/category-form.html', form=form, editing=True, cat=cat)


@admin_bp.route('/categories/<int:id>/delete', methods=['POST'])
@admin_required
def delete_category(id):
    """删除分类。同时从所有文章中移除该分类（多对多关联）。

    删除前遍历所有包含此分类的文章，手动解除关联关系，
    确保多对多关联表也被清理。
    """
    cat = Category.query.get_or_404(id)
    # 遍历所有包含此分类的文章，解除关联
    for post in Post.query.filter(Post.categories.any(id=id)).all():
        post.categories = [c for c in post.categories if c.id != id]
    db.session.delete(cat)
    db.session.commit()
    _invalidate_sidebar_cache()
    flash('分类已删除', 'success')
    return redirect(url_for('admin.category_list'))


# ═══════════════════════════════════════════════
# 评论管理
# ═══════════════════════════════════════════════

@admin_bp.route('/comments')
@admin_required
def comment_list():
    """评论列表页。

    显示所有评论（含已审核和未审核），按时间倒序排列。

    Template: admin/comment-list.html
    """
    comments = Comment.query.order_by(Comment.created_at.desc()).all()
    return render_template('admin/comment-list.html', comments=comments)


@admin_bp.route('/comments/<int:id>/approve', methods=['POST'])
@admin_required
def approve_comment(id):
    """审核通过评论。

    将评论的 is_approved 设为 True，使其在前台可见。
    """
    comment = Comment.query.get_or_404(id)
    comment.is_approved = True
    db.session.commit()
    flash('评论已审核通过', 'success')
    return redirect(url_for('admin.comment_list'))


@admin_bp.route('/comments/<int:id>/delete', methods=['POST'])
@admin_required
def delete_comment(id):
    """删除评论。"""
    comment = Comment.query.get_or_404(id)
    db.session.delete(comment)
    db.session.commit()
    flash('评论已删除', 'success')
    return redirect(url_for('admin.comment_list'))


# ═══════════════════════════════════════════════
# 用户管理
# ═══════════════════════════════════════════════

@admin_bp.route('/users')
@admin_required
def user_list():
    """用户列表页。

    Template: admin/user-list.html
    """
    users = User.query.order_by(User.created_at.desc()).all()
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
        flash('用户已创建', 'success')
        return redirect(url_for('admin.user_list'))
    return render_template('admin/user-form.html', form=form, user=None)


@admin_bp.route('/users/<int:id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_user(id):
    """编辑用户信息。

    可修改用户名、邮箱、显示名、简介、管理员权限。
    密码字段为空时不修改密码。

    Template: admin/user-form.html (editing)
    """
    user = User.query.get_or_404(id)
    form = UserForm(obj=user)
    if form.validate_on_submit():
        user.username = form.username.data
        user.email = form.email.data
        user.display_name = form.display_name.data
        user.bio = form.bio.data
        user.is_admin = form.is_admin.data
        # 密码留空则不修改
        if form.password.data:
            user.set_password(form.password.data)
        db.session.commit()
        flash('用户已更新', 'success')
        return redirect(url_for('admin.user_list'))
    return render_template('admin/user-form.html', form=form, user=user)


@admin_bp.route('/users/<int:id>/delete', methods=['POST'])
@admin_required
def delete_user(id):
    """删除用户（不能删除自己，同时删除该用户的文章和评论）。

    安全限制：
      - 不能删除当前登录的管理员自己
      - 级联删除该用户的所有文章（以及文章的评论）
    """
    user = User.query.get_or_404(id)
    if user.id == current_user.id:
        flash('不能删除自己', 'error')
        return redirect(url_for('admin.user_list'))
    # 删除该用户的所有文章（及关联评论）
    for post in user.posts.all():
        Comment.query.filter_by(post_id=post.id).delete()
        db.session.delete(post)
    db.session.delete(user)
    db.session.commit()
    flash('用户已删除', 'success')
    return redirect(url_for('admin.user_list'))


# ═══════════════════════════════════════════════
# 个人资料
# ═══════════════════════════════════════════════

@admin_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """个人资料编辑页，支持头像上传。

    功能：
      - 修改显示名、简介
      - 上传新头像（自动缩放至 200px 宽，PNG/JPEG）
      - 修改邮箱（检查唯一性）
      - 修改密码（留空则不修改）

    注意：此路由使用 @login_required 而非 @admin_required，
    任何已登录用户均可编辑自己的资料。

    Template: admin/profile.html
    """
    form = ProfileForm(obj=current_user)
    if form.validate_on_submit():
        current_user.display_name = form.display_name.data
        current_user.bio = form.bio.data

        # ── 头像上传 ──────────────────────────
        if 'avatar' in request.files:
            file = request.files['avatar']
            if file and file.filename:
                # 判断文件扩展名
                ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'png'
                if ext in ('png', 'jpg', 'jpeg', 'gif', 'webp'):
                    from PIL import Image
                    import io as _io
                    img = Image.open(file)
                    # 缩放到 200px 宽（保持宽高比）
                    ratio = min(200 / img.width, 1.0)
                    if ratio < 1:
                        h = int(img.height * ratio)
                        img = img.resize((int(200), h), Image.LANCZOS)
                    buf = _io.BytesIO()
                    fmt = 'JPEG' if ext in ('jpg', 'jpeg') else 'PNG'
                    img.save(buf, fmt, quality=85, optimize=True)
                    buf.seek(0)
                    # 生成唯一文件名，避免覆盖
                    filename = 'avatar_' + str(uuid.uuid4()) + '.' + ext
                    from flask import current_app
                    upload_dir = os.path.join(current_app.root_path, 'static', 'uploads')
                    os.makedirs(upload_dir, exist_ok=True)
                    with open(os.path.join(upload_dir, filename), 'wb') as f:
                        f.write(buf.getvalue())
                    current_user.avatar = 'uploads/' + filename
                    logger.info('更新头像: user=%s new=%s', current_user.username, filename)

        # ── 邮箱：检查唯一性 ──────────────────
        if form.email.data and form.email.data != current_user.email:
            existing = User.query.filter_by(email=form.email.data).first()
            if existing:
                flash('邮箱已被占用', 'error')
                return render_template('admin/profile.html', form=form)
            current_user.email = form.email.data

        # ── 修改密码 ──────────────────────────
        if form.password.data:
            current_user.set_password(form.password.data)

        db.session.commit()
        flash('个人资料已更新', 'success')
        return redirect(url_for('admin.profile'))
    return render_template('admin/profile.html', form=form)


# ═══════════════════════════════════════════════
# 图片上传 API
# ═══════════════════════════════════════════════

@admin_bp.route('/upload-image', methods=['POST'])
@login_required
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
    # 校验文件扩展名
    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'png'
    if ext not in ('png', 'jpg', 'jpeg', 'gif', 'webp'):
        return jsonify({'error': '不支持的格式'}), 400
    # 使用 PIL 重新编码图片（统一质量控制）
    from PIL import Image
    import io as _io
    img = Image.open(file)
    buf = _io.BytesIO()
    img.save(buf, 'JPEG' if ext in ('jpg', 'jpeg') else 'PNG', quality=85, optimize=True)
    buf.seek(0)
    # 生成 UUID 文件名，避免路径冲突
    filename = str(uuid.uuid4()) + '.' + ext
    from flask import current_app
    upload_dir = os.path.join(current_app.root_path, 'static', 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    with open(os.path.join(upload_dir, filename), 'wb') as f:
        f.write(buf.getvalue())
    logger.info('图片上传: %s → uploads/%s (%dx%d, %dKB)',
                file.filename, filename, img.width, img.height, buf.tell() // 1024)
    url = url_for('static', filename='uploads/' + filename)
    return jsonify({'url': url})
