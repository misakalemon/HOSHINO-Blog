# -*- coding: utf-8 -*-
"""
HOSHINO Blog — 价格爬虫模块

职责：
  从多个电商网站爬取电子产品最新价格，存入 MySQL。
  每个网站一个爬虫函数，统一接口。

支持的网站：
  jd       — 京东（使用价格 API: p.3.cn/prices/mgets）
  smzdm    — 什么值得买（页面解析）

扩展方式：
  在 _CRAWLERS 字典中注册新爬虫函数即可。
"""
import re
import json
import logging
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}
_TIMEOUT = 15


# ═══════════════════════════════════════════════
# 京东爬虫（使用价格 API）
# ═══════════════════════════════════════════════
def _jd_product_id(url):
    """从京东商品 URL 中提取商品 ID。"""
    m = re.search(r'/(\d+)\.html', url)
    return m.group(1) if m else None


def crawl_jd(url):
    """从京东商品页抓取价格。

    使用京东公开的价格查询 API：
      https://p.3.cn/prices/mgets?skuIds=J_{product_id}&type=1
    """
    pid = _jd_product_id(url)
    if not pid:
        logger.warning('京东 URL 解析失败: %s', url)
        return None
    api_url = f'https://p.3.cn/prices/mgets?skuIds=J_{pid}&type=1'
    try:
        resp = requests.get(api_url, headers=_HEADERS, timeout=_TIMEOUT)
        data = resp.json()
        if data and 'p' in data[0]:
            return float(data[0]['p'])
        logger.warning('京东 API 返回异常: %s', url)
        return None
    except Exception as e:
        logger.error('京东爬取异常 %s: %s', url, e)
        return None


# ═══════════════════════════════════════════════
# 什么值得买爬虫
# ═══════════════════════════════════════════════
def crawl_smzdm(url):
    """从什么值得买抓取价格。"""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.encoding = 'utf-8'
        html = resp.text
        soup = BeautifulSoup(html, 'lxml')

        price_el = soup.select_one('.price, .red')
        if price_el:
            text = price_el.get_text(strip=True)
            m = re.search(r'[\d.]+', text)
            if m:
                return float(m.group(0))
        m = re.search(r'[¥￥](\d+[\d.,]*)', html)
        if m:
            return float(m.group(1).replace(',', ''))
        return None
    except Exception as e:
        logger.error('什么值得买爬取异常 %s: %s', url, e)
        return None


# ═══════════════════════════════════════════════
# 爬虫注册表
# ═══════════════════════════════════════════════
_CRAWLERS = {
    'jd': crawl_jd,
    'smzdm': crawl_smzdm,
}


def crawl_price(site, url):
    """统一入口：根据网站代号调用对应爬虫。"""
    crawler = _CRAWLERS.get(site)
    if not crawler:
        logger.warning('不支持的网站: %s', site)
        return None
    return crawler(url)


def crawl_all_active_sources():
    """爬取所有启用的商品来源的最新价格。"""
    from blog.models import db, ProductSource, PriceRecord

    count = 0
    sources = ProductSource.query.filter_by(is_active=True).all()
    for src in sources:
        price = crawl_price(src.site, src.url)
        if price is not None:
            record = PriceRecord(
                source_id=src.id,
                product_id=src.product_id,
                price=price,
            )
            db.session.add(record)
            src.latest_price = price
            count += 1
            logger.info('价格记录: %s [%s] → %.2f', src.product.name, src.site, price)
        else:
            logger.warning('爬取失败: %s [%s] %s', src.product.name, src.site, src.url)
    if count > 0:
        db.session.commit()
    return count


def init_sample_products():
    """首次使用时添加示例商品（全品类覆盖）。"""
    from blog.models import db, Product, ProductSource

    if Product.query.first() is not None:
        return

    samples = [
        # ═══ 手机 ═══
        {'name': 'Apple iPhone 16 Pro Max',     'brand': 'Apple',  'category': '手机',
         'sources': [('jd', 'https://item.jd.com/100174572548.html')]},
        {'name': 'Samsung Galaxy S25 Ultra',    'brand': 'Samsung','category': '手机',
         'sources': [('jd', 'https://item.jd.com/100108355715.html')]},
        {'name': 'Xiaomi 15 Pro',               'brand': 'Xiaomi', 'category': '手机',
         'sources': [('jd', 'https://item.jd.com/100131956936.html')]},
        {'name': 'Huawei Mate 70 Pro',          'brand': 'Huawei', 'category': '手机',
         'sources': [('jd', 'https://item.jd.com/100116726437.html')]},
        {'name': 'OPPO Find X8 Pro',            'brand': 'OPPO',   'category': '手机',
         'sources': [('jd', 'https://item.jd.com/100164281995.html')]},

        # ═══ 平板 ═══
        {'name': 'Apple iPad Pro M4 13"',       'brand': 'Apple',  'category': '平板',
         'sources': [('jd', 'https://item.jd.com/100141480906.html')]},
        {'name': 'Apple iPad Air M3 11"',       'brand': 'Apple',  'category': '平板',
         'sources': [('jd', 'https://item.jd.com/100150126742.html')]},
        {'name': 'Samsung Galaxy Tab S10 Ultra','brand': 'Samsung','category': '平板',
         'sources': [('jd', 'https://item.jd.com/100164153307.html')]},

        # ═══ 笔记本 ═══
        {'name': 'Apple MacBook Air M4',        'brand': 'Apple',  'category': '笔记本',
         'sources': [('jd', 'https://item.jd.com/100177944530.html')]},
        {'name': 'Apple MacBook Pro 14 M4 Pro', 'brand': 'Apple',  'category': '笔记本',
         'sources': [('jd', 'https://item.jd.com/100173659642.html')]},
        {'name': 'ThinkPad X1 Carbon Gen 13',   'brand': 'Lenovo', 'category': '笔记本',
         'sources': [('jd', 'https://item.jd.com/100193112338.html')]},
        {'name': 'ASUS ROG 幻 16 Air',          'brand': 'ASUS',   'category': '笔记本',
         'sources': [('jd', 'https://item.jd.com/100126600659.html')]},
        {'name': 'Dell XPS 16',                 'brand': 'Dell',   'category': '笔记本',
         'sources': [('jd', 'https://item.jd.com/100181315793.html')]},

        # ═══ 台式机配件 ═══
        {'name': 'Intel Core Ultra 9 285K',     'brand': 'Intel',  'category': 'CPU',
         'sources': [('jd', 'https://item.jd.com/100170268454.html')]},
        {'name': 'AMD Ryzen 7 9800X3D',         'brand': 'AMD',    'category': 'CPU',
         'sources': [('jd', 'https://item.jd.com/100175189830.html')]},
        {'name': 'NVIDIA RTX 5090',             'brand': 'NVIDIA', 'category': '显卡',
         'sources': [('jd', 'https://item.jd.com/100193916771.html')]},
        {'name': 'NVIDIA RTX 5080',             'brand': 'NVIDIA', 'category': '显卡',
         'sources': [('jd', 'https://item.jd.com/100193917115.html')]},
        {'name': 'AMD Radeon RX 9070 XT',       'brand': 'AMD',    'category': '显卡',
         'sources': [('jd', 'https://item.jd.com/100194564188.html')]},
        {'name': 'Kingston DDR5 32GB 6000MHz',  'brand': 'Kingston','category': '内存',
         'sources': [('jd', 'https://item.jd.com/100062247258.html')]},
        {'name': 'Samsung 990 Pro 2TB NVMe',    'brand': 'Samsung','category': '固态硬盘',
         'sources': [('jd', 'https://item.jd.com/100036241965.html')]},
        {'name': 'ASUS ROG STRIX Z890-E',       'brand': 'ASUS',   'category': '主板',
         'sources': [('jd', 'https://item.jd.com/100170952762.html')]},
        {'name': 'Corsair RM850x 850W',         'brand': 'Corsair','category': '电源',
         'sources': [('jd', 'https://item.jd.com/100015925463.html')]},
        {'name': 'NZXT Kraken X73 360mm',       'brand': 'NZXT',   'category': '散热器',
         'sources': [('jd', 'https://item.jd.com/100016003235.html')]},

        # ═══ 显示器 ═══
        {'name': 'Dell U2724D 4K 27"',          'brand': 'Dell',   'category': '显示器',
         'sources': [('jd', 'https://item.jd.com/100074454893.html')]},
        {'name': 'ASUS ROG PG32UCDM 4K OLED',   'brand': 'ASUS',   'category': '显示器',
         'sources': [('jd', 'https://item.jd.com/100093863807.html')]},

        # ═══ 耳机 ═══
        {'name': 'Apple AirPods Pro 2 USB-C',   'brand': 'Apple',  'category': '耳机',
         'sources': [('jd', 'https://item.jd.com/100049970733.html')]},
        {'name': 'Sony WH-1000XM5',             'brand': 'Sony',   'category': '耳机',
         'sources': [('jd', 'https://item.jd.com/100038261160.html')]},
        {'name': 'Bose QC Ultra',               'brand': 'Bose',   'category': '耳机',
         'sources': [('jd', 'https://item.jd.com/100060138638.html')]},

        # ═══ 智能穿戴 ═══
        {'name': 'Apple Watch Ultra 2',          'brand': 'Apple',  'category': '手表',
         'sources': [('jd', 'https://item.jd.com/100142494883.html')]},
        {'name': 'Samsung Galaxy Watch 7',       'brand': 'Samsung','category': '手表',
         'sources': [('jd', 'https://item.jd.com/100144540042.html')]},

        # ═══ 相机 ═══
        {'name': 'Sony A7M5 (A7 V)',            'brand': 'Sony',   'category': '相机',
         'sources': [('jd', 'https://item.jd.com/100145120855.html')]},
        {'name': 'Canon EOS R5 Mark II',        'brand': 'Canon',  'category': '相机',
         'sources': [('jd', 'https://item.jd.com/100157916372.html')]},

        # ═══ 键鼠外设 ═══
        {'name': 'Logitech MX Master 3S',       'brand': 'Logitech','category': '鼠标',
         'sources': [('jd', 'https://item.jd.com/100032446103.html')]},
        {'name': 'Razer DeathAdder V3 Pro',     'brand': 'Razer',  'category': '鼠标',
         'sources': [('jd', 'https://item.jd.com/100052291508.html')]},

        # ═══ 游戏主机 ═══
        {'name': 'Sony PS5 Pro',                'brand': 'Sony',   'category': '游戏机',
         'sources': [('jd', 'https://item.jd.com/100142386543.html')]},
        {'name': 'Nintendo Switch 2',           'brand': 'Nintendo','category': '游戏机',
         'sources': [('jd', 'https://item.jd.com/100181387730.html')]},
    ]

    for item in samples:
        product = Product(name=item['name'], brand=item['brand'], category=item['category'])
        db.session.add(product)
        db.session.flush()
        for site, url in item['sources']:
            source = ProductSource(product_id=product.id, site=site, url=url)
            db.session.add(source)
    db.session.commit()
    logger.info('已添加 %d 个示例商品，覆盖全品类', len(samples))
