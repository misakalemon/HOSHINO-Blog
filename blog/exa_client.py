import logging
import re
import threading
import time

import requests

logger = logging.getLogger(__name__)

_EXA_SEARCH = 'https://api.exa.ai/search'


class ExaClient:
    """Exa 搜索价格爬虫

    使用 Exa 搜索 API 在海外电商网站上查找产品价格。
    可绕过 GFW 获取 Amazon、BestBuy、Newegg 等被屏蔽站点的价格。

    需要 EXA_API_KEY，从 https://exa.ai 注册获取。
    搜索 + 内容获取，一次 API 调用即可完成。
    """

    def __init__(self, api_key=''):
        self._ready = bool(api_key)
        self._session = requests.Session()
        self._session.headers.update({
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'User-Agent': 'HoshinoBlog/1.0',
        })
        self._session.timeout = 20
        self._rate_limiter = threading.Semaphore(5)
        self._usd_cny_rate = 7.2
        if api_key:
            self._fetch_exchange_rate()
        else:
            logger.info('Exa 未配置（EXA_API_KEY 为空），跳过')

    def _fetch_exchange_rate(self):
        urls = [
            'https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json',
            'https://latest.currency-api.pages.dev/v1/currencies/usd.json',
            'https://open.er-api.com/v6/latest/USD',
        ]
        for url in urls:
            try:
                r = requests.get(url, timeout=5)
                data = r.json()
                rate = None
                if 'usd' in data and 'cny' in data['usd']:
                    rate = data['usd']['cny']
                elif data.get('result') == 'success' and 'CNY' in data.get('rates', {}):
                    rate = data['rates']['CNY']
                if rate:
                    self._usd_cny_rate = rate
                    logger.info('USD/CNY 实时汇率: %.4f', self._usd_cny_rate)
                    return
            except Exception as e:
                logger.debug('汇率源 %s 失败: %s', url.split('/')[2], e)
        logger.warning('所有汇率源均失败，使用默认 %.2f', self._usd_cny_rate)

    def fetch_price(self, product_name):
        """搜索产品价格，返回 {'site': ..., 'price': ..., 'url': ...} 或 None

        海外站点（amazon/bestbuy/newegg/bh）提取的是 USD，自动按 1 USD = {USD_TO_CNY} CNY 转人民币。
        国内站点（jd/smzdm）返回人民币原值。
        """
        if not self._ready:
            return None

        price, url, domain = self._search_and_extract(product_name)
        if price is not None:
            if domain in ('amazon.com', 'bestbuy.com', 'newegg.com', 'bhphotovideo.com'):
                price = round(price * self._usd_cny_rate, 2)
            return {'site': 'exa', 'price': price, 'url': url or ''}
        return None

    def _search_and_extract(self, product_name):
        """搜索产品页面并提取价格

        策略：
        1. 用 Exa search + contents 在 Amazon/BestBuy/Newegg 上搜索产品
        2. 从返回的页面文本中用正则提取价格
        3. 优先使用 Amazon 结果（价格格式最稳定）
        """
        domains = ['amazon.com', 'bestbuy.com', 'newegg.com', 'bhphotovideo.com',
                    'jd.com', 'smzdm.com']
        for domain in domains:
            try:
                result = self._search_domain(product_name, domain)
                if result:
                    price = self._extract_price(result.get('text', ''))
                    if price:
                        sym = '¥' if domain in ('jd.com', 'smzdm.com') else '$'
                        logger.info('Exa 从 %s 找到 %s: %s%.0f',
                                    domain, product_name[:30], sym, price)
                        return price, result.get('url'), domain
            except Exception as e:
                logger.debug('Exa %s 搜索 %s 失败: %s',
                             domain, product_name[:20], e)
        return None, None, None

    def _search_domain(self, product_name, domain):
        """在指定域名上搜索产品，返回首条结果"""
        with self._rate_limiter:
            payload = {
                'query': f'{product_name} price site:{domain}',
                'numResults': 3,
                'useAutoprompt': False,
                'contents': {'text': {'maxCharacters': 3000}},
            }
            resp = self._session.post(_EXA_SEARCH, json=payload)
            if resp.status_code == 429:
                logger.warning('Exa %s 限频，等待 1s 重试', domain)
                time.sleep(1)
                resp = self._session.post(_EXA_SEARCH, json=payload)
            if resp.status_code != 200:
                logger.warning('Exa 搜索 %s %d', domain, resp.status_code)
                return None

            data = resp.json()
            results = data.get('results', [])
            if not results:
                return None

            best = results[0]
            text = best.get('text') or best.get('snippet') or ''
            return {'url': best.get('url', ''), 'title': best.get('title', ''), 'text': text}

    _MIN_PRICE = 30

    def _extract_price(self, text):
        """从页面文本中提取价格

        按优先级匹配：
        - 美元价格 $XX.XX (Amazon 标准格式)
        - 价格标签: salePrice / currentPrice / price
        - 中文 ¥ 价格（B&H 等双语站）
        """
        if not text:
            return None

        # USD 价格模式（Amazon 最常见）
        usd_patterns = [
            r'(?:salePrice|currentPrice|finalPrice|priceNow)["\']?\s*[:=]\s*\$?(\d+(?:,\d{3})*(?:\.\d{2})?)',
            r'["\']price["\']?\s*[:=]\s*\$?(\d+(?:,\d{3})*(?:\.\d{2})?)',
            r'\$\s*(\d+(?:,\d{3})*(?:\.\d{2})?)\s*</span>',
        ]
        for p in usd_patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                try:
                    v = float(m.group(1).replace(',', ''))
                    if v >= self._MIN_PRICE:
                        return v
                except ValueError:
                    pass

        # 通用的货币前缀价格
        generic_patterns = [
            r'\$\s*(\d+(?:,\d{3})*(?:\.\d{2})?)',
            r'¥\s*(\d+(?:,\d{3})*(?:\.\d{2})?)',
        ]
        for p in generic_patterns:
            matches = re.findall(p, text)
            if matches:
                try:
                    v = float(matches[0].replace(',', ''))
                    if v >= self._MIN_PRICE:
                        return v
                except ValueError:
                    pass

        return None
