"""
HOSHINO Blog — 站点设置（运行时可改，存数据库，替代改源码）

配置项按分组定义，后台 /admin/settings 页面编辑。前台通过上下文处理器
注入 site_settings 字典 + site_name，模板用 {{ site_settings.xxx }} 读取。

布尔值存 'true'/'false' 字符串，用 is_true() 判断。
"""

from .models import SiteSetting, db

# ── 分组定义（供后台表单渲染）──────────────────
GROUPS = [
    {
        'title': '基本信息',
        'fields': [
            {'key': 'site_name', 'label': '站点名', 'type': 'text'},
            {'key': 'site_subtitle', 'label': '页头副标题', 'type': 'text'},
            {'key': 'meta_description', 'label': 'SEO 描述', 'type': 'text'},
        ],
    },
    {
        'title': '首页 Hero 区',
        'fields': [
            {'key': 'hero_badge', 'label': '徽标文字', 'type': 'text'},
            {'key': 'hero_title', 'label': '主标题（支持 HTML）', 'type': 'textarea'},
            {'key': 'hero_button1', 'label': '按钮1 文字', 'type': 'text'},
            {'key': 'hero_button2', 'label': '按钮2 文字', 'type': 'text'},
        ],
    },
    {
        'title': '交互开关',
        'fields': [
            {'key': 'enable_registration', 'label': '开放用户注册', 'type': 'bool'},
            {'key': 'comment_moderation', 'label': '评论需审核', 'type': 'bool'},
        ],
    },
    {
        'title': '自定义代码',
        'fields': [
            {'key': 'custom_css', 'label': '自定义 CSS（注入到全站 <head>）', 'type': 'textarea'},
            {'key': 'custom_js', 'label': '自定义 JS（注入到全站 </body> 前）', 'type': 'textarea'},
        ],
    },
]

# ── 默认值 ──────────────────────────────────────
DEFAULTS = {
    'site_name': 'Hoshino',
    'site_subtitle': '星野、参上！',
    'meta_description': 'Hoshino Blog',
    'hero_badge': '✦ 个人博客',
    'hero_title': '最喜欢<br><span class="highlight">小鸟游星野</span>',
    'hero_button1': '粒子散开',
    'hero_button2': '星尘迸发',
    'enable_registration': 'false',
    'comment_moderation': 'true',
    'custom_css': '',
    'custom_js': '',
}

# 所有合法 key（用于校验表单提交）
_VALID_KEYS = set(DEFAULTS.keys())


def get_all_settings():
    """返回合并后的设置字典（DB 值覆盖默认值）。"""
    result = dict(DEFAULTS)
    try:
        result.update(SiteSetting.get_all())
    except Exception:
        pass
    return result


def get_setting(key, default=None):
    """读取单项设置，DB 优先，回退默认值。"""
    val = SiteSetting.get(key, None)
    if val is not None:
        return val
    return DEFAULTS.get(key, default)


def set_setting(key, value):
    """写入单项设置（仅合法 key）。"""
    if key not in _VALID_KEYS:
        return
    SiteSetting.set(key, value)


def is_true(key):
    """判断布尔型设置是否为真。"""
    return get_setting(key, 'false').lower() in ('true', '1', 'yes')


# ── 访问统计 ──────────────────────────────────────
ANALYTICS_DEFAULTS = {
    'analytics_provider': 'none',  # none/umami/plausible/baidu/google/custom
    'analytics_src': '',
    'analytics_site_id': '',
    'analytics_custom': '',
}


def render_analytics_script(db_map=None):
    """根据配置生成统计脚本 HTML（注入到前台 <head>）。

    传入 db_map 可复用已查询的设置字典，避免重复查库。
    """
    if db_map is None:
        db_map = SiteSetting.get_all()
    provider = db_map.get('analytics_provider', ANALYTICS_DEFAULTS['analytics_provider']) or 'none'
    src = db_map.get('analytics_src', '') or ''
    site_id = db_map.get('analytics_site_id', '') or ''
    custom = db_map.get('analytics_custom', '') or ''
    if provider == 'umami' and src and site_id:
        return f'<script async src="{src}" data-website-id="{site_id}"></script>'
    if provider == 'plausible' and site_id:
        s = src or 'https://plausible.io/js/script.js'
        return f'<script defer data-domain="{site_id}" src="{s}"></script>'
    if provider == 'baidu' and site_id:
        return (
            '<script>var _hmt=_hmt||[];(function(){var hm=document.createElement("script");'
            f'hm.src="https://hm.baidu.com/hm.js?{site_id}";'
            'var s=document.getElementsByTagName("script")[0];s.parentNode.insertBefore(hm,s);})();</script>'
        )
    if provider == 'google' and site_id:
        return (
            f'<script async src="https://www.googletagmanager.com/gtag/js?id={site_id}"></script>'
            '<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}'
            f'gtag("js",new Date());gtag("config","{site_id}");</script>'
        )
    if provider == 'custom' and custom:
        return custom
    return ''


def inject_settings():
    """上下文处理器：注入 site_settings + site_name 到所有模板。

    单次请求只查一次 DB（SiteSetting.get_all），render_analytics_script 复用结果。
    DB 异常时回退默认值，不影响页面渲染。
    """
    try:
        all_db = SiteSetting.get_all()
    except Exception:
        all_db = {}
    settings = dict(DEFAULTS)
    settings.update(all_db)
    return {
        'site_settings': settings,
        'site_name': settings.get('site_name', 'Hoshino'),
        'site_subtitle': settings.get('site_subtitle', ''),
        'analytics_script': render_analytics_script(all_db),
    }