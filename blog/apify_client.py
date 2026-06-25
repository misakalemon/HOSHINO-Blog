import re
import logging
from urllib.parse import quote
from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_AMAZON_SEARCH = 'https://www.amazon.com/s?k={}'
_AMAZON_PRODUCT = 'https://www.amazon.com/dp/{}'


class AmazonScraper:
    """Amazon 价格爬虫（curl_cffi + BeautifulSoup 直爬）。"""

    def __init__(self):
        self._ready = True
        self._proxy = None

    def set_proxy(self, proxy_url):
        self._proxy = proxy_url

    def _get(self, url, timeout=5):
        kwargs = {'impersonate': 'chrome', 'timeout': timeout}
        if self._proxy:
            kwargs['proxies'] = {'http': self._proxy, 'https': self._proxy}
        return curl_requests.get(url, **kwargs)

    def _search(self, keyword):
        url = _AMAZON_SEARCH.format(quote(keyword))
        r = self._get(url)
        if r.status_code != 200:
            logger.warning('Amazon 搜索失败: %s → %s', keyword[:30], r.status_code)
            return None
        soup = BeautifulSoup(r.text, 'lxml')
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
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, 'lxml')

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
                price = self._parse_price(item['asin'])
                if price:
                    return price
        return None


scraper = AmazonScraper()
