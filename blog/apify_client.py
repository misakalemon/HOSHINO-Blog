# -*- coding: utf-8 -*-
"""
HOSHINO Blog — Apify 价格数据获取模块

通过 Apify REST API 调用价格爬虫 Actor。
需要先在 Apify Store 中找到可用的价格 Actor 并配置到 .env。

使用方式：
  1. 在 .env 中配置 APIFY_TOKEN
  2. 在 .env 中配置 APIFY_ACTOR（推荐：在 Apify Store 搜索 "amazon price"）

Actor ID 格式：Apify API 使用 ~ 分隔符（username~actor-name），
.env 中写 / 或 ~ 均可，代码自动归一化为 ~。

注意：所有硬编码的默认 Actor 已经过期下架，
必须通过 .env 指定一个有效的 Actor ID 才能使用价格爬取功能。
"""
import json
import time
import logging
from urllib.parse import quote
import requests

logger = logging.getLogger(__name__)

_APIFY_API = 'https://api.apify.com/v2'
_TIMEOUT = 30


class ApifyClient:
    """Apify API 客户端（轻量，无需安装 apify-client 包）。"""

    def __init__(self, token=None, actors=None):
        self.token = token or ''
        self._ready = bool(token)
        # 归一化 actor ID：/ → ~（支持 .env 中两种写法）
        self._actors = [self._normalize_actor(a) for a in (actors or [])] if actors else []

    @staticmethod
    def _normalize_actor(actor_id):
        """归一化 Actor ID 格式：username/actor-name → username~actor-name。"""
        parts = actor_id.split('/')
        if len(parts) == 2:
            return f'{parts[0]}~{parts[1]}'
        return actor_id

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
        """从 Amazon 搜索并获取产品最低价格。

        支持以下 Actor 的输出格式：
          - junglee/free-amazon-product-scraper: price.value
          - wilico/amazon-price-scraper:        current_price

        如果配置了多个 Actor（_actors 列表），依次尝试直到成功。
        如果未配置任何 Actor，返回 None。
        """
        if not self._actors:
            logger.debug('未配置 Apify Actor，跳过价格查询: %s', product_name)
            return None

        search_url = f'https://www.amazon.com/s?k={quote(product_name)}'
        for actor in self._actors:
            result = self._run_actor(actor, {
                'categoryUrls': [{'url': search_url}],
                'maxItemsPerStartUrl': 3,
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
                    return min(prices)
            time.sleep(1)
        return None


# 全局实例（由 app.py 初始化时注入 token）
client = ApifyClient()


def init_apify(app):
    """从 app.config 读取 APIFY_TOKEN 和 APIFY_ACTOR 并初始化客户端。

    APIFY_ACTOR 未配置时，Actor 列表为空，价格爬取跳过。
    硬编码的默认 Actor 已全部下架，不再预设。
    """
    token = app.config.get('APIFY_TOKEN', '')
    actor = app.config.get('APIFY_ACTOR') or ''
    if actor:
        actors = [actor]
    else:
        actors = []

    client.token = token
    client._actors = [client._normalize_actor(a) for a in actors]
    client._ready = bool(token)

    if token:
        if client._actors:
            logger.info('Apify 客户端已就绪, Actor=%s', client._actors)
        else:
            logger.warning(
                'Apify Token 已配置但 APIFY_ACTOR 未设置，'
                '价格爬取跳过。请在 .env 中配置 APIFY_ACTOR。'
                '获取方式：访问 https://console.apify.com/store，'
                '搜索 amazon-price-scraper 并复制 Actor ID（格式：username~actor-name）'
            )
    else:
        logger.info('Apify 未配置（APIFY_TOKEN 为空），价格爬取跳过')
