# -*- coding: utf-8 -*-
"""
HOSHINO Blog — 价格爬虫模块

数据来源（按优先级）：
  1. Baidu 搜索价格提取 — 百度搜索结果页解析（Selenium）
  2. Suning / ZOL 页面价格 — 产品报价网站解析（Selenium）
  3. 手动录入             — 管理员网页输入（最后保障）

依赖：
  - Docker: selenium/standalone-chromium:latest 容器
  - Python: selenium, cloudscraper
"""
import re
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from .models import db, ProductSource, PriceRecord, Product

logger = logging.getLogger(__name__)

_MAX_WORKERS = 2
_SELENIUM_URL = 'http://localhost:4444/wd/hub'
_BROWSER_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'


# ═══════════════════════════════════════════════
# Selenium 工具
# ═══════════════════════════════════════════════

def _create_driver():
    """创建远程 Selenium WebDriver 实例。"""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('user-agent=' + _BROWSER_UA)
    return webdriver.Remote(
        command_executor=_SELENIUM_URL,
        options=options,
    )


# ═══════════════════════════════════════════════
# Baidu 搜索价格提取
# ═══════════════════════════════════════════════

def crawl_via_baidu(product_name):
    """通过百度搜索 + Selenium 提取产品价格。

    Args:
        product_name: 产品名称，如 'iPhone 16 Pro Max'

    Returns:
        float: 价格，失败返回 None
    """
    driver = None
    try:
        driver = _create_driver()
        query = f'{product_name} 价格'
        driver.get(f'https://www.baidu.com/s?wd={query}')
        import time
        time.sleep(2)

        html = driver.page_source

        # 多重价格模式提取
        prices = set()
        patterns = [
            r'(?:价格|售价|到手价)[：:\s]*[¥￥]?\s*([\d,]+(?:\.\d{2})?)',
            r'[¥￥]\s*([\d,]+(?:\.\d{2})?)',
            r'([\d,]+(?:\.\d{2})?)\s*元',
        ]
        for pat in patterns:
            for m in re.finditer(pat, html):
                try:
                    v = float(m.group(1).replace(',', ''))
                    if 100 < v < 99999:
                        prices.add(v)
                except (ValueError, IndexError):
                    continue

        if not prices:
            return None

        # 取中位数范围的平均值（去掉头尾25%异常值）
        sorted_p = sorted(prices)
        n = len(sorted_p)
        if n >= 4:
            mid = sorted_p[n // 4: 3 * n // 4]
            return round(sum(mid) / len(mid), 2)
        return sorted_p[0]

    except Exception as e:
        logger.error('Baidu 搜索失败 %s: %s', product_name, e)
        return None
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


# ═══════════════════════════════════════════════
# 通用价格提取
# ═══════════════════════════════════════════════

def crawl_price(site, url):
    """爬取价格入口。"""
    # 尝试 Selenium + 页面解析
    driver = None
    try:
        driver = _create_driver()
        driver.get(url)
        import time
        time.sleep(3)
        html = driver.page_source

        for pat in [
            r'"price"[^}]*?"pc"\s*:\s*([\d.]+)',
            r'data-price="([\d.]+)"',
            r'jdPrice["\']?\s*[:=]\s*["\']?([\d.]+)',
            r'"salePrice"\s*:\s*"([\d.]+)"',
            r'"priceDisplay"\s*:\s*"([\d.]+)"',
            r'¥([\d.]+)',
        ]:
            m = re.search(pat, html)
            if m:
                try:
                    val = float(m.group(1))
                    if 1 < val < 9999999:
                        return val
                except ValueError:
                    continue
    except Exception as e:
        logger.debug('Selenium 页面解析失败 %s: %s', url, e)
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    return None


def crawl_all_active_sources():
    """爬取所有商品价格。"""
    products = Product.query.all()
    count = 0

    for product in products:
        logger.info('正在爬取: %s', product.name)
        price = crawl_via_baidu(product.name)

        if price is not None:
            source = ProductSource.query.filter_by(
                product_id=product.id, site='baidu'
            ).first()
            if not source:
                source = ProductSource(
                    product_id=product.id, site='baidu',
                    url='', is_active=True,
                )
                db.session.add(source)
                db.session.flush()

            record = PriceRecord(
                source_id=source.id,
                product_id=product.id,
                price=price,
            )
            db.session.add(record)
            source.latest_price = price
            count += 1
            logger.info('✅ %s → ¥%.0f', product.name, price)
        else:
            logger.warning('❌ %s: 未获取到价格', product.name)

    if count > 0:
        db.session.commit()
    logger.info('爬取完成: %d/%d 成功', count, len(products))
    return count


# ═══════════════════════════════════════════════
# 品类参考价格
# ═══════════════════════════════════════════════

CATEGORY_REF_PRICES = {
    '手机': 5999, '平板': 4999, '笔记本': 8999,
    'CPU': 3299, '显卡': 6999, '内存': 799,
    '固态硬盘': 999, '主板': 2499, '电源': 899,
    '散热器': 599, '显示器': 3999, '耳机': 1999,
    '手表': 3999, '相机': 15999, '鼠标': 499, '游戏机': 3999,
}


def get_ref_price(category):
    return CATEGORY_REF_PRICES.get(category, 0)


def init_sample_products():
    """初始化示例商品。"""
    from blog.models import db, Product, ProductSource

    if Product.query.first() is not None:
        return

    samples = [
        {'name': 'Apple iPhone 16 Pro Max',    'brand': 'Apple',  'category': '手机',
         'sources': []},
        {'name': 'Samsung Galaxy S25 Ultra',   'brand': 'Samsung','category': '手机',
         'sources': []},
        {'name': 'AMD Ryzen 7 9800X3D',        'brand': 'AMD',    'category': 'CPU',
         'sources': []},
        {'name': 'NVIDIA RTX 5090',            'brand': 'NVIDIA', 'category': '显卡',
         'sources': []},
        {'name': 'Apple MacBook Air M4',       'brand': 'Apple',  'category': '笔记本',
         'sources': []},
        {'name': 'Sony WH-1000XM5',            'brand': 'Sony',   'category': '耳机',
         'sources': []},
        {'name': 'Apple Watch Ultra 2',        'brand': 'Apple',  'category': '手表',
         'sources': []},
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
