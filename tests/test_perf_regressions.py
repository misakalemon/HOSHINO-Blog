"""性能相关回归测试（2026-09 全项目审计批次 C）

覆盖三类"改了容易被改回去"的性能契约：

  1. 历史快照关系不得用 ``lazy='joined'``（会把父表整行随每条快照重复传输，
     视频历史可达数千条，父表含 MEDIUMTEXT）
  2. 索引声明必须与迁移 DDL 一致（模型加了索引但旧库没有 = 白加）
  3. 词云配置在热路径必须走进程级缓存（否则一轮全量预计算数万次 SELECT）
"""

import ast
import importlib.util
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

pytestmark = pytest.mark.pure


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding='utf-8')


def _relationships(src: str) -> dict:
    """提取 {类名.属性名: lazy 值}（AST 精确，注释与 docstring 不计）。"""
    result = {}
    for cls in [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ClassDef)]:
        for stmt in cls.body:
            if not (isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call)):
                continue
            fn = stmt.value.func
            if not (isinstance(fn, ast.Attribute) and fn.attr == 'relationship'):
                continue
            target = stmt.targets[0].id if isinstance(stmt.targets[0], ast.Name) else '?'
            lazy = None
            for kw in stmt.value.keywords:
                if kw.arg == 'lazy' and isinstance(kw.value, ast.Constant):
                    lazy = kw.value.value
            result[f'{cls.name}.{target}'] = lazy
    return result


# ── 1. 历史快照关系必须惰性加载 ──────────────────────────
def test_history_relationships_are_lazy_select():
    rels = _relationships(_read('blog/core/models.py'))
    assert rels.get('BiliUpHistory.up') == 'select', (
        "BiliUpHistory.up 应为 lazy='select'：粉丝曲线只用本行数值列，"
        'JOIN 会把父表整行随每条快照重复传输'
    )
    assert rels.get('BiliVideoHistory.video') == 'select', (
        "BiliVideoHistory.video 应为 lazy='select'：视频历史可达数千条，"
        'JOIN 会重复携带父表 MEDIUMTEXT 字段'
    )


def test_no_new_joined_on_history_models():
    """防止将来又把 joined 加回历史表（明确保留白名单：短视频表数据量小）。"""
    rels = _relationships(_read('blog/core/models.py'))
    joined = {k: v for k, v in rels.items() if v == 'joined'}
    assert set(joined) <= {'BiliWatchedVideo.video'}, f'新增了 joined 关系: {joined}'


# ── 2. 索引声明与迁移 DDL 必须一致 ───────────────────────
@pytest.mark.parametrize(
    'index_name, ddl_fragment',
    [
        ('ix_bili_video_up_pubdate',
         'CREATE INDEX ix_bili_video_up_pubdate ON bili_videos (up_id, pubdate)'),
        ('ix_comments_post_approved',
         'CREATE INDEX ix_comments_post_approved ON comments (post_id, is_approved)'),
    ],
)
def test_index_declared_in_model_and_migration(index_name, ddl_fragment):
    models_src = _read('blog/core/models.py')
    init_src = _read('blog/__init__.py')
    assert f"'{index_name}'" in models_src, f'模型未声明索引 {index_name}'
    assert ddl_fragment in init_src, f'迁移未创建索引 {index_name}（旧库不会生效）'


def test_migration_checks_comments_indexes():
    """迁移必须把 comments 的既有索引纳入存在性检查，避免重复创建报错。"""
    assert "inspector.get_indexes('comments')" in _read('blog/__init__.py')


# ── 3. 词云配置热路径必须走缓存 ──────────────────────────
def test_wordcloud_config_direct_calls_only_inside_cache():
    """generator 内直接调用 WordCloudConfig.get_or_create() 只允许缓存函数内一处。"""
    src = _read('blog/wordcloud/generator.py')
    calls = [
        node
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == 'get_or_create'
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == 'WordCloudConfig'
    ]
    assert len(calls) == 1, (
        f'generator 内有 {len(calls)} 处直接 get_or_create 调用；'
        '热路径应使用 get_wordcloud_config()（进程级 TTL 缓存）'
    )


@pytest.mark.parametrize(
    'rel, expected',
    [('blog/core/routes.py', 2), ('blog/bilibili/public_routes.py', 3)],
)
def test_web_pages_use_cached_config(rel, expected):
    src = _read(rel)
    assert src.count('get_wordcloud_config().to_dict()') == expected
    assert 'WordCloudConfig.get_or_create().to_dict()' not in src


def test_admin_invalidates_config_cache_on_save():
    assert 'invalidate_wordcloud_config_cache()' in _read('blog/core/admin.py')


# ── 4. 缓存视图行为（直接加载模块，绕开 blog 包导入）─────
@pytest.fixture(scope='module')
def gen_module():
    spec = importlib.util.spec_from_file_location(
        'wordcloud_generator_under_test', _ROOT / 'blog/wordcloud/generator.py'
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_config_view_attribute_access(gen_module):
    view = gen_module._ConfigView({'stop_words': 'a\nb', 'top_n_bili': 30}, {'shape': 'circle'})
    assert view.stop_words == 'a\nb'
    assert view.top_n_bili == 30


def test_config_view_to_dict_returns_copy(gen_module):
    view = gen_module._ConfigView({}, {'shape': 'circle'})
    first = view.to_dict()
    assert first == {'shape': 'circle'}
    first['shape'] = 'mutated'
    assert view.to_dict()['shape'] == 'circle', 'to_dict 必须返回副本，避免调用方污染缓存'


def test_config_view_unknown_attribute_raises(gen_module):
    view = gen_module._ConfigView({}, {})
    with pytest.raises(AttributeError):
        _ = view.not_exist


# ── 5. SQLite 测试后端的兼容层必须存在 ───────────────────
def test_sqlite_backend_registers_mysql_function_shims():
    """SQLite 后端必须为 MySQL 专有函数注册 shim。

    生产代码含 MySQL 专有 SQL：
      - 首页加权随机排序（blog/core/routes.py:_render_index）用
        unix_timestamp() + rand()，这是无条件执行的请求路径；
      - 词云按月分组用 date_format()。
    若 conftest 的 shim 被移除，SQLite（默认测试后端）下这些路径会报
    "no such function"，测试将失败或（更糟）在异常被吞的路径上"假绿"。
    """
    src = _read('tests/conftest.py')
    assert "create_function('unix_timestamp'" in src, 'SQLite 缺少 unix_timestamp shim'
    assert "create_function('rand'" in src, 'SQLite 缺少 rand shim'
    assert "create_function('date_format'" in src, 'SQLite 缺少 date_format shim'
    assert 'TEST_SQLITE_FK' in src, (
        '应保留可选的外键严格模式开关（TEST_SQLITE_FK=1）：'
        'SQLite 默认关闭外键，而生产 MySQL 的级联删除依赖外键生效，'
        '需要时可开启以验证级联语义'
    )


def test_mysql_only_paths_are_known():
    """固化"SQLite 无法覆盖"的 MySQL 专有路径清单。

    这些路径只能在 CI 的 mysql-integration job 中验证；此断言的作用是
    当有人改动这些代码时提醒复核（断言失败通常意味着该清单需要更新，
    或对应实现已改为方言无关）。
    """
    assert 'func.unix_timestamp' in _read('blog/core/routes.py'), (
        '首页排序若已改为方言无关实现，请同步更新本清单与 conftest 的 shim 说明'
    )
    gen_src = _read('blog/wordcloud/generator.py')
    assert 'on_duplicate_key_update' in gen_src, (
        '词云 upsert 若已改为方言无关实现（如 merge/ON CONFLICT），请更新本清单'
    )
