"""HOSHINO Blog — API 令牌发布博文接口测试 (blog/api.py)

纯函数（_SLUG_RE / _serialize_post / _can_edit / _validate_post_payload 无 DB 分支 /
_resolve_categories 错误分支 / token_required 无 Bearer 分支）用 @pytest.mark.pure 标记；
涉及 DB 的端点与查询依赖 app/_db fixture，在 CI 配置 MySQL 后运行。
"""
# ruff: noqa: PLR2004, PLC0415
import datetime
from unittest.mock import MagicMock

import pytest

import blog.api as api_mod


# ── _SLUG_RE (纯函数) ───────────────────────────────────────
@pytest.mark.pure
class TestSlugRegex:
    def test_valid_lowercase(self):
        assert api_mod._SLUG_RE.match('hello')

    def test_valid_with_digits(self):
        assert api_mod._SLUG_RE.match('hello123')

    def test_valid_with_hyphens(self):
        assert api_mod._SLUG_RE.match('hello-world')

    def test_valid_single_char(self):
        assert api_mod._SLUG_RE.match('a')

    def test_valid_all_digits(self):
        assert api_mod._SLUG_RE.match('123')

    def test_invalid_uppercase(self):
        assert not api_mod._SLUG_RE.match('Hello')

    def test_invalid_space(self):
        assert not api_mod._SLUG_RE.match('hello world')

    def test_invalid_underscore(self):
        assert not api_mod._SLUG_RE.match('hello_world')

    def test_invalid_empty(self):
        assert not api_mod._SLUG_RE.match('')

    def test_invalid_special_chars(self):
        assert not api_mod._SLUG_RE.match('hello.world')

    def test_invalid_leading_hyphen(self):
        # 连字符在字符类中允许，但 ^[a-z0-9\-]+$ 允许连字符在任何位置
        assert api_mod._SLUG_RE.match('-hello')


# ── _serialize_post (纯函数) ────────────────────────────────
@pytest.mark.pure
class TestSerializePost:
    def _make_post(self, **overrides):
        post = MagicMock()
        post.id = 1
        post.title = 'Title'
        post.slug = 'slug'
        post.summary = 'summary'
        post.content = 'content'
        post.cover_image = 'cover.jpg'
        post.html_content = '<p>html</p>'
        post.is_published = True
        post.author_id = 2
        cat = MagicMock()
        cat.id = 10
        cat.name = 'Tech'
        cat.slug = 'tech'
        post.categories = [cat]
        post.created_at = datetime.datetime(2024, 1, 1, 12, 0, 0)
        post.updated_at = datetime.datetime(2024, 1, 2, 12, 0, 0)
        for k, v in overrides.items():
            setattr(post, k, v)
        return post

    def test_full_post(self):
        result = api_mod._serialize_post(self._make_post())
        assert result['id'] == 1
        assert result['title'] == 'Title'
        assert result['slug'] == 'slug'
        assert result['summary'] == 'summary'
        assert result['content'] == 'content'
        assert result['cover_image'] == 'cover.jpg'
        assert result['html_content'] == '<p>html</p>'
        assert result['is_published'] is True
        assert result['author_id'] == 2
        assert result['categories'] == [{'id': 10, 'name': 'Tech', 'slug': 'tech'}]
        assert result['created_at'] == '2024-01-01T12:00:00'
        assert result['updated_at'] == '2024-01-02T12:00:00'

    def test_none_summary(self):
        result = api_mod._serialize_post(self._make_post(summary=None))
        assert result['summary'] == ''

    def test_none_content(self):
        result = api_mod._serialize_post(self._make_post(content=None))
        assert result['content'] == ''

    def test_none_cover(self):
        result = api_mod._serialize_post(self._make_post(cover_image=None))
        assert result['cover_image'] == ''

    def test_none_html(self):
        result = api_mod._serialize_post(self._make_post(html_content=None))
        assert result['html_content'] == ''

    def test_none_created_at(self):
        result = api_mod._serialize_post(self._make_post(created_at=None))
        assert result['created_at'] is None

    def test_none_updated_at(self):
        result = api_mod._serialize_post(self._make_post(updated_at=None))
        assert result['updated_at'] is None

    def test_empty_categories(self):
        result = api_mod._serialize_post(self._make_post(categories=[]))
        assert result['categories'] == []


# ── _can_edit (纯函数) ──────────────────────────────────────
@pytest.mark.pure
class TestCanEdit:
    def test_editor_can_edit_any(self):
        post = MagicMock(author_id=1)
        user = MagicMock(is_editor=True, id=99)
        assert api_mod._can_edit(post, user) is True

    def test_admin_can_edit_any(self):
        post = MagicMock(author_id=1)
        user = MagicMock(is_editor=True, id=99)
        assert api_mod._can_edit(post, user) is True

    def test_author_can_edit_own(self):
        post = MagicMock(author_id=1)
        user = MagicMock(is_editor=False, id=1)
        assert api_mod._can_edit(post, user) is True

    def test_author_cannot_edit_others(self):
        post = MagicMock(author_id=1)
        user = MagicMock(is_editor=False, id=2)
        assert api_mod._can_edit(post, user) is False


# ── _resolve_categories 错误分支 (纯函数) ───────────────────
@pytest.mark.pure
class TestResolveCategoriesPure:
    def test_none(self):
        cats, err = api_mod._resolve_categories(None)
        assert cats == []
        assert err is None

    def test_not_list_string(self):
        cats, err = api_mod._resolve_categories('x')
        assert cats is None
        assert err == 'categories 必须是数组'

    def test_not_list_int(self):
        cats, err = api_mod._resolve_categories(123)
        assert cats is None
        assert err == 'categories 必须是数组'

    def test_too_many(self):
        cats, err = api_mod._resolve_categories(list(range(api_mod._MAX_CATEGORIES + 1)))
        assert cats is None
        assert err == f'最多 {api_mod._MAX_CATEGORIES} 个分类'

    def test_bool_element(self):
        cats, err = api_mod._resolve_categories([True])
        assert cats is None
        assert '整数 id 或字符串 slug' in err

    def test_float_element(self):
        cats, err = api_mod._resolve_categories([1.5])
        assert cats is None
        assert '整数 id 或字符串 slug' in err

    def test_dict_element(self):
        cats, err = api_mod._resolve_categories([{'a': 1}])
        assert cats is None
        assert '整数 id 或字符串 slug' in err

    def test_none_element(self):
        cats, err = api_mod._resolve_categories([None])
        assert cats is None
        assert '整数 id 或字符串 slug' in err


# ── _validate_post_payload 无 DB 分支 (纯函数) ──────────────
@pytest.mark.pure
class TestValidatePostPayloadPure:
    def test_non_dict(self):
        _, err, code = api_mod._validate_post_payload('not a dict')
        assert code == 400
        assert err == '请求体必须是 JSON 对象'

    def test_non_dict_list(self):
        _, err, code = api_mod._validate_post_payload([1, 2])
        assert code == 400

    # ── title 校验 ──
    def test_create_missing_title(self):
        _, err, code = api_mod._validate_post_payload({'slug': 's'})
        assert code == 400
        assert 'title' in err

    def test_create_empty_title(self):
        _, err, code = api_mod._validate_post_payload({'title': '   ', 'slug': 's'})
        assert code == 400

    def test_title_not_string(self):
        _, err, code = api_mod._validate_post_payload({'title': 123, 'slug': 's'})
        assert code == 400

    def test_title_too_long(self):
        _, err, code = api_mod._validate_post_payload({'title': 'x' * 257, 'slug': 's'})
        assert code == 400

    def test_title_stripped(self):
        fields, err, _ = api_mod._validate_post_payload({'title': '  T  ', 'slug': 's'})
        assert err is None
        assert fields['title'] == 'T'

    # ── slug 校验 ──
    def test_create_missing_slug(self):
        _, err, code = api_mod._validate_post_payload({'title': 'T'})
        assert code == 400
        assert 'slug' in err

    def test_invalid_slug_uppercase(self):
        _, err, code = api_mod._validate_post_payload({'title': 'T', 'slug': 'Bad'})
        assert code == 400

    def test_invalid_slug_space(self):
        _, err, code = api_mod._validate_post_payload({'title': 'T', 'slug': 'bad slug'})
        assert code == 400

    def test_slug_too_long(self):
        _, err, code = api_mod._validate_post_payload({'title': 'T', 'slug': 'a' * 257})
        assert code == 400

    # ── content 校验 ──
    def test_content_too_long(self):
        _, err, code = api_mod._validate_post_payload({
            'title': 'T', 'slug': 's', 'content': 'x' * (api_mod._MAX_CONTENT_LEN + 1)
        })
        assert code == 400

    def test_content_bleached(self):
        fields, err, _ = api_mod._validate_post_payload({
            'title': 'T', 'slug': 's', 'content': '<script>x</script><strong>bold</strong>'
        })
        assert err is None
        assert '<script>' not in fields['content']
        assert '<strong>' in fields['content']

    def test_content_empty_string(self):
        fields, err, _ = api_mod._validate_post_payload({'title': 'T', 'slug': 's', 'content': ''})
        assert err is None
        assert fields['content'] == ''

    # ── cover / html / is_published ──
    def test_cover_truncated_to_512(self):
        fields, err, _ = api_mod._validate_post_payload({
            'title': 'T', 'slug': 's', 'cover_image': 'x' * 600
        })
        assert err is None
        assert len(fields['cover_image']) == 512

    def test_html_sanitized(self):
        fields, err, _ = api_mod._validate_post_payload({
            'title': 'T', 'slug': 's', 'html_content': '<script>alert(1)</script><p>ok</p>'
        })
        assert err is None
        assert '<script>' not in fields['html_content']

    def test_html_empty_string(self):
        fields, err, _ = api_mod._validate_post_payload({
            'title': 'T', 'slug': 's', 'html_content': ''
        })
        assert err is None
        assert fields['html_content'] == ''

    def test_is_published_truthy(self):
        fields, err, _ = api_mod._validate_post_payload({
            'title': 'T', 'slug': 's', 'is_published': 1
        })
        assert err is None
        assert fields['is_published'] is True

    def test_is_published_falsy(self):
        fields, err, _ = api_mod._validate_post_payload({
            'title': 'T', 'slug': 's', 'is_published': 0
        })
        assert err is None
        assert fields['is_published'] is False

    # ── create 默认值 ──
    def test_create_defaults(self):
        fields, err, code = api_mod._validate_post_payload({'title': 'T', 'slug': 's'})
        assert err is None
        assert code is None
        assert fields['summary'] == ''
        assert fields['content'] == ''
        assert fields['cover_image'] == ''
        assert fields['html_content'] == ''
        assert fields['is_published'] is False
        assert fields['categories'] == []

    def test_summary_provided(self):
        fields, err, _ = api_mod._validate_post_payload({
            'title': 'T', 'slug': 's', 'summary': 'my summary'
        })
        assert err is None
        assert fields['summary'] == 'my summary'

    # ── editing=True 部分更新 ──
    def test_editing_partial_title(self):
        fields, err, code = api_mod._validate_post_payload({'title': 'New'}, editing=True)
        assert err is None
        assert code is None
        assert fields['title'] == 'New'
        assert 'slug' not in fields
        assert fields['categories'] == []

    def test_editing_no_fields(self):
        fields, err, code = api_mod._validate_post_payload({}, editing=True)
        assert err is None
        assert fields == {'categories': []}

    def test_editing_keeps_provided_only(self):
        fields, err, _ = api_mod._validate_post_payload(
            {'summary': 'only summary'}, editing=True
        )
        assert err is None
        assert fields == {'summary': 'only summary', 'categories': []}

    # ── categories 错误分支（不查 DB）──
    def test_categories_not_list(self):
        _, err, code = api_mod._validate_post_payload({
            'title': 'T', 'slug': 's', 'categories': 'not a list'
        })
        assert code == 400

    def test_categories_too_many(self):
        _, err, code = api_mod._validate_post_payload({
            'title': 'T', 'slug': 's',
            'categories': list(range(api_mod._MAX_CATEGORIES + 1))
        })
        assert code == 400

    def test_categories_bool_element(self):
        _, err, code = api_mod._validate_post_payload({
            'title': 'T', 'slug': 's', 'categories': [True]
        })
        assert code == 400

    def test_categories_invalid_element(self):
        _, err, code = api_mod._validate_post_payload({
            'title': 'T', 'slug': 's', 'categories': [1.5]
        })
        assert code == 400

    def test_categories_none(self):
        fields, err, _ = api_mod._validate_post_payload({
            'title': 'T', 'slug': 's', 'categories': None
        })
        assert err is None
        assert fields['categories'] == []



# ── token_required 无 Bearer 分支 (纯函数) ──────────────────
@pytest.mark.pure
class TestTokenRequiredPure:
    def _make_app(self):
        from flask import Flask

        return Flask(__name__)

    def test_no_auth_header(self):
        app = self._make_app()

        @api_mod.token_required
        def view():
            return 'ok', 200

        with app.test_request_context('/x', headers={}):
            resp, code = view()
        assert code == 401
        assert resp.get_json()['ok'] is False

    def test_non_bearer_prefix(self):
        app = self._make_app()

        @api_mod.token_required
        def view():
            return 'ok', 200

        with app.test_request_context('/x', headers={'Authorization': 'Basic abc'}):
            resp, code = view()
        assert code == 401

    def test_bearer_empty_token(self):
        app = self._make_app()

        @api_mod.token_required
        def view():
            return 'ok', 200

        with app.test_request_context('/x', headers={'Authorization': 'Bearer '}):
            resp, code = view()
        assert code == 401

    def test_bearer_non_hsk_token(self):
        """令牌不以 hsk_ 开头，lookup 返回 None，不查 DB。"""
        app = self._make_app()

        @api_mod.token_required
        def view():
            return 'ok', 200

        with app.test_request_context('/x', headers={'Authorization': 'Bearer not-hsk-token'}):
            resp, code = view()
        assert code == 401
        assert '令牌无效' in resp.get_json()['error']


# ── DB 依赖 fixtures ────────────────────────────────────────
@pytest.fixture
def api_user_token(app, _db):
    """创建普通用户 + 有效令牌，返回 (raw_token, user_id)。"""
    from blog.models import ApiToken, User

    with app.app_context():
        user = User(username='apiuser', email='api@t.com', role='user', is_active=True)
        user.set_password('p')
        _db.session.add(user)
        _db.session.commit()
        raw, _token = ApiToken.generate(user.id, 'test-token')
        return raw, user.id


@pytest.fixture
def api_editor_token(app, _db):
    """创建编辑用户 + 有效令牌，返回 (raw_token, user_id)。"""
    from blog.models import ApiToken, User

    with app.app_context():
        user = User(username='editor', email='ed@t.com', role='editor', is_active=True)
        user.set_password('p')
        _db.session.add(user)
        _db.session.commit()
        raw, _token = ApiToken.generate(user.id, 'editor-token')
        return raw, user.id


def _auth(raw):
    return {'Authorization': f'Bearer {raw}'}


# ── _resolve_post (DB) ──────────────────────────────────────
class TestResolvePost:
    def test_by_id(self, app, _db):
        from blog.models import Post, User

        with app.app_context():
            u = User(username='rp', email='rp@t.com')
            u.set_password('p')
            _db.session.add(u)
            _db.session.commit()
            post = Post(title='T', slug='s', content='c', author_id=u.id)
            _db.session.add(post)
            _db.session.commit()
            pid = post.id
            found = api_mod._resolve_post(str(pid))
            assert found is not None
            assert found.id == pid

    def test_by_slug(self, app, _db):
        from blog.models import Post, User

        with app.app_context():
            u = User(username='rp2', email='rp2@t.com')
            u.set_password('p')
            _db.session.add(u)
            _db.session.commit()
            post = Post(title='T', slug='my-slug', content='c', author_id=u.id)
            _db.session.add(post)
            _db.session.commit()
            found = api_mod._resolve_post('my-slug')
            assert found is not None
            assert found.slug == 'my-slug'

    def test_not_found_id(self, app, _db):
        with app.app_context():
            assert api_mod._resolve_post('999999') is None

    def test_not_found_slug(self, app, _db):
        with app.app_context():
            assert api_mod._resolve_post('no-such-slug') is None


# ── _resolve_categories 成功分支 (DB) ───────────────────────
class TestResolveCategoriesDb:
    def test_by_ids(self, app, _db):
        from blog.models import Category

        with app.app_context():
            c1 = Category(name='A', slug='a')
            c2 = Category(name='B', slug='b')
            _db.session.add_all([c1, c2])
            _db.session.commit()
            cats, err = api_mod._resolve_categories([c1.id, c2.id])
            assert err is None
            assert len(cats) == 2

    def test_by_slugs(self, app, _db):
        from blog.models import Category

        with app.app_context():
            c = Category(name='Tech', slug='tech')
            _db.session.add(c)
            _db.session.commit()
            cats, err = api_mod._resolve_categories(['tech'])
            assert err is None
            assert len(cats) == 1
            assert cats[0].slug == 'tech'

    def test_mixed_ids_and_slugs(self, app, _db):
        from blog.models import Category

        with app.app_context():
            c1 = Category(name='A', slug='a')
            c2 = Category(name='B', slug='b')
            _db.session.add_all([c1, c2])
            _db.session.commit()
            cats, err = api_mod._resolve_categories([c1.id, 'b'])
            assert err is None
            assert len(cats) == 2

    def test_empty_list(self, app, _db):
        with app.app_context():
            cats, err = api_mod._resolve_categories([])
            assert err is None
            assert cats == []

    def test_nonexistent_id_returns_empty(self, app, _db):
        with app.app_context():
            cats, err = api_mod._resolve_categories([99999])
            assert err is None
            assert cats == []

    def test_dedup_ids(self, app, _db):
        from blog.models import Category

        with app.app_context():
            c = Category(name='A', slug='a')
            _db.session.add(c)
            _db.session.commit()
            cats, err = api_mod._resolve_categories([c.id, c.id])
            assert err is None
            assert len(cats) == 1


# ── _validate_post_payload 带 categories (DB) ───────────────
class TestValidatePostPayloadDb:
    def test_categories_empty_list(self, app, _db):
        with app.app_context():
            fields, err, _ = api_mod._validate_post_payload({
                'title': 'T', 'slug': 's', 'categories': []
            })
        assert err is None
        assert fields['categories'] == []

    def test_categories_by_ids(self, app, _db):
        from blog.models import Category

        with app.app_context():
            c = Category(name='A', slug='a')
            _db.session.add(c)
            _db.session.commit()
            fields, err, _ = api_mod._validate_post_payload({
                'title': 'T', 'slug': 's', 'categories': [c.id]
            })
            assert err is None
            assert len(fields['categories']) == 1

    def test_categories_by_slugs(self, app, _db):
        from blog.models import Category

        with app.app_context():
            _db.session.add(Category(name='Tech', slug='tech'))
            _db.session.commit()
            fields, err, _ = api_mod._validate_post_payload({
                'title': 'T', 'slug': 's', 'categories': ['tech']
            })
            assert err is None
            assert len(fields['categories']) == 1


# ── _after_post_change (DB) ─────────────────────────────────
class TestAfterPostChange:
    def test_silent_on_wordcloud_failure(self, app, _db):
        from blog.models import Post, User

        with app.app_context():
            u = User(username='wc', email='w@t.com')
            u.set_password('p')
            _db.session.add(u)
            _db.session.commit()
            post = Post(title='T', slug='s', content='c', author_id=u.id)
            _db.session.add(post)
            _db.session.commit()
            # 不应抛异常（wordcloud/缓存失败均被捕获）
            api_mod._after_post_change(post)


# ── 令牌认证 (DB) ───────────────────────────────────────────
class TestTokenAuth:
    def test_valid_token(self, app, _db, client, api_user_token):
        raw, _ = api_user_token
        rv = client.get('/api/v1/me', headers=_auth(raw))
        assert rv.status_code == 200

    def test_invalid_token(self, app, _db, client):
        rv = client.get('/api/v1/me', headers=_auth('hsk_invalid_token'))
        assert rv.status_code == 401

    def test_expired_token(self, app, _db, client, monkeypatch):
        from blog.models import ApiToken, User
        import blog.models as models_mod

        # 生产代码比较 token.expires_at（DB 读出为 naive）与 now_cst()（aware），
        # 混合 aware/naive 会 TypeError。monkey-patch 返回 naive 使比较一致。
        monkeypatch.setattr(
            models_mod, 'now_cst',
            lambda: datetime.datetime.now()
        )

        with app.app_context():
            u = User(username='exp', email='e@t.com', role='user', is_active=True)
            u.set_password('p')
            _db.session.add(u)
            _db.session.commit()
            expired = datetime.datetime.now() - datetime.timedelta(seconds=1)
            raw, _ = ApiToken.generate(u.id, 'exp', expires_at=expired)
        rv = client.get('/api/v1/me', headers=_auth(raw))
        assert rv.status_code == 401

    def test_inactive_user_token(self, app, _db, client):
        from blog.models import ApiToken, User

        with app.app_context():
            u = User(username='inactive', email='i@t.com', role='user', is_active=False)
            u.set_password('p')
            _db.session.add(u)
            _db.session.commit()
            raw, _ = ApiToken.generate(u.id, 't')
        rv = client.get('/api/v1/me', headers=_auth(raw))
        assert rv.status_code == 401


# ── whoami (DB) ─────────────────────────────────────────────
class TestWhoami:
    def test_returns_user_info(self, app, _db, client, api_user_token):
        raw, user_id = api_user_token
        rv = client.get('/api/v1/me', headers=_auth(raw))
        assert rv.status_code == 200
        data = rv.get_json()
        assert data['ok'] is True
        assert data['user']['id'] == user_id
        assert data['user']['username'] == 'apiuser'
        assert data['user']['role'] == 'user'
        assert data['user']['is_editor'] is False

    def test_display_name_fallback(self, app, _db, client):
        from blog.models import ApiToken, User

        with app.app_context():
            u = User(username='noname', email='n@t.com', role='user', is_active=True,
                     display_name='')
            u.set_password('p')
            _db.session.add(u)
            _db.session.commit()
            raw, _ = ApiToken.generate(u.id, 't')
        rv = client.get('/api/v1/me', headers=_auth(raw))
        assert rv.get_json()['user']['display_name'] == 'noname'


# ── list_posts (DB) ─────────────────────────────────────────
class TestListPosts:
    def test_empty_list(self, app, _db, client, api_user_token):
        raw, _ = api_user_token
        rv = client.get('/api/v1/posts', headers=_auth(raw))
        assert rv.status_code == 200
        data = rv.get_json()
        assert data['ok'] is True
        assert data['total'] == 0
        assert data['posts'] == []

    def test_lists_own_posts(self, app, _db, client, api_user_token):
        raw, _ = api_user_token
        client.post('/api/v1/posts', json={'title': 'P', 'slug': 'p', 'content': 'c'},
                    headers=_auth(raw))
        rv = client.get('/api/v1/posts', headers=_auth(raw))
        assert rv.get_json()['total'] == 1

    def test_pagination(self, app, _db, client, api_user_token):
        raw, _ = api_user_token
        for i in range(5):
            client.post('/api/v1/posts',
                        json={'title': f'P{i}', 'slug': f'p{i}', 'content': 'c'},
                        headers=_auth(raw))
        rv = client.get('/api/v1/posts?page=1&per_page=2', headers=_auth(raw))
        data = rv.get_json()
        assert data['total'] == 5
        assert len(data['posts']) == 2
        assert data['page'] == 1
        assert data['per_page'] == 2

    def test_per_page_capped_100(self, app, _db, client, api_user_token):
        raw, _ = api_user_token
        rv = client.get('/api/v1/posts?per_page=999', headers=_auth(raw))
        assert rv.get_json()['per_page'] == 100

    def test_status_filter_published(self, app, _db, client, api_user_token):
        raw, _ = api_user_token
        client.post('/api/v1/posts',
                    json={'title': 'D', 'slug': 'd', 'content': 'c', 'is_published': False},
                    headers=_auth(raw))
        client.post('/api/v1/posts',
                    json={'title': 'P', 'slug': 'p', 'content': 'c', 'is_published': True},
                    headers=_auth(raw))
        rv = client.get('/api/v1/posts?status=published', headers=_auth(raw))
        assert rv.get_json()['total'] == 1

    def test_status_filter_draft(self, app, _db, client, api_user_token):
        raw, _ = api_user_token
        client.post('/api/v1/posts',
                    json={'title': 'D', 'slug': 'd', 'content': 'c', 'is_published': False},
                    headers=_auth(raw))
        client.post('/api/v1/posts',
                    json={'title': 'P', 'slug': 'p', 'content': 'c', 'is_published': True},
                    headers=_auth(raw))
        rv = client.get('/api/v1/posts?status=draft', headers=_auth(raw))
        assert rv.get_json()['total'] == 1

    def test_search_query(self, app, _db, client, api_user_token):
        raw, _ = api_user_token
        client.post('/api/v1/posts',
                    json={'title': 'Python Guide', 'slug': 'py', 'content': 'c'},
                    headers=_auth(raw))
        client.post('/api/v1/posts',
                    json={'title': 'Other', 'slug': 'ot', 'content': 'c'},
                    headers=_auth(raw))
        rv = client.get('/api/v1/posts?q=Python', headers=_auth(raw))
        assert rv.get_json()['total'] == 1


# ── get_post (DB) ───────────────────────────────────────────
class TestGetPost:
    def test_by_id(self, app, _db, client, api_user_token):
        raw, _ = api_user_token
        rv = client.post('/api/v1/posts',
                         json={'title': 'P', 'slug': 'p1', 'content': 'c'},
                         headers=_auth(raw))
        post_id = rv.get_json()['post']['id']
        rv2 = client.get(f'/api/v1/posts/{post_id}', headers=_auth(raw))
        assert rv2.status_code == 200
        assert rv2.get_json()['post']['id'] == post_id

    def test_by_slug(self, app, _db, client, api_user_token):
        raw, _ = api_user_token
        client.post('/api/v1/posts',
                    json={'title': 'P', 'slug': 'my-slug', 'content': 'c'},
                    headers=_auth(raw))
        rv = client.get('/api/v1/posts/my-slug', headers=_auth(raw))
        assert rv.status_code == 200
        assert rv.get_json()['post']['slug'] == 'my-slug'

    def test_not_found(self, app, _db, client, api_user_token):
        raw, _ = api_user_token
        rv = client.get('/api/v1/posts/999999', headers=_auth(raw))
        assert rv.status_code == 404

    def test_non_author_cannot_view_others(self, app, _db, client):
        """普通用户不能查看他人的文章（返回 404 而非 403，避免泄露存在性）。"""
        from blog.models import ApiToken, User

        with app.app_context():
            a = User(username='owner', email='o@t.com', role='user', is_active=True)
            a.set_password('p')
            b = User(username='viewer', email='v@t.com', role='user', is_active=True)
            b.set_password('p')
            _db.session.add_all([a, b])
            _db.session.commit()
            raw_a, _ = ApiToken.generate(a.id, 'ta')
            raw_b, _ = ApiToken.generate(b.id, 'tb')
        rv = client.post('/api/v1/posts',
                         json={'title': 'Private', 'slug': 'priv', 'content': 'c'},
                         headers=_auth(raw_a))
        post_id = rv.get_json()['post']['id']
        rv2 = client.get(f'/api/v1/posts/{post_id}', headers=_auth(raw_b))
        assert rv2.status_code == 404

    def test_editor_can_view_others(self, app, _db, client, api_user_token, api_editor_token):
        raw_author, _ = api_user_token
        raw_editor, _ = api_editor_token
        rv = client.post('/api/v1/posts',
                         json={'title': 'P', 'slug': 'shared', 'content': 'c'},
                         headers=_auth(raw_author))
        post_id = rv.get_json()['post']['id']
        rv2 = client.get(f'/api/v1/posts/{post_id}', headers=_auth(raw_editor))
        assert rv2.status_code == 200


# ── create_post (DB) ────────────────────────────────────────
class TestCreatePost:
    def test_success(self, app, _db, client, api_user_token):
        raw, user_id = api_user_token
        rv = client.post('/api/v1/posts', json={
            'title': 'Test Post', 'slug': 'test-post', 'content': '# Hello',
        }, headers=_auth(raw))
        assert rv.status_code == 201
        data = rv.get_json()
        assert data['ok'] is True
        assert data['post']['title'] == 'Test Post'
        assert data['post']['slug'] == 'test-post'
        assert data['post']['author_id'] == user_id
        assert data['post']['is_published'] is False

    def test_with_categories(self, app, _db, client, api_user_token):
        from blog.models import Category

        raw, _ = api_user_token
        with app.app_context():
            c = Category(name='Tech', slug='tech')
            _db.session.add(c)
            _db.session.commit()
            cid = c.id
        rv = client.post('/api/v1/posts', json={
            'title': 'P', 'slug': 'p', 'content': 'c', 'categories': [cid]
        }, headers=_auth(raw))
        assert rv.status_code == 201
        cats = rv.get_json()['post']['categories']
        assert len(cats) == 1
        assert cats[0]['slug'] == 'tech'

    def test_with_category_slugs(self, app, _db, client, api_user_token):
        from blog.models import Category

        raw, _ = api_user_token
        with app.app_context():
            _db.session.add(Category(name='Life', slug='life'))
            _db.session.commit()
        rv = client.post('/api/v1/posts', json={
            'title': 'P', 'slug': 'p', 'content': 'c', 'categories': ['life']
        }, headers=_auth(raw))
        assert rv.status_code == 201
        assert len(rv.get_json()['post']['categories']) == 1

    def test_missing_title(self, app, _db, client, api_user_token):
        raw, _ = api_user_token
        rv = client.post('/api/v1/posts', json={'slug': 's'}, headers=_auth(raw))
        assert rv.status_code == 400

    def test_missing_slug(self, app, _db, client, api_user_token):
        raw, _ = api_user_token
        rv = client.post('/api/v1/posts', json={'title': 'T'}, headers=_auth(raw))
        assert rv.status_code == 400

    def test_duplicate_slug(self, app, _db, client, api_user_token):
        raw, _ = api_user_token
        client.post('/api/v1/posts',
                    json={'title': 'P', 'slug': 'dup', 'content': 'c'},
                    headers=_auth(raw))
        rv = client.post('/api/v1/posts',
                         json={'title': 'P2', 'slug': 'dup', 'content': 'c'},
                         headers=_auth(raw))
        assert rv.status_code == 409

    def test_invalid_slug(self, app, _db, client, api_user_token):
        raw, _ = api_user_token
        rv = client.post('/api/v1/posts',
                         json={'title': 'T', 'slug': 'Invalid Slug', 'content': 'c'},
                         headers=_auth(raw))
        assert rv.status_code == 400

    def test_published_flag(self, app, _db, client, api_user_token):
        raw, _ = api_user_token
        rv = client.post('/api/v1/posts', json={
            'title': 'P', 'slug': 'pub', 'content': 'c', 'is_published': True
        }, headers=_auth(raw))
        assert rv.get_json()['post']['is_published'] is True

    def test_non_dict_body(self, app, _db, client, api_user_token):
        raw, _ = api_user_token
        rv = client.post('/api/v1/posts', json=[1, 2], headers=_auth(raw))
        assert rv.status_code == 400


# ── update_post (DB) ────────────────────────────────────────
class TestUpdatePost:
    def test_update_title(self, app, _db, client, api_user_token):
        raw, _ = api_user_token
        rv = client.post('/api/v1/posts',
                         json={'title': 'P', 'slug': 'up', 'content': 'c'},
                         headers=_auth(raw))
        post_id = rv.get_json()['post']['id']
        rv2 = client.put(f'/api/v1/posts/{post_id}', json={'title': 'Updated'},
                         headers=_auth(raw))
        assert rv2.status_code == 200
        assert rv2.get_json()['post']['title'] == 'Updated'

    def test_update_slug(self, app, _db, client, api_user_token):
        raw, _ = api_user_token
        rv = client.post('/api/v1/posts',
                         json={'title': 'P', 'slug': 'old-slug', 'content': 'c'},
                         headers=_auth(raw))
        post_id = rv.get_json()['post']['id']
        rv2 = client.put(f'/api/v1/posts/{post_id}', json={'slug': 'new-slug'},
                         headers=_auth(raw))
        assert rv2.status_code == 200
        assert rv2.get_json()['post']['slug'] == 'new-slug'

    def test_update_slug_conflict(self, app, _db, client, api_user_token):
        raw, _ = api_user_token
        client.post('/api/v1/posts',
                    json={'title': 'A', 'slug': 'slug-a', 'content': 'c'},
                    headers=_auth(raw))
        rv = client.post('/api/v1/posts',
                         json={'title': 'B', 'slug': 'slug-b', 'content': 'c'},
                         headers=_auth(raw))
        post_id = rv.get_json()['post']['id']
        rv2 = client.put(f'/api/v1/posts/{post_id}', json={'slug': 'slug-a'},
                         headers=_auth(raw))
        assert rv2.status_code == 409

    def test_update_not_found(self, app, _db, client, api_user_token):
        raw, _ = api_user_token
        rv = client.put('/api/v1/posts/999999', json={'title': 'X'},
                        headers=_auth(raw))
        assert rv.status_code == 404

    def test_non_author_cannot_edit(self, app, _db, client):
        from blog.models import ApiToken, User

        with app.app_context():
            a = User(username='auth', email='a@t.com', role='user', is_active=True)
            a.set_password('p')
            b = User(username='intruder', email='b@t.com', role='user', is_active=True)
            b.set_password('p')
            _db.session.add_all([a, b])
            _db.session.commit()
            raw_a, _ = ApiToken.generate(a.id, 'ta')
            raw_b, _ = ApiToken.generate(b.id, 'tb')
        rv = client.post('/api/v1/posts',
                         json={'title': 'A post', 'slug': 'a-post', 'content': 'c'},
                         headers=_auth(raw_a))
        post_id = rv.get_json()['post']['id']
        rv2 = client.put(f'/api/v1/posts/{post_id}', json={'title': 'hacked'},
                         headers=_auth(raw_b))
        assert rv2.status_code == 403

    def test_editor_can_edit_others(self, app, _db, client, api_user_token, api_editor_token):
        raw_author, _ = api_user_token
        raw_editor, _ = api_editor_token
        rv = client.post('/api/v1/posts',
                         json={'title': 'P', 'slug': 'ed', 'content': 'c'},
                         headers=_auth(raw_author))
        post_id = rv.get_json()['post']['id']
        rv2 = client.put(f'/api/v1/posts/{post_id}', json={'title': 'Editor Updated'},
                         headers=_auth(raw_editor))
        assert rv2.status_code == 200

    def test_update_partial_no_fields(self, app, _db, client, api_user_token):
        raw, _ = api_user_token
        rv = client.post('/api/v1/posts',
                         json={'title': 'P', 'slug': 'p', 'content': 'c'},
                         headers=_auth(raw))
        post_id = rv.get_json()['post']['id']
        rv2 = client.put(f'/api/v1/posts/{post_id}', json={},
                         headers=_auth(raw))
        assert rv2.status_code == 200


# ── list_categories (DB) ────────────────────────────────────
class TestListCategories:
    def test_empty(self, app, _db, client, api_user_token):
        raw, _ = api_user_token
        rv = client.get('/api/v1/categories', headers=_auth(raw))
        assert rv.status_code == 200
        assert rv.get_json()['categories'] == []

    def test_returns_categories(self, app, _db, client, api_user_token):
        from blog.models import Category

        raw, _ = api_user_token
        with app.app_context():
            _db.session.add(Category(name='Tech', slug='tech'))
            _db.session.add(Category(name='Life', slug='life'))
            _db.session.commit()
        rv = client.get('/api/v1/categories', headers=_auth(raw))
        data = rv.get_json()
        assert data['ok'] is True
        slugs = {c['slug'] for c in data['categories']}
        assert {'tech', 'life'} <= slugs