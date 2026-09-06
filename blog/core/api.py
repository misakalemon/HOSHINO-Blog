"""
HOSHINO Blog — 外部 API 蓝图（供 AI agent 等程序化客户端发布/编辑博文）

认证方式：HTTP 头 Authorization: Bearer <令牌>
令牌在后台 /admin/tokens 页面申请，绑定到某个后台用户，
拥有该用户在后台的博文操作权限（创建/编辑自己的文章，编辑/管理员可编辑任何文章）。

端点：
  GET    /api/v1/posts              — 文章列表（分页 + 模糊搜索）
  GET    /api/v1/posts/<id_or_slug> — 文章详情
  POST   /api/v1/posts              — 创建文章
  PUT    /api/v1/posts/<id_or_slug> — 编辑文章
  DELETE /api/v1/posts/<id_or_slug> — 删除文章

安全：
  - 本蓝图已豁免 CSRF（程序化客户端无 session）
  - 正文经 bleach 白名单过滤（与后台一致）
  - HTML 源码经 _sanitize_html 净化（与后台一致）
  - 令牌仅存哈希，明文仅创建时返回一次
"""

import logging
import re
from functools import wraps

import bleach
from flask import Blueprint, abort, g, jsonify, request

from .admin import _invalidate_sidebar_cache, _sanitize_html
from .models import ApiToken, Category, Post, User, db
from .routes import ALLOWED_ATTRS, ALLOWED_TAGS
from .utils import now_cst

logger = logging.getLogger(__name__)

api_bp = Blueprint('api', __name__, url_prefix='/api/v1')

_SLUG_RE = re.compile(r'^[a-z0-9\-]+$')
_MAX_CATEGORIES = 15
_MAX_CONTENT_LEN = 500000


# ═══════════════════════════════════════════════
# 令牌认证
# ═══════════════════════════════════════════════
def token_required(f):
    """装饰器：从 Authorization: Bearer <token> 头认证令牌。

    认证成功后将令牌对应的 User 挂到 g.token_user，令牌对象挂到 g.api_token。
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return jsonify({'ok': False, 'error': '缺少有效的 Authorization 头'}), 401
        raw = auth[len('Bearer '):].strip()
        token = ApiToken.lookup(raw)
        if token is None:
            return jsonify({'ok': False, 'error': '令牌无效或已过期'}), 401
        user = db.session.get(User, token.user_id)
        if user is None or not user.is_active:
            return jsonify({'ok': False, 'error': '令牌所属用户不可用'}), 401
        g.api_token = token
        g.token_user = user
        try:
            token.touch()
        except Exception:
            db.session.rollback()
        return f(*args, **kwargs)

    return decorated


# ═══════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════
def _resolve_post(id_or_slug):
    """按 id（纯数字）或 slug 定位文章，找不到返回 None。"""
    if id_or_slug.isdigit():
        return db.session.get(Post, int(id_or_slug))
    return Post.query.filter_by(slug=id_or_slug).first()


def _resolve_categories(raw):
    """把 categories 字段解析为 Category 对象列表。

    支持三种形式：
      - 整数列表 [1, 2, 3]  → 按 id 查询
      - 字符串列表 ["tech", "Agent"] → 先按 slug 查，未命中再按 name 查
    混合时按元素类型分别处理。返回 (categories, error_msg)。
    """
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return None, 'categories 必须是数组'
    if len(raw) > _MAX_CATEGORIES:
        return None, f'最多 {_MAX_CATEGORIES} 个分类'
    ids, names = set(), set()
    for item in raw:
        if isinstance(item, bool):
            return None, '分类元素必须是整数 id 或字符串 slug/name'
        if isinstance(item, int):
            ids.add(item)
        elif isinstance(item, str):
            names.add(item)
        else:
            return None, '分类元素必须是整数 id 或字符串 slug/name'
    query = Category.query
    cats = []
    if ids:
        cats.extend(query.filter(Category.id.in_(ids)).all())
    if names:
        by_slug = {c.slug: c for c in query.filter(Category.slug.in_(names)).all()}
        matched_slugs = set(by_slug.keys())
        remaining = names - matched_slugs
        cats.extend(by_slug.values())
        if remaining:
            by_name = {c.name: c for c in query.filter(Category.name.in_(remaining)).all()}
            cats.extend(by_name.values())
    return cats, None


def _validate_post_payload(data, editing=False):
    """校验并规范化文章字段。返回 (fields, error_msg, status_code)。

    editing=True 时允许部分字段缺省（保留原值）。
    """
    if not isinstance(data, dict):
        return None, '请求体必须是 JSON 对象', 400

    fields = {}

    title = data.get('title')
    if title is not None:
        if not isinstance(title, str) or not title.strip():
            return None, 'title 不能为空', 422
        if len(title) > 256:
            return None, 'title 最长 256 字符', 422
        fields['title'] = title.strip()
    elif not editing:
        return None, 'title 必填', 422

    slug = data.get('slug')
    if slug is not None:
        if not isinstance(slug, str) or not _SLUG_RE.match(slug):
            return None, 'slug 只允许小写字母、数字和连字符', 422
        if len(slug) > 256:
            return None, 'slug 最长 256 字符', 422
        fields['slug'] = slug
    elif not editing:
        return None, 'slug 必填', 422

    summary = data.get('summary')
    if summary is not None:
        fields['summary'] = str(summary)
    elif not editing:
        fields['summary'] = ''

    content = data.get('content')
    if content is not None:
        content = str(content)
        if len(content) > _MAX_CONTENT_LEN:
            return None, f'content 最长 {_MAX_CONTENT_LEN} 字符', 422
        fields['content'] = bleach.clean(content or '', tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS)
    elif not editing:
        fields['content'] = ''

    cover = data.get('cover_image')
    if cover is not None:
        fields['cover_image'] = str(cover)[:512]
    elif not editing:
        fields['cover_image'] = ''

    html_content = data.get('html_content')
    if html_content is not None:
        fields['html_content'] = _sanitize_html(str(html_content))
    elif not editing:
        fields['html_content'] = ''

    if 'is_published' in data:
        fields['is_published'] = bool(data['is_published'])
    elif not editing:
        fields['is_published'] = False

    if 'is_top' in data:
        fields['is_top'] = bool(data['is_top'])
    elif not editing:
        fields['is_top'] = False

    cats, err = _resolve_categories(data.get('categories'))
    if err:
        return None, err, 422
    fields['categories'] = cats

    return fields, None, None


def _serialize_post(post):
    """把 Post 序列化为 JSON 可返回的字典。"""
    from flask import url_for
    try:
        post_url = url_for('blog.post', slug=post.slug, _external=True)
    except Exception:
        post_url = None
    content_text = post.content or ''
    return {
        'id': post.id,
        'title': post.title,
        'slug': post.slug,
        'summary': post.summary or '',
        'content': content_text,
        'word_count': len(content_text),
        'cover_image': post.cover_image or '',
        'html_content': post.html_content or '',
        'is_published': post.is_published,
        'is_top': post.is_top,
        'author_id': post.author_id,
        'categories': [{'id': c.id, 'name': c.name, 'slug': c.slug} for c in post.categories],
        'created_at': post.created_at.isoformat() if post.created_at else None,
        'updated_at': post.updated_at.isoformat() if post.updated_at else None,
        'url': post_url,
    }


def _can_edit(post, user):
    """是否有权编辑该文章：作者只能编辑自己的，编辑/管理员可编辑任何文章。"""
    return user.is_editor or post.author_id == user.id


def _after_post_change(post):
    """文章变更后的副作用：清缓存 + 投递词云任务。"""
    _invalidate_sidebar_cache()
    try:
        from ..wordcloud.generator import submit_task
        submit_task('post', post_id=post.id)
    except Exception:
        logger.warning('词云任务投递失败，已忽略', exc_info=True)


# ═══════════════════════════════════════════════
# 文章 API
# ═══════════════════════════════════════════════
@api_bp.route('/posts', methods=['GET'])
@token_required
def list_posts():
    """文章列表（分页）。

    查询参数：
      page     — 页码，默认 1
      per_page — 每页数量，默认 20，最大 100
      status   — all/published/draft，默认 all（仅返回当前令牌用户可见范围）
      q        — 标题/摘要模糊搜索
    """
    user = g.token_user
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(100, max(1, request.args.get('per_page', 20, type=int)))
    status = request.args.get('status', 'all')
    q = (request.args.get('q') or '').strip()

    query = Post.query
    if not user.is_editor:
        query = query.filter_by(author_id=user.id)
    if status == 'published':
        query = query.filter_by(is_published=True)
    elif status == 'draft':
        query = query.filter_by(is_published=False)
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(Post.title.like(like), Post.summary.like(like)))

    total = query.count()
    items = (
        query.order_by(Post.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return jsonify({
        'ok': True,
        'total': total,
        'page': page,
        'per_page': per_page,
        'posts': [_serialize_post(p) for p in items],
    })


@api_bp.route('/posts/<id_or_slug>', methods=['GET'])
@token_required
def get_post(id_or_slug):
    """文章详情。非编辑/管理员只能查看自己的文章。"""
    post = _resolve_post(id_or_slug)
    if post is None:
        return jsonify({'ok': False, 'error': '文章不存在'}), 404
    if not g.token_user.is_editor and post.author_id != g.token_user.id:
        return jsonify({'ok': False, 'error': '文章不存在'}), 404
    return jsonify({'ok': True, 'post': _serialize_post(post)})


@api_bp.route('/posts', methods=['POST'])
@token_required
def create_post():
    """创建文章。

    请求体 JSON：
      title        — 必填，标题
      slug         — 必填，URL 标识（^[a-z0-9\\-]+$）
      content      — Markdown 正文
      summary      — 摘要
      cover_image  — 封面图 URL
      html_content — 自定义 HTML 源码
      categories   — 分类数组（整数 id 或字符串 slug）
      is_published — 是否发布（默认 false）
    """
    fields, err, code = _validate_post_payload(request.get_json(silent=True) or {}, editing=False)
    if err:
        return jsonify({'ok': False, 'error': err}), code

    if Post.query.filter_by(slug=fields['slug']).first():
        return jsonify({'ok': False, 'error': 'slug 已被其他文章使用'}), 409

    post = Post(
        title=fields['title'],
        slug=fields['slug'],
        summary=fields['summary'],
        content=fields['content'],
        cover_image=fields['cover_image'],
        html_content=fields['html_content'],
        html_file_url='',
        author_id=g.token_user.id,
        is_published=fields['is_published'],
        is_top=fields['is_top'],
    )
    post.categories = fields['categories']
    db.session.add(post)
    db.session.commit()
    _after_post_change(post)
    logger.info('API 创建文章: id=%d title="%s" by user=%d', post.id, post.title, g.token_user.id)
    return jsonify({'ok': True, 'post': _serialize_post(post)}), 201


@api_bp.route('/posts/<id_or_slug>', methods=['PUT'])
@token_required
def update_post(id_or_slug):
    """编辑文章。仅提供需要修改的字段即可。

    权限：作者只能编辑自己的文章，编辑/管理员可编辑任何文章。
    """
    post = _resolve_post(id_or_slug)
    if post is None:
        return jsonify({'ok': False, 'error': '文章不存在'}), 404
    if not _can_edit(post, g.token_user):
        return jsonify({'ok': False, 'error': '无权编辑该文章'}), 403

    fields, err, code = _validate_post_payload(request.get_json(silent=True) or {}, editing=True)
    if err:
        return jsonify({'ok': False, 'error': err}), code

    if 'slug' in fields and fields['slug'] != post.slug:
        existing = Post.query.filter(Post.slug == fields['slug'], Post.id != post.id).first()
        if existing:
            return jsonify({'ok': False, 'error': 'slug 已被其他文章使用'}), 409

    for key in ('title', 'slug', 'summary', 'content', 'cover_image', 'html_content', 'is_published', 'is_top'):
        if key in fields:
            setattr(post, key, fields[key])
    if 'categories' in fields:
        post.categories = fields['categories']
    post.updated_at = now_cst()
    db.session.commit()
    _after_post_change(post)
    logger.info('API 更新文章: id=%d title="%s" by user=%d', post.id, post.title, g.token_user.id)
    return jsonify({'ok': True, 'post': _serialize_post(post)})


@api_bp.route('/posts/<id_or_slug>', methods=['DELETE'])
@token_required
def delete_post(id_or_slug):
    """删除文章。

    权限：作者只能删除自己的文章，编辑/管理员可删除任何文章。
    删除会级联清除关联评论和分类关联（由外键 ON DELETE CASCADE 保证）。
    """
    post = _resolve_post(id_or_slug)
    if post is None:
        return jsonify({'ok': False, 'error': '文章不存在'}), 404
    if not _can_edit(post, g.token_user):
        return jsonify({'ok': False, 'error': '无权删除该文章'}), 403

    post_id, post_title = post.id, post.title
    db.session.delete(post)
    db.session.commit()
    _invalidate_sidebar_cache()
    try:
        from .cache import cache_delete_pattern
        cache_delete_pattern('page:post:*')
    except Exception:
        pass
    logger.info('API 删除文章: id=%d title="%s" by user=%d', post_id, post_title, g.token_user.id)
    return jsonify({'ok': True, 'deleted': True, 'id': post_id})


@api_bp.route('/categories', methods=['GET'])
@token_required
def list_categories():
    """分类列表（便于 AI agent 查询可用分类 id/slug）。"""
    cats = Category.query.order_by(Category.name).all()
    return jsonify({
        'ok': True,
        'categories': [{'id': c.id, 'name': c.name, 'slug': c.slug} for c in cats],
    })


@api_bp.route('/me', methods=['GET'])
@token_required
def whoami():
    """返回令牌对应的用户信息，便于客户端校验令牌有效性。"""
    user = g.token_user
    return jsonify({
        'ok': True,
        'user': {
            'id': user.id,
            'username': user.username,
            'display_name': user.display_name or user.username,
            'role': user.role,
            'is_editor': user.is_editor,
            'is_admin': user.is_admin,
        },
    })