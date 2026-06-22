# -*- coding: utf-8 -*-
"""
HOSHINO Blog — Apify 价格数据获取模块

通过 Apify REST API 调用的 Actor：
  - apify/amazon-price-scraper    — Amazon 商品价格
  - apify/google-shopping-scraper — Google Shopping

使用方式：
  在 .env 中配置 APIFY_TOKEN 即可启用。
  调用 fetch_price(product_name) 获取价格。
"""
import json
import logging
import requests

logger = logging.getLogger(__name__)

_APIFY_API = 'https://api.apify.com/v2'
_AMAZON_ACTOR = 'apify/amazon-price-scraper'
_GS_ACTOR = 'apify/google-shopping-scraper'
_TIMEOUT = 30


class ApifyClient:
    """Apify API 客户端（轻量，无需安装 apify-client 包）。"""

    def __init__(self, token=None):
        self.token = token or ''
        self._ready = bool(token)

    def _headers(self):
        return {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.token}',
        }

    def _run_actor(self, actor_id, run_input):
        """启动一个 Actor 并等待结果。"""
        if not self._ready:
            return None
        url = f'{_APIFY_API}/acts/{actor_id}/runs'
        try:
            # 启动 actor
            r = requests.post(url, headers=self._headers(),
                              json=run_input, timeout=15)
            if not r.ok:
                logger.error('Apify 启动失败 %s: %s', actor_id, r.text[:200])
                return None
            run = r.json().get('data', {})
            run_id = run.get('id')
            default_kv_id = run.get('defaultKeyValueStoreId')

            if not run_id or not default_kv_id:
                return None

            # 等待完成并获取结果
            import time
            for _ in range(30):
                time.sleep(2)
                r2 = requests.get(f'{_APIFY_API}/acts/{actor_id}/runs/{run_id}',
                                   headers=self._headers(), timeout=10)
                status = r2.json().get('data', {}).get('status')
                if status == 'SUCCEEDED':
                    break
                elif status in ('FAILED', 'ABORTED', 'TIMED-OUT'):
                    logger.warning('Apify run %s: %s', run_id, status)
                    return None

            # 读取结果
            r3 = requests.get(
                f'{_APIFY_API}/key-value-stores/{default_kv_id}/records/OUTPUT',
                headers=self._headers(), timeout=10
            )
            if r3.ok:
                return r3.json()
            return None
        except requests.exceptions.ConnectionError:
            logger.warning('Apify API 连接失败（可能被墙）')
            return None
        except Exception as e:
            logger.error('Apify 异常: %s', e)
            return None

    def fetch_amazon_price(self, product_name):
        """从 Amazon 搜索并获取产品价格。"""
        result = self._run_actor(_AMAZON_ACTOR, {
            'searchTerms': [product_name],
            'maxResults': 3,
            'country': 'US',
        })
        if not result:
            return None
        prices = []
        for item in (result if isinstance(result, list) else []):
            price = item.get('price') or item.get('priceValue')
            if price:
                try:
                    prices.append(float(price))
                except (ValueError, TypeError):
                    continue
        return min(prices) if prices else None


# 全局实例（由 app.py 初始化时注入 token）
client = ApifyClient()


def init_apify(app):
    """从 app.config 读取 APIFY_TOKEN 并初始化客户端。"""
    token = app.config.get('APIFY_TOKEN', '')
    client.token = token
    client._ready = bool(token)
    if token:
        logger.info('Apify 客户端已就绪')
    else:
        logger.info('Apify 未配置（APIFY_TOKEN 为空），价格爬取跳过')
