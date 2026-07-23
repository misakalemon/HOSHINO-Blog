"""
HOSHINO Blog — Amazon 价格爬虫

职责：
   使用 curl_cffi 模拟 Chrome 浏览器指纹直爬 Amazon 商品页面，
   获取商品价格信息。支持 HTTP 代理（服务器在国内时必须使用海外代理）。

技术要点：
   - curl_cffi.impersonate='chrome'：模拟 Chrome TLS 指纹，绕过 Cloudflare 反爬
   - BeautifulSoup 解析 Amazon 搜索结果和商品详情页
   - 重试机制：最多 3 次，指数退避
   - 价格选择器优先级：a-price > priceblock_ourprice > priceblock_dealprice > a-price-whole

使用方式：
   from blog.apify_client import scraper
   scraper._proxy = 'http://user:pass@host:port'  # 可选
   price = scraper.get_price('B0XXXXX')
"""

import logging
import re
import time
from urllib.parse import quote

from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests

logger = logging.getLogger(__name__)

# Amazon 搜索/商品页 URL 模板
_AMAZON_SEARCH = 'https://www.amazon.com/s?k={}'
_AMAZON_PRODUCT = 'https://www.amazon.com/dp/{}'
_MAX_RETRIES = 3        # 最大重试次数
_RETRY_DELAY = 5        # 重试基础延迟（秒），实际延迟 = _RETRY_DELAY × (attempt + 1)
_REQUEST_DELAY = 2.0    # 请求间隔（秒），预留防风控


class AmazonScraper:
    """Amazon 价格爬虫（curl_cffi + BeautifulSoup 直爬）。
    
    使用 curl_cffi 模拟 Chrome 浏览器 TLS 指纹，绕过 Amazon 的 Cloudflare 反爬机制。
    支持通过 HTTP 代理访问（国内服务器必须配置海外代理）。
    """

    def __init__(self):
        self._ready = True
        self._proxy = None  # HTTP 代理地址，由 app.py 在启动时设置

    def _get(self, url, timeout=10):
        """发送 HTTP GET 请求，带重试和代理支持。
        
        使用 curl_cffi 的 impersonate='chrome' 模拟 Chrome 浏览器指纹，
        绕过 Cloudflare 等 TLS 指纹检测。失败时指数退避重试。
        
        Args:
            url: 请求 URL
            timeout: 请求超时秒数
            
        Returns:
            Response 对象（成功时）或 None（所有重试均失败时）
        """
        kwargs = {'impersonate': 'chrome', 'timeout': timeout}
        if self._proxy:
            kwargs['proxies'] = {'http': self._proxy, 'https': self._proxy}
        for attempt in range(_MAX_RETRIES):
            try:
                r = curl_requests.get(url, **kwargs)
                if r.status_code == 200:
                    return r
                logger.warning('Amazon 请求失败 (尝试 %d/%d): %s → %s',
                               attempt + 1, _MAX_RETRIES, url[:60], r.status_code)
            except Exception as e:
                logger.warning('Amazon 请求异常 (尝试 %d/%d): %s: %s',
                               attempt + 1, _MAX_RETRIES, url[:60], e)
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_DELAY * (attempt + 1))
        return None

    def _search(self, keyword):
        url = _AMAZON_SEARCH.format(quote(keyword))
        r = self._get(url)
        if r is None:
            return None
        try:
            soup = BeautifulSoup(r.text, 'html.parser')
        except Exception as e:
            logger.warning('Amazon 搜索页解析失败: %s', e)
            return None
        results = []
        for item in soup.select('div[data-component-type="s-search-result"]'):
            asin = item.get('data-asin', '')
            if not asin:
                continue
            title_el = item.select_one('h2')
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            results.append({'asin': asin, 'title': title})
        return results

    def _parse_price(self, asin):
        url = _AMAZON_PRODUCT.format(asin)
        r = self._get(url)
        if r is None:
            return None
        try:
            soup = BeautifulSoup(r.text, 'html.parser')
        except Exception as e:
            logger.warning('Amazon 商品页解析失败 %s: %s', asin, e)
            return None

        for sel in ['.a-price .a-offscreen', '#priceblock_ourprice',
                     '#priceblock_dealprice', '.a-price-whole']:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(strip=True)
                nums = re.findall(r'[\d,]+\.?\d*', text)
                if nums:
                    try:
                        return float(nums[0].replace(',', ''))
                    except (ValueError, IndexError):
                        pass
        return None

    @staticmethod
    def _title_matches(asin_title, search_keyword):
        kw_lower = search_keyword.lower()
        title_lower = asin_title.lower()
        if kw_lower in title_lower:
            return True
        kw_tokens = set(re.findall(r'[a-zA-Z0-9]+', kw_lower))
        title_tokens = set(re.findall(r'[a-zA-Z0-9]+', title_lower))
        common = [t for t in (kw_tokens & title_tokens) if len(t) >= 3]
        return len(common) >= 2

    def fetch_amazon_price(self, product_name):
        results = self._search(product_name)
        if not results:
            return None
        for item in results:
            if self._title_matches(item['title'], product_name):
                time.sleep(_REQUEST_DELAY)
                price = self._parse_price(item['asin'])
                if price:
                    return price
        return None


scraper = AmazonScraper()
