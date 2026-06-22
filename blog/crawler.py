# -*- coding: utf-8 -*-
"""
HOSHINO Blog — 价格数据模块

⚠️ 重要说明 ⚠️
当前所有搜索引擎（百度/必应/搜狗）的价格搜索路线已失效：
- Baidu: 全面滑块验证码，Selenium 无法绕过
- Bing: 搜索结果不包含结构化价格数据
- Sogou: 同上

价格获取方式：
  1. ✅ 手动录入（管理员网页输入）— 主要方式
  2. ✅ 品类参考价 — 无价格时的兜底显示
  3. 🔜 爬虫占位 — 后续接入可靠数据源后启用

新品发布后，管理员可在网页上添加商品，系统会自动显示该品类的参考价格。
"""
import re
import logging
from .models import db, ProductSource, PriceRecord, Product

logger = logging.getLogger(__name__)


def crawl_all_active_sources():
    """爬取所有商品价格（Apify → 参考价兜底）。

    当 APIFY_TOKEN 已配置时，通过 Apify Amazon Price Scraper
    获取商品价格。未配置时仅创建 manual 占位来源。
    """
    from .apify_client import client

    created = 0
    fetched = 0

    pending_records = []  # 收集待提交的记录

    for product in Product.query.all():
        if product.latest_price():
            continue

        price = None
        source = None
        if client._ready:
            try:
                price = client.fetch_amazon_price(product.name)
                if price:
                    source = ProductSource.query.filter_by(
                        product_id=product.id, site='amazon'
                    ).first()
                    if not source:
                        source = ProductSource(
                            product_id=product.id, site='amazon',
                            url='', is_active=True,
                        )
                        db.session.add(source)
                        db.session.flush()
                    source.latest_price = price
                    pending_records.append(
                        PriceRecord(source_id=source.id, product_id=product.id, price=price)
                    )
                    fetched += 1
                    logger.info('✅ %s → ¥%.0f (Amazon)', product.name, price)
                    continue
            except Exception as e:
                logger.warning('Apify 获取 %s 失败: %s', product.name, e)
                db.session.rollback()  # 回滚部分脏 session

        if not product.sources:
            src = ProductSource(
                product_id=product.id, site='manual', url='', is_active=True,
            )
            db.session.add(src)
            created += 1

    # 统一提交
    if pending_records:
        db.session.add_all(pending_records)
    if created or fetched:
        db.session.commit()
    logger.info('价格爬取完成: %d 条 Apify, %d 个占位来源', fetched, created)
    return fetched


# ═══════════════════════════════════════════════
# 全品类电子元器件数据库
# ═══════════════════════════════════════════════

ALL_PRODUCTS = [
    # ═══════════════════════════════════════════════
    # 📱 智能手机 (2024-2026)
    # ═══════════════════════════════════════════════
    {'name': 'Apple iPhone 16 Pro Max',  'brand': 'Apple',  'category': '手机'},
    {'name': 'Apple iPhone 16 Pro',      'brand': 'Apple',  'category': '手机'},
    {'name': 'Apple iPhone 16 Plus',     'brand': 'Apple',  'category': '手机'},
    {'name': 'Apple iPhone 16',          'brand': 'Apple',  'category': '手机'},
    {'name': 'Apple iPhone 15 Pro Max',  'brand': 'Apple',  'category': '手机'},
    {'name': 'Apple iPhone 15 Pro',      'brand': 'Apple',  'category': '手机'},
    {'name': 'Apple iPhone 15 Plus',     'brand': 'Apple',  'category': '手机'},
    {'name': 'Apple iPhone 15',          'brand': 'Apple',  'category': '手机'},
    {'name': 'Apple iPhone SE 4',        'brand': 'Apple',  'category': '手机'},
    {'name': 'Samsung Galaxy S25 Ultra', 'brand': 'Samsung', 'category': '手机'},
    {'name': 'Samsung Galaxy S25+',      'brand': 'Samsung', 'category': '手机'},
    {'name': 'Samsung Galaxy S25',       'brand': 'Samsung', 'category': '手机'},
    {'name': 'Samsung Galaxy S24 Ultra', 'brand': 'Samsung', 'category': '手机'},
    {'name': 'Samsung Galaxy S24+',      'brand': 'Samsung', 'category': '手机'},
    {'name': 'Samsung Galaxy S24',       'brand': 'Samsung', 'category': '手机'},
    {'name': 'Samsung Galaxy Z Fold6',   'brand': 'Samsung', 'category': '手机'},
    {'name': 'Samsung Galaxy Z Flip6',   'brand': 'Samsung', 'category': '手机'},
    {'name': 'Samsung Galaxy Z Fold5',   'brand': 'Samsung', 'category': '手机'},
    {'name': 'Samsung Galaxy Z Flip5',   'brand': 'Samsung', 'category': '手机'},
    {'name': 'Samsung Galaxy A56',       'brand': 'Samsung', 'category': '手机'},
    {'name': 'Samsung Galaxy A55',       'brand': 'Samsung', 'category': '手机'},
    {'name': 'Samsung Galaxy A36',       'brand': 'Samsung', 'category': '手机'},
    {'name': 'Samsung Galaxy A35',       'brand': 'Samsung', 'category': '手机'},
    {'name': 'Xiaomi 15 Pro',            'brand': 'Xiaomi',  'category': '手机'},
    {'name': 'Xiaomi 15',                'brand': 'Xiaomi',  'category': '手机'},
    {'name': 'Xiaomi 14 Ultra',          'brand': 'Xiaomi',  'category': '手机'},
    {'name': 'Xiaomi 14 Pro',            'brand': 'Xiaomi',  'category': '手机'},
    {'name': 'Xiaomi 14',                'brand': 'Xiaomi',  'category': '手机'},
    {'name': 'Huawei Mate 70 Pro',       'brand': 'Huawei',  'category': '手机'},
    {'name': 'Huawei Mate 70',           'brand': 'Huawei',  'category': '手机'},
    {'name': 'Huawei Pura 70 Ultra',     'brand': 'Huawei',  'category': '手机'},
    {'name': 'Huawei Pura 70 Pro',       'brand': 'Huawei',  'category': '手机'},
    {'name': 'Huawei P60 Pro',           'brand': 'Huawei',  'category': '手机'},
    {'name': 'OnePlus 13',               'brand': 'OnePlus', 'category': '手机'},
    {'name': 'OnePlus 12',               'brand': 'OnePlus', 'category': '手机'},
    {'name': 'OnePlus Open',             'brand': 'OnePlus', 'category': '手机'},
    {'name': 'OPPO Find X8 Pro',         'brand': 'OPPO',    'category': '手机'},
    {'name': 'OPPO Find X8',             'brand': 'OPPO',    'category': '手机'},
    {'name': 'OPPO Find X7 Ultra',       'brand': 'OPPO',    'category': '手机'},
    {'name': 'vivo X200 Pro',            'brand': 'vivo',    'category': '手机'},
    {'name': 'vivo X200',                'brand': 'vivo',    'category': '手机'},
    {'name': 'vivo X100 Pro',            'brand': 'vivo',    'category': '手机'},
    {'name': 'Google Pixel 10 Pro',      'brand': 'Google',  'category': '手机'},
    {'name': 'Google Pixel 10',          'brand': 'Google',  'category': '手机'},
    {'name': 'Google Pixel 9 Pro',       'brand': 'Google',  'category': '手机'},
    {'name': 'Google Pixel 9',           'brand': 'Google',  'category': '手机'},
    {'name': 'Google Pixel 8 Pro',       'brand': 'Google',  'category': '手机'},
    {'name': 'Honor Magic7 Pro',         'brand': 'Honor',   'category': '手机'},
    {'name': 'Honor Magic6 Pro',         'brand': 'Honor',   'category': '手机'},
    {'name': 'Honor 200 Pro',            'brand': 'Honor',   'category': '手机'},
    {'name': 'Nothing Phone 3',          'brand': 'Nothing', 'category': '手机'},
    {'name': 'Nothing Phone 2a',         'brand': 'Nothing', 'category': '手机'},
    # Redmi 子品牌
    {'name': 'Redmi K80 Pro',            'brand': 'Redmi',   'category': '手机'},
    {'name': 'Redmi K80',                'brand': 'Redmi',   'category': '手机'},
    {'name': 'Redmi K70 Ultra',          'brand': 'Redmi',   'category': '手机'},
    {'name': 'Redmi K70 Pro',            'brand': 'Redmi',   'category': '手机'},
    {'name': 'Redmi K70',                'brand': 'Redmi',   'category': '手机'},
    {'name': 'Redmi Note 14 Pro+',       'brand': 'Redmi',   'category': '手机'},
    {'name': 'Redmi Note 14 Pro',        'brand': 'Redmi',   'category': '手机'},
    {'name': 'Redmi Note 13 Pro+',       'brand': 'Redmi',   'category': '手机'},
    {'name': 'Redmi Note 13 Pro',        'brand': 'Redmi',   'category': '手机'},
    {'name': 'Redmi Turbo 4',            'brand': 'Redmi',   'category': '手机'},
    # Realme
    {'name': 'Realme GT7 Pro',           'brand': 'Realme',  'category': '手机'},
    {'name': 'Realme GT6',               'brand': 'Realme',  'category': '手机'},
    {'name': 'Realme GT5 Pro',           'brand': 'Realme',  'category': '手机'},
    {'name': 'Realme 14 Pro+',           'brand': 'Realme',  'category': '手机'},
    {'name': 'Realme 13 Pro+',           'brand': 'Realme',  'category': '手机'},
    # iQOO
    {'name': 'iQOO 13',                  'brand': 'iQOO',    'category': '手机'},
    {'name': 'iQOO 12',                  'brand': 'iQOO',    'category': '手机'},
    {'name': 'iQOO Neo10 Pro',           'brand': 'iQOO',    'category': '手机'},
    {'name': 'iQOO Neo9 Pro',            'brand': 'iQOO',    'category': '手机'},
    {'name': 'iQOO Z9 Turbo',            'brand': 'iQOO',    'category': '手机'},
    # ASUS ROG Phone
    {'name': 'ASUS ROG Phone 9 Pro',     'brand': 'ASUS',    'category': '手机'},
    {'name': 'ASUS ROG Phone 9',         'brand': 'ASUS',    'category': '手机'},
    {'name': 'ASUS ROG Phone 8 Pro',     'brand': 'ASUS',    'category': '手机'},
    {'name': 'ASUS Zenfone 11 Ultra',    'brand': 'ASUS',    'category': '手机'},
    # Sony Xperia
    {'name': 'Sony Xperia 1 VI',         'brand': 'Sony',    'category': '手机'},
    {'name': 'Sony Xperia 5 VI',         'brand': 'Sony',    'category': '手机'},
    {'name': 'Sony Xperia 10 VI',        'brand': 'Sony',    'category': '手机'},
    # Motorola
    {'name': 'Motorola Edge 50 Ultra',   'brand': 'Motorola','category': '手机'},
    {'name': 'Motorola Edge 50 Pro',     'brand': 'Motorola','category': '手机'},
    {'name': 'Motorola Razr 50 Ultra',   'brand': 'Motorola','category': '手机'},
    {'name': 'Motorola Razr 2024',       'brand': 'Motorola','category': '手机'},
    {'name': 'Motorola G85',             'brand': 'Motorola','category': '手机'},
    # ZTE / Nubia
    {'name': 'Nubia Z70 Ultra',          'brand': 'Nubia',   'category': '手机'},
    {'name': 'Nubia Z60 Ultra',          'brand': 'Nubia',   'category': '手机'},
    {'name': 'Nubia Red Magic 10 Pro',   'brand': 'Nubia',   'category': '手机'},
    {'name': 'Nubia Red Magic 9 Pro',    'brand': 'Nubia',   'category': '手机'},
    # Meizu
    {'name': 'Meizu 21 Pro',             'brand': 'Meizu',   'category': '手机'},
    {'name': 'Meizu 21 Note',            'brand': 'Meizu',   'category': '手机'},
    # Tecno / Infinix
    {'name': 'Tecno Camon 30 Pro',       'brand': 'Tecno',   'category': '手机'},
    {'name': 'Tecno Phantom V Fold 2',   'brand': 'Tecno',   'category': '手机'},
    {'name': 'Infinix GT 20 Pro',        'brand': 'Infinix', 'category': '手机'},
    {'name': 'Infinix Zero 40',          'brand': 'Infinix', 'category': '手机'},
    # 更多 Huawei
    {'name': 'Huawei Mate X6',           'brand': 'Huawei',  'category': '手机'},
    {'name': 'Huawei Mate X5',           'brand': 'Huawei',  'category': '手机'},
    {'name': 'Huawei Nova 12 Ultra',     'brand': 'Huawei',  'category': '手机'},
    {'name': 'Huawei Nova 12 Pro',       'brand': 'Huawei',  'category': '手机'},
    # 更多 Honor
    {'name': 'Honor Magic V3',           'brand': 'Honor',   'category': '手机'},
    {'name': 'Honor Magic V2',           'brand': 'Honor',   'category': '手机'},
    {'name': 'Honor 90 GT',              'brand': 'Honor',   'category': '手机'},
    {'name': 'Honor X50 GT',             'brand': 'Honor',   'category': '手机'},
    {'name': 'Honor X9b',                'brand': 'Honor',   'category': '手机'},
    # 更多 Samsung Galaxy A/M
    {'name': 'Samsung Galaxy A16',       'brand': 'Samsung', 'category': '手机'},
    {'name': 'Samsung Galaxy A15',       'brand': 'Samsung', 'category': '手机'},
    {'name': 'Samsung Galaxy A25',       'brand': 'Samsung', 'category': '手机'},
    {'name': 'Samsung Galaxy M55',       'brand': 'Samsung', 'category': '手机'},
    {'name': 'Samsung Galaxy M15',       'brand': 'Samsung', 'category': '手机'},
    # 更多 Xiaomi
    {'name': 'Xiaomi Mix Flip',          'brand': 'Xiaomi',  'category': '手机'},
    {'name': 'Xiaomi Mix Fold 4',        'brand': 'Xiaomi',  'category': '手机'},
    {'name': 'Xiaomi Civi 4 Pro',        'brand': 'Xiaomi',  'category': '手机'},
    # 更多 OPPO
    {'name': 'OPPO Find N5',             'brand': 'OPPO',    'category': '手机'},
    {'name': 'OPPO Find N3',             'brand': 'OPPO',    'category': '手机'},
    {'name': 'OPPO Reno 13 Pro',         'brand': 'OPPO',    'category': '手机'},
    {'name': 'OPPO Reno 13',             'brand': 'OPPO',    'category': '手机'},
    {'name': 'OPPO Reno 12 Pro',         'brand': 'OPPO',    'category': '手机'},
    # 更多 vivo
    {'name': 'vivo X Fold3 Pro',         'brand': 'vivo',    'category': '手机'},
    {'name': 'vivo S20 Pro',             'brand': 'vivo',    'category': '手机'},
    {'name': 'vivo S19',                 'brand': 'vivo',    'category': '手机'},
    {'name': 'vivo iQOO Pad',            'brand': 'vivo',    'category': '手机'},
    # 更多 Google
    {'name': 'Google Pixel 9 Pro Fold',  'brand': 'Google',  'category': '手机'},
    {'name': 'Google Pixel 8a',          'brand': 'Google',  'category': '手机'},
    # 更多 OnePlus
    {'name': 'OnePlus Ace 3 Pro',        'brand': 'OnePlus', 'category': '手机'},
    {'name': 'OnePlus Ace 3',            'brand': 'OnePlus', 'category': '手机'},
    {'name': 'OnePlus Nord 4',           'brand': 'OnePlus', 'category': '手机'},

    # ═══════════════════════════════════════════════
    # 💻 笔记本电脑 (2024-2026)
    # ═══════════════════════════════════════════════
    {'name': 'Apple MacBook Air M4',             'brand': 'Apple',   'category': '笔记本'},
    {'name': 'Apple MacBook Air M3',             'brand': 'Apple',   'category': '笔记本'},
    {'name': 'Apple MacBook Pro 14 M4 Pro',      'brand': 'Apple',   'category': '笔记本'},
    {'name': 'Apple MacBook Pro 16 M4 Max',      'brand': 'Apple',   'category': '笔记本'},
    {'name': 'Apple MacBook Pro 14 M3 Pro',      'brand': 'Apple',   'category': '笔记本'},
    {'name': 'Lenovo ThinkPad X1 Carbon Gen 13', 'brand': 'Lenovo',  'category': '笔记本'},
    {'name': 'Lenovo ThinkPad X1 Carbon Gen 12', 'brand': 'Lenovo',  'category': '笔记本'},
    {'name': 'Lenovo ThinkPad X9',               'brand': 'Lenovo',  'category': '笔记本'},
    {'name': 'Lenovo ThinkPad T14s Gen 6',       'brand': 'Lenovo',  'category': '笔记本'},
    {'name': 'Lenovo Yoga 9i Gen 9',             'brand': 'Lenovo',  'category': '笔记本'},
    {'name': 'Lenovo Legion Pro 7i',             'brand': 'Lenovo',  'category': '笔记本'},
    {'name': 'Lenovo Legion 5 Pro',              'brand': 'Lenovo',  'category': '笔记本'},
    {'name': 'Lenovo ThinkBook 16p',             'brand': 'Lenovo',  'category': '笔记本'},
    {'name': 'Dell XPS 16',                      'brand': 'Dell',    'category': '笔记本'},
    {'name': 'Dell XPS 14',                      'brand': 'Dell',    'category': '笔记本'},
    {'name': 'Dell XPS 13',                      'brand': 'Dell',    'category': '笔记本'},
    {'name': 'Dell Alienware m18',               'brand': 'Alienware','category': '笔记本'},
    {'name': 'Dell Alienware m16',               'brand': 'Alienware','category': '笔记本'},
    {'name': 'Dell Inspiron 16 Plus',             'brand': 'Dell',    'category': '笔记本'},
    {'name': 'ASUS ROG Zephyrus G16',            'brand': 'ASUS',    'category': '笔记本'},
    {'name': 'ASUS ROG Zephyrus G14',            'brand': 'ASUS',    'category': '笔记本'},
    {'name': 'ASUS ROG Strix Scar 18',           'brand': 'ASUS',    'category': '笔记本'},
    {'name': 'ASUS ZenBook 14 OLED',             'brand': 'ASUS',    'category': '笔记本'},
    {'name': 'ASUS TUF Gaming A16',              'brand': 'ASUS',    'category': '笔记本'},
    {'name': 'ASUS ProArt P16',                  'brand': 'ASUS',    'category': '笔记本'},
    {'name': 'HP Spectre x360 16',               'brand': 'HP',      'category': '笔记本'},
    {'name': 'HP Spectre x360 14',               'brand': 'HP',      'category': '笔记本'},
    {'name': 'HP Envy 16',                       'brand': 'HP',      'category': '笔记本'},
    {'name': 'HP Pavilion Plus 16',              'brand': 'HP',      'category': '笔记本'},
    {'name': 'HP Omen 17',                       'brand': 'HP',      'category': '笔记本'},
    {'name': 'Microsoft Surface Laptop 7',       'brand': 'Microsoft','category':'笔记本'},
    {'name': 'Microsoft Surface Pro 11',         'brand': 'Microsoft','category':'笔记本'},
    {'name': 'Microsoft Surface Laptop Studio 2','brand': 'Microsoft','category':'笔记本'},
    {'name': 'Razer Blade 16',                   'brand': 'Razer',   'category': '笔记本'},
    {'name': 'Razer Blade 14',                   'brand': 'Razer',   'category': '笔记本'},
    {'name': 'Samsung Galaxy Book4 Ultra',       'brand': 'Samsung', 'category': '笔记本'},
    {'name': 'Samsung Galaxy Book4 Pro',         'brand': 'Samsung', 'category': '笔记本'},
    {'name': 'Acer Swift Go 14',                 'brand': 'Acer',    'category': '笔记本'},
    {'name': 'Acer Predator Helios 18',          'brand': 'Acer',    'category': '笔记本'},
    {'name': 'Acer Aspire Vero 16',              'brand': 'Acer',    'category': '笔记本'},
    {'name': 'Huawei MateBook X Pro 2024',       'brand': 'Huawei',  'category': '笔记本'},
    {'name': 'Huawei MateBook 14',               'brand': 'Huawei',  'category': '笔记本'},

    # ═══════════════════════════════════════════════
    # 📟 平板电脑 (2024-2026)
    # ═══════════════════════════════════════════════
    {'name': 'Apple iPad Pro M4 13"',            'brand': 'Apple',   'category': '平板'},
    {'name': 'Apple iPad Pro M4 11"',            'brand': 'Apple',   'category': '平板'},
    {'name': 'Apple iPad Air M3 13"',            'brand': 'Apple',   'category': '平板'},
    {'name': 'Apple iPad Air M3 11"',            'brand': 'Apple',   'category': '平板'},
    {'name': 'Apple iPad 11th Gen',              'brand': 'Apple',   'category': '平板'},
    {'name': 'Apple iPad Mini 7',                'brand': 'Apple',   'category': '平板'},
    {'name': 'Samsung Galaxy Tab S10 Ultra',     'brand': 'Samsung', 'category': '平板'},
    {'name': 'Samsung Galaxy Tab S10+',          'brand': 'Samsung', 'category': '平板'},
    {'name': 'Samsung Galaxy Tab S9 Ultra',      'brand': 'Samsung', 'category': '平板'},
    {'name': 'Samsung Galaxy Tab S9 FE',         'brand': 'Samsung', 'category': '平板'},
    {'name': 'Huawei MatePad Pro 13.2"',         'brand': 'Huawei',  'category': '平板'},
    {'name': 'Huawei MatePad Air',               'brand': 'Huawei',  'category': '平板'},
    {'name': 'Xiaomi Pad 7 Pro',                 'brand': 'Xiaomi',  'category': '平板'},
    {'name': 'Xiaomi Pad 6S Pro',                'brand': 'Xiaomi',  'category': '平板'},
    {'name': 'OnePlus Pad 2',                    'brand': 'OnePlus', 'category': '平板'},
    {'name': 'Lenovo Tab P12 Pro',               'brand': 'Lenovo',  'category': '平板'},

    # ═══════════════════════════════════════════════
    # ⌚ 智能手表 (2024-2026)
    # ═══════════════════════════════════════════════
    {'name': 'Apple Watch Ultra 2',              'brand': 'Apple',   'category': '手表'},
    {'name': 'Apple Watch Series 10',            'brand': 'Apple',   'category': '手表'},
    {'name': 'Apple Watch Series 9',             'brand': 'Apple',   'category': '手表'},
    {'name': 'Apple Watch SE 2',                 'brand': 'Apple',   'category': '手表'},
    {'name': 'Samsung Galaxy Watch Ultra',       'brand': 'Samsung', 'category': '手表'},
    {'name': 'Samsung Galaxy Watch 7',           'brand': 'Samsung', 'category': '手表'},
    {'name': 'Samsung Galaxy Watch 6 Classic',   'brand': 'Samsung', 'category': '手表'},
    {'name': 'Huawei Watch GT 5 Pro',            'brand': 'Huawei',  'category': '手表'},
    {'name': 'Huawei Watch GT 5',                'brand': 'Huawei',  'category': '手表'},
    {'name': 'Huawei Watch D2',                  'brand': 'Huawei',  'category': '手表'},
    {'name': 'Xiaomi Watch S4',                  'brand': 'Xiaomi',  'category': '手表'},
    {'name': 'Xiaomi Watch S3',                  'brand': 'Xiaomi',  'category': '手表'},
    {'name': 'Google Pixel Watch 3',             'brand': 'Google',  'category': '手表'},
    {'name': 'Google Pixel Watch 2',             'brand': 'Google',  'category': '手表'},
    {'name': 'Garmin Fenix 8',                   'brand': 'Garmin',  'category': '手表'},
    {'name': 'Garmin Forerunner 265',            'brand': 'Garmin',  'category': '手表'},
    {'name': 'Amazfit T-Rex 3',                  'brand': 'Amazfit', 'category': '手表'},
    {'name': 'Amazfit Balance',                  'brand': 'Amazfit', 'category': '手表'},

    # ═══════════════════════════════════════════════
    # 🎧 耳机 (2024-2026)
    # ═══════════════════════════════════════════════
    {'name': 'Apple AirPods Pro 2 USB-C',        'brand': 'Apple',   'category': '耳机'},
    {'name': 'Apple AirPods 4',                  'brand': 'Apple',   'category': '耳机'},
    {'name': 'Apple AirPods Max 2',              'brand': 'Apple',   'category': '耳机'},
    {'name': 'Sony WH-1000XM5',                  'brand': 'Sony',    'category': '耳机'},
    {'name': 'Sony WF-1000XM5',                  'brand': 'Sony',    'category': '耳机'},
    {'name': 'Bose QuietComfort Ultra',          'brand': 'Bose',    'category': '耳机'},
    {'name': 'Bose QuietComfort Ultra Earbuds',  'brand': 'Bose',    'category': '耳机'},
    {'name': 'Sennheiser Momentum 4',            'brand': 'Sennheiser','category':'耳机'},
    {'name': 'Samsung Galaxy Buds3 Pro',          'brand': 'Samsung', 'category': '耳机'},
    {'name': 'Samsung Galaxy Buds FE',            'brand': 'Samsung', 'category': '耳机'},
    {'name': 'Xiaomi Buds 5 Pro',                 'brand': 'Xiaomi',  'category': '耳机'},
    {'name': 'Nothing Ear 2',                     'brand': 'Nothing', 'category': '耳机'},
    {'name': 'Beats Studio Buds+',                'brand': 'Beats',   'category': '耳机'},
    {'name': 'JBL Tune 770NC',                    'brand': 'JBL',     'category': '耳机'},
    {'name': 'Anker Soundcore Space A40',         'brand': 'Anker',   'category': '耳机'},
    {'name': 'SteelSeries Arctis Nova Pro',       'brand': 'SteelSeries','category':'耳机'},
    {'name': 'Razer BlackShark V2 Pro',           'brand': 'Razer',    'category': '耳机'},
    {'name': 'Logitech G Pro X 2',                'brand': 'Logitech', 'category': '耳机'},
    {'name': 'HyperX Cloud Alpha Wireless',       'brand': 'HyperX',   'category': '耳机'},

    # ═══════════════════════════════════════════════
    # 📷 相机 (2024-2026)
    # ═══════════════════════════════════════════════
    {'name': 'Sony A1 II',                       'brand': 'Sony',    'category': '相机'},
    {'name': 'Sony A7 V (A7M5)',                 'brand': 'Sony',    'category': '相机'},
    {'name': 'Sony A7 IV',                       'brand': 'Sony',    'category': '相机'},
    {'name': 'Sony A7C II',                      'brand': 'Sony',    'category': '相机'},
    {'name': 'Sony A6700',                       'brand': 'Sony',    'category': '相机'},
    {'name': 'Sony ZV-E10 II',                   'brand': 'Sony',    'category': '相机'},
    {'name': 'Canon EOS R5 Mark II',             'brand': 'Canon',   'category': '相机'},
    {'name': 'Canon EOS R6 Mark III',            'brand': 'Canon',   'category': '相机'},
    {'name': 'Canon EOS R8',                     'brand': 'Canon',   'category': '相机'},
    {'name': 'Canon EOS R50',                    'brand': 'Canon',   'category': '相机'},
    {'name': 'Nikon Z8',                         'brand': 'Nikon',   'category': '相机'},
    {'name': 'Nikon Z6 III',                     'brand': 'Nikon',   'category': '相机'},
    {'name': 'Nikon Zf',                         'brand': 'Nikon',   'category': '相机'},
    {'name': 'Fujifilm GFX100 II',               'brand': 'Fujifilm','category': '相机'},
    {'name': 'Fujifilm X-T5',                    'brand': 'Fujifilm','category': '相机'},
    {'name': 'Fujifilm X100VI',                  'brand': 'Fujifilm','category': '相机'},
    {'name': 'Fujifilm X-S20',                   'brand': 'Fujifilm','category': '相机'},
    {'name': 'Panasonic Lumix S9',               'brand': 'Panasonic','category':'相机'},
    {'name': 'OM System OM-1 Mark II',           'brand': 'OM System','category':'相机'},
    {'name': 'DJI Osmo Pocket 3',                'brand': 'DJI',     'category': '相机'},
    {'name': 'DJI Osmo Action 5 Pro',            'brand': 'DJI',     'category': '相机'},
    {'name': 'GoPro Hero 13 Black',              'brand': 'GoPro',   'category': '相机'},

    # ═══════════════════════════════════════════════
    # 🖥️ 显示器 (2024-2026)
    # ═══════════════════════════════════════════════
    {'name': 'Dell U3224KB 6K 32"',              'brand': 'Dell',    'category': '显示器'},
    {'name': 'Dell U2724D 4K 27"',               'brand': 'Dell',    'category': '显示器'},
    {'name': 'Dell Alienware AW3225QF 4K',       'brand': 'Alienware','category':'显示器'},
    {'name': 'ASUS ROG PG32UCDM 4K OLED',        'brand': 'ASUS',    'category': '显示器'},
    {'name': 'ASUS ROG PG27AQDM 27" OLED',       'brand': 'ASUS',    'category': '显示器'},
    {'name': 'Samsung Odyssey OLED G8 34"',      'brand': 'Samsung', 'category': '显示器'},
    {'name': 'Samsung Odyssey Neo G9 57"',       'brand': 'Samsung', 'category': '显示器'},
    {'name': 'LG 32UN880 4K',                    'brand': 'LG',      'category': '显示器'},
    {'name': 'LG 27GP950 4K 144Hz',              'brand': 'LG',      'category': '显示器'},
    {'name': 'LG OLED 27GS95QE',                 'brand': 'LG',      'category': '显示器'},
    {'name': 'Apple Studio Display',             'brand': 'Apple',   'category': '显示器'},
    {'name': 'BenQ PD3225U 4K',                  'brand': 'BenQ',    'category': '显示器'},
    {'name': 'Acer Predator X32 FP',             'brand': 'Acer',    'category': '显示器'},
    {'name': 'Gigabyte M32U 4K',                 'brand': 'Gigabyte','category': '显示器'},
    {'name': 'MSI MPG 321URX 4K OLED',           'brand': 'MSI',     'category': '显示器'},
    {'name': 'Huawei MateView 28"',              'brand': 'Huawei',  'category': '显示器'},

    # ═══════════════════════════════════════════════
    # 🖥️ Intel CPU (13/14代 + Ultra 200S)
    # ═══════════════════════════════════════════════
    {'name': 'Intel Core Ultra 9 285K',          'brand': 'Intel',  'category': 'CPU'},
    {'name': 'Intel Core Ultra 7 265K',          'brand': 'Intel',  'category': 'CPU'},
    {'name': 'Intel Core Ultra 5 245K',          'brand': 'Intel',  'category': 'CPU'},
    {'name': 'Intel Core Ultra 9 285',           'brand': 'Intel',  'category': 'CPU'},
    {'name': 'Intel Core Ultra 7 265',           'brand': 'Intel',  'category': 'CPU'},
    {'name': 'Intel Core Ultra 5 225H',          'brand': 'Intel',  'category': 'CPU'},
    {'name': 'Intel Core i9-14900K',             'brand': 'Intel',  'category': 'CPU'},
    {'name': 'Intel Core i9-14900',              'brand': 'Intel',  'category': 'CPU'},
    {'name': 'Intel Core i7-14700K',             'brand': 'Intel',  'category': 'CPU'},
    {'name': 'Intel Core i7-14700',              'brand': 'Intel',  'category': 'CPU'},
    {'name': 'Intel Core i5-14600K',             'brand': 'Intel',  'category': 'CPU'},
    {'name': 'Intel Core i5-14500',              'brand': 'Intel',  'category': 'CPU'},
    {'name': 'Intel Core i3-14100F',             'brand': 'Intel',  'category': 'CPU'},
    {'name': 'Intel Core i9-13900K',             'brand': 'Intel',  'category': 'CPU'},
    {'name': 'Intel Core i7-13700K',             'brand': 'Intel',  'category': 'CPU'},
    {'name': 'Intel Core i5-13600K',             'brand': 'Intel',  'category': 'CPU'},
    {'name': 'Intel Core i5-13400',              'brand': 'Intel',  'category': 'CPU'},

    # ═══════════════════════════════════════════════
    # 🖥️ AMD CPU (Ryzen 7000/9000)
    # ═══════════════════════════════════════════════
    {'name': 'AMD Ryzen 9 9950X',                'brand': 'AMD',    'category': 'CPU'},
    {'name': 'AMD Ryzen 9 9900X',                'brand': 'AMD',    'category': 'CPU'},
    {'name': 'AMD Ryzen 7 9800X3D',              'brand': 'AMD',    'category': 'CPU'},
    {'name': 'AMD Ryzen 7 9700X',                'brand': 'AMD',    'category': 'CPU'},
    {'name': 'AMD Ryzen 5 9600X',                'brand': 'AMD',    'category': 'CPU'},
    {'name': 'AMD Ryzen 9 7950X3D',              'brand': 'AMD',    'category': 'CPU'},
    {'name': 'AMD Ryzen 9 7950X',                'brand': 'AMD',    'category': 'CPU'},
    {'name': 'AMD Ryzen 7 7800X3D',              'brand': 'AMD',    'category': 'CPU'},
    {'name': 'AMD Ryzen 7 7700X',                'brand': 'AMD',    'category': 'CPU'},
    {'name': 'AMD Ryzen 5 7600X',                'brand': 'AMD',    'category': 'CPU'},
    {'name': 'AMD Ryzen 5 7600',                 'brand': 'AMD',    'category': 'CPU'},
    {'name': 'AMD Ryzen 7 5700X3D',              'brand': 'AMD',    'category': 'CPU'},

    # ═══════════════════════════════════════════════
    # 🎮 NVIDIA 显卡 (RTX 40/50)
    # ═══════════════════════════════════════════════
    {'name': 'NVIDIA RTX 5090',                  'brand': 'NVIDIA', 'category': '显卡'},
    {'name': 'NVIDIA RTX 5080',                  'brand': 'NVIDIA', 'category': '显卡'},
    {'name': 'NVIDIA RTX 5070 Ti',               'brand': 'NVIDIA', 'category': '显卡'},
    {'name': 'NVIDIA RTX 5070',                  'brand': 'NVIDIA', 'category': '显卡'},
    {'name': 'NVIDIA RTX 5060 Ti',               'brand': 'NVIDIA', 'category': '显卡'},
    {'name': 'NVIDIA RTX 5060',                  'brand': 'NVIDIA', 'category': '显卡'},
    {'name': 'NVIDIA RTX 4090',                  'brand': 'NVIDIA', 'category': '显卡'},
    {'name': 'NVIDIA RTX 4080 Super',            'brand': 'NVIDIA', 'category': '显卡'},
    {'name': 'NVIDIA RTX 4070 Ti Super',         'brand': 'NVIDIA', 'category': '显卡'},
    {'name': 'NVIDIA RTX 4070 Super',            'brand': 'NVIDIA', 'category': '显卡'},
    {'name': 'NVIDIA RTX 4060 Ti',               'brand': 'NVIDIA', 'category': '显卡'},
    {'name': 'NVIDIA RTX 4060',                  'brand': 'NVIDIA', 'category': '显卡'},

    # ═══════════════════════════════════════════════
    # 🎮 AMD 显卡 (RX 7000/9000)
    # ═══════════════════════════════════════════════
    {'name': 'AMD Radeon RX 9070 XT',            'brand': 'AMD',    'category': '显卡'},
    {'name': 'AMD Radeon RX 9070',               'brand': 'AMD',    'category': '显卡'},
    {'name': 'AMD Radeon RX 9060 XT',            'brand': 'AMD',    'category': '显卡'},
    {'name': 'AMD Radeon RX 7900 XTX',           'brand': 'AMD',    'category': '显卡'},
    {'name': 'AMD Radeon RX 7900 XT',            'brand': 'AMD',    'category': '显卡'},
    {'name': 'AMD Radeon RX 7800 XT',            'brand': 'AMD',    'category': '显卡'},
    {'name': 'AMD Radeon RX 7700 XT',            'brand': 'AMD',    'category': '显卡'},
    {'name': 'AMD Radeon RX 7600 XT',            'brand': 'AMD',    'category': '显卡'},

    # ═══════════════════════════════════════════════
    # 💾 内存 DDR5 (2024-2026)
    # ═══════════════════════════════════════════════
    {'name': 'Kingston Fury DDR5 32GB 6000MHz',  'brand': 'Kingston',  'category': '内存'},
    {'name': 'Kingston Fury DDR5 16GB 5600MHz',  'brand': 'Kingston',  'category': '内存'},
    {'name': 'Corsair Vengeance DDR5 32GB 6000','brand': 'Corsair',  'category': '内存'},
    {'name': 'Corsair Dominator Titanium DDR5 32GB','brand':'Corsair','category': '内存'},
    {'name': 'G.Skill Trident Z5 DDR5 32GB',     'brand': 'G.Skill',   'category': '内存'},
    {'name': 'G.Skill Flare X5 DDR5 32GB',       'brand': 'G.Skill',   'category': '内存'},
    {'name': 'Crucial DDR5 Pro 32GB 5600MHz',    'brand': 'Crucial',   'category': '内存'},
    {'name': 'TEAMGROUP T-Force DDR5 32GB',      'brand': 'TEAMGROUP', 'category': '内存'},
    {'name': 'ADATA XPG Lancer DDR5 32GB',       'brand': 'ADATA',     'category': '内存'},
    {'name': 'Patriot Viper DDR5 32GB',          'brand': 'Patriot',   'category': '内存'},

    # ═══════════════════════════════════════════════
    # 💾 固态硬盘 NVMe (2024-2026)
    # ═══════════════════════════════════════════════
    {'name': 'Samsung 990 Pro 2TB NVMe',         'brand': 'Samsung',  'category': '固态硬盘'},
    {'name': 'Samsung 990 Pro 1TB NVMe',         'brand': 'Samsung',  'category': '固态硬盘'},
    {'name': 'Samsung 990 EVO Plus 2TB',         'brand': 'Samsung',  'category': '固态硬盘'},
    {'name': 'WD Black SN850X 2TB',              'brand': 'WD',       'category': '固态硬盘'},
    {'name': 'WD Black SN850X 1TB',              'brand': 'WD',       'category': '固态硬盘'},
    {'name': 'WD Blue SN580 1TB',                'brand': 'WD',       'category': '固态硬盘'},
    {'name': 'Seagate FireCuda 530 2TB',         'brand': 'Seagate',  'category': '固态硬盘'},
    {'name': 'Seagate FireCuda 540 1TB',         'brand': 'Seagate',  'category': '固态硬盘'},
    {'name': 'SK Hynix Platinum P41 2TB',        'brand': 'SK Hynix', 'category': '固态硬盘'},
    {'name': 'SK Hynix Platinum P41 1TB',        'brand': 'SK Hynix', 'category': '固态硬盘'},
    {'name': 'Crucial T700 2TB NVMe',            'brand': 'Crucial',  'category': '固态硬盘'},
    {'name': 'Crucial T500 1TB NVMe',            'brand': 'Crucial',  'category': '固态硬盘'},
    {'name': 'Kingston KC3000 2TB',              'brand': 'Kingston', 'category': '固态硬盘'},
    {'name': 'Kingston NV3 1TB',                 'brand': 'Kingston', 'category': '固态硬盘'},

    # ═══════════════════════════════════════════════
    # 🔌 Intel 主板 (Z790/Z890/B760)
    # ═══════════════════════════════════════════════
    {'name': 'ASUS ROG STRIX Z890-E',            'brand': 'ASUS',     'category': '主板'},
    {'name': 'ASUS ROG STRIX Z790-E',            'brand': 'ASUS',     'category': '主板'},
    {'name': 'ASUS ROG MAXIMUS Z890 HERO',       'brand': 'ASUS',     'category': '主板'},
    {'name': 'ASUS TUF GAMING Z890-PLUS',        'brand': 'ASUS',     'category': '主板'},
    {'name': 'ASUS TUF GAMING B760M-PLUS',       'brand': 'ASUS',     'category': '主板'},
    {'name': 'MSI MEG Z890 ACE',                 'brand': 'MSI',      'category': '主板'},
    {'name': 'MSI MPG Z790 CARBON MAX',          'brand': 'MSI',      'category': '主板'},
    {'name': 'MSI MAG Z790 TOMAHAWK',            'brand': 'MSI',      'category': '主板'},
    {'name': 'MSI PRO B760M-A',                  'brand': 'MSI',      'category': '主板'},
    {'name': 'Gigabyte Z890 AORUS MASTER',       'brand': 'Gigabyte', 'category': '主板'},
    {'name': 'Gigabyte Z790 AORUS ELITE',        'brand': 'Gigabyte', 'category': '主板'},
    {'name': 'Gigabyte B760 AORUS ELITE',        'brand': 'Gigabyte', 'category': '主板'},
    {'name': 'ASRock Z890 Taichi',               'brand': 'ASRock',   'category': '主板'},
    {'name': 'ASRock Z790 Pro RS',               'brand': 'ASRock',   'category': '主板'},

    # ═══════════════════════════════════════════════
    # 🔌 AMD 主板 (X670/X870/B650)
    # ═══════════════════════════════════════════════
    {'name': 'ASUS ROG CROSSHAIR X870E',         'brand': 'ASUS',     'category': '主板'},
    {'name': 'ASUS ROG STRIX X870E-E',           'brand': 'ASUS',     'category': '主板'},
    {'name': 'ASUS TUF GAMING B650M-PLUS',       'brand': 'ASUS',     'category': '主板'},
    {'name': 'MSI MEG X670E ACE',                'brand': 'MSI',      'category': '主板'},
    {'name': 'MSI MAG X670E TOMAHAWK',           'brand': 'MSI',      'category': '主板'},
    {'name': 'MSI PRO B650M-A',                  'brand': 'MSI',      'category': '主板'},
    {'name': 'Gigabyte X870E AORUS MASTER',      'brand': 'Gigabyte', 'category': '主板'},
    {'name': 'Gigabyte B650 AORUS ELITE',        'brand': 'Gigabyte', 'category': '主板'},
    {'name': 'ASRock X870E Taichi',              'brand': 'ASRock',   'category': '主板'},
    {'name': 'ASRock B650M Pro RS',              'brand': 'ASRock',   'category': '主板'},

    # ═══════════════════════════════════════════════
    # ⚡ 电源 (2024-2026)
    # ═══════════════════════════════════════════════
    {'name': 'Corsair RM1200x Shift 1200W',      'brand': 'Corsair',  'category': '电源'},
    {'name': 'Corsair RM1000x 1000W',            'brand': 'Corsair',  'category': '电源'},
    {'name': 'Corsair RM850x 850W',              'brand': 'Corsair',  'category': '电源'},
    {'name': 'Corsair HX1500i 1500W',            'brand': 'Corsair',  'category': '电源'},
    {'name': 'Seasonic Prime TX-1600',           'brand': 'Seasonic', 'category': '电源'},
    {'name': 'Seasonic Prime TX-1000',           'brand': 'Seasonic', 'category': '电源'},
    {'name': 'Seasonic FOCUS GX-850',            'brand': 'Seasonic', 'category': '电源'},
    {'name': 'EVGA SuperNOVA 1000 G7',           'brand': 'EVGA',     'category': '电源'},
    {'name': 'Cooler Master MWE 850W',           'brand': 'CoolerMaster','category':'电源'},
    {'name': 'be quiet! Dark Power 13 1000W',    'brand': 'be quiet!','category': '电源'},
    {'name': 'NZXT C1200',                       'brand': 'NZXT',     'category': '电源'},
    {'name': 'Thermaltake Toughpower GF3 1200W', 'brand': 'Thermaltake','category':'电源'},
    {'name': 'MSI MAG A850GL',                   'brand': 'MSI',      'category': '电源'},
    {'name': 'ASUS ROG THOR 1200P2',             'brand': 'ASUS',     'category': '电源'},

    # ═══════════════════════════════════════════════
    # 🌡️ 散热器 (2024-2026)
    # ═══════════════════════════════════════════════
    {'name': 'NZXT Kraken X73 360mm',            'brand': 'NZXT',     'category': '散热器'},
    {'name': 'NZXT Kraken Elite 360mm',          'brand': 'NZXT',     'category': '散热器'},
    {'name': 'Corsair H150i Elite 360mm',        'brand': 'Corsair',  'category': '散热器'},
    {'name': 'Corsair H100i Elite 240mm',        'brand': 'Corsair',  'category': '散热器'},
    {'name': 'Noctua NH-D15 G2',                 'brand': 'Noctua',   'category': '散热器'},
    {'name': 'Noctua NH-U12A',                   'brand': 'Noctua',   'category': '散热器'},
    {'name': 'DeepCool AK620',                   'brand': 'DeepCool', 'category': '散热器'},
    {'name': 'DeepCool LT720 360mm',             'brand': 'DeepCool', 'category': '散热器'},
    {'name': 'Thermalright Peerless Assassin 120','brand': 'Thermalright','category':'散热器'},
    {'name': 'Thermalright Phantom Spirit 120',  'brand': 'Thermalright','category':'散热器'},
    {'name': 'Lian Li Galahad II Trinity 360mm', 'brand': 'Lian Li',  'category': '散热器'},
    {'name': 'ARCTIC Liquid Freezer III 360mm',  'brand': 'ARCTIC',   'category': '散热器'},
    {'name': 'be quiet! Dark Rock Pro 5',        'brand': 'be quiet!','category': '散热器'},
    {'name': 'Cooler Master MasterLiquid 360',   'brand': 'CoolerMaster','category':'散热器'},

    # ═══════════════════════════════════════════════
    # 🖥️ 机箱 (2024-2026)
    # ═══════════════════════════════════════════════
    {'name': 'NZXT H7 Flow',                     'brand': 'NZXT',     'category': '机箱'},
    {'name': 'NZXT H5 Flow',                     'brand': 'NZXT',     'category': '机箱'},
    {'name': 'NZXT H6 Flow RGB',                 'brand': 'NZXT',     'category': '机箱'},
    {'name': 'Corsair 5000D Airflow',            'brand': 'Corsair',  'category': '机箱'},
    {'name': 'Corsair 4000D Airflow',            'brand': 'Corsair',  'category': '机箱'},
    {'name': 'Lian Li O11 Dynamic EVO RGB',      'brand': 'Lian Li',  'category': '机箱'},
    {'name': 'Lian Li O11 Vision',               'brand': 'Lian Li',  'category': '机箱'},
    {'name': 'Fractal Design North',             'brand': 'Fractal',  'category': '机箱'},
    {'name': 'Fractal Design Meshify 2',         'brand': 'Fractal',  'category': '机箱'},
    {'name': 'Fractal Design Torrent',           'brand': 'Fractal',  'category': '机箱'},
    {'name': 'Cooler Master MasterBox NR200P',   'brand': 'CoolerMaster','category':'机箱'},
    {'name': 'be quiet! Silent Base 802',        'brand': 'be quiet!','category': '机箱'},
    {'name': 'ASUS ROG Hyperion GR701',          'brand': 'ASUS',     'category': '机箱'},

    # ═══════════════════════════════════════════════
    # 🖱️ 鼠标 (2024-2026)
    # ═══════════════════════════════════════════════
    {'name': 'Logitech MX Master 3S',            'brand': 'Logitech', 'category': '鼠标'},
    {'name': 'Logitech MX Anywhere 3S',          'brand': 'Logitech', 'category': '鼠标'},
    {'name': 'Logitech G Pro X Superlight 2',    'brand': 'Logitech', 'category': '鼠标'},
    {'name': 'Logitech G502 X Plus',             'brand': 'Logitech', 'category': '鼠标'},
    {'name': 'Razer DeathAdder V3 Pro',          'brand': 'Razer',    'category': '鼠标'},
    {'name': 'Razer Viper V3 Pro',               'brand': 'Razer',    'category': '鼠标'},
    {'name': 'Razer Basilisk V3 Pro',            'brand': 'Razer',    'category': '鼠标'},
    {'name': 'ASUS ROG Harpe Ace',               'brand': 'ASUS',     'category': '鼠标'},
    {'name': 'SteelSeries Aerox 9 Wireless',     'brand': 'SteelSeries','category':'鼠标'},
    {'name': 'Zowie EC2-CW',                     'brand': 'Zowie',    'category': '鼠标'},
    {'name': 'Finalmouse UltralightX',           'brand': 'Finalmouse','category':'鼠标'},
    {'name': 'Lamzu Atlantis',                   'brand': 'Lamzu',    'category': '鼠标'},

    # ═══════════════════════════════════════════════
    # ⌨️ 键盘 (2024-2026)
    # ═══════════════════════════════════════════════
    {'name': 'Keychron Q1 Pro',                  'brand': 'Keychron', 'category': '键盘'},
    {'name': 'Keychron Q3 Pro',                  'brand': 'Keychron', 'category': '键盘'},
    {'name': 'Keychron V1',                      'brand': 'Keychron', 'category': '键盘'},
    {'name': 'Razer BlackWidow V4 Pro',          'brand': 'Razer',    'category': '键盘'},
    {'name': 'Razer Huntsman V3 Pro',            'brand': 'Razer',    'category': '键盘'},
    {'name': 'Logitech G915 X',                  'brand': 'Logitech', 'category': '键盘'},
    {'name': 'Corsair K70 Max',                  'brand': 'Corsair',  'category': '键盘'},
    {'name': 'SteelSeries Apex Pro TKL',         'brand': 'SteelSeries','category':'键盘'},
    {'name': 'Wooting 60HE+',                    'brand': 'Wooting',  'category': '键盘'},
    {'name': 'Wooting 80HE',                     'brand': 'Wooting',  'category': '键盘'},
    {'name': 'ASUS ROG Azoth',                   'brand': 'ASUS',     'category': '键盘'},
    {'name': 'NuPhy Air75 V2',                   'brand': 'NuPhy',    'category': '键盘'},
    {'name': 'MonsGeek M1',                      'brand': 'MonsGeek', 'category': '键盘'},

    # ═══════════════════════════════════════════════
    # 🎮 游戏主机/掌机 (2024-2026)
    # ═══════════════════════════════════════════════
    {'name': 'Sony PS5 Pro',                     'brand': 'Sony',     'category': '游戏机'},
    {'name': 'Sony PS5 Slim',                    'brand': 'Sony',     'category': '游戏机'},
    {'name': 'Xbox Series X',                    'brand': 'Microsoft','category': '游戏机'},
    {'name': 'Xbox Series S',                    'brand': 'Microsoft','category': '游戏机'},
    {'name': 'Nintendo Switch 2',                'brand': 'Nintendo', 'category': '游戏机'},
    {'name': 'Nintendo Switch OLED',             'brand': 'Nintendo', 'category': '游戏机'},
    {'name': 'ASUS ROG Ally X',                  'brand': 'ASUS',     'category': '游戏机'},
    {'name': 'ASUS ROG Ally',                    'brand': 'ASUS',     'category': '游戏机'},
    {'name': 'Lenovo Legion Go',                 'brand': 'Lenovo',   'category': '游戏机'},
    {'name': 'Steam Deck OLED',                  'brand': 'Valve',    'category': '游戏机'},
    {'name': 'MSI Claw',                         'brand': 'MSI',     'category': '游戏机'},

    # ═══════════════════════════════════════════════
    # 📡 路由器/网络 (2024-2026)
    # ═══════════════════════════════════════════════
    {'name': 'ASUS ROG Rapture GT-BE19000',      'brand': 'ASUS',     'category': '路由器'},
    {'name': 'ASUS RT-AX86U Pro',                'brand': 'ASUS',     'category': '路由器'},
    {'name': 'ASUS GT-AX11000 Pro',              'brand': 'ASUS',     'category': '路由器'},
    {'name': 'TP-Link Archer BE800',             'brand': 'TP-Link',  'category': '路由器'},
    {'name': 'TP-Link Archer AX11000',           'brand': 'TP-Link',  'category': '路由器'},
    {'name': 'TP-Link Deco X95',                 'brand': 'TP-Link',  'category': '路由器'},
    {'name': 'Ubiquiti UniFi 7 Pro',             'brand': 'Ubiquiti', 'category': '路由器'},
    {'name': 'Ubiquiti Dream Router 7',          'brand': 'Ubiquiti', 'category': '路由器'},
    {'name': 'MikroTik RB5009',                  'brand': 'MikroTik', 'category': '路由器'},
    {'name': 'MikroTik RB4011',                  'brand': 'MikroTik', 'category': '路由器'},
    {'name': 'Xiaomi Router BE7000',             'brand': 'Xiaomi',   'category': '路由器'},
    {'name': 'Netgear Nighthawk RS700',          'brand': 'Netgear',  'category': '路由器'},
    {'name': 'GL.iNet GL-MT6000',                'brand': 'GL.iNet',  'category': '路由器'},

    # ═══════════════════════════════════════════════
    # 🖨️ 打印机 (常用机型)
    # ═══════════════════════════════════════════════
    {'name': 'HP LaserJet M209dwe',              'brand': 'HP',       'category': '打印机'},
    {'name': 'HP OfficeJet Pro 9015e',            'brand': 'HP',       'category': '打印机'},
    {'name': 'Brother HL-L2350DW',               'brand': 'Brother',  'category': '打印机'},
    {'name': 'Canon PIXMA G3270',                'brand': 'Canon',    'category': '打印机'},
    {'name': 'Epson EcoTank L3256',              'brand': 'Epson',    'category': '打印机'},

    # ═══════════════════════════════════════════════
    # 🏠 智能音箱/智能家居 (2024-2026)
    # ═══════════════════════════════════════════════
    {'name': 'Apple HomePod mini',               'brand': 'Apple',    'category': '智能音箱'},
    {'name': 'Apple HomePod 2',                  'brand': 'Apple',    'category': '智能音箱'},
    {'name': 'Amazon Echo Dot 5',                'brand': 'Amazon',   'category': '智能音箱'},
    {'name': 'Google Nest Audio',                'brand': 'Google',   'category': '智能音箱'},
    {'name': 'Xiaomi Smart Speaker Pro',          'brand': 'Xiaomi',   'category': '智能音箱'},
    {'name': 'Huawei Sound X 2024',              'brand': 'Huawei',   'category': '智能音箱'},
    {'name': 'Xiaomi Smart Hub 2',               'brand': 'Xiaomi',   'category': '智能家居'},
    {'name': 'TP-Link Tapo C425',                'brand': 'TP-Link',  'category': '智能家居'},
    {'name': 'Xiaomi Robot Vacuum X20+',          'brand': 'Xiaomi',   'category': '智能家居'},
    {'name': 'Dreame Bot L20 Ultra',             'brand': 'Dreame',   'category': '智能家居'},
    {'name': 'Nest Learning Thermostat 4',        'brand': 'Google',   'category': '智能家居'},
    {'name': 'Philips Hue Play Gradient',        'brand': 'Philips',  'category': '智能家居'},
    {'name': 'SwitchBot Hub 2',                  'brand': 'SwitchBot','category': '智能家居'},
]


def init_sample_products():
    """初始化全品类商品数据库。

    首次启动时自动导入 ALL_PRODUCTS。
    之后新品发布时，管理员可通过网页添加商品，系统自动获取价格。
    """
    from blog.models import db, Product

    if Product.query.first() is not None:
        return

    for item in ALL_PRODUCTS:
        p = Product(name=item['name'], brand=item['brand'], category=item['category'],
                    specs=_generate_specs(item['name'], item['brand'], item['category']))
        db.session.add(p)
    db.session.commit()
    logger.info('已初始化 %d 个商品，覆盖 %d 个品类',
                len(ALL_PRODUCTS),
                len(set(p['category'] for p in ALL_PRODUCTS)))


def get_ref_price(category):
    """返回品类参考价格。"""
    ref = {
        'CPU': 3299, '显卡': 6999, '内存': 899, '固态硬盘': 999,
        '主板': 2499, '电源': 899, '散热器': 599, '机箱': 699,
        '显示器': 3999, '手机': 5999, '平板': 4999, '笔记本': 8999,
        '耳机': 1999, '手表': 3999, '相机': 15999, '鼠标': 499,
        '键盘': 799, '游戏机': 3999, '路由器': 999,
    }
    return ref.get(category, 1000)


def _generate_specs(name, brand, category):
    """根据品类自动生成关键规格参数。"""
    name_lower = name.lower()

    if category == 'CPU':
        core_count = '16C/32T' if '9' in name and 'Ultra 9' in name else \
                     '8C/16T' if '7' in name and '9700' in name else \
                     '8C/16T' if '7' in name else \
                     '6C/12T' if '5' in name else '4C/8T'
        socket = 'LGA1851' if 'Ultra' in name else \
                 'AM5' if 'Ryzen' in name else 'LGA1700'
        tdp = '125W' if '9' in name or '7' in name else '65W'
        return {'核心/线程': core_count, '接口': socket, 'TDP': tdp, '架构': 'Zen 5' if '9000' in name else 'Arrow Lake' if 'Ultra' in name else 'Raptor Lake'}

    if category == '显卡':
        vram = '24GB' if '5090' in name or '4090' in name else \
               '16GB' if '5080' in name or '4080' in name or '7900' in name else \
               '12GB' if '5070' in name or '4070' in name else '8GB'
        return {'显存': vram, '显存类型': 'GDDR7' if '50' in name else 'GDDR6X', '接口': 'PCIe 5.0'}

    if category == '内存':
        size = '32GB (2×16GB)' if '32GB' in name else '16GB (2×8GB)'
        speed = '6000MHz' if '6000' in name else '5600MHz'
        return {'容量': size, '频率': speed, '类型': 'DDR5', '散热': '铝合金散热片'}

    if category == '固态硬盘':
        size = '2TB' if '2TB' in name else '1TB'
        return {'容量': size, '接口': 'M.2 NVMe PCIe 4.0', '顺序读取': '7450MB/s' if '990' in name else '7300MB/s', '顺序写入': '6900MB/s'}

    if category == '主板':
        chipset = 'Z890' if 'Z890' in name else 'Z790' if 'Z790' in name else \
                  'X870E' if 'X870' in name else 'X670E' if 'X670' in name else \
                  'B760' if 'B760' in name else 'B650'
        socket_mb = 'LGA1851' if chipset.startswith('Z8') else \
                    'LGA1700' if chipset == 'Z790' or chipset == 'B760' else 'AM5'
        return {'芯片组': chipset, 'CPU插槽': socket_mb, '内存插槽': '4×DDR5', 'PCIe': 'PCIe 5.0'}

    if category == '电源':
        wattage = '1000W' if '1000' in name else '850W'
        return {'功率': wattage, '认证': '80+ Gold', '模组化': '全模组', '风扇': '135mm'}

    if category == '散热器':
        return {'类型': '360mm AIO' if '360' in name or 'X73' in name or 'H150' in name else '风冷', '风扇': '3×120mm' if '360' in name else '双塔', 'TDP': '280W+' if '360' in name or 'D15' in name else '260W', '兼容': 'Intel LGA1851/1700 & AMD AM5'}

    if category == '机箱':
        return {'类型': 'ATX中塔', '主板兼容': 'ATX / M-ATX / ITX', '显卡限长': '420mm', '散热器限高': '170mm'}

    if category == '显示器':
        size_disp = '27"' if '27' in name else '32"' if '32' in name else '34"'
        panel = 'OLED' if 'OLED' in name or 'OLED' in name else 'IPS'
        res = '4K UHD' if '4K' in name else '3440×1440' if '34' in name else '4K'
        return {'尺寸': size_disp, '面板': panel, '分辨率': res, '刷新率': '240Hz' if '240' in name else '144Hz'}

    if category == '手机':
        soc = 'A19 Pro' if 'iPhone 16' in name else \
              'Snapdragon 8 Elite' if 'Samsung' in name or 'OnePlus' in name or 'Xiaomi' in name else \
              'Tensor G5' if 'Pixel' in name else '麒麟9010'
        screen = '6.9"' if 'Pro Max' in name or 'Ultra' in name else '6.3"' if 'Pro' in name else '6.1"'
        return {'处理器': soc, '屏幕': screen, 'RAM': '12GB' if 'Pro' in name else '8GB', '存储': '256GB'}

    if category == '平板':
        return {'处理器': 'Apple M4' if 'M4' in name else 'Apple M3', '屏幕': '13"' if '13' in name else '11"', '存储': '256GB', '系统': 'iPadOS'}

    if category == '笔记本':
        cpu_nb = 'Apple M4' if 'MacBook' in name and 'M4' in name else 'Apple M4 Pro' if 'M4 Pro' in name else \
                 'Core Ultra 9' if 'ROG' in name else 'Core Ultra 7'
        ram_nb = '24GB统一内存' if 'MacBook' in name else '32GB DDR5'
        return {'处理器': cpu_nb, '内存': ram_nb, '存储': '512GB SSD' if 'Air' in name else '1TB SSD', '屏幕': '13.6"' if 'Air' in name else '14.2"' if 'Pro' in name else '16"'}

    if category == '耳机':
        driver = '40mm' if 'WH-1000' in name or 'Momentum' in name else 'H2芯片' if 'AirPods' in name else '35mm'
        anc = '自适应降噪' if 'Ultra' in name or '1000X' in name else '主动降噪'
        return {'驱动单元': driver, '降噪': anc, '续航': '30h' if '1000X' in name or 'Ultra' in name else '6h', '连接': '蓝牙 5.3'}

    if category == '手表':
        chip = 'Apple S9 SiP' if 'Apple' in name else 'Exynos W1000'
        screen_watch = '49mm' if 'Ultra' in name else '45mm'
        return {'芯片': chip, '表盘': screen_watch, '防水': '100m' if 'Ultra' in name else '50m', '续航': '72h' if 'Ultra' in name else '36h'}

    if category == '相机':
        sensor = '全画幅' if 'A7' in name or 'R5' in name or 'Z8' in name else 'APS-C'
        mp = '61MP' if 'R5' in name else '50MP' if 'Z8' in name else '45MP' if 'A7' in name else '40MP'
        return {'传感器': sensor, '有效像素': mp, '防抖': '机身5轴防抖', '视频': '8K 30p'}

    if category == '鼠标':
        sensor_ms = 'HERO 2' if 'Logitech' in name else 'Focus Pro 30K'
        return {'传感器': sensor_ms, '连接': '无线 2.4G / 蓝牙', '续航': '70h' if 'Logitech' in name else '90h', '重量': '60g'}

    if category == '键盘':
        return {'类型': '机械键盘', '轴体': '热插拔', '连接': '有线/无线/蓝牙', '布局': '75%'}

    if category == '游戏机':
        soc_console = '定制 AMD Ryzen Zen 2' if 'PS5' in name else '定制 NVIDIA'
        storage_console = '2TB SSD' if 'Pro' in name else '1TB SSD'
        return {'处理器': soc_console, '存储': storage_console, '光线追踪': '支持', 'HDR': '支持'}

    if category == '路由器':
        wifi = 'WiFi 7' if 'AX' not in name else 'WiFi 6'
        speed_router = '11000Mbps' if '11000' in name else '10000Mbps'
        return {'WiFi标准': wifi, '速度': speed_router, '频段': '三频', '天线': '8根'}

    return {}
