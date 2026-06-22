# -*- coding: utf-8 -*-
"""
HOSHINO Blog — Apify 价格数据获取模块

通过 Apify REST API 调用的 Actor：
  默认使用 _AMAZON_ACTORS 列表（硬编码）或 .env 中 APIFY_ACTOR 自定义。

使用方式：
  在 .env 中配置 APIFY_TOKEN 即可启用。
  可选 .env 中配置 APIFY_ACTOR 指定自定义 Actor。
"""
import json
import time
import logging
import requests

logger = logging.getLogger(__name__)

_APIFY_API = 'https://api.apify.com/v2'
# 默认 Actor 列表（当 .env 未配置 APIFY_ACTOR 时使用）
_DEFAULT_ACTORS = [
    'apify~amazon-price-scraper',
    'junglee~amazon-price-scraper',
    'vaclavrut~amazon-scraper',
    'drobnikj~crawler-amazon-prices',
]
_TIMEOUT = 30


class ApifyClient:
    """Apify API 客户端（轻量，无需安装 apify-client 包）。"""

    def __init__(self, token=None, actors=None):
        self.token = token or ''
        self._ready = bool(token)
        self._actors = actors or _DEFAULT_ACTORS

    def _headers(self):
        return {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.token}',
        }

    def _run_actor(self, actor_id, run_input):
        """启动一个 Actor 并等待结果。

        流程：启动 → 轮询状态（60s）→ 成功则读取 OUTPUT。
        返回 None 的场景：
          - token 无效（403）
          - Actor 不存在（404）
          - 运行失败/超时
          - 网络异常
        """
        if not self._ready:
            return None
        url = f'{_APIFY_API}/acts/{actor_id}/runs'
        try:
            r = requests.post(url, headers=self._headers(),
                              json=run_input, timeout=15)
            # 403 = token 无效，快速失败不继续尝试其他 actor
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
            if not run_id or not default_kv_id:
                return None

            # 轮询等待完成，最多 60 秒
            succeeded = False
            for _ in range(30):
                time.sleep(2)
                r2 = requests.get(f'{_APIFY_API}/acts/{actor_id}/runs/{run_id}',
                                   headers=self._headers(), timeout=10)
                status = r2.json().get('data', {}).get('status')
                if status == 'SUCCEEDED':
                    succeeded = True
                    break
                elif status in ('FAILED', 'ABORTED', 'TIMED-OUT'):
                    logger.warning('Apify run 失败: %s → %s', run_id, status)
                    return None
            if not succeeded:
                logger.warning('Apify run 超时（60s）: %s', run_id)
                return None

            # 读取 OUTPUT
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
        """从 Amazon 搜索并获取产品价格（尝试多个爬虫 Actor）。"""
        for actor in self._actors:
            result = self._run_actor(actor, {
                'searchTerms': [product_name],
                'maxResults': 3,
                'country': 'US',
            })
            if result:
                prices = []
                items = result if isinstance(result, list) else (
                    result.get('results') or result.get('data') or []
                )
                for item in items:
                    price = (item.get('price') or item.get('priceValue')
                             or item.get('amount') or item.get('priceAmount'))
                    if price:
                        try:
                            prices.append(float(price))
                        except (ValueError, TypeError):
                            continue
                if prices:
                    return min(prices)
            time.sleep(1)
        return None


# 全局实例（由 app.py 初始化时注入 token）
client = ApifyClient()


def init_apify(app):
    """从 app.config 读取 APIFY_TOKEN 和 APIFY_ACTOR 并初始化客户端。"""
    token = app.config.get('APIFY_TOKEN', '')
    actor = app.config.get('APIFY_ACTOR') or ''
    actors = [actor] if actor else None  # None 表示用默认列表
    client.token = token
    client._actors = actors or _DEFAULT_ACTORS
    client._ready = bool(token)
    if token:
        logger.info('Apify 客户端已就绪, Actor=%s', client._actors)
    else:
        logger.info('Apify 未配置（APIFY_TOKEN 为空），价格爬取跳过')
