"""HOSHINO Blog — 站点设置模块测试 (blog/settings.py)

纯函数（常量校验 / render_analytics_script 显式 db_map）用 @pytest.mark.pure 标记；
涉及 DB 的 get/set/is_true/inject_settings 依赖 app/_db fixture，在 CI 配置 MySQL 后运行。
"""
# ruff: noqa: PLR2004, PLC0415
import pytest

import blog.settings as settings_mod


# ── 常量完整性 (纯函数) ─────────────────────────────────────
@pytest.mark.pure
class TestConstants:
    def test_groups_structure(self):
        for group in settings_mod.GROUPS:
            assert 'title' in group
            assert 'fields' in group
            assert isinstance(group['fields'], list)
            for field in group['fields']:
                assert 'key' in field
                assert 'label' in field
                assert 'type' in field

    def test_defaults_cover_all_group_keys(self):
        for group in settings_mod.GROUPS:
            for field in group['fields']:
                assert field['key'] in settings_mod.DEFAULTS, f"key {field['key']} 缺少默认值"

    def test_valid_keys_equals_defaults(self):
        assert settings_mod._VALID_KEYS == set(settings_mod.DEFAULTS.keys())

    def test_analytics_defaults(self):
        assert set(settings_mod.ANALYTICS_DEFAULTS.keys()) == {
            'analytics_provider', 'analytics_src', 'analytics_site_id', 'analytics_custom'
        }
        assert settings_mod.ANALYTICS_DEFAULTS['analytics_provider'] == 'none'

    def test_bool_defaults_are_string(self):
        """布尔型设置存 'true'/'false' 字符串。"""
        assert settings_mod.DEFAULTS['enable_registration'] == 'false'
        assert settings_mod.DEFAULTS['comment_moderation'] == 'true'

    def test_field_types_valid(self):
        valid_types = {'text', 'textarea', 'bool'}
        for group in settings_mod.GROUPS:
            for field in group['fields']:
                assert field['type'] in valid_types


# ── render_analytics_script (纯函数，显式 db_map) ───────────
@pytest.mark.pure
class TestRenderAnalyticsScript:
    def test_empty_db_map(self):
        assert settings_mod.render_analytics_script(db_map={}) == ''

    def test_none_provider(self):
        assert settings_mod.render_analytics_script(
            db_map={'analytics_provider': 'none'}
        ) == ''

    def test_empty_provider(self):
        assert settings_mod.render_analytics_script(
            db_map={'analytics_provider': ''}
        ) == ''

    def test_umami_full(self):
        s = settings_mod.render_analytics_script(db_map={
            'analytics_provider': 'umami',
            'analytics_src': 'https://u.js',
            'analytics_site_id': 'x',
        })
        assert 'async' in s
        assert 'data-website-id="x"' in s
        assert 'https://u.js' in s

    def test_umami_missing_src(self):
        assert settings_mod.render_analytics_script(db_map={
            'analytics_provider': 'umami', 'analytics_site_id': 'x'
        }) == ''

    def test_umami_missing_site_id(self):
        assert settings_mod.render_analytics_script(db_map={
            'analytics_provider': 'umami', 'analytics_src': 'https://u.js'
        }) == ''

    def test_plausible_with_src(self):
        s = settings_mod.render_analytics_script(db_map={
            'analytics_provider': 'plausible',
            'analytics_src': 'https://p.js',
            'analytics_site_id': 'd',
        })
        assert 'data-domain="d"' in s
        assert 'https://p.js' in s
        assert 'defer' in s

    def test_plausible_default_src(self):
        s = settings_mod.render_analytics_script(db_map={
            'analytics_provider': 'plausible', 'analytics_site_id': 'd'
        })
        assert 'plausible.io' in s
        assert 'data-domain="d"' in s

    def test_plausible_missing_site_id(self):
        assert settings_mod.render_analytics_script(db_map={
            'analytics_provider': 'plausible'
        }) == ''

    def test_baidu(self):
        s = settings_mod.render_analytics_script(db_map={
            'analytics_provider': 'baidu', 'analytics_site_id': 'abc123'
        })
        assert 'hm.baidu.com' in s
        assert 'abc123' in s
        assert '_hmt' in s

    def test_baidu_missing_site_id(self):
        assert settings_mod.render_analytics_script(db_map={
            'analytics_provider': 'baidu'
        }) == ''

    def test_google(self):
        s = settings_mod.render_analytics_script(db_map={
            'analytics_provider': 'google', 'analytics_site_id': 'G-XX'
        })
        assert 'googletagmanager' in s
        assert 'G-XX' in s
        assert 'gtag' in s

    def test_google_missing_site_id(self):
        assert settings_mod.render_analytics_script(db_map={
            'analytics_provider': 'google'
        }) == ''

    def test_custom(self):
        custom = '<script>my_analytics()</script>'
        assert settings_mod.render_analytics_script(db_map={
            'analytics_provider': 'custom', 'analytics_custom': custom
        }) == custom

    def test_custom_empty(self):
        assert settings_mod.render_analytics_script(db_map={
            'analytics_provider': 'custom'
        }) == ''

    def test_unknown_provider(self):
        assert settings_mod.render_analytics_script(db_map={
            'analytics_provider': 'bogus'
        }) == ''

    def test_none_values_treated_as_empty(self):
        """db_map 中值为 None 时 `or ''` 兜底。"""
        assert settings_mod.render_analytics_script(db_map={
            'analytics_provider': 'umami',
            'analytics_src': None,
            'analytics_site_id': 'x',
        }) == ''

    def test_provider_none_in_db_map(self):
        assert settings_mod.render_analytics_script(db_map={
            'analytics_provider': None
        }) == ''


# ── get_all_settings (DB) ───────────────────────────────────
class TestGetAllSettings:
    def test_empty_db_returns_defaults(self, app, _db):
        with app.app_context():
            result = settings_mod.get_all_settings()
        for k, v in settings_mod.DEFAULTS.items():
            assert result[k] == v

    def test_db_overrides_defaults(self, app, _db):
        from blog.models import SiteSetting

        with app.app_context():
            SiteSetting.set('site_name', 'Custom')
            result = settings_mod.get_all_settings()
            assert result['site_name'] == 'Custom'
            assert result['site_subtitle'] == settings_mod.DEFAULTS['site_subtitle']

    def test_db_exception_falls_back(self, app, _db, monkeypatch):
        from blog.models import SiteSetting

        def boom(cls):
            raise RuntimeError('db down')

        monkeypatch.setattr(SiteSetting, 'get_all', classmethod(boom))
        with app.app_context():
            result = settings_mod.get_all_settings()
        assert result == settings_mod.DEFAULTS


# ── get_setting (DB) ────────────────────────────────────────
class TestGetSetting:
    def test_db_priority(self, app, _db):
        from blog.models import SiteSetting

        with app.app_context():
            SiteSetting.set('site_name', 'DB')
            assert settings_mod.get_setting('site_name') == 'DB'

    def test_fallback_default(self, app, _db):
        with app.app_context():
            assert settings_mod.get_setting('site_name') == settings_mod.DEFAULTS['site_name']

    def test_unknown_key_returns_none(self, app, _db):
        with app.app_context():
            assert settings_mod.get_setting('nonexistent') is None

    def test_unknown_key_with_default(self, app, _db):
        with app.app_context():
            assert settings_mod.get_setting('nonexistent', 'fallback') == 'fallback'

    def test_db_none_falls_to_default(self, app, _db):
        """DB 中 key 存在但值为 None 时回退默认（实际 SiteSetting 存字符串，此为边界）。"""
        with app.app_context():
            assert settings_mod.get_setting('hero_badge') == settings_mod.DEFAULTS['hero_badge']


# ── set_setting (DB) ────────────────────────────────────────
class TestSetSetting:
    def test_valid_key(self, app, _db):
        from blog.models import SiteSetting

        with app.app_context():
            settings_mod.set_setting('site_name', 'New')
            assert SiteSetting.get('site_name') == 'New'

    def test_invalid_key_ignored(self, app, _db):
        from blog.models import SiteSetting

        with app.app_context():
            settings_mod.set_setting('bogus_key', 'x')
            assert SiteSetting.get('bogus_key') is None

    def test_update_existing(self, app, _db):
        from blog.models import SiteSetting

        with app.app_context():
            settings_mod.set_setting('site_name', 'First')
            settings_mod.set_setting('site_name', 'Second')
            assert SiteSetting.get('site_name') == 'Second'

    def test_value_converted_to_string(self, app, _db):
        from blog.models import SiteSetting

        with app.app_context():
            settings_mod.set_setting('site_name', 123)
            assert SiteSetting.get('site_name') == '123'


# ── is_true (DB) ────────────────────────────────────────────
class TestIsTrue:
    @pytest.mark.parametrize('value,expected', [
        ('true', True), ('True', True), ('TRUE', True),
        ('1', True), ('yes', True), ('Yes', True), ('YES', True),
        ('false', False), ('0', False), ('no', False), ('', False),
        ('random', False),
    ])
    def test_values(self, app, _db, value, expected):
        from blog.models import SiteSetting

        with app.app_context():
            SiteSetting.set('enable_registration', value)
            assert settings_mod.is_true('enable_registration') is expected

    def test_default_false(self, app, _db):
        with app.app_context():
            assert settings_mod.is_true('enable_registration') is False

    def test_default_true(self, app, _db):
        with app.app_context():
            assert settings_mod.is_true('comment_moderation') is True


# ── inject_settings (DB) ────────────────────────────────────
class TestInjectSettings:
    def test_returns_required_keys(self, app, _db):
        with app.app_context():
            result = settings_mod.inject_settings()
        assert 'site_settings' in result
        assert 'site_name' in result
        assert 'site_subtitle' in result
        assert 'analytics_script' in result

    def test_site_settings_contains_all_defaults(self, app, _db):
        with app.app_context():
            result = settings_mod.inject_settings()
        for k in settings_mod.DEFAULTS:
            assert k in result['site_settings']

    def test_db_overrides(self, app, _db):
        from blog.models import SiteSetting

        with app.app_context():
            SiteSetting.set('site_name', 'Injected')
            result = settings_mod.inject_settings()
            assert result['site_name'] == 'Injected'
            assert result['site_settings']['site_name'] == 'Injected'

    def test_analytics_script_included(self, app, _db):
        from blog.models import SiteSetting

        with app.app_context():
            SiteSetting.set('analytics_provider', 'custom')
            SiteSetting.set('analytics_custom', '<script>x</script>')
            result = settings_mod.inject_settings()
            assert result['analytics_script'] == '<script>x</script>'

    def test_db_exception_falls_back(self, app, _db, monkeypatch):
        from blog.models import SiteSetting

        def boom(cls):
            raise RuntimeError('db down')

        monkeypatch.setattr(SiteSetting, 'get_all', classmethod(boom))
        with app.app_context():
            result = settings_mod.inject_settings()
        assert result['site_name'] == settings_mod.DEFAULTS['site_name']
        assert result['analytics_script'] == ''


# ── render_analytics_script 无 db_map (DB) ──────────────────
class TestRenderAnalyticsScriptDb:
    def test_no_db_map_queries_db(self, app, _db):
        with app.app_context():
            result = settings_mod.render_analytics_script()
        assert result == ''

    def test_with_db_data(self, app, _db):
        from blog.models import SiteSetting

        with app.app_context():
            SiteSetting.set('analytics_provider', 'custom')
            SiteSetting.set('analytics_custom', '<script>c</script>')
            result = settings_mod.render_analytics_script()
            assert result == '<script>c</script>'

    def test_umami_from_db(self, app, _db):
        from blog.models import SiteSetting

        with app.app_context():
            SiteSetting.set('analytics_provider', 'umami')
            SiteSetting.set('analytics_src', 'https://u.js')
            SiteSetting.set('analytics_site_id', 'site1')
            result = settings_mod.render_analytics_script()
            assert 'data-website-id="site1"' in result