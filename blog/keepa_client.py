import logging
import time
import requests

logger = logging.getLogger(__name__)

KEEPA_API_URL = 'https://api.keepa.com'
DOMAIN_US = 1


class KeepaClient:
    def __init__(self, api_key=None):
        self.api_key = api_key or ''
        self._ready = bool(api_key)
        self._last_request = 0

    def _rate_limit(self):
        elapsed = time.time() - self._last_request
        if elapsed < 1.5:
            time.sleep(1.5 - elapsed)
        self._last_request = time.time()

    def search(self, keyword, stats=30):
        if not self._ready:
            return None
        self._rate_limit()
        try:
            r = requests.get(f'{KEEPA_API_URL}/search', params={
                'key': self.api_key,
                'domain': DOMAIN_US,
                'type': 'product',
                'term': keyword,
                'stats': stats,
            }, timeout=20)
            if r.status_code == 403:
                logger.error('Keepa API Key 无效（403）')
                self._ready = False
                return None
            if r.status_code == 429:
                logger.warning('Keepa 频率限制，等待重试')
                time.sleep(10)
                return self.search(keyword, stats)
            if not r.ok:
                logger.warning('Keepa API 错误: %s %s', r.status_code, r.text[:200])
                return None
            data = r.json()
            return data.get('products', [])
        except Exception as e:
            logger.warning('Keepa 查询失败: %s', e)
        return None

    def fetch_price(self, product_name):
        if not self._ready:
            logger.debug('Keepa 未配置，跳过价格查询: %s', product_name)
            return None

        products = self.search(product_name)
        if not products:
            return None

        kw_tokens = set(product_name.lower().split())
        target_lower = product_name.lower()

        for item in products:
            title = item.get('title', '') or ''
            stats = item.get('stats') or {}
            source_urls = item.get('sourceURLs') or {}
            price = None
            for key in ('current', 'current_BB'):
                arr = stats.get('current') or stats.get(key)
                if arr and len(arr) > 0:
                    p = arr[0]
                    if p and p > 0:
                        price = p / 100.0
                        break
            if price is None:
                arr = stats.get('avg')
                if arr and len(arr) > 0:
                    p = arr[0]
                    if p and p > 0:
                        price = p / 100.0
            if price is not None:
                title_lower = title.lower()
                if target_lower in title_lower:
                    return price
                title_tokens = set(title_lower.split())
                common = kw_tokens & title_tokens
                long_common = [t for t in common if len(t) >= 3]
                if long_common:
                    return price

        return None


client = KeepaClient()


def init_keepa(app):
    api_key = app.config.get('KEEPA_API_KEY', '')
    client.api_key = api_key
    client._ready = bool(api_key)
    if client._ready:
        logger.info('Keepa 客户端已就绪')
    else:
        logger.info('Keepa 未配置（KEEPA_API_KEY 为空），跳过')
