# -*- coding: utf-8 -*-
"""
HOSHINO Blog — 价格数据模块

⚠️ 重要说明 ⚠️
国内主流电商平台（京东、苏宁、淘宝等）均采用 JS 动态渲染价格，
且配备严格的反爬机制。直接 HTTP 请求无法获取真实价格数据。

本模块采用以下策略获取价格：
  1. 手动录入（主要方式） — 管理员在网页上直接输入价格
  2. 默认建议价（辅助）   — 基于品类提供价格参考范围
  3. 爬虫占位（可扩展）   — 预留接口，接入 API 或浏览器自动化后启用

依赖：
  cloudscraper — 用于绕过 Cloudflare 保护（如后续启用）
"""
import logging

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════
# 品类参考价格（单位：元）
# 当产品无价格记录时，作为默认建议显示
# ═══════════════════════════════════════════════
CATEGORY_REF_PRICES = {
    '手机':    5999,
    '平板':    4999,
    '笔记本':  8999,
    'CPU':     3299,
    '显卡':    6999,
    '内存':    799,
    '固态硬盘': 999,
    '主板':    2499,
    '电源':    899,
    '散热器':  599,
    '显示器':  3999,
    '耳机':    1999,
    '手表':    3999,
    '相机':    15999,
    '鼠标':    499,
    '游戏机':  3999,
}


def get_ref_price(category):
    """返回品类参考价格。

    Args:
        category: 品类名称

    Returns:
        int: 参考价格（元），未知品类返回 0
    """
    return CATEGORY_REF_PRICES.get(category, 0)


def crawl_price(site, url):
    """爬取价格（占位）。

    当前所有国内电商均无法通过 HTTP 直接抓取价格。
    此函数保留接口，后续可接入 Playwright/Selenium 等浏览器自动化方案。
    """
    logger.debug('爬虫占位: site=%s url=%s', site, url)
    return None


def crawl_all_active_sources():
    """爬取所有启用的商品来源（占位）。

    当前返回 0，表示无自动抓取。
    管理员请使用网页上的手动录入功能输入价格。
    """
    logger.info('自动爬虫未启用，请使用手动录入功能输入价格')
    return 0


def init_sample_products():
    """初始化示例商品。"""
    from blog.models import db, Product, ProductSource

    if Product.query.first() is not None:
        return

    samples = [
        # ═══ 手机 ═══
        {'name': 'Apple iPhone 16 Pro Max',    'brand': 'Apple',  'category': '手机',
         'sources': []},
        {'name': 'Samsung Galaxy S25 Ultra',   'brand': 'Samsung','category': '手机',
         'sources': []},
        {'name': 'Xiaomi 15 Pro',              'brand': 'Xiaomi', 'category': '手机',
         'sources': []},
        {'name': 'Huawei Mate 70 Pro',         'brand': 'Huawei', 'category': '手机',
         'sources': []},

        # ═══ 平板 ═══
        {'name': 'Apple iPad Pro M4 13"',      'brand': 'Apple',  'category': '平板',
         'sources': []},
        {'name': 'Apple iPad Air M3 11"',      'brand': 'Apple',  'category': '平板',
         'sources': []},

        # ═══ 笔记本 ═══
        {'name': 'Apple MacBook Air M4',       'brand': 'Apple',  'category': '笔记本',
         'sources': []},
        {'name': 'Apple MacBook Pro 14 M4 Pro','brand': 'Apple',  'category': '笔记本',
         'sources': []},
        {'name': 'ThinkPad X1 Carbon Gen 13',  'brand': 'Lenovo', 'category': '笔记本',
         'sources': []},
        {'name': 'ASUS ROG 幻 16 Air',         'brand': 'ASUS',   'category': '笔记本',
         'sources': []},
        {'name': 'Dell XPS 16',                'brand': 'Dell',   'category': '笔记本',
         'sources': []},

        # ═══ CPU ═══
        {'name': 'AMD Ryzen 7 9800X3D',        'brand': 'AMD',    'category': 'CPU',
         'sources': []},
        {'name': 'Intel Core Ultra 9 285K',    'brand': 'Intel',  'category': 'CPU',
         'sources': []},

        # ═══ 显卡 ═══
        {'name': 'NVIDIA RTX 5090',            'brand': 'NVIDIA', 'category': '显卡',
         'sources': []},
        {'name': 'NVIDIA RTX 5080',            'brand': 'NVIDIA', 'category': '显卡',
         'sources': []},
        {'name': 'AMD Radeon RX 9070 XT',      'brand': 'AMD',    'category': '显卡',
         'sources': []},

        # ═══ 内存 ═══
        {'name': 'Kingston DDR5 32GB 6000MHz', 'brand': 'Kingston','category': '内存',
         'sources': []},

        # ═══ 固态硬盘 ═══
        {'name': 'Samsung 990 Pro 2TB NVMe',   'brand': 'Samsung','category': '固态硬盘',
         'sources': []},

        # ═══ 主板 ═══
        {'name': 'ASUS ROG STRIX Z890-E',      'brand': 'ASUS',   'category': '主板',
         'sources': []},

        # ═══ 电源 ═══
        {'name': 'Corsair RM850x 850W',        'brand': 'Corsair','category': '电源',
         'sources': []},

        # ═══ 散热器 ═══
        {'name': 'NZXT Kraken X73 360mm',      'brand': 'NZXT',   'category': '散热器',
         'sources': []},

        # ═══ 显示器 ═══
        {'name': 'Dell U2724D 4K 27"',         'brand': 'Dell',   'category': '显示器',
         'sources': []},
        {'name': 'ASUS ROG PG32UCDM 4K OLED',  'brand': 'ASUS',   'category': '显示器',
         'sources': []},

        # ═══ 耳机 ═══
        {'name': 'Sony WH-1000XM5',            'brand': 'Sony',   'category': '耳机',
         'sources': []},
        {'name': 'Apple AirPods Pro 2 USB-C',  'brand': 'Apple',  'category': '耳机',
         'sources': []},

        # ═══ 手表 ═══
        {'name': 'Apple Watch Ultra 2',         'brand': 'Apple',  'category': '手表',
         'sources': []},

        # ═══ 相机 ═══
        {'name': 'Sony A7M5 (A7 V)',           'brand': 'Sony',   'category': '相机',
         'sources': []},

        # ═══ 键鼠 ═══
        {'name': 'Logitech MX Master 3S',      'brand': 'Logitech','category': '鼠标',
         'sources': []},

        # ═══ 游戏机 ═══
        {'name': 'Sony PS5 Pro',               'brand': 'Sony',   'category': '游戏机',
         'sources': []},
    ]

    for item in samples:
        p = Product(name=item['name'], brand=item['brand'], category=item['category'])
        db.session.add(p)
        db.session.flush()
        for site, url in item['sources']:
            db.session.add(ProductSource(product_id=p.id, site=site, url=url))
    db.session.commit()
    logger.info('已添加 %d 个示例商品', len(samples))
