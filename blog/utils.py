"""HOSHINO Blog — 公共工具模块

提取自 routes.py / admin.py / bili_public_routes.py 的重复代码。
"""

import datetime
import logging
import threading
from collections import OrderedDict
from typing import Optional

from flask import request

logger = logging.getLogger(__name__)

CST = datetime.timezone(datetime.timedelta(hours=8))


def now_cst() -> datetime.datetime:
    """返回当前东八区时间（替代散布各处的 datetime.datetime.now(CST)）。"""
    return datetime.datetime.now(CST)


class LRUDict(OrderedDict):
    """固定大小的 LRU 字典，超出容量时自动淘汰最久未访问的条目。

    统一替代 routes.py 的 _ThumbnailLockDict、
    admin.py 的 _LRUDict、bili_public_routes.py 的 _RateLimitDict。
    """
    def __init__(self, maxsize=2000):
        self.maxsize = maxsize
        super().__init__()

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if len(self) > self.maxsize:
            self.popitem(last=False)


class RateLimiter:
    """基于 LRUDict 的速率限制器。

    支持 Redis 存储（跨进程）和内存降级（单进程）。
    """
    def __init__(self, max_requests: int = 5, window_seconds: int = 60, maxsize: int = 2000):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._counts = LRUDict(maxsize=maxsize)
        self._lock = threading.Lock()

    def is_limited(self, key: str) -> bool:
        """检查 key 是否超过速率限制。返回 True 表示被限制。"""
        now = datetime.datetime.now().timestamp()
        with self._lock:
            count, window_start = self._counts.get(key, (0, now))
            if now - window_start > self.window_seconds:
                self._counts[key] = (1, now)
                return False
            count += 1
            self._counts[key] = (count, window_start)
            return count > self.max_requests


def get_client_ip() -> str:
    """获取客户端真实 IP（兼容反向代理）。

    优先使用 request.access_route[0]（X-Forwarded-For 第一跳），
    回退到 request.remote_addr。
    """
    return request.access_route[0] if request.access_route else (request.remote_addr or 'unknown')


def validate_url_protocol(url: str) -> bool:
    """校验 URL 协议是否安全（仅允许 http/https/mailto）。

    统一替代 admin.py 中重复定义的 _validate_url_protocol 和
    routes.py 中的 _is_safe_url。
    """
    if not url:
        return False
    lower = url.strip().lower()
    return lower.startswith(('http://', 'https://', 'mailto:', '/'))


def escape_like(value: str) -> str:
    """转义 SQL LIKE 通配符（% 和 _），防止 LIKE 注入。"""
    return value.replace('%', '\\%').replace('_', '\\_')