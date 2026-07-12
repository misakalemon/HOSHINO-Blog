"""B 站 API 封装（基于 bilibili-api-python）"""
import asyncio
import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Generator

from bilibili_api import Credential
from bilibili_api import sync as _bili_sync
from bilibili_api import user as _user_mod
from bilibili_api import video as _video_mod

from .config import PAGE_SIZE, REQUEST_INTERVAL

logger = logging.getLogger(__name__)

_credential: Credential | None = None

# 按线程隔离的事件循环（每个线程独立，不互相干扰）
_loop_local = threading.local()

# 并发信号量 — 限制同时发往 B 站 API 的请求数，防风控
_api_semaphore = threading.Semaphore(5)


_API_TIMEOUT = 30.0


def _sync(coro):
    """使用线程本地事件循环执行异步协程，受并发信号量保护，带 30s 超时"""
    with _api_semaphore:
        loop = getattr(_loop_local, 'loop', None)
        if loop is None or loop.is_closed():
            if loop is not None and loop.is_closed():
                try:
                    loop.close()
                except Exception:
                    pass
            loop = asyncio.new_event_loop()
            _loop_local.loop = loop
        try:
            return loop.run_until_complete(asyncio.wait_for(coro, timeout=_API_TIMEOUT))
        except asyncio.TimeoutError:
            logger.error("B站 API 请求超时 (%ds)", _API_TIMEOUT)
            _loop_local.loop = None
            raise TimeoutError(f"B站 API 请求超时 ({_API_TIMEOUT}s)")
        except Exception:
            try:
                if not loop.is_closed():
                    loop.run_until_complete(loop.shutdown_asyncgens())
                    loop.close()
            except Exception:
                pass
            _loop_local.loop = None
            raise


def _is_risk_control(e: Exception) -> bool:
    """判断异常是否为 B站 风控/限流"""
    err_str = str(e).lower()
    codes = ['429', '-509', '-352', '412', 'too many requests', 'ratelimit', '被拒绝']
    return any(c in err_str for c in codes)


def _is_auth_error(e: Exception) -> bool:
    """判断异常是否为登录凭证过期/未登录"""
    err_str = str(e).lower()
    codes = ['-401', '未登录', '请先登录', 'credential', 'session expired']
    return any(c in err_str for c in codes)


def set_cookies(cookie_str: str):
    """设置登录态 Cookie（SESSDATA=abc; bili_jct=def; buvid3=ghi）"""
    global _credential
    cookies = {}
    for item in cookie_str.split(";"):
        item = item.strip()
        if "=" in item:
            k, v = item.split("=", 1)
            cookies[k.strip()] = v.strip()
    _credential = Credential(
        sessdata=cookies.get("SESSDATA", ""),
        bili_jct=cookies.get("bili_jct", ""),
        buvid3=cookies.get("buvid3", ""),
        buvid4=cookies.get("buvid4", ""),
        dedeuserid=cookies.get("DedeUserID", ""),
        ac_time_value=cookies.get("ac_time_value", ""),
    )


def set_credential(cred: Credential):
    """直接设置全局 Credential 对象（用于官方库登录，保留完整状态）"""
    global _credential
    _credential = cred


def is_logged_in() -> bool:
    if _credential is None:
        return False
    try:
        return _sync(_credential.verify())
    except Exception:
        return False


def extract_mid(space_url: str) -> int:
    """从 UP 主空间 URL 中提取 mid"""
    m = re.search(r"space\.bilibili\.com/(\d+)", space_url)
    if not m:
        raise ValueError(f"无法从 URL 中提取 mid: {space_url}")
    return int(m.group(1))


def get_user_info(mid: int) -> dict:
    """获取 UP 主信息（名称、头像、粉丝数、视频数），Cookie 过期时自动降级为匿名"""
    try:
        u = _user_mod.User(mid, credential=_credential)
        info = _sync(u.get_user_info())
    except Exception as e:
        if _credential and _is_auth_error(e):
            logger.warning("UP主信息获取凭证过期，使用匿名: %s", e)
            u = _user_mod.User(mid)
            info = _sync(u.get_user_info())
        else:
            raise
    return {
        'name': info.get('name', ''),
        'avatar': info.get('face', ''),
        'follower_count': info.get('follower', 0),
        'video_count': info.get('video', 0),
    }


def get_video_list(mid: int, max_pages: int | None = None) -> Generator[dict, None, None]:
    """获取指定 mid 的所有视频基本信息（分页迭代，含风控指数退避 + Cookie过期自动降级）
    
    Args:
        mid: B站 mid
        max_pages: 最多翻页数，None 表示全部
    """
    u = _user_mod.User(mid, credential=_credential)
    pn = 1
    retry_delay = 30
    auth_retried = False

    while True:
        if max_pages is not None and pn > max_pages:
            break
        logger.info("正在获取第 %d 页视频列表 ...", pn)
        try:
            data = _sync(u.get_videos(ps=PAGE_SIZE, pn=pn))
        except Exception as e:
            logger.error("获取第 %d 页视频列表失败: %s", pn, e)
            if _credential and _is_auth_error(e) and not auth_retried:
                logger.warning("凭证过期，切换为匿名访问后重试第 %d 页", pn)
                auth_retried = True
                u = _user_mod.User(mid)
                continue
            if _is_risk_control(e):
                logger.warning("⚠️ 触发风控，等待 %ds 后重试...", retry_delay)
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 600)
                continue  # 重试当前页
            break

        vlist = data.get("list", {}).get("vlist", [])
        if not vlist:
            logger.info("第 %d 页 vlist 为空，结束迭代", pn)
            break

        page_info = data.get("page", {})
        first_pubdate = vlist[0].get("created", 0)
        first_pubdate_str = (
            datetime.fromtimestamp(first_pubdate, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            if first_pubdate else "?"
        )
        logger.info("第 %d 页返回 %d/%d 个视频 (total=%s, ps=%s), 首 bvid=%s pubdate=%s",
                    pn, len(vlist), PAGE_SIZE, page_info.get("count"),
                    page_info.get("ps", "?"),
                    vlist[0].get("bvid", "?"), first_pubdate_str)

        for item in vlist:
            pubdate_ts = item.get("created", 0)
            yield {
                "aid": int(item.get("aid", 0)),
                "bvid": item.get("bvid", ""),
                "title": item["title"],
                "description": item.get("description", ""),
                "duration": _parse_duration(item.get("length", "00:00")),
                "pubdate": pubdate_ts,
                "pub_date": (
                    datetime.fromtimestamp(pubdate_ts, tz=timezone.utc).date()
                    if pubdate_ts else None
                ),
                "pub_datetime": (
                    datetime.fromtimestamp(pubdate_ts, tz=timezone.utc)
                    if pubdate_ts else None
                ),
                "view_count": item.get("play", 0),
                "comment_count": item.get("comment", 0),
                "danmaku_count": item.get("video_review", 0),
            }

        page = data.get("page", {})
        total_pages = (page.get("count", 0) + PAGE_SIZE - 1) // PAGE_SIZE
        if pn >= total_pages:
            break
        pn += 1
        import random
        time.sleep(REQUEST_INTERVAL * 2 + random.random() * 3.0)


def get_video_stat(bvid: str) -> dict:
    """获取单个视频的详细统计数据，Cookie 过期时自动降级为匿名"""
    try:
        v = _video_mod.Video(bvid=bvid, credential=_credential)
        info = _sync(v.get_info())
    except Exception as e:
        if _credential and _is_auth_error(e):
            logger.warning("视频统计获取凭证过期，使用匿名: %s", e)
            v = _video_mod.Video(bvid=bvid)
            info = _sync(v.get_info())
        else:
            raise
    stat = info.get("stat", {})
    return {
        "view_count": stat.get("view", 0),
        "like_count": stat.get("like", 0),
        "coin_count": stat.get("coin", 0),
        "favorite_count": stat.get("favorite", 0),
        "share_count": stat.get("share", 0),
        "comment_count": stat.get("reply", 0),
        "danmaku_count": stat.get("danmaku", 0),
    }


def _parse_duration(length_str: str) -> int:
    if not length_str or not length_str.strip():
        return 0
    parts = list(map(int, length_str.split(":")))
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    elif len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return 0
