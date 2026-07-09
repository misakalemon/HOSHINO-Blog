"""B 站扫码登录（适配 Flask 路由）"""
import logging
import os
import time
import urllib.parse
from urllib.parse import unquote

import requests

from .bili_api import set_cookies
from .config import COOKIE_FILE, HEADERS, TIMEOUT

logger = logging.getLogger(__name__)

_NOT_SCANNED = 86101
_SCANNED = 86090
_EXPIRED = 86038
_SUCCESS = 0

API_QR_GENERATE = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
API_QR_POLL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"


def generate_qr() -> dict:
    """生成二维码，返回 { url, qrcode_key }"""
    resp = requests.get(API_QR_GENERATE, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"生成二维码失败: {data.get('message', '')}")
    return {"url": data["data"]["url"], "qrcode_key": data["data"]["qrcode_key"]}


def poll_qr(qrcode_key: str) -> dict:
    """轮询扫码状态，返回完整 data dict"""
    resp = requests.get(
        API_QR_POLL,
        params={"qrcode_key": qrcode_key},
        headers=HEADERS,
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def parse_cookies_from_url(redirect_url: str) -> str:
    """从登录成功后的重定向 URL 中解析 Cookie 字符串"""
    parsed = urllib.parse.urlparse(redirect_url)
    params = urllib.parse.parse_qs(parsed.query)
    cookie_keys = [
        "bili_jct", "DedeUserID", "DedeUserID__ckMd5",
        "SESSDATA", "sid", "buvid3", "buvid4", "buvid_fp", "ac_time_value",
    ]
    cookies = []
    for key in cookie_keys:
        if key in params:
            cookies.append(f"{key}={params[key][0]}")
    return "; ".join(cookies)


def fetch_cookies_via_redirect(redirect_url: str) -> str:
    """请求重定向 URL 获取完整 Set-Cookie（跟随重定向以接收 SESSDATA）"""
    try:
        s = requests.Session()
        s.headers.update(HEADERS)
        resp = s.get(redirect_url, timeout=TIMEOUT, allow_redirects=True)
        # 调试日志：打印重定向链路中的 Cookie
        for i, r in enumerate(resp.history):
            logger.debug("重定向第 %d 步: url=%s, cookies=%s", i + 1, r.url, dict(r.cookies))
        logger.debug("最终 URL: %s, cookies: %s", resp.url, dict(s.cookies))
        # get_dict() 自动去重（避免同名 Cookie 异常），unquote 解码 URL 编码的值
        cookie_parts = [f"{k}={unquote(v)}" for k, v in s.cookies.get_dict().items()]
        return "; ".join(cookie_parts)
    except Exception as e:
        logger.warning("通过重定向获取 Cookie 失败: %s", e)
        return ""


def save_cookies(cookie_str: str):
    """保存 Cookie 到文件"""
    path = COOKIE_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(cookie_str)
    logger.info("B站 Cookie 已保存到: %s", path)


def load_cookies() -> str | None:
    """从文件加载 Cookie，如果文件不存在返回 None"""
    path = COOKIE_FILE
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        logger.warning("读取 Cookie 文件失败: %s", e)
        return None


def apply_cookies():
    """尝试从文件加载 Cookie 并设置到 API 模块"""
    cookie_str = load_cookies()
    if cookie_str:
        logger.debug("读取到的 Cookie 原始字符串 (前100字符): %s ...", cookie_str[:100])
        set_cookies(cookie_str)
        from .bili_api import is_logged_in
        if is_logged_in():
            logger.info("✅ 已加载 B站 登录态 Cookie")
            return True
        else:
            logger.warning("Cookie 已过期，请重新登录")
    return False
