"""B站 API 封装

基于 bilibili-api-python，统一封装：
- 线程安全的事件循环管理（_sync + threading.local）
- 并发信号量限流（Semaphore(5) 防 B站 风控）
- Cookie 过期自动降级为匿名访问
- 两路视频发现：arc/search 翻页 + 动态流兜底
"""

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

# IP 级封禁追踪 — 任意线程检测到 412 后记录在此，供调用方决定是否熔断
_last_412_time: float = 0.0


def was_recently_blocked(cooldown: float = 0) -> bool:
    """检查最近是否被 B站 IP 级封禁（412）"""
    global _last_412_time
    if cooldown <= 0:
        return _last_412_time > 0
    return time.time() - _last_412_time < cooldown


# 按线程隔离的事件循环（每个线程独立，不互相干扰）
_loop_local = threading.local()

# 并发信号量 — 限制同时发往 B 站 API 的请求数，防风控
_api_semaphore = threading.Semaphore(5)


_API_TIMEOUT = 30.0


def _sync(coro):
    """在线程本地事件循环中执行协程，并发上限 5 路，单路 30s 超时。

    每个线程拥有独立的 asyncio 事件循环（threading.local 隔离）。
    超时或异常后关闭循环并重建，防止 fd/异步生成器资源泄漏。
    """
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
            logger.error('B站 API 请求超时 (%ds)', _API_TIMEOUT)
            try:
                if not loop.is_closed():
                    loop.run_until_complete(loop.shutdown_asyncgens())
                    loop.close()
            except Exception:
                pass
            _loop_local.loop = None
            raise TimeoutError(f'B站 API 请求超时 ({_API_TIMEOUT}s)')
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
    """判断异常是否为 B站 风控/限流（可重试）"""
    err_str = str(e).lower()
    codes = ['429', '-509', '-352', 'too many requests', 'ratelimit', '被拒绝']
    return any(c in err_str for c in codes)


def _is_ip_blocked(e: Exception) -> bool:
    """判断异常是否为 IP 级安全封禁（412 验证页，不可重试）"""
    return '412' in str(e).lower()


def _is_auth_error(e: Exception) -> bool:
    """判断异常是否为登录凭证过期/未登录"""
    err_str = str(e).lower()
    codes = ['-401', '未登录', '请先登录', 'credential', 'session expired']
    return any(c in err_str for c in codes)


def set_cookies(cookie_str: str):
    """设置登录态 Cookie（SESSDATA=abc; bili_jct=def; buvid3=ghi）"""
    global _credential
    cookies = {}
    for item in cookie_str.split(';'):
        item = item.strip()
        if '=' in item:
            k, v = item.split('=', 1)
            cookies[k.strip()] = v.strip()
    _credential = Credential(
        sessdata=cookies.get('SESSDATA', ''),
        bili_jct=cookies.get('bili_jct', ''),
        buvid3=cookies.get('buvid3', ''),
        buvid4=cookies.get('buvid4', ''),
        dedeuserid=cookies.get('DedeUserID', ''),
        ac_time_value=cookies.get('ac_time_value', ''),
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
    m = re.search(r'space\.bilibili\.com/(\d+)', space_url)
    if not m:
        raise ValueError(f'无法从 URL 中提取 mid: {space_url}')
    return int(m.group(1))


def get_user_info(mid: int) -> dict:
    """获取 UP 主基本信息。

    主 API: x/space/wbi/acc/info（名称/头像/视频数）
    Cookie 过期 → 自动降级匿名
    粉丝数 fallback: x/relation/stat（匿名 acc/info 不返回 follower 字段）
    """
    try:
        u = _user_mod.User(mid, credential=_credential)
        info = _sync(u.get_user_info())
    except Exception as e:
        if _credential and _is_auth_error(e):
            logger.warning('UP主信息获取凭证过期，使用匿名: %s', e)
            u = _user_mod.User(mid)
            info = _sync(u.get_user_info())
        else:
            raise
    follower = info.get('follower')
    if follower is None:
        try:
            rel = _sync(_user_mod.User(mid).get_relation_info())
            follower = rel.get('follower', 0)
        except Exception:
            logger.warning('粉丝数获取失败 mid=%d', mid)
            follower = 0
    return {
        'name': info.get('name', ''),
        'avatar': (info.get('face', '') or '').replace('http://', 'https://'),
        'follower_count': follower,
        'video_count': info.get('video') or 0,
    }


def get_video_list(mid: int, max_pages: int | None = None) -> Generator[dict, None, None]:
    """分页获取 UP 主视频列表（pubdate 倒序）。

    使用 arc/search API，逐页 yield 视频 dict。
    含四种错误处理路径：
      1) Cookie 过期 → 切换匿名 User 重试（仅一次）
      2) IP 级封禁 412 → 立即 break，不重试
      3) 风控限流 → 指数退避等待后重试（每页最多 3 次）
      4) 其他错误 → break 终止迭代

    pagination 策略：
      - 有 page.count 时按 total_pages 计算翻页数
      - page.count==0 或缺失时按 vlist 长度判断（len < PAGE_SIZE 即最后一页）
    """
    u = _user_mod.User(mid, credential=_credential)
    pn = 1
    retry_delay = 30
    auth_retried = False
    page_retries = 0
    MAX_PAGE_RETRIES = 3

    while True:
        if max_pages is not None and pn > max_pages:
            break
        logger.info('正在获取第 %d 页视频列表 ...', pn)
        try:
            data = _sync(u.get_videos(ps=PAGE_SIZE, pn=pn))
            page_retries = 0  # 成功则重置本页重试计数
        except Exception as e:
            logger.error('获取第 %d 页视频列表失败: %s', pn, e)
            if _credential and _is_auth_error(e) and not auth_retried:
                logger.warning('凭证过期，切换为匿名访问后重试第 %d 页', pn)
                auth_retried = True
                u = _user_mod.User(mid)
                continue
            if _is_ip_blocked(e):
                global _last_412_time
                _last_412_time = time.time()
                logger.error('IP 被安全封禁(412)，停止爬取')
                break
            if _is_risk_control(e):
                page_retries += 1
                if page_retries > MAX_PAGE_RETRIES:
                    logger.error('第 %d 页重试 %d 次仍被风控，停止', pn, MAX_PAGE_RETRIES)
                    break
                logger.warning(
                    '⚠️ 触发风控，等待 %ds 后重试 (第 %d/%d 次)...',
                    retry_delay,
                    page_retries,
                    MAX_PAGE_RETRIES,
                )
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 600)
                continue
            break

        vlist = data.get('list', {}).get('vlist', [])
        if not vlist:
            logger.info('第 %d 页 vlist 为空，结束迭代', pn)
            break

        page_info = data.get('page', {})
        first_pubdate = vlist[0].get('created', 0)
        first_pubdate_str = (
            datetime.fromtimestamp(first_pubdate, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
            if first_pubdate
            else '?'
        )
        logger.info(
            '第 %d 页返回 %d/%d 个视频 (total=%s, ps=%s), 首 bvid=%s pubdate=%s',
            pn,
            len(vlist),
            PAGE_SIZE,
            page_info.get('count'),
            page_info.get('ps', '?'),
            vlist[0].get('bvid', '?'),
            first_pubdate_str,
        )

        for item in vlist:
            pubdate_ts = item.get('created', 0)
            yield {
                'aid': int(item.get('aid', 0)),
                'bvid': item.get('bvid', ''),
                'title': item['title'],
                'description': item.get('description', ''),
                'duration': _parse_duration(item.get('length', '00:00')),
                'pubdate': pubdate_ts,
                'pub_date': (
                    datetime.fromtimestamp(pubdate_ts, tz=timezone.utc).date()
                    if pubdate_ts
                    else None
                ),
                'pub_datetime': (
                    datetime.fromtimestamp(pubdate_ts, tz=timezone.utc) if pubdate_ts else None
                ),
                'view_count': item.get('play', 0),
                'comment_count': item.get('comment', 0),
                'danmaku_count': item.get('video_review', 0),
            }

        page = data.get('page', {})
        total_count = page.get('count', 0)
        total_pages = (total_count + PAGE_SIZE - 1) // PAGE_SIZE if total_count > 0 else 0
        if pn >= total_pages and total_pages > 0:
            break
        # 当 API 不返回 count 或 count=0 时，依赖 vlist 长度推断是否还有下页
        if total_pages == 0 and len(vlist) < PAGE_SIZE:
            break
        pn += 1
        import random

        # 匿名访问时翻倍间隔，降低风控概率
        sleep_base = REQUEST_INTERVAL * 4 if _credential is None else REQUEST_INTERVAL * 2
        time.sleep(sleep_base + random.random() * 3.0)


def get_video_list_from_dynamics(mid: int) -> list[dict]:
    """动态流兜底 — 捕获 arc/search 遗漏的视频（通常是 shorts / 短视频）。

    请求 x/polymer/web-dynamic/v1/feed/space 获取最近 ~12 条动态：
      DYNAMIC_TYPE_AV → 自身投稿，直接提取 bvid
      DYNAMIC_TYPE_FORWARD → 转发，取 orig 中的 bvid
    对每个 bvid 调 Video.get_info() 拿到完整元数据；
    过滤 owner_mid != 目标 mid 的转发视频。

    返回 list[dict]，字段格式与 get_video_list 对齐。
    """
    u = _user_mod.User(mid, credential=_credential)
    try:
        data = _sync(u.get_dynamics_new())
    except Exception as e:
        if _credential and _is_auth_error(e):
            u = _user_mod.User(mid)
            data = _sync(u.get_dynamics_new())
        else:
            logger.warning('动态发现: get_dynamics_new 失败 mid=%d: %s', mid, e)
            time.sleep(3.0)
            u = _user_mod.User(mid)
            try:
                data = _sync(u.get_dynamics_new())
            except Exception as e2:
                logger.warning('动态发现: get_dynamics_new 重试失败 mid=%d: %s', mid, e2)
                return []

    items = data.get('items') or []
    seen_bvids: set[str] = set()
    results: list[dict] = []

    for item in items:
        work = item
        if item.get('type') == 'DYNAMIC_TYPE_FORWARD':
            orig = item.get('orig')
            if orig:
                work = orig
        modules = work.get('modules') or {}
        mod_dyn = modules.get('module_dynamic') or {}
        major = mod_dyn.get('major') or {}
        archive = major.get('archive') or {}
        bvid = archive.get('bvid', '')
        if not bvid or not bvid.startswith('BV') or bvid in seen_bvids:
            continue
        seen_bvids.add(bvid)

        try:
            if _credential is not None:
                info = _sync(_video_mod.Video(bvid=bvid, credential=_credential).get_info())
            else:
                info = _sync(_video_mod.Video(bvid=bvid).get_info())
        except Exception as e:
            try:
                info = _sync(_video_mod.Video(bvid=bvid).get_info())
            except Exception as e2:
                logger.warning(
                    '动态发现: 视频 %s 信息获取失败 (cred=%s): %s / %s',
                    bvid,
                    _credential is not None,
                    e,
                    e2,
                )
                time.sleep(3.0)
                continue

        # 跳过非本 UP 主的转发视频
        owner_mid = info.get('owner', {}).get('mid', 0)
        if owner_mid != mid:
            logger.debug('动态发现: 跳过转发视频 %s (owner=%d != mid=%d)', bvid, owner_mid, mid)
            continue

        pubdate_ts = info.get('pubdate', 0)
        stat = info.get('stat', {})
        results.append(
            {
                'aid': int(info.get('aid', 0)),
                'bvid': bvid,
                'title': info.get('title', ''),
                'description': info.get('desc', ''),
                'duration': info.get('duration', 0),
                'pubdate': pubdate_ts,
                'pub_date': (
                    datetime.fromtimestamp(pubdate_ts, tz=timezone.utc).date()
                    if pubdate_ts
                    else None
                ),
                'pub_datetime': (
                    datetime.fromtimestamp(pubdate_ts, tz=timezone.utc) if pubdate_ts else None
                ),
                'view_count': stat.get('view', 0),
                'like_count': stat.get('like', 0),
                'coin_count': stat.get('coin', 0),
                'favorite_count': stat.get('favorite', 0),
                'share_count': stat.get('share', 0),
                'comment_count': stat.get('reply', 0),
                'danmaku_count': stat.get('danmaku', 0),
            }
        )

    logger.info('动态发现: mid=%d 找到 %d 个视频 (去重后)', mid, len(results))
    return results


def get_video_stat(bvid: str) -> dict:
    """获取单个视频的详细统计数据，Cookie 过期时自动降级为匿名"""
    try:
        v = _video_mod.Video(bvid=bvid, credential=_credential)
        info = _sync(v.get_info())
    except Exception as e:
        if _credential and _is_auth_error(e):
            logger.warning('视频统计获取凭证过期，使用匿名: %s', e)
            v = _video_mod.Video(bvid=bvid)
            info = _sync(v.get_info())
        else:
            raise
    stat = info.get('stat', {})
    return {
        'view_count': stat.get('view', 0),
        'like_count': stat.get('like', 0),
        'coin_count': stat.get('coin', 0),
        'favorite_count': stat.get('favorite', 0),
        'share_count': stat.get('share', 0),
        'comment_count': stat.get('reply', 0),
        'danmaku_count': stat.get('danmaku', 0),
    }


def _parse_duration(length_str: str) -> int:
    if not length_str or not length_str.strip():
        return 0
    try:
        parts = list(map(int, length_str.split(':')))
    except (ValueError, TypeError):
        logger.warning('无法解析视频时长: %r', length_str)
        return 0
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    elif len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return 0
