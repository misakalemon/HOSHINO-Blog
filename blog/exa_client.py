import logging
import re
import threading
import time

import requests

logger = logging.getLogger(__name__)

_EXA_SEARCH = 'https://api.exa.ai/search'

# 域名 → 币种映射
DOMAIN_CURRENCY = {
    'amazon.com': 'USD',
    'bestbuy.com': 'USD',
    'newegg.com': 'USD',
    'bhphotovideo.com': 'USD',
    'walmart.com': 'USD',
    'target.com': 'USD',
    'costco.com': 'USD',
    'microcenter.com': 'USD',
    'adorama.com': 'USD',
    'ebay.com': 'USD',
    'aliexpress.com': 'USD',
    'amazon.de': 'EUR',
    'mediamarkt.de': 'EUR',
    'saturn.de': 'EUR',
    'amazon.co.uk': 'GBP',
    'ebay.co.uk': 'GBP',
    'jd.com': 'CNY',
    'smzdm.com': 'CNY',
}

# 币种符号 → 币种代码
CURRENCY_SYMBOL_MAP = {
    '$': 'USD',
    '¥': 'CNY',
    '€': 'EUR',
    '£': 'GBP',
}


class ExaClient:
    """Exa 搜索价格爬虫

    使用 Exa 搜索 API 在海外电商网站上查找产品价格。
    所有外币价格自动按实时汇率换算为人民币。

    支持 18 个电商站点（按优先级）：
      Amazon(.com/.de/.co.uk), BestBuy, Newegg, B&H, Walmart,
      Target, Costco, Micro Center, Adorama, eBay(.com/.co.uk),
      AliExpress, MediaMarkt, Saturn, JD.com, SMZDM

    需要 EXA_API_KEY，从 https://exa.ai 注册获取。
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
        # 各币种对人民币汇率（兜底值）
        self._rates = {
            'USD': 7.2,
            'EUR': 7.8,
            'GBP': 9.1,
        }
        if api_key:
            self._fetch_exchange_rates()
        else:
            logger.info('Exa 未配置（EXA_API_KEY 为空），跳过')

    def _fetch_exchange_rates(self):
        """获取 USD/CNY、EUR/CNY、GBP/CNY 实时汇率"""
        base_urls = [
            'https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/{}.json',
            'https://latest.currency-api.pages.dev/v1/currencies/{}.json',
        ]
        all_rates = {}
        for code in ('usd', 'eur', 'gbp'):
            for base_url in base_urls:
                try:
                    r = requests.get(base_url.format(code), timeout=5)
                    data = r.json()
                    rate = data.get(code, {}).get('cny')
                    if rate:
                        all_rates[code.upper()] = rate
                        break
                except Exception:
                    continue
        if not all_rates:
            try:
                r = requests.get('https://open.er-api.com/v6/latest/USD', timeout=5)
                data = r.json()
                if data.get('result') == 'success' and 'CNY' in data.get('rates', {}):
                    usd = data['rates']['CNY']
                    all_rates['USD'] = usd
                    if 'EUR' in data['rates']:
                        all_rates['EUR'] = usd / data['rates']['EUR']
                    if 'GBP' in data['rates']:
                        all_rates['GBP'] = usd / data['rates']['GBP']
            except Exception:
                pass
        if all_rates:
            self._rates.update(all_rates)
        logger.info('实时汇率: %s', ' | '.join(
            f'{k}/CNY={v:.4f}' for k, v in sorted(self._rates.items())
        ))

    def fetch_price(self, product_name):
        """搜索产品价格，返回 {'site': ..., 'price': ..., 'url': ...} 或 None

        所有外币价格自动按实时汇率换算为人民币。
        """
        if not self._ready:
            return None

        price, url, domain = self._search_and_extract(product_name)
        if price is not None:
            currency = DOMAIN_CURRENCY.get(domain, 'USD')
            if currency != 'CNY':
                rate = self._rates.get(currency, self._rates.get('USD', 7.2))
                price = round(price * rate, 2)
            return {'site': 'exa', 'price': price, 'url': url or ''}
        return None

    def _search_and_extract(self, product_name):
        """搜索产品页面并提取价格"""
        domains = [
            'amazon.com', 'bestbuy.com', 'newegg.com', 'bhphotovideo.com',
            'walmart.com', 'target.com', 'costco.com', 'microcenter.com',
            'adorama.com', 'ebay.com', 'aliexpress.com',
            'amazon.de', 'mediamarkt.de', 'saturn.de',
            'amazon.co.uk', 'ebay.co.uk',
            'jd.com', 'smzdm.com',
        ]
        for domain in domains:
            try:
                result = self._search_domain(product_name, domain)
                if result:
                    price, currency = self._extract_price(result.get('text', ''))
                    if price:
                        logger.info('Exa 从 %s 找到 %s: %s%.0f → CNY%.0f',
                                    domain, product_name[:30], currency, price,
                                    price * self._rates.get(currency, 1))
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
        """从页面文本中提取价格，返回 (price, currency_code) 或 (None, None)

        检测的币种符号：$ → USD, ¥ → CNY, € → EUR, £ → GBP
        """
        if not text:
            return None, None

        # JSON 价格字段（通常不带币种符号，默认按域名币种处理 — 此处直接返回 USD 待调用方转换）
        json_patterns = [
            r'(?:salePrice|currentPrice|finalPrice|priceNow)["\']?\s*[:=]\s*\$?(\d+(?:,\d{3})*(?:\.\d{2})?)',
            r'["\']price["\']?\s*[:=]\s*\$?(\d+(?:,\d{3})*(?:\.\d{2})?)',
            r'\$\s*(\d+(?:,\d{3})*(?:\.\d{2})?)\s*</span>',
        ]
        for p in json_patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                try:
                    v = float(m.group(1).replace(',', ''))
                    if v >= self._MIN_PRICE:
                        return v, 'USD'
                except ValueError:
                    pass

        # 带符号的价格：按符号确定币种
        symbol_patterns = [
            (r'\$\s*(\d+(?:,\d{3})*(?:\.\d{2})?)', 'USD'),
            (r'¥\s*(\d+(?:,\d{3})*(?:\.\d{2})?)', 'CNY'),
            (r'€\s*(\d+(?:,\d{3})*(?:\.\d{2})?)', 'EUR'),
            (r'£\s*(\d+(?:,\d{3})*(?:\.\d{2})?)', 'GBP'),
        ]
        for pattern, currency in symbol_patterns:
            matches = re.findall(pattern, text)
            if matches:
                try:
                    v = float(matches[0].replace(',', ''))
                    if v >= self._MIN_PRICE:
                        return v, currency
                except ValueError:
                    pass

        # 文本前缀价格（Our Price / Sale / Now 等，默认 USD）
        prefix_patterns = [
            r'(?:Our Price|Sale|Now|Special|Price|Current|Was)\s*[:$]\s*\$?(\d+(?:,\d{3})*(?:\.\d{2})?)',
            r'(?:starting at|from|only|just)\s*\$?\s*(\d+(?:,\d{3})*(?:\.\d{2})?)',
            r'(?:was|was:)\s*\$?\s*\d+(?:,\d{3})*(?:\.\d{2})?\s*(?:,\s*)?(?:now|sale)\s*[:$]?\s*\$?(\d+(?:,\d{3})*(?:\.\d{2})?)',
            r'(?:price|total)\s*[:$]\s*\$?\s*(\d+(?:,\d{3})*(?:\.\d{2})?)',
        ]
        for p in prefix_patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                try:
                    v = float(m.group(1).replace(',', ''))
                    if v >= self._MIN_PRICE:
                        return v, 'USD'
                except ValueError:
                    pass

        # 价格范围 $XX.XX - $XX.XX，取最低价
        range_match = re.search(r'\$\s*(\d+(?:,\d{3})*(?:\.\d{2})?)\s*(?:–|-|to)\s*\$', text)
        if range_match:
            try:
                v = float(range_match.group(1).replace(',', ''))
                if v >= self._MIN_PRICE:
                    return v, 'USD'
            except ValueError:
                pass

        return None, None
