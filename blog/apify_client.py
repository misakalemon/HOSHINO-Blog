import logging
import re
import time
from urllib.parse import quote

from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests

logger = logging.getLogger(__name__)

_AMAZON_SEARCH = 'https://www.amazon.com/s?k={}'
_AMAZON_PRODUCT = 'https://www.amazon.com/dp/{}'
_MAX_RETRIES = 3
_RETRY_DELAY = 5
_REQUEST_DELAY = 2.0


class AmazonScraper:
    """Amazon 价格爬虫（curl_cffi + BeautifulSoup 直爬）。"""

    def __init__(self):
        self._ready = True
        self._proxy = None

    def _get(self, url, timeout=10):
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
