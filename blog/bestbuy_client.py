import logging
from urllib.parse import quote
import requests

logger = logging.getLogger(__name__)

BB_API_URL = 'https://api.bestbuy.com/v1/products'


class BestbuyClient:
    def __init__(self, api_key=None):
        self.api_key = api_key or ''
        self._ready = bool(api_key)

    def search(self, keyword, page_size=5):
        if not self._ready:
            return None
        try:
            params = {
                'format': 'json',
                'apiKey': self.api_key,
                'pageSize': page_size,
                'show': 'name,salePrice,regularPrice,url,sku',
                'sort': 'bestSelling',
            }
            r = requests.get(
                f"{BB_API_URL}(search={quote(keyword)})",
                params=params, timeout=15
            )
            if r.status_code == 403:
                logger.error('Best Buy API Key 无效')
                self._ready = False
                return None
            if not r.ok:
                logger.warning('Best Buy API 错误: %s %s', r.status_code, r.text[:200])
                return None
            data = r.json()
            return data.get('products', [])
        except Exception as e:
            logger.warning('Best Buy API 查询失败: %s', e)
        return None

    def fetch_price(self, product_name):
        if not self._ready:
            logger.debug('Best Buy 未配置，跳过价格查询: %s', product_name)
            return None

        products = self.search(product_name)
        if not products:
            return None

        prices = []
        for item in products:
            price = item.get('salePrice') or item.get('regularPrice')
            if price is not None:
                try:
                    prices.append(float(price))
                except (ValueError, TypeError):
                    pass

        return min(prices) if prices else None


client = BestbuyClient()


def init_bestbuy(app):
    api_key = app.config.get('BESTBUY_API_KEY', '')
    client.api_key = api_key
    client._ready = bool(api_key)
    if client._ready:
        logger.info('Best Buy 客户端已就绪')
    else:
        logger.info('Best Buy 未配置（BESTBUY_API_KEY 为空），跳过')
