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

    安全策略：默认只信任 request.remote_addr（TCP 对端，不可伪造）。
    仅在显式配置 TRUST_PROXY=true（且部署在受信反向代理之后，代理会
    覆盖/规范化 X-Forwarded-For）时，才读取 access_route 首跳。
    否则攻击者可伪造 X-Forwarded-For 绕过基于 IP 的限流。
    """
    from flask import current_app

    trust_proxy = bool(current_app and current_app.config.get('TRUST_PROXY'))
    if trust_proxy:
        return request.access_route[0] if request.access_route else (request.remote_addr or 'unknown')
    return request.remote_addr or 'unknown'


def validate_url_protocol(url: str) -> bool:
    """校验 URL 协议是否安全（仅允许 http/https/mailto）。

    统一替代 admin.py 中重复定义的 _validate_url_protocol 和
    routes.py 中的 _is_safe_url。
    """
    if not url:
        return False
    lower = url.strip().lower()
    return lower.startswith(('http://', 'https://', 'mailto:', '/'))


def is_safe_image_url(url: str) -> bool:
    """校验图片 URL 是否安全。

    接受：
      - 外部完整 URL（http/https）
      - 站内绝对路径（/static/、/uploads/、/images/）
      - 站内相对路径（uploads/、images/）——前端裁剪上传回填的
        data.url.replace('/static/', '') 正是这种格式（如 uploads/xxx.webp）

    拒绝 javascript:/data: 等恶意协议，并拒绝含 '..' 路径穿越段的
    值（防止拼接进文件删除/读取路径时越界）。
    """
    if not url:
        return True
    s = url.strip().lower()
    # 拒绝路径穿越段（.. 作为路径组件）
    if '..' in s.split('/'):
        return False
    return s.startswith(('http://', 'https://', '/static/', '/uploads/', '/images/',
                         'uploads/', 'images/'))


def escape_like(value: str) -> str:
    """转义 SQL LIKE 通配符（% 和 _）以及转义符本身，防止 LIKE 注入。

    必须先转义反斜杠，否则输入中的 \\% 会先被解释为"字面反斜杠+通配符"，
    使 % 重新变为通配符（转义绕过）。
    调用处需配合 .ilike(..., escape='\\\\') 指定转义字符。
    """
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')