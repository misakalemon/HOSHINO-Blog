"""图片字段健康检查：封面 / 头像 / 特色卡片 / Hero 画像

用途：页面出现"封面空白/白图"时，快速判断属于哪一类问题。

判定规则（与 /thumb 缩略图服务、image_src() 模板函数的行为对齐）：
  [OK]    相对路径 + 文件存在 + PIL 可解码        → 正常显示
  [PREFIX] 带 /static/ 或 static/ 前缀            → 旧格式；/thumb 已能兼容，
                                                    但建议重新保存该条目以规范化
  [MISS]  站内路径但文件不存在                    → /thumb 返回占位透明图，
                                                    页面必然空白 → 需重新上传
  [BROKEN] 文件存在但 PIL 无法解码                → 缩略图生成失败（降级返回原图）
  [EXT]   外链（http/https）                      → 由浏览器直连；若对方 CDN 有
                                                    防盗链则可能空白，需服务端代理
  [EMPTY] 未设置                                  → 模板不渲染图片区域
  [OTHER] 非图片值（如 emoji 图标）               → 按 emoji 渲染

用法（项目根目录，激活项目环境后）：
    python tools/check_covers.py
    可选加 --all 显示所有条目（默认只列出有问题的与统计）
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from blog.core.models import (  # noqa: E402
    FeaturedCard,
    HeroImage,
    Post,
    User,
    WordCloudConfig,
)

IMAGE_EXT_HINT = ('uploads/', 'images/')


def classify(value):
    """返回 (类别, 说明)。类别见模块 docstring。"""
    if not value or not str(value).strip():
        return 'EMPTY', '未设置'
    v = str(value).strip()
    if v.startswith(('http://', 'https://')):
        return 'EXT', v
    if v.startswith('/static/'):
        return 'PREFIX', v
    if v.startswith('static/'):
        return 'PREFIX', v
    if v.startswith(IMAGE_EXT_HINT):
        return 'LOCAL', v
    return 'OTHER', v


def inspect_local(app, rel_path):
    """检查站内文件：返回 (类别, 说明)。"""
    rel = rel_path
    if rel.startswith('/static/'):
        rel = rel[len('/static/'):]
    elif rel.startswith('static/'):
        rel = rel[len('static/'):]
    full = os.path.join(app.root_path, 'static', rel)
    if not os.path.isfile(full):
        return 'MISS', f'文件不存在: static/{rel}'
    size = os.path.getsize(full)
    try:
        from PIL import Image

        with Image.open(full) as im:
            dims = f'{im.width}x{im.height} {im.format} {im.mode}'
    except Exception as e:  # 损坏文件
        return 'BROKEN', f'{size / 1024:.0f}KB 无法解码: {type(e).__name__}: {e}'
    return 'OK', f'{dims}  {size / 1024:.0f}KB'


def main():
    show_all = '--all' in sys.argv
    app = create_app()

    rows = []      # (来源, 值, 类别, 说明)
    with app.app_context():
        for p in Post.query.order_by(Post.id).all():
            if p.cover_image:
                rows.append((f'文章 #{p.id} {p.title[:24]}', p.cover_image))
        for c in FeaturedCard.query.order_by(FeaturedCard.id).all():
            if c.icon:
                rows.append((f'特色卡片 #{c.id} icon', c.icon))
            if c.image_url:
                rows.append((f'特色卡片 #{c.id} image_url', c.image_url))
        for h in HeroImage.query.order_by(HeroImage.id).all():
            if h.image_url:
                rows.append((f'Hero 画像 #{h.id}', h.image_url))
        for u in User.query.order_by(User.id).all():
            if u.avatar:
                rows.append((f'用户 #{u.id} {u.username} 头像', u.avatar))
        wc = WordCloudConfig.query.first()
        if wc is not None and wc.shape_image:
            rows.append(('词云形状图', wc.shape_image))

        report = []
        stats = {}
        for source, value in rows:
            kind, _ = classify(value)
            if kind == 'LOCAL':
                kind, detail = inspect_local(app, value)
            elif kind in ('PREFIX',):
                # 前缀形式：先按站内文件检查，再标注需要规范化
                sub_kind, detail = inspect_local(app, value)
                if sub_kind != 'OK':
                    kind = sub_kind
                detail = f'{detail}（值带前缀，建议重新保存以规范化）'
            elif kind == 'EMPTY':
                detail = '未设置'
            elif kind == 'EXT':
                detail = '由浏览器直连（对方 CDN 防盗链会导致空白）'
            else:
                detail = '非常规值（按 emoji/文本渲染）'
            stats[kind] = stats.get(kind, 0) + 1
            report.append((kind, source, value, detail))

    order = {'MISS': 0, 'BROKEN': 1, 'PREFIX': 2, 'EXT': 3, 'OTHER': 4, 'OK': 5, 'EMPTY': 6}
    report.sort(key=lambda r: order.get(r[0], 9))

    print('=' * 78)
    print('图片字段健康检查')
    print('=' * 78)
    for kind, source, value, detail in report:
        if kind == 'OK' and not show_all:
            continue
        print(f'[{kind:6s}] {source}')
        print(f'           值: {value[:90]}')
        print(f'           详情: {detail}')
    print('-' * 78)
    print('统计: ' + '  '.join(f'{k}={v}' for k, v in sorted(stats.items())))
    problems = sum(v for k, v in stats.items() if k in ('MISS', 'BROKEN'))
    print(f'需要处理（文件缺失/损坏）: {problems} 项')
    if problems:
        print('→ 这些封面在页面上必然空白：请到后台重新上传对应图片')
    if stats.get('PREFIX'):
        print('→ 带 /static/ 前缀的值已能被 /thumb 兼容，但建议重新保存条目以规范化')
    if stats.get('EXT'):
        print('→ 外链图片由浏览器直连；若对方有防盗链（如 B站 CDN），需改为上传到本站')
    if not show_all and not problems:
        print('（未发现文件缺失/损坏问题；加 --all 可查看全部条目）')


if __name__ == '__main__':
    main()
