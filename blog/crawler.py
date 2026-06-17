# -*- coding: utf-8 -*-
"""
HOSHINO Blog — 价格爬虫模块

职责：
  从多个电商网站爬取电子产品最新价格，存入 MySQL。
  每个网站一个爬虫函数，统一接口。

支持的网站：
  jd       — 京东商品页价格提取
  smzdm    — 什么值得买价格提取
  suning   — 苏宁易购价格提取（占位）

扩展方式：
  在 _CRAWLERS 字典中注册新爬虫函数即可。
  函数签名：def crawl_xxx(url: str) -> float | None
"""
import re
import logging
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# 请求头，模拟浏览器访问
_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}

# 请求超时（秒）
_TIMEOUT = 15


# ── 各网站爬虫 ─────────────────────────────

def crawl_jd(url):
    """从京东商品页抓取价格。

    京东价格数据通过页面内嵌的 JSON 传递：
      window.pageConfig = {... price: { pc: 123.00 } ...}
    或通过 data-price 属性。

    Args:
        url: 京东商品页 URL

    Returns:
        float: 价格，失败返回 None
    """
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.encoding = 'utf-8'
        html = resp.text

        # 方式1：从页面 JSON 配置中提取 price.pc
        m = re.search(r'"price"\s*:\s*\{[^}]*?"pc"\s*:\s*([\d.]+)', html)
        if m:
            return float(m.group(1))

        # 方式2：从 data-price 属性提取
        m = re.search(r'data-price="([\d.]+)"', html)
        if m:
            return float(m.group(1))

        # 方式3：从价格标签提取
        soup = BeautifulSoup(html, 'lxml')
        price_el = soup.select_one('.p-price .price, .J-p-')
        if price_el:
            text = price_el.get_text(strip=True)
            m = re.search(r'[\d.]+', text)
            if m:
                return float(m.group(0))

        logger.warning('京东价格提取失败: %s', url)
        return None
    except Exception as e:
        logger.error('京东爬取异常 %s: %s', url, e)
        return None


def crawl_smzdm(url):
    """从什么值得买抓取价格。

    价格通常在商品标题附近或价格标签内。

    Args:
        url: 什么值得买商品页 URL

    Returns:
        float: 价格，失败返回 None
    """
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.encoding = 'utf-8'
        html = resp.text
        soup = BeautifulSoup(html, 'lxml')

        # 方式1：价格标签
        price_el = soup.select_one('.price, .red')
        if price_el:
            text = price_el.get_text(strip=True)
            m = re.search(r'[\d.]+', text)
            if m:
                return float(m.group(0))

        # 方式2：页面标题中的价格
        m = re.search(r'[¥￥](\d+[\d.,]*)', html)
        if m:
            return float(m.group(1).replace(',', ''))

        logger.warning('什么值得买价格提取失败: %s', url)
        return None
    except Exception as e:
        logger.error('什么值得买爬取异常 %s: %s', url, e)
        return None


# ── 爬虫注册表 ─────────────────────────────
# 新增网站时，在此注册即可
_CRAWLERS = {
    'jd': crawl_jd,
    'smzdm': crawl_smzdm,
}


def crawl_price(site, url):
    """统一入口：根据网站代号调用对应爬虫。

    Args:
        site: 网站代号（如 'jd', 'smzdm'）
        url: 商品页 URL

    Returns:
        float: 价格，失败返回 None
    """
    crawler = _CRAWLERS.get(site)
    if not crawler:
        logger.warning('不支持的网站: %s', site)
        return None
    return crawler(url)


def crawl_all_active_sources():
    """爬取所有启用的商品来源的最新价格。

    从数据库读取 is_active=True 的 ProductSource，
    逐个调用对应爬虫，并将结果写入 PriceRecord 表。

    此函数供每日定时任务调用。

    Returns:
        int: 成功爬取的记录数
    """
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
    """首次使用时添加示例商品（数据库中无商品时调用）。

    提供几款常见电子产品的京东链接作为演示。
    """
    from blog.models import db, Product, ProductSource

    if Product.query.first() is not None:
        return  # 已有商品，跳过

    samples = [
        {
            'name': 'Apple AirPods Pro 2',
            'brand': 'Apple',
            'category': '耳机',
            'sources': [
                ('jd', 'https://item.jd.com/100049970733.html'),
            ],
        },
        {
            'name': 'Sony WH-1000XM5',
            'brand': 'Sony',
            'category': '耳机',
            'sources': [
                ('jd', 'https://item.jd.com/100038261160.html'),
            ],
        },
        {
            'name': 'Apple iPhone 16 Pro',
            'brand': 'Apple',
            'category': '手机',
            'sources': [
                ('jd', 'https://item.jd.com/100174572548.html'),
            ],
        },
        {
            'name': 'Apple MacBook Air M3',
            'brand': 'Apple',
            'category': '笔记本',
            'sources': [
                ('jd', 'https://item.jd.com/100075578404.html'),
            ],
        },
    ]

    for item in samples:
        product = Product(
            name=item['name'],
            brand=item['brand'],
            category=item['category'],
        )
        db.session.add(product)
        db.session.flush()  # 获取 product.id

        for site, url in item['sources']:
            source = ProductSource(
                product_id=product.id,
                site=site,
                url=url,
            )
            db.session.add(source)

    db.session.commit()
    logger.info('已添加 %d 个示例商品', len(samples))
