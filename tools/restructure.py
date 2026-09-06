#!/usr/bin/env python3
"""项目结构重构脚本 — 拆分 blog/ 为 core/infra/wordcloud/bilibili 子包。

自动化执行：
1. 创建子包目录
2. git mv 移动文件
3. 批量替换所有 import 路径
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 文件移动映射: (源路径, 目标路径)
MOVES = [
    ('blog/models.py',         'blog/core/models.py'),
    ('blog/admin.py',          'blog/core/admin.py'),
    ('blog/routes.py',         'blog/core/routes.py'),
    ('blog/api.py',            'blog/core/api.py'),
    ('blog/forms.py',          'blog/core/forms.py'),
    ('blog/cache.py',          'blog/core/cache.py'),
    ('blog/settings.py',       'blog/core/settings.py'),
    ('blog/utils.py',          'blog/core/utils.py'),
    ('blog/backup.py',         'blog/infra/backup.py'),
    ('blog/logger.py',         'blog/infra/logger.py'),
    ('blog/logwatch.py',       'blog/infra/logwatch.py'),
    ('blog/mail.py',           'blog/infra/mail.py'),
    ('blog/task_queue.py',     'blog/infra/task_queue.py'),
    ('blog/wordcloud.py',      'blog/wordcloud/generator.py'),
    ('blog/wordcloud_runner.py','blog/wordcloud/runner.py'),
    ('blog/bili_routes.py',    'blog/bilibili/admin_routes.py'),
    ('blog/bili_public_routes.py','blog/bilibili/public_routes.py'),
]

# 模块名 → 新的子包路径
MODULE_MAP = {
    'models':         'core.models',
    'admin':          'core.admin',
    'routes':         'core.routes',
    'api':            'core.api',
    'forms':          'core.forms',
    'cache':          'core.cache',
    'settings':       'core.settings',
    'utils':          'core.utils',
    'backup':         'infra.backup',
    'logger':         'infra.logger',
    'logwatch':       'infra.logwatch',
    'mail':           'infra.mail',
    'task_queue':     'infra.task_queue',
    'wordcloud':      'wordcloud.generator',
    'wordcloud_runner':'wordcloud.runner',
    'bili_routes':    'bilibili.admin_routes',
    'bili_public_routes':'bilibili.public_routes',
}

# 同包内的模块（不需要跨包引用）
SAME_PACKAGE = {
    'core':  {'models','admin','routes','api','forms','cache','settings','utils'},
    'infra': {'backup','logger','logwatch','mail','task_queue'},
    'wordcloud': {'generator','runner'},
    'bilibili': {'bili_api','config','login','admin_routes','public_routes'},
}

# 旧模块名 → 新模块名（同包内重命名）
RENAME_IN_PACKAGE = {
    'wordcloud': 'generator',
    'wordcloud_runner': 'runner',
    'bili_routes': 'admin_routes',
    'bili_public_routes': 'public_routes',
}


def run(cmd):
    print(f'  $ {cmd}')
    r = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        print(f'    FAILED: {r.stderr}', file=sys.stderr)
    return r


def get_package(filepath):
    """返回文件所属子包名（core/infra/wordcloud/bilibili/None）。"""
    parts = filepath.replace('\\', '/').split('/')
    if len(parts) >= 2 and parts[0] == 'blog':
        if parts[1] in ('core', 'infra', 'wordcloud', 'bilibili'):
            return parts[1]
    return None


def replace_imports(filepath, content):
    """替换文件中的 import 路径。"""
    pkg = get_package(filepath)
    
    # 1. 替换绝对 import: blog.xxx → blog.<new>
    for old_mod, new_path in MODULE_MAP.items():
        content = content.replace(f'blog.{old_mod}', f'blog.{new_path}')
    
    # 2. 替换相对 import: from .xxx import
    #    规则取决于当前文件在哪个子包
    for old_mod, new_path in MODULE_MAP.items():
        pattern = f'from .{old_mod} import'
        
        if pkg is None:
            # blog/__init__.py 或 blog/ 根目录文件
            replacement = f'from .{new_path} import'
        else:
            # 在子包内
            new_pkg = new_path.split('.')[0]  # core/infra/wordcloud/bilibili
            new_name = new_path.split('.')[1]  # models/admin/...
            
            if new_pkg == pkg and old_mod in SAME_PACKAGE.get(pkg, set()):
                # 同包：from .new_name import
                replacement = f'from .{new_name} import'
            else:
                # 跨包：from ..new_path import
                replacement = f'from ..{new_path} import'
        
        content = content.replace(pattern, replacement)
    
    # 3. 替换 bilibili/ 已有文件中的 from ..xxx import
    #    这些文件原本在 bilibili/ 子目录，用 .. 引用 blog/ 根模块
    if pkg == 'bilibili':
        for old_mod, new_path in MODULE_MAP.items():
            pattern = f'from ..{old_mod} import'
            new_pkg = new_path.split('.')[0]
            new_name = new_path.split('.')[1]
            # bilibili/ 引用其他子包用 ..，但现在要多一层
            # from ..models → from ..core.models
            replacement = f'from ..{new_path} import'
            content = content.replace(pattern, replacement)
    
    # 4. 处理 wordcloud/ 内部引用
    #    wordcloud_runner.py 原本用 from .wordcloud.generator import
    #    移到 wordcloud/ 后，from .wordcloud → from .generator
    #    上面的逻辑已处理（同包重命名）
    
    return content


def main():
    print('=== 1. 创建子包目录 ===')
    for d in ['blog/core', 'blog/infra', 'blog/wordcloud']:
        os.makedirs(os.path.join(ROOT, d), exist_ok=True)
        init_path = os.path.join(ROOT, d, '__init__.py')
        if not os.path.exists(init_path):
            with open(init_path, 'w', encoding='utf-8') as f:
                f.write(f'"""{d.split("/")[-1]} 子包。"""\n')
            print(f'  创建 {init_path}')
    
    print('\n=== 2. git mv 移动文件 ===')
    for src, dst in MOVES:
        src_full = os.path.join(ROOT, src)
        dst_full = os.path.join(ROOT, dst)
        if not os.path.exists(src_full):
            print(f'  跳过（不存在）: {src}')
            continue
        run(f'git mv "{src}" "{dst}"')
    
    print('\n=== 3. 替换 import 路径 ===')
    # 收集所有需要改的 .py 文件
    files_to_process = []
    for root, dirs, files in os.walk(ROOT):
        # 跳过 .git, __pycache__, venv 等
        dirs[:] = [d for d in dirs if d not in ('.git', '__pycache__', 'venv', '.codeartsdoer', 'node_modules', '.ruff_cache', '.pytest_cache')]
        for f in files:
            if f.endswith('.py'):
                fp = os.path.join(root, f)
                rel = os.path.relpath(fp, ROOT).replace('\\', '/')
                files_to_process.append(rel)
    
    for relpath in sorted(files_to_process):
        fullpath = os.path.join(ROOT, relpath)
        with open(fullpath, 'r', encoding='utf-8') as f:
            original = f.read()
        
        modified = replace_imports(relpath, original)
        
        if modified != original:
            with open(fullpath, 'w', encoding='utf-8') as f:
                f.write(modified)
            print(f'  已更新: {relpath}')
    
    print('\n=== 完成 ===')


if __name__ == '__main__':
    main()