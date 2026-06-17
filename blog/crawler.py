# -*- coding: utf-8 -*-
"""
HOSHINO Blog — 价格爬虫模块

多平台价格抓取：
  jd       — 京东（页面解析 + 正则）
  smzdm    — 什么值得买（页面解析）
  suning   — 苏宁易购（页面解析）
  yixun    — 易迅（占位）

特性：
  - 并发爬取（ThreadPoolExecutor，默认 5 线程）
  - 超时控制（8s 单次，超时跳过不阻塞）
  - 错误分级，降级友好
"""
import re
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'zh-CN,zh;q=0.9',
}
_TIMEOUT = 8
_MAX_WORKERS = 5


# ═══════════════════════════════════════════════
# 通用工具
# ═══════════════════════════════════════════════

def _fetch_html(url, headers=None):
    """抓取页面 HTML，失败返回 None。"""
    h = {**_HEADERS, **(headers or {})}
    try:
        r = requests.get(url, headers=h, timeout=_TIMEOUT)
        r.encoding = 'utf-8'
        return r.text if r.ok else None
    except Exception:
        return None


def _find_price_re(html, patterns):
    """从 HTML 中用多个正则依次尝试提取价格。"""
    for pat in patterns:
        m = re.search(pat, html)
        if m:
            try:
                return float(m.group(1))
            except (ValueError, IndexError):
                continue
    return None


# ═══════════════════════════════════════════════
# 京东爬虫
# ═══════════════════════════════════════════════

def crawl_jd(url):
    """京东价格抓取。

    优先级：API → 页面 JSON → 标签属性 → 价格标签
    """
    pid = re.search(r'/(\d+)\.html', url)
    pid = pid.group(1) if pid else None

    # 方式1: 页面直接提取（跳过不可用的 API）
    html = _fetch_html(url)
    if html:
        # 多个正则依次尝试
        price = _find_price_re(html, [
            r'"price"\s*:\s*\{[^}]*?"pc"\s*:\s*([\d.]+)',
            r'data-price="([\d.]+)"',
            r'<span class="price"[^>]*>([\d.]+)',
            r'<span class="p-price">\s*<span[^>]*>\s*([\d.]+)',
            r'￥([\d.]+)',
        ])
        if price:
            return price

    logger.warning('京东价格提取失败: %s', url)
    return None


# ═══════════════════════════════════════════════
# 什么值得买爬虫
# ═══════════════════════════════════════════════

def crawl_smzdm(url):
    """什么值得买价格抓取。"""
    html = _fetch_html(url)
    if not html:
        return None

    soup = BeautifulSoup(html, 'lxml')
    price_el = soup.select_one('.price, .red')
    if price_el:
        text = price_el.get_text(strip=True)
        m = re.search(r'[\d.]+', text)
        if m:
            return float(m.group(0))

    price = _find_price_re(html, [r'[¥￥](\d+[\d.,]*)'])
    if price:
        return price
    return None


# ═══════════════════════════════════════════════
# 苏宁易购爬虫
# ═══════════════════════════════════════════════

def crawl_suning(url):
    """苏宁易购价格抓取。"""
    html = _fetch_html(url)
    if not html:
        return None
    price = _find_price_re(html, [
        r'"priceDisplay"\s*:\s*"([\d.]+)"',
        r'"salePrice"\s*:\s*"([\d.]+)"',
        r'class="price-display"[^>]*>([\d.]+)',
        r'￥([\d.]+)',
    ])
    if price:
        return price
    logger.warning('苏宁价格提取失败: %s', url)
    return None


# ═══════════════════════════════════════════════
# 爬虫注册表
# ═══════════════════════════════════════════════

_CRAWLERS = {
    'jd': crawl_jd,
    'smzdm': crawl_smzdm,
    'suning': crawl_suning,
}


def crawl_price(site, url):
    """统一入口：根据网站代号调用对应爬虫。"""
    c = _CRAWLERS.get(site)
    if not c:
        logger.warning('不支持的网站: %s', site)
        return None
    return c(url)


def crawl_all_active_sources():
    """并发爬取所有启用的商品来源。"""
    from blog.models import db, ProductSource, PriceRecord

    sources = ProductSource.query.filter_by(is_active=True).all()
    if not sources:
        return 0

    results = []
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as exc:
        fut_map = {exc.submit(crawl_price, s.site, s.url): s for s in sources}
        for fut in as_completed(fut_map, timeout=120):
            s = fut_map[fut]
            try:
                price = fut.result()
            except Exception as e:
                logger.error('爬取线程异常 %s [%s]: %s', s.product.name, s.site, e)
                price = None
            results.append((s, price))

    count = 0
    for src, price in results:
        if price is not None:
            record = PriceRecord(
                source_id=src.id,
                product_id=src.product_id,
                price=price,
            )
            db.session.add(record)
            src.latest_price = price
            count += 1
            logger.info('✓ %s [%s] → ¥%.2f', src.product.name, src.site, price)
        else:
            logger.warning('✗ %s [%s] 失败', src.product.name, src.site)
    if count > 0:
        db.session.commit()
    logger.info('爬取完成: %d/%d 成功', count, len(sources))
    return count


def init_sample_products():
    """首次使用时添加示例商品（全品类覆盖 + 多平台）。"""
    from blog.models import db, Product, ProductSource

    if Product.query.first() is not None:
        return

    # 每个商品可配置多平台来源，格式: (平台代号, URL)
    samples = [
        # ═══ 手机 ═══
        {'name': 'Apple iPhone 16 Pro Max',    'brand': 'Apple',  'category': '手机',
         'sources': [('jd', 'https://item.jd.com/100174572548.html')]},
        {'name': 'Samsung Galaxy S25 Ultra',   'brand': 'Samsung','category': '手机',
         'sources': [('jd', 'https://item.jd.com/100108355715.html')]},
        {'name': 'Xiaomi 15 Pro',              'brand': 'Xiaomi', 'category': '手机',
         'sources': [('jd', 'https://item.jd.com/100131956936.html')]},
        {'name': 'Huawei Mate 70 Pro',         'brand': 'Huawei', 'category': '手机',
         'sources': [('jd', 'https://item.jd.com/100116726437.html')]},

        # ═══ 平板 ═══
        {'name': 'Apple iPad Pro M4 13"',      'brand': 'Apple',  'category': '平板',
         'sources': [('jd', 'https://item.jd.com/100141480906.html')]},

        # ═══ 笔记本 ═══
        {'name': 'Apple MacBook Air M4',       'brand': 'Apple',  'category': '笔记本',
         'sources': [('jd', 'https://item.jd.com/100177944530.html')]},
        {'name': 'ThinkPad X1 Carbon Gen 13',  'brand': 'Lenovo', 'category': '笔记本',
         'sources': [('jd', 'https://item.jd.com/100193112338.html')]},

        # ═══ CPU ═══
        {'name': 'AMD Ryzen 7 9800X3D',        'brand': 'AMD',    'category': 'CPU',
         'sources': [('jd', 'https://item.jd.com/100175189830.html')]},
        {'name': 'Intel Core Ultra 9 285K',    'brand': 'Intel',  'category': 'CPU',
         'sources': [('jd', 'https://item.jd.com/100170268454.html')]},

        # ═══ 显卡 ═══
        {'name': 'NVIDIA RTX 5090',            'brand': 'NVIDIA', 'category': '显卡',
         'sources': [('jd', 'https://item.jd.com/100193916771.html')]},
        {'name': 'NVIDIA RTX 5080',            'brand': 'NVIDIA', 'category': '显卡',
         'sources': [('jd', 'https://item.jd.com/100193917115.html')]},

        # ═══ 内存 ═══
        {'name': 'Kingston DDR5 32GB 6000',    'brand': 'Kingston','category': '内存',
         'sources': [('jd', 'https://item.jd.com/100062247258.html')]},

        # ═══ 固态硬盘 ═══
        {'name': 'Samsung 990 Pro 2TB NVMe',   'brand': 'Samsung','category': '固态硬盘',
         'sources': [('jd', 'https://item.jd.com/100036241965.html')]},

        # ═══ 主板 ═══
        {'name': 'ASUS ROG STRIX Z890-E',      'brand': 'ASUS',   'category': '主板',
         'sources': [('jd', 'https://item.jd.com/100170952762.html')]},

        # ═══ 电源 ═══
        {'name': 'Corsair RM850x 850W',        'brand': 'Corsair','category': '电源',
         'sources': [('jd', 'https://item.jd.com/100015925463.html')]},

        # ═══ 散热器 ═══
        {'name': 'NZXT Kraken X73 360mm',      'brand': 'NZXT',   'category': '散热器',
         'sources': [('jd', 'https://item.jd.com/100016003235.html')]},

        # ═══ 显示器 ═══
        {'name': 'Dell U2724D 4K 27"',         'brand': 'Dell',   'category': '显示器',
         'sources': [('jd', 'https://item.jd.com/100074454893.html')]},

        # ═══ 耳机 ═══
        {'name': 'Sony WH-1000XM5',            'brand': 'Sony',   'category': '耳机',
         'sources': [('jd', 'https://item.jd.com/100038261160.html')]},

        # ═══ 手表 ═══
        {'name': 'Apple Watch Ultra 2',         'brand': 'Apple',  'category': '手表',
         'sources': [('jd', 'https://item.jd.com/100142494883.html')]},

        # ═══ 相机 ═══
        {'name': 'Sony A7M5 (A7 V)',           'brand': 'Sony',   'category': '相机',
         'sources': [('jd', 'https://item.jd.com/100145120855.html')]},

        # ═══ 键鼠 ═══
        {'name': 'Logitech MX Master 3S',      'brand': 'Logitech','category': '鼠标',
         'sources': [('jd', 'https://item.jd.com/100032446103.html')]},

        # ═══ 游戏机 ═══
        {'name': 'Sony PS5 Pro',               'brand': 'Sony',   'category': '游戏机',
         'sources': [('jd', 'https://item.jd.com/100142386543.html')]},
    ]

    for item in samples:
        p = Product(name=item['name'], brand=item['brand'], category=item['category'])
        db.session.add(p)
        db.session.flush()
        for site, url in item['sources']:
            db.session.add(ProductSource(product_id=p.id, site=site, url=url))
    db.session.commit()
    logger.info('已添加 %d 个示例商品', len(samples))
