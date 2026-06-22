import json
import re
import time
import logging
from urllib.parse import quote
import requests
from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_AMAZON_SEARCH = 'https://www.amazon.com/s?k={}'
_AMAZON_PRODUCT = 'https://www.amazon.com/dp/{}'
_APIFY_API = 'https://api.apify.com/v2'


class AmazonScraper:
    """Amazon 价格爬虫（curl_cffi + BeautifulSoup 直爬）。"""

    def __init__(self):
        self._ready = True
        self._proxy = None

    def set_proxy(self, proxy_url):
        self._proxy = proxy_url

    def _get(self, url, timeout=30):
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


class ApifyAPIClient:
    """Apify REST API 客户端（调用 Apify Actor 爬取价格）。"""

    def __init__(self, token=None, actors=None):
        self.token = token or ''
        self._ready = bool(token)
        self._actors = [self._normalize_actor(a) for a in (actors or [])] if actors else []

    @staticmethod
    def _normalize_actor(actor_id):
        parts = actor_id.split('/')
        return f'{parts[0]}~{parts[1]}' if len(parts) == 2 else actor_id

    def _headers(self):
        return {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.token}',
        }

    def _run_actor(self, actor_id, run_input):
        if not self._ready:
            return None
        url = f'{_APIFY_API}/acts/{actor_id}/runs'
        try:
            r = requests.post(url, headers=self._headers(), json=run_input, timeout=15)
            if r.status_code == 403:
                logger.error('Apify Token 无效（403），请检查 APIFY_TOKEN')
                self._ready = False
                return None
            if not r.ok:
                logger.warning('Apify Actor 不可用 %s: %s', actor_id, r.status_code)
                return None
            run = r.json().get('data', {})
            run_id = run.get('id')
            default_kv_id = run.get('defaultKeyValueStoreId')
            default_dataset_id = run.get('defaultDatasetId')
            if not run_id:
                return None
            for _ in range(30):
                time.sleep(2)
                r2 = requests.get(f'{_APIFY_API}/acts/{actor_id}/runs/{run_id}',
                                   headers=self._headers(), timeout=10)
                status = r2.json().get('data', {}).get('status')
                if status == 'SUCCEEDED':
                    result = None
                    if default_kv_id:
                        r3 = requests.get(
                            f'{_APIFY_API}/key-value-stores/{default_kv_id}/records/OUTPUT',
                            headers=self._headers(), timeout=10
                        )
                        if r3.ok:
                            result = r3.json()
                    if result is None and default_dataset_id:
                        r3 = requests.get(
                            f'{_APIFY_API}/datasets/{default_dataset_id}/items',
                            headers=self._headers(), timeout=10
                        )
                        if r3.ok:
                            result = r3.json()
                    return result
                elif status in ('FAILED', 'ABORTED', 'TIMED-OUT'):
                    logger.warning('Apify run 失败: %s → %s', run_id, status)
                    return None
            logger.warning('Apify run 超时（60s）: %s', run_id)
            return None
        except requests.exceptions.ConnectionError:
            logger.warning('Apify API 连接失败（可能被墙）')
            return None
        except Exception as e:
            logger.error('Apify 异常: %s', e)
            return None

    def fetch_amazon_price(self, product_name):
        if not self._actors:
            logger.debug('未配置 Apify Actor，跳过: %s', product_name)
            return None
        search_url = f'https://www.amazon.com/s?k={quote(product_name)}'
        for actor in self._actors:
            result = self._run_actor(actor, {
                'categoryUrls': [{'url': search_url}],
                'maxItemsPerStartUrl': 10,
                'maxSearchPagesPerStartUrl': 1,
            })
            if result:
                prices = []
                items = result if isinstance(result, list) else []
                for item in items:
                    if item.get('error'):
                        continue
                    price = None
                    p_obj = item.get('price')
                    if isinstance(p_obj, dict):
                        price = p_obj.get('value')
                    if price is None:
                        price = item.get('current_price')
                    if price is not None:
                        try:
                            prices.append(float(price))
                        except (ValueError, TypeError):
                            continue
                if prices:
                    return max(prices)
            time.sleep(1)
        return None


scraper = AmazonScraper()
apify_api = ApifyAPIClient()


def init_apify(app):
    scraper._proxy = app.config.get('SCRAPING_PROXY') or None
    scraper._ready = True
    logger.info('Amazon 爬虫已就绪%s',
                '，代理: ' + scraper._proxy if scraper._proxy else '（无代理）')

    token = app.config.get('APIFY_TOKEN', '')
    actor = app.config.get('APIFY_ACTOR') or ''
    actors = [actor] if actor else []
    apify_api.token = token
    apify_api._actors = [apify_api._normalize_actor(a) for a in actors]
    apify_api._ready = bool(token)
    if token and actors:
        logger.info('Apify API 已就绪, Actor=%s', apify_api._actors)
    elif token and not actors:
        logger.warning('Apify Token 已配置但 APIFY_ACTOR 未设置')
