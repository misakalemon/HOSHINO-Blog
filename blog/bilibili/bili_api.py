"""B 站 API 封装（基于 bilibili-api-python）"""
import logging
import re
import time
from datetime import datetime, timezone
from typing import Generator

from bilibili_api import sync, Credential
from bilibili_api import user as _user_mod
from bilibili_api import video as _video_mod

from .config import PAGE_SIZE, REQUEST_INTERVAL

logger = logging.getLogger(__name__)

_credential: Credential | None = None


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
        dedeuserid=cookies.get("DedeUserID", ""),
        ac_time_value=cookies.get("ac_time_value", ""),
    )


def is_logged_in() -> bool:
    if _credential is None:
        return False
    try:
        return sync(_credential.verify())
    except Exception:
        return False


def extract_mid(space_url: str) -> int:
    """从 UP 主空间 URL 中提取 mid"""
    m = re.search(r"space\.bilibili\.com/(\d+)", space_url)
    if not m:
        raise ValueError(f"无法从 URL 中提取 mid: {space_url}")
    return int(m.group(1))


def get_user_info(mid: int) -> dict:
    """获取 UP 主信息（名称、头像、粉丝数、视频数）"""
    u = _user_mod.User(mid, credential=_credential)
    info = sync(u.get_user_info())
    return {
        'name': info.get('name', ''),
        'avatar': info.get('face', ''),
        'follower_count': info.get('follower', 0),
        'video_count': info.get('video', 0),
    }


def get_video_list(mid: int) -> Generator[dict, None, None]:
    """获取指定 mid 的所有视频基本信息（分页迭代）"""
    u = _user_mod.User(mid, credential=_credential)
    pn = 1

    while True:
        logger.info("正在获取第 %d 页视频列表 ...", pn)
        try:
            data = sync(u.get_videos(ps=PAGE_SIZE, pn=pn))
        except Exception as e:
            logger.error("获取第 %d 页视频列表失败: %s", pn, e)
            break

        vlist = data.get("list", {}).get("vlist", [])
        if not vlist:
            break

        for item in vlist:
            pubdate_ts = item.get("created", 0)
            yield {
                "aid": item["aid"],
                "bvid": item["bvid"],
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
    """获取单个视频的详细统计数据"""
    v = _video_mod.Video(bvid=bvid, credential=_credential)
    info = sync(v.get_info())
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
    parts = list(map(int, length_str.split(":")))
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    elif len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return 0
