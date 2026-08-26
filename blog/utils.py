"""HOSHINO Blog — 公共工具模块

提取自 routes.py / admin.py / bili_public_routes.py 的重复代码。
"""

import datetime
import logging
import threading
from collections import OrderedDict
from typing import Optional

from flask import current_app, request

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


def build_site_url(endpoint: str, **values) -> str:
    """生成站点绝对 URL（供邮件链接等需要外链的场景）。

    优先使用配置的 SITE_BASE_URL（如 https://hoshino-blog.iepose.cn）：
      - worker 后台线程构建链接时不依赖请求上下文/SERVER_NAME，
        直接从 url_map 解析路径拼接到基础 URL 上，避免生成 localhost/内网 IP
      - 未配置 SITE_BASE_URL 时回退到 url_for(_external=True)（需请求上下文或 SERVER_NAME）

    Args:
        endpoint: Flask 端点名，如 'bili_public.verify_subscription'
        **values: 路径参数（token 等）

    Returns:
        str: 绝对 URL
    """
    from flask import url_for

    try:
        base = (current_app.config.get('SITE_BASE_URL') or '').rstrip('/')
    except Exception:
        base = ''
    if base:
        # 不依赖 Flask url_for（worker 线程无请求上下文时 url_for 需 SERVER_NAME）：
        # 直接从 url_map 找端点规则，替换路径参数
        try:
            rule = current_app.url_map._rules_by_endpoint.get(endpoint)
            if not rule:
                raise KeyError(endpoint)
            # 选择第一个匹配的规则（通常只有一个）
            r = rule[0]
            path = r.rule
            # URL 参数默认值（如无）不需要处理；仅替换 path 中的 <...>
            import re as _re
            def _conv(m):
                pname = m.group(1).split(':')[-1] if m.group(1) else ''
                return str(values.get(pname, ''))
            path = _re.sub(r'<(?:(?:string|int|float|path):)?([^<>]*)>', _conv, path)
            # 端点可能带 url_prefix，url_map 规则已含前缀（Blueprint 注册时自动加）
            return f'{base}{path}'
        except Exception as e:
            logger.warning('build_site_url 解析失败 endpoint=%s: %s', endpoint, e)
            # 回退：依赖 SERVER_NAME 或请求上下文
            return url_for(endpoint, _external=True, **values)
    return url_for(endpoint, _external=True, **values)


def escape_like(value: str) -> str:
    """转义 SQL LIKE 通配符（% 和 _）以及转义符本身，防止 LIKE 注入。

    必须先转义反斜杠，否则输入中的 \\% 会先被解释为"字面反斜杠+通配符"，
    使 % 重新变为通配符（转义绕过）。
    调用处需配合 .ilike(..., escape='\\\\') 指定转义字符。
    """
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')