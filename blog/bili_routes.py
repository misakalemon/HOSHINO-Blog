"""Bilibili 管理路由 — UP 主管理 / 爬取调度 / 扫码登录

管理后台的 Bilibili 相关功能，包括：
  - UP 主 CRUD（增删改查）
  - B 站扫码登录 / 登出
  - 视频重点追踪（watch/unwatch）
  - 视频遗漏检查（对比 API video_count 与 DB 实际数）

爬取架构概要：
  增量检查（每 30min）→ _check_new_videos
    arc/search 翻前 10 页 + 动态流兜底 + 最新 10 视频跟踪 + 重点视频跟踪
  每日深扫（02:00）    → _run_scrape
    补全缺失视频 + 动态流兜底 + Hot/Warm/Cold 三层统计更新
  手动刷新             → refresh_up / refresh_up_all → _run_scrape

线程安全：
  _scrape_running / _incremental_running / _scrape_progress
  三者受 _scrape_lock 保护，深扫与增量可并行但同一 UP 互斥。

防封机制：
  每视频请求后随机睡眠 _VIDEO_SLEEP_BASE + [0, JITTER) 秒
  检测到 412 IP 封禁时全局熔断 _CIRCUIT_COOLDOWN 秒
  风控时指数退避重试（retry_delay 从 30s → 600s）
"""

import datetime

CST = datetime.timezone(datetime.timedelta(hours=8))  # 东八区（中国标准时间）

import json
import logging
import os
import random
import threading
import time

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import login_required

from sqlalchemy.exc import IntegrityError

from blog.models import (
    BiliSubscription,
    BiliUp,
    BiliUpHistory,
    BiliVideo,
    BiliVideoHistory,
    BiliWatchedVideo,
    db,
)
from .admin import editor_required

logger = logging.getLogger(__name__)

bili_bp = Blueprint('bili', __name__, url_prefix='/admin/bilibili')  # 管理后台 Bilibili 子路由


@bili_bp.route('/')
@editor_required
def index():
    """UP 主管理列表页 — 按更新时间倒序显示所有 UP 主

    Returns:
        HTML 页面，渲染 admin/bili_index.html
    """
    ups = BiliUp.query.order_by(BiliUp.updated_at.desc()).all()
    # 检查 B站 登录状态
    from blog.bilibili.login import apply_cookies

    logged_in = apply_cookies()
    return render_template('admin/bili_index.html', ups=ups, bili_logged_in=logged_in)


# ── B站 扫码登录 ────────────────────────────────


@bili_bp.route('/qr-gen')
@editor_required
def qr_generate():
    """生成 B 站登录二维码

    使用官方库生成扫码登录二维码，返回 base64 编码的图片数据
    供前端展示给用户扫码。

    Returns:
        JSON: {ok: True, qrcode_key: str, img: str(base64)}
              或 {ok: False, error: str}
    """
    from blog.bilibili.login import generate_qr_v2

    try:
        data = generate_qr_v2()
        return {'ok': True, 'qrcode_key': data['qrcode_key'], 'img': data['img']}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@bili_bp.route('/qr-poll')
@editor_required
def qr_poll():
    """轮询 B 站扫码登录状态

    前端周期性调用此接口查询用户是否已完成扫码。

    Query Params:
        key (str): 之前 qr_generate 返回的 qrcode_key

    Returns:
        JSON: B 站 OAuth 轮询结果（含登录态 Cookie 信息）
    """
    qrcode_key = request.args.get('key', '')
    if not qrcode_key:
        return {'ok': False, 'error': 'missing key'}

    from blog.bilibili.login import poll_qr_v2

    return poll_qr_v2(qrcode_key)


@bili_bp.route('/logout-bili', methods=['POST'])
@editor_required
def logout_bili():
    """清除 B 站登录 Cookie 文件

    删除本地 COOKIE_FILE 以退出 B 站登录态。
    POST 请求，成功/失败均重定向到管理首页。

    Returns:
        HTTP 重定向到 bili.index
    """
    from blog.bilibili.config import COOKIE_FILE

    try:
        if os.path.exists(COOKIE_FILE):
            os.remove(COOKIE_FILE)
        flash('已退出 B站 登录', 'success')
    except Exception as e:
        flash(f'退出失败: {e}', 'error')
    return redirect(url_for('bili.index'))


@bili_bp.route('/up/<int:up_id>')
@editor_required
def up_detail(up_id):
    """查看单个 UP 主的视频列表（分页，每页 30 条）

    Args:
        up_id (int): UP 主数据库 ID

    Query Params:
        page (int): 页码，默认 1

    Returns:
        HTML 页面，渲染 admin/bili_videos.html
    """
    page = request.args.get('page', 1, type=int)
    per_page = 30
    up = BiliUp.query.get_or_404(up_id)
    pagination = (
        BiliVideo.query.filter_by(up_id=up_id)
        .order_by(BiliVideo.pubdate.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )
    # 加载所有重点追踪视频 ID 集合，方便前端标记
    watched_ids = {w.video_id for w in BiliWatchedVideo.query.all()}
    return render_template(
        'admin/bili_videos.html', up=up, pagination=pagination, watched_ids=watched_ids
    )


@bili_bp.route('/refresh/<int:up_id>', methods=['POST'])
@editor_required
def refresh_up(up_id):
    """重新爬取单个 UP 主的数据（最多 30 个新视频）

    在 _scrape_lock 保护下检查并发状态，然后启动后台线程执行 _run_scrape
    并立即返回，不阻塞 HTTP 请求。

    Args:
        up_id (int): UP 主数据库 ID

    Returns:
        HTTP 重定向到 up_detail 页
    """
    up = BiliUp.query.get_or_404(up_id)
    # 检查是否正在爬取 — 加锁防止竞态
    with _scrape_lock:
        if up.mid in _scrape_running:
            flash('该 UP 主正在爬取中', 'error')
            return redirect(url_for('bili.up_detail', up_id=up_id))
        # 初始化进度日志 & 标记运行态
        _scrape_progress[up.mid] = []
        _scrape_running.add(up.mid)
    # 获取 Flask app 对象以在线程中创建应用上下文
    app = current_app._get_current_object()
    t = threading.Thread(
        target=_run_scrape, args=(up.mid, up.space_url, app), kwargs={'max_videos': 30}, daemon=True
    )
    t.start()
    flash(f'已开始刷新「{up.name or up.mid}」的数据', 'success')
    return redirect(url_for('bili.up_detail', up_id=up_id))


@bili_bp.route('/refresh-all/<int:up_id>', methods=['POST'])
@editor_required
def refresh_up_all(up_id):
    """重新爬取单个 UP 主的所有视频数据（无配额限制，force=True）

    与 refresh_up 的区别：传入 force=True 跳过 should_fill 条件判断、
    跳过 age 检查，强制翻全量更新所有视频。

    Args:
        up_id (int): UP 主数据库 ID

    Returns:
        HTTP 重定向到 up_detail 页
    """
    up = BiliUp.query.get_or_404(up_id)
    with _scrape_lock:
        if up.mid in _scrape_running:
            flash('该 UP 主正在爬取中', 'error')
            return redirect(url_for('bili.up_detail', up_id=up_id))
        _scrape_progress[up.mid] = []
        _scrape_running.add(up.mid)
    app = current_app._get_current_object()
    t = threading.Thread(
        target=_run_scrape, args=(up.mid, up.space_url, app), kwargs={'force': True}, daemon=True
    )
    t.start()
    flash(f'已开始强制刷新「{up.name or up.mid}」的所有视频', 'success')
    return redirect(url_for('bili.up_detail', up_id=up_id))


@bili_bp.route('/up/<int:up_id>/refresh-comments', methods=['POST'])
@editor_required
def refresh_up_comments(up_id):
    """刷新指定 UP 主的评论并重新生成词云。

    后台线程执行：
      1. 取该 UP 主最新 50 个视频
      2. 逐个爬取评论（补缺 + 刷新）
      3. 重新生成该 UP 主的单视频词云

    Args:
        up_id (int): UP 主数据库 ID

    Returns:
        HTTP 重定向到 up_detail 页
    """
    up = BiliUp.query.get_or_404(up_id)
    with _scrape_lock:
        if up.mid in _scrape_running:
            flash('该 UP 主正在爬取中，请等待完成', 'error')
            return redirect(url_for('bili.up_detail', up_id=up_id))
        _scrape_running.add(up.mid)

    app = current_app._get_current_object()

    def _run():
        try:
            from blog.wordcloud import precompute_up_wordclouds

            with app.app_context():
                videos = BiliVideo.query.filter_by(up_id=up_id).order_by(
                    BiliVideo.pubdate.desc()
                ).limit(50).all()
                for v in videos:
                    try:
                        n = _crawl_video_comments(v)
                        if n:
                            logger.info('评论 [%s] 爬取 %d 条', v.bvid[:8], n)
                        time.sleep(3.0 + random.random() * 2.0)
                    except Exception as e:
                        logger.warning('视频 %s 评论失败: %s', v.bvid, e)

                precompute_up_wordclouds(up_id)
                logger.info('UP主 %s 词云已刷新', up_id)
        finally:
            with _scrape_lock:
                _scrape_running.discard(up.mid)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    flash(f'已开始刷新「{up.name or up.mid}」的评论与词云', 'success')
    return redirect(url_for('bili.up_detail', up_id=up_id))


@bili_bp.route('/delete/<int:up_id>', methods=['POST'])
@editor_required
def delete_up(up_id):
    """删除 UP 主及其所有关联视频、历史数据

    级联删除由 DB 外键约束自动处理。删除前检查该 UP 主是否正在爬取中。

    Args:
        up_id (int): UP 主数据库 ID

    Returns:
        HTTP 重定向到 bili.index
    """
    up = BiliUp.query.get_or_404(up_id)
    # 如果正在爬取，拒绝删除以防止数据不一致
    if up.mid in _scrape_running:
        flash('该 UP 主正在爬取中，请等待完成后再删除', 'error')
        return redirect(url_for('bili.index'))
    db.session.delete(up)
    db.session.commit()
    flash(f'已删除 UP 主「{up.name or up.mid}」及其视频数据', 'success')
    return redirect(url_for('bili.index'))


@bili_bp.route('/delete-video/<int:video_id>', methods=['POST'])
@editor_required
def delete_video(video_id):
    """删除单条视频记录及关联历史快照

    Args:
        video_id (int): 视频数据库 ID（级联删除由外键处理）

    Returns:
        HTTP 重定向到所属 UP 主的 up_detail 页
    """
    video = BiliVideo.query.get_or_404(video_id)
    up_id = video.up_id
    db.session.delete(video)
    db.session.commit()
    flash(f'已删除视频 {video.bvid}', 'success')
    return redirect(url_for('bili.up_detail', up_id=up_id))


@bili_bp.route('/video/<int:video_id>/watch', methods=['POST'])
@editor_required
def watch_video(video_id):
    """将视频加入重点追踪列表

    加入后每 30 分钟增量检查 _check_new_videos 时会单独更新其统计数据
    并记录 BiliVideoHistory 快照，用于细粒度趋势观察。

    Args:
        video_id (int): 视频数据库 ID

    Returns:
        JSON: {ok: True, watched: True}
              或 {ok: False, error: str}
    """
    video = BiliVideo.query.get_or_404(video_id)
    # 检查是否已在重点追踪列表中
    if BiliWatchedVideo.query.filter_by(video_id=video_id).first():
        return {'ok': False, 'error': '已在重点追踪列表中'}
    db.session.add(BiliWatchedVideo(video_id=video_id))
    db.session.commit()
    return {'ok': True, 'watched': True}


@bili_bp.route('/video/<int:video_id>/unwatch', methods=['POST'])
@editor_required
def unwatch_video(video_id):
    """将视频移出重点追踪列表

    Args:
        video_id (int): 视频数据库 ID

    Returns:
        JSON: {ok: True, watched: False}
    """
    db.session.query(BiliWatchedVideo).filter_by(video_id=video_id).delete()
    db.session.commit()
    return {'ok': True, 'watched': False}


@bili_bp.route('/check-missing')
@editor_required
def check_missing():
    """检查所有 UP 主视频是否有遗漏（对比 API video_count 与 DB 实际数）

    逐个 UP 主调用 B 站 API 获取 video_count（该 UP 主视频总数），
    与数据库中实际视频数对比，以百分比形式展示数据库完整性。

    Returns:
        JSON: {
            ok: True,
            results: [{name, mid, up_id, db, api, missing, percent, error}],
            total: int
        }
    """
    from blog.bilibili.login import apply_cookies
    from blog.bilibili.bili_api import get_user_info

    apply_cookies()

    results = []
    ups = BiliUp.query.order_by(BiliUp.updated_at.desc()).all()
    for up in ups:
        db_count = BiliVideo.query.filter_by(up_id=up.id).count()
        try:
            ui = get_user_info(up.mid)
            api_count = ui.get('video_count', 0)
        except Exception as e:
            # API 调用失败时记录错误信息，标记为未知
            results.append(
                dict(
                    name=up.name,
                    mid=up.mid,
                    up_id=up.id,
                    db=db_count,
                    api='?',
                    missing='?',
                    percent='-',
                    error=str(e),
                )
            )
            continue

        # 计算缺失数量及完整百分比
        if api_count > 0:
            missing = max(0, api_count - db_count)
            pct = f'{db_count / api_count * 100:.1f}%'
        else:
            missing = '?'
            pct = '-'
        results.append(
            dict(
                name=up.name,
                mid=up.mid,
                up_id=up.id,
                db=db_count,
                api=api_count,
                missing=missing,
                percent=pct,
                error=None,
            )
        )

    return {'ok': True, 'results': results, 'total': len(results)}


# ── 爬取任务共享状态 ────────────────────────────
# 深扫运行中的 mid 集合（每日刷新 / 手动触发），启动前需先检查
_scrape_running: set[int] = set()
# 增量检查运行中的 mid 集合（与深扫互斥：启动前同时检查两者）
_incremental_running: set[int] = set()
# 实时爬取日志 {mid: [str, ...]} 供 AJAX scrape-status 轮询
_scrape_progress: dict[int, list[str]] = {}
# 上述三个共享状态的互斥锁 — 读写均需持有
_scrape_lock = threading.Lock()
# 每视频请求后的睡眠（防风控）— BASE + [0, JITTER) 秒
_VIDEO_SLEEP_BASE = 7.0
_VIDEO_SLEEP_JITTER = 3.0
# 全局熔断器 — 检测到 412 IP封禁后自动暂停所有爬取直到此时间戳（Unix 秒）
_circuit_open_until: float = 0.0
_CIRCUIT_COOLDOWN = 60 * 60  # 封禁后冷却 60 分钟


def _insert_or_update_video(up, video_info, aid, bvid, title_short):
    """插入新视频或更新已有视频的统计数据。

    先尝试插入新记录；若 aid 唯一性冲突（IntegrityError），
    则查询已有记录并仅更新统计数字段（view/like/coin 等），
    不覆盖标题、发布时间等元信息。
    每次成功插入或更新后，同时写入一条 BiliVideoHistory 快照。

    Args:
        up (BiliUp): 所属 UP 主 ORM 对象
        video_info (dict): 视频完整信息，包含 title/bvid/aid/pubdate/duration
            以及 view_count/like_count 等统计字段
        aid (int): B 站 av 号（唯一约束）
        bvid (str): B 站 BV 号
        title_short (str): 截断后的视频标题（最长 30 字符，仅用于日志）

    Returns:
        (video_or_None, is_new: bool)
        is_new=True 表示第一次入库；is_new=False 表示仅更新了已有记录
    """
    is_new = True
    try:
        # 尝试插入新视频记录
        video = BiliVideo(up_id=up.id, **video_info)
        db.session.add(video)
        db.session.flush()
        # 新视频：异步抓取标签（不阻塞流程）
        try:
            from blog.bilibili.bili_api import get_video_tags
            tags = get_video_tags(bvid)
            if tags:
                video.tags = tags
                db.session.flush()
        except Exception as e:
            logger.warning('视频 %s 标签获取失败: %s', bvid, e)
    except IntegrityError:
        # aid 冲突 → 已有记录，回退并更新统计字段
        db.session.rollback()
        existing = BiliVideo.query.filter_by(aid=aid).first()
        if existing:
            # 仅更新统计字段，不覆盖标题/发布时间等元信息
            for key in (
                'view_count',
                'like_count',
                'coin_count',
                'favorite_count',
                'share_count',
                'comment_count',
                'danmaku_count',
            ):
                if key in video_info:
                    setattr(existing, key, video_info[key])
            existing.updated_at = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
            video = existing
            is_new = False
        else:
            return None, False
    except Exception as e:
        # 非预期的数据库异常
        db.session.rollback()
        logger.warning('视频 %s 「%s」入库失败: %s', bvid, title_short, e)
        return None, False
    try:
        # 写入统计历史快照
        db.session.add(
            BiliVideoHistory(
                video_id=video.id,
                view_count=video_info.get('view_count', 0),
                like_count=video_info.get('like_count', 0),
                coin_count=video_info.get('coin_count', 0),
                favorite_count=video_info.get('favorite_count', 0),
                share_count=video_info.get('share_count', 0),
                comment_count=video_info.get('comment_count', 0),
                danmaku_count=video_info.get('danmaku_count', 0),
            )
        )
    except Exception:
        db.session.rollback()
        return None, False
    return video, is_new


_COMMENT_PAGES = 10
_COMMENT_SLEEP_BASE = 4.0
_COMMENT_SLEEP_JITTER = 3.0


def _crawl_video_comments(video, max_pages: int = _COMMENT_PAGES):
    """爬取单个视频的热门评论（最多前 max_pages 页）。

    使用 B 站 API 按热度排序分页获取评论，每页间隔随机延时防风控。
    自动检测风控/封禁并降级。

    Args:
        video (BiliVideo): 视频 ORM 对象（需有 id 和 aid）
        max_pages (int):   最大翻页数（默认 10 页）
    Returns:
        int: 爬取的评论总数
    """
    from blog.bilibili.bili_api import get_video_comments, _is_risk_control, was_recently_blocked
    from .models import BiliVideoComment

    total = 0
    for page in range(1, max_pages + 1):
        if was_recently_blocked():
            break
        try:
            comments = get_video_comments(video.aid, page)
        except Exception as e:
            if _is_risk_control(e):
                logger.warning('视频 %s 评论触发风控，第 %d 页跳过', video.bvid, page)
                time.sleep(15.0)
                continue
            logger.warning('视频 %s 第 %d 页评论失败: %s', video.bvid, page, e)
            break

        if not comments:
            break

        for c in comments:
            ctime = c.get('ctime', 0)
            content = (c.get('content') or '')[:2000]
            if not content:
                continue
            existing = BiliVideoComment.query.filter_by(
                video_id=video.id,
                ctime=ctime,
                content=content,
            ).first()
            if existing:
                continue
            db.session.add(BiliVideoComment(
                video_id=video.id,
                content=content,
                author=(c.get('author') or '')[:64],
                ctime=ctime,
                like_count=c.get('like_count', 0),
            ))
            total += 1

        db.session.commit()

        if len(comments) < 20:
            break

        time.sleep(_COMMENT_SLEEP_BASE + random.random() * _COMMENT_SLEEP_JITTER)

    return total


def _check_new_videos(mid: int, app):
    """增量检查 — 每 30 分钟执行，发现新视频并更新统计数据。

    从零开始逐步构建的渐进式爬取策略：
      1. 加载 DB 中已记录的 bvid/aid 集合（用于快速判重）
      2. arc/search API 翻前 10 页（按 pubdate 倒序）
         → 利用连续已知视频计数提前终止（连续 30 个已知即视为已无新视频）
      3. 动态流兜底（始终执行，捕获 arc/search 可能遗漏的 shorts/新视频）
         → B 站动态接口会返回近期活跃视频
      4. 追踪最新 10 个视频的统计数据变化（30 分钟快照）
      5. 追踪用户标记的重点关注视频（加入 BiliWatchedVideo 的视频）

    线程安全：
      - 启动前需检查 _scrape_running 和 _incremental_running（互斥锁保护）
      - 运行完毕在 finally 中清理 _incremental_running 和 _scrape_progress

    风控处理：
      - 每个视频请求后随机睡眠 _VIDEO_SLEEP_BASE + [0, JITTER) 秒
      - 检测到 412 时打开全局熔断器，暂停所有爬取

    Args:
        mid (int): 目标 UP 主的 B 站 mid
        app (Flask): Flask 应用实例（用于在线程中创建应用上下文）
    """
    # 全局熔断检查 — 如果最近触发了 412 IP 封禁，跳过本次增量
    global _circuit_open_until
    if time.time() < _circuit_open_until:
        logger.warning('全局熔断中，跳过增量检查 mid=%d', mid)
        return

    # 获取该 mid 的进度日志列表（引用，后续直接 append）
    with _scrape_lock:
        prog = _scrape_progress.get(mid, [])
    _up_name = ['?']

    def emit(line: str):
        """向进度日志追加一行并同时输出到日志系统"""
        prog.append(f'[{time.strftime("%H:%M:%S")}] [{_up_name[0]}] {line}')
        logger.info('[%s] %s', _up_name[0], line)

    with app.app_context():
        try:
            import datetime
            from blog.bilibili.bili_api import get_video_list, get_video_stat

            up = BiliUp.query.filter_by(mid=mid).first()
            if not up:
                return
            _up_name[0] = up.name or str(mid)

            # 取数据库已有的 bvid 和 aid 集合 — 用于快速判重
            existing_bvids = {
                r[0]
                for r in BiliVideo.query.with_entities(BiliVideo.bvid).filter_by(up_id=up.id).all()
            }
            existing_aids = {
                r[0]
                for r in BiliVideo.query.with_entities(BiliVideo.aid).filter_by(up_id=up.id).all()
            }

            count = 0
            consecutive_known = 0  # 连续已知视频计数 — 超阈值说明已无新视频
            _batch_count = 0
            # 连续 30 个视频全部已知 → 认为已经扫描到已入库的尾部，提前停止
            MAX_CONSECUTIVE_KNOWN = 30
            # arc/search API 逐页遍历（最多 10 页）
            for video_info in get_video_list(mid, max_pages=10):
                bvid = video_info['bvid']
                aid = video_info['aid']
                title_short = (video_info.get('title') or '')[:30]
                is_known = bvid in existing_bvids or aid in existing_aids
                if is_known:
                    consecutive_known += 1
                    if consecutive_known > MAX_CONSECUTIVE_KNOWN:
                        logger.info('连续 %d 个视频已知，跳过后续页', consecutive_known)
                        break
                    continue
                consecutive_known = 0
                logger.info(
                    '增量检查: bvid=%s aid=%s title=%s known=%s', bvid, aid, title_short, is_known
                )

                try:
                    # 获取视频统计数据并合并到 video_info 中
                    stat = get_video_stat(bvid)
                    video_info.update(stat)
                    # 随机延时防 B 站风控
                    time.sleep(_VIDEO_SLEEP_BASE + random.random() * _VIDEO_SLEEP_JITTER)
                except Exception as e:
                    logger.warning('视频 %s 统计获取失败: %s', bvid, e)
                    time.sleep(12.0)
                    continue

                video, ok = _insert_or_update_video(up, video_info, aid, bvid, title_short)
                if not ok:
                    continue

                # 批量提交 — 每 20 条 flush 一次减少事务压力
                _batch_count += 1
                if _batch_count >= 20:
                    db.session.commit()
                    _batch_count = 0

                count += 1
                existing_bvids.add(bvid)
                existing_aids.add(aid)
                title_short = (video_info.get('title') or '')[:30]
                emit(f'发现新视频 [{count}] {title_short}')

            # 动态发现兜底：arc/search 可能遗漏 shorts / 新投稿
            # B 站动态接口会返回 UP 主最近发布的视频，作为补充
            from blog.bilibili.bili_api import get_video_list_from_dynamics

            try:
                dyn_videos = get_video_list_from_dynamics(mid)
            except Exception as e:
                logger.warning('动态发现失败 mid=%d: %s', mid, e)
                dyn_videos = []
            _batch_count = 0
            for video_info in dyn_videos:
                bvid = video_info['bvid']
                aid = video_info['aid']
                title_short = (video_info.get('title') or '')[:30]
                if bvid in existing_bvids or aid in existing_aids:
                    continue
                video, ok = _insert_or_update_video(up, video_info, aid, bvid, title_short)
                if not ok:
                    continue

                # 动态发现结果也使用批量提交
                _batch_count += 1
                if _batch_count >= 20:
                    db.session.commit()
                    _batch_count = 0

                count += 1
                existing_bvids.add(bvid)
                existing_aids.add(aid)
                emit(f'[动态发现] 新视频 [{count}] {title_short}')
            if dyn_videos:
                emit(f'动态发现完成，共扫描 {len(dyn_videos)} 个视频')
            db.session.commit()

            # 更新 UP 主的视频总数
            up.video_count = BiliVideo.query.filter_by(up_id=up.id).count()
            db.session.commit()
            if count:
                emit(f'增量完成，新增 {count} 个视频')
                # ── 发送邮件通知给已订阅的用户 ──────────
                try:
                    new_videos = (
                        BiliVideo.query.filter_by(up_id=up.id)
                        .order_by(BiliVideo.pubdate.desc())
                        .limit(count)
                        .all()
                    )
                    # 构造邮件模板所需的数据
                    new_videos_data = [
                        {
                            'title': v.title or '',
                            'bvid': v.bvid,
                            'pub_date': v.pub_date.strftime('%Y-%m-%d') if v.pub_date else '',
                            'duration': f'{v.duration // 60}:{v.duration % 60:02d}'
                            if v.duration
                            else '',
                            'view_count': v.view_count or 0,
                            'like_count': v.like_count or 0,
                        }
                        for v in new_videos
                    ]
                    # 查询已通过邮箱验证的订阅者
                    subs = BiliSubscription.query.filter_by(up_id=up.id, verified=True).all()
                    if subs:
                        from blog.mail import send_new_video_notify

                        emit(f'发送邮件通知给 {len(subs)} 个订阅者')
                        for sub in subs:
                            unsub_url = url_for(
                                'bili_public.unsubscribe', token=sub.token, _external=True
                            )
                            send_new_video_notify(
                                sub.email, up.name or str(up.mid), new_videos_data, unsub_url
                            )
                except Exception as e:
                    logger.error('发送新视频通知失败 mid=%d: %s', mid, e)

            # ── 追踪最新 10 个视频的统计（每 30 分钟快照）──
            try:
                latest = (
                    BiliVideo.query.filter_by(up_id=up.id)
                    .order_by(BiliVideo.pubdate.desc())
                    .limit(10)
                    .all()
                )
                if latest:
                    emit(f'追踪最新 {len(latest)} 个视频统计')
                for v in latest:
                    # 记录更新前的旧值，用于计算增量
                    old_view = v.view_count or 0
                    old_like = v.like_count or 0
                    old_coin = v.coin_count or 0
                    old_fav = v.favorite_count or 0
                    old_share = v.share_count or 0
                    old_comment = v.comment_count or 0
                    old_danmaku = v.danmaku_count or 0

                    stat = get_video_stat(v.bvid)
                    for key, val in stat.items():
                        setattr(v, key, val)
                    # 记录历史快照
                    db.session.add(
                        BiliVideoHistory(
                            video_id=v.id,
                            view_count=stat.get('view_count', 0),
                            like_count=stat.get('like_count', 0),
                            coin_count=stat.get('coin_count', 0),
                            favorite_count=stat.get('favorite_count', 0),
                            share_count=stat.get('share_count', 0),
                            comment_count=stat.get('comment_count', 0),
                            danmaku_count=stat.get('danmaku_count', 0),
                        )
                    )
                    db.session.commit()
                    title_short = (v.title or '')[:30]
                    nv = stat.get('view_count', 0)
                    nl = stat.get('like_count', 0)
                    nc = stat.get('coin_count', 0)
                    nf = stat.get('favorite_count', 0)
                    ns = stat.get('share_count', 0)
                    ncm = stat.get('comment_count', 0)
                    nd = stat.get('danmaku_count', 0)
                    emit(f'[跟踪] 「{title_short}」')
                    emit(
                        f'  播放:{nv:,}(+{nv - old_view:,})  点赞:{nl:,}(+{nl - old_like:,})  投币:{nc:,}(+{nc - old_coin:,})  收藏:{nf:,}(+{nf - old_fav:,})'
                    )
                    emit(
                        f'  转发:{ns:,}(+{ns - old_share:,})  评论:{ncm:,}(+{ncm - old_comment:,})  弹幕:{nd:,}(+{nd - old_danmaku:,})'
                    )
                    time.sleep(_VIDEO_SLEEP_BASE + random.random() * _VIDEO_SLEEP_JITTER)
            except Exception as e:
                logger.error('最新视频追踪失败 mid=%d: %s', mid, e)

            # ── 追踪用户标记的重点关注视频 ────────────
            try:
                watched = (
                    BiliVideo.query.join(BiliWatchedVideo).filter(BiliVideo.up_id == up.id).all()
                )
                if watched:
                    emit(f'追踪 {len(watched)} 个重点视频')
                    count += len(watched)
                for v in watched:
                    stat = get_video_stat(v.bvid)
                    for key, val in stat.items():
                        setattr(v, key, val)
                    db.session.add(
                        BiliVideoHistory(
                            video_id=v.id,
                            view_count=stat.get('view_count', 0),
                            like_count=stat.get('like_count', 0),
                            coin_count=stat.get('coin_count', 0),
                            favorite_count=stat.get('favorite_count', 0),
                            share_count=stat.get('share_count', 0),
                            comment_count=stat.get('comment_count', 0),
                            danmaku_count=stat.get('danmaku_count', 0),
                        )
                    )
                    db.session.commit()
                    title_short = (v.title or '')[:30]
                    emit(
                        f'[重点] 「{title_short}」  播放:{stat.get("view_count", 0):,}  点赞:{stat.get("like_count", 0):,}  投币:{stat.get("coin_count", 0):,}'
                    )
                    time.sleep(_VIDEO_SLEEP_BASE + random.random() * _VIDEO_SLEEP_JITTER)
            except Exception as e:
                logger.error('重点视频追踪失败 mid=%d: %s', mid, e)

            # 检查 B站 API 层是否已检测到 412（可能在 get_video_list 内部处理，未抛异常到此处）
            from blog.bilibili.bili_api import was_recently_blocked
            if was_recently_blocked(cooldown=300) and time.time() >= _circuit_open_until:
                _circuit_open_until = time.time() + _CIRCUIT_COOLDOWN
                logger.error('API 层检测到 412 封禁，全局熔断 %d 分钟', _CIRCUIT_COOLDOWN // 60)

        except Exception as e:
            logger.error('增量检查失败 mid=%d: %s', mid, e)
            from blog.bilibili.bili_api import _is_ip_blocked
            if _is_ip_blocked(e):
                _circuit_open_until = time.time() + _CIRCUIT_COOLDOWN
                logger.error('检测到 412 封禁，全局熔断 %d 分钟', _CIRCUIT_COOLDOWN // 60)
        finally:
            # 无论成功还是异常，都必须清理运行状态
            with _scrape_lock:
                _incremental_running.discard(mid)
                _scrape_progress.pop(mid, None)
            db.session.remove()


@bili_bp.route('/scrape-status')
@editor_required
def scrape_status():
    """返回指定 UP 主的爬取进度日志（JSON，供前端 AJAX 轮询）

    前端通过定时调用此接口获取实时爬取进度，使用 deepcopy
    以避免在读取过程中进度日志被后台线程修改。

    Query Params:
        mid (int): 目标 UP 主的 B 站 mid

    Returns:
        JSON: {
            running: bool,   # 该 mid 是否正在爬取中
            lines: [str]     # 实时日志行列表
        }
    """
    mid = request.args.get('mid', type=int)
    if not mid:
        return {'running': False, 'lines': []}
    from copy import deepcopy

    with _scrape_lock:
        lines = deepcopy(_scrape_progress.get(mid, []))
        running = (mid in _scrape_running) or (mid in _incremental_running)
    return {'running': running, 'lines': lines}


@bili_bp.route('/scrape', methods=['POST'])
@editor_required
def scrape():
    """启动新 UP 主的爬取任务（根据 space_url 自动提取 mid）

    解析前端提交的 UP 主空间链接（如 https://space.bilibili.com/12345），
    自动提取 mid 后启动后台线程执行 _run_scrape 完整爬取。

    与 refresh_up/refresh_up_all 不同，此路由从零开始爬取
    一个全新的 UP 主（无 DB 记录）。

    Returns:
        JSON: {ok: True, mid: int}
              或 {ok: False, error: str}
    """
    space_url = request.form.get('space_url', '').strip()
    if not space_url:
        flash('请输入 UP 主空间链接', 'error')
        return redirect(url_for('bili.index'))

    try:
        from blog.bilibili.bili_api import extract_mid

        mid = extract_mid(space_url)
    except ValueError as e:
        flash(str(e), 'error')
        return redirect(url_for('bili.index'))

    with _scrape_lock:
        if mid in _scrape_running:
            return {'ok': False, 'error': '该 UP 主正在爬取中，请等待完成'}
        _scrape_progress[mid] = []
        _scrape_running.add(mid)

    # 在后台线程中执行爬取（传入 app 实例以建立应用上下文）
    app = current_app._get_current_object()
    t = threading.Thread(target=_run_scrape, args=(mid, space_url, app), daemon=True)
    t.start()
    return {'ok': True, 'mid': mid}


def _run_scrape(mid: int, space_url: str, app, max_videos: int | None = None, force: bool = False):
    """深扫 — 每日刷新或手动触发的完整爬取。

    从零开始逐步构建的全面爬取策略：
      A. 获取/更新 UP 主信息（名称/头像/粉丝数）
      B. 补全缺失视频（should_fill=True 时）
         → arc/search API 翻全量，已知跳过，新视频入库 + BiliVideoHistory
      C. 动态流兜底（始终执行，不受 should_fill 影响）
         → 捕获 arc/search API 可能遗漏的 shorts/新视频
      D. 三层统计更新（Hot ≤7d / Warm 8~30d / Cold >30d）
         → Hot：全部更新，不跳过（min_age_hours=0）
         → Warm：配额剩余时更新，1 小时内跳过，按 updated_at ASC 优先更新
         → Cold：配额剩余时处理，24 小时内跳过
         → 跳过本次新入库的视频（fill_new_bvids，已有最新数据）
         → 每个视频 7~10s 随机间隔，防风控 + 指数退避重试
         → max_videos 控制总更新数上限

    风控处理：
      - 全局熔断器检测（_circuit_open_until）
      - 风控时指数退避：30s → 60s → 120s → ... → 600s（最大值）
      - 412 封禁触发 60 分钟全局冷却

    Args:
        mid (int):          B 站 mid
        space_url (str):    空间页链接
        app (Flask):        Flask 应用实例（线程内 app_context 使用）
        max_videos (int):   最多更新视频数，None=不限制
        force (bool):       True 时跳过 should_fill 条件判断，强制翻全量；
                           同时跳过 age 检查（min_age_hours 不生效）
    """
    # 全局熔断检查 — force 模式允许忽略熔断
    global _circuit_open_until
    if not force and time.time() < _circuit_open_until:
        logger.warning('全局熔断中，跳过深扫 mid=%d', mid)
        with _scrape_lock:
            _scrape_running.discard(mid)
            _scrape_progress.pop(mid, None)
        return

    # 获取该 mid 的进度日志列表引用
    prog = _scrape_progress.get(mid, [])
    _up_name = ['?']

    def emit(line: str):
        """向进度日志追加一行并同时输出到日志系统"""
        prog.append(f'[{time.strftime("%H:%M:%S")}] [{_up_name[0]}] {line}')
        logger.info('[%s] %s', _up_name[0], line)

    with app.app_context():
        try:
            import datetime
            from blog.bilibili.bili_api import _is_risk_control, get_video_stat, get_user_info

            up = BiliUp.query.filter_by(mid=mid).first()
            total_in_api = None
            # A. 获取/更新 UP 主信息
            try:
                ui = get_user_info(mid)
                total_in_api = ui.get('video_count', 0)
                if up:
                    # 已有记录：更新最新信息
                    up.name = ui.get('name', up.name)
                    up.avatar = ui.get('avatar', up.avatar)
                    up.follower_count = ui.get('follower_count', 0)
                else:
                    # 新 UP 主：创建记录
                    up = BiliUp(
                        mid=mid,
                        space_url=space_url,
                        name=ui.get('name', ''),
                        avatar=ui.get('avatar', ''),
                        follower_count=ui.get('follower_count', 0),
                    )
                    db.session.add(up)
                db.session.commit()
                try:
                    # 记录粉丝数历史快照
                    db.session.add(BiliUpHistory(up_id=up.id, follower_count=up.follower_count))
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                _up_name[0] = ui.get('name', str(mid))
                emit(
                    f'UP主信息  |  粉丝: {ui.get("follower_count", 0):,}  |  视频总数: {ui.get("video_count", 0)}'
                )
            except Exception as e:
                emit(f'获取 UP 主信息失败: {e}')
                if not up:
                    # 最低限度创建 UP 主记录
                    up = BiliUp(mid=mid, space_url=space_url)
                    db.session.add(up)
                    db.session.commit()
                _up_name[0] = up.name or str(mid)

            emit('初始化数据库...')

            # B. 补全缺失视频 — 判断是否需要从 API 拉取
            total_in_db = BiliVideo.query.filter_by(up_id=up.id).count()
            should_fill = (
                total_in_db == 0
                or total_in_api is None
                or (total_in_api > 0 and total_in_db < total_in_api)
                or (total_in_api == 0 and total_in_db > 0)
                or force
            )
            fill_count = 0
            fill_new_bvids: set[str] = set()
            # 预加载现有 BVID/AID 集合用于判重
            existing_ids = {
                r[0]
                for r in BiliVideo.query.with_entities(BiliVideo.bvid).filter_by(up_id=up.id).all()
            }
            existing_aids = {
                r[0]
                for r in BiliVideo.query.with_entities(BiliVideo.aid).filter_by(up_id=up.id).all()
            }
            if should_fill:
                from blog.bilibili.bili_api import get_video_list as _get_video_list

                # 计算需补数量：-1 表示数量未知，翻全量
                need = (total_in_api - total_in_db) if total_in_api is not None and total_in_api > 0 else -1
                if need > 0:
                    emit(f'[补全] 发现 {need} 个缺失视频，开始补齐...')
                else:
                    emit(f'[补全] DB 有 {total_in_db} 个视频，开始从 API 补齐...')

                _batch_count = 0
                # arc/search API 翻全量遍历
                for video_info in _get_video_list(mid):
                    bvid = video_info['bvid']
                    aid = video_info['aid']
                    title_short = (video_info.get('title') or '')[:30]
                    is_known = bvid in existing_ids or aid in existing_aids
                    logger.info('补全循环: bvid=%s title=%s known=%s', bvid, title_short, is_known)
                    if is_known:
                        continue
                    try:
                        # 获取统计数据并合并
                        stat = get_video_stat(bvid)
                        video_info.update(stat)
                        # 随机延时防 B 站风控
                        time.sleep(_VIDEO_SLEEP_BASE + random.random() * _VIDEO_SLEEP_JITTER)
                    except Exception:
                        logger.warning('视频 %s 「%s」补全时统计获取失败', bvid, title_short)
                        time.sleep(12.0)
                        continue
                    video, ok = _insert_or_update_video(up, video_info, aid, bvid, title_short)
                    if not ok:
                        continue

                    # 批量提交 — 每 20 条一次减少事务压力
                    _batch_count += 1
                    if _batch_count >= 20:
                        db.session.commit()
                        _batch_count = 0

                    fill_count += 1
                    existing_ids.add(bvid)
                    existing_aids.add(aid)
                    fill_new_bvids.add(bvid)
                    emit(f'[补全] ({fill_count}) 「{title_short}」')
                    # 如果已知准确数量且已补完，提前结束
                    if need > 0 and fill_count >= need:
                        break

            # C. 动态发现兜底：始终执行，捕获 arc/search 可能遗漏的 shorts/新视频
            from blog.bilibili.bili_api import get_video_list_from_dynamics

            try:
                dyn_videos = get_video_list_from_dynamics(mid)
            except Exception as e:
                logger.warning('补全动态发现失败 mid=%d: %s', mid, e)
                dyn_videos = []
            _batch_count = 0
            for video_info in dyn_videos:
                bvid = video_info['bvid']
                aid = video_info['aid']
                title_short = (video_info.get('title') or '')[:30]
                if bvid in existing_ids or aid in existing_aids:
                    continue
                video, ok = _insert_or_update_video(up, video_info, aid, bvid, title_short)
                if not ok:
                    continue

                # 动态发现结果也使用批量提交
                _batch_count += 1
                if _batch_count >= 20:
                    db.session.commit()
                    _batch_count = 0

                fill_count += 1
                existing_ids.add(bvid)
                existing_aids.add(aid)
                fill_new_bvids.add(bvid)
                emit(f'[补全/动态] ({fill_count}) 「{title_short}」')
            if dyn_videos:
                emit(f'补全动态扫描完成，共 {len(dyn_videos)} 个')
            db.session.commit()

            if fill_count:
                emit(f'[补全] 完成，新增 {fill_count} 个视频')

            # ── D. 三层统计更新 ──────────────────────
            # fill_new_bvids: 本次新入库的视频 BVID — Hot 阶段排除这些（已有最新数据）
            filled_bvids = fill_new_bvids
            count = 0
            hot_done = 0
            warm_done = 0
            cold_done = 0
            retry_delay = 30  # 风控退避初始延迟（秒）
            # 使用东八区时间计算三层截止日期
            now = datetime.datetime.now(CST)
            cutoff_hot = now - datetime.timedelta(days=7)   # 7 天内 → Hot
            cutoff_warm = now - datetime.timedelta(days=30)  # 8~30 天 → Warm

            def _update_video(v, label='', min_age_hours=1):
                """更新单个视频的统计数据并写 BiliVideoHistory。

                步骤：
                  1. min_age_hours 跳过：如果视频在指定小时数内已更新过，跳过（force 模式除外）
                  2. 调用 API 获取最新统计
                  3. 若触发风控：指数退避（30s→600s），返回 False 让外层 continue
                  4. 若成功：更新 ORM 字段 + 写入历史快照 + 记录日志

                Args:
                    v (BiliVideo): 视频 ORM 对象
                    label (str):   日志标签（'Hot'/'Warm'/'Cold'）
                    min_age_hours (int):
                        最小间隔小时数。更新距上次更新不足此值的视频会被跳过。
                        Hot=0（不跳过），Warm=1，Cold=24

                Returns:
                    True  — 成功或 min-age 跳过
                    False — 风控/失败，需要外层 continue 跳到下一个视频
                """
                nonlocal count, retry_delay, hot_done, warm_done, cold_done
                bvid = v.bvid

                # 跳过近期已更新视频（force 模式下忽略此检查）
                if (
                    not force
                    and v.updated_at
                    and (datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))) - v.updated_at).total_seconds()
                    < min_age_hours * 3600
                ):
                    title_short = (v.title or '')[:30]
                    emit(f'  跳过「{title_short}」— 最近 {min_age_hours} 小时内已更新')
                    return True

                # 记录旧值用于计算增量
                old_view = v.view_count or 0
                old_like = v.like_count or 0
                old_coin = v.coin_count or 0
                old_fav = v.favorite_count or 0
                old_share = v.share_count or 0
                old_comment = v.comment_count or 0
                old_danmaku = v.danmaku_count or 0

                try:
                    stat = get_video_stat(bvid)
                    retry_delay = 30  # 成功后重置退避延迟
                    time.sleep(_VIDEO_SLEEP_BASE + random.random() * _VIDEO_SLEEP_JITTER)
                except Exception as e:
                    if _is_risk_control(e):
                        logger.warning('触发风控，等待 %ds 后跳过...', retry_delay)
                        time.sleep(retry_delay)
                        retry_delay = min(retry_delay * 2, 600)
                        return False
                    logger.warning('视频 %s 统计获取失败: %s', bvid, e)
                    time.sleep(8.0)
                    return False

                # 更新视频统计字段
                for key, val in stat.items():
                    setattr(v, key, val)
                v.updated_at = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
                count += 1
                if label.startswith('Hot'):
                    hot_done += 1
                elif label.startswith('Warm'):
                    warm_done += 1
                elif label.startswith('Cold'):
                    cold_done += 1

                try:
                    # 写入统计历史快照
                    db.session.add(
                        BiliVideoHistory(
                            video_id=v.id,
                            view_count=stat.get('view_count', 0),
                            like_count=stat.get('like_count', 0),
                            coin_count=stat.get('coin_count', 0),
                            favorite_count=stat.get('favorite_count', 0),
                            share_count=stat.get('share_count', 0),
                            comment_count=stat.get('comment_count', 0),
                            danmaku_count=stat.get('danmaku_count', 0),
                        )
                    )
                    db.session.commit()
                except Exception:
                    db.session.rollback()

                # 日志输出：标题 + 各指标数值及增量
                title_short = (v.title or '')[:30]
                nv = stat.get('view_count', 0)
                nl = stat.get('like_count', 0)
                nc = stat.get('coin_count', 0)
                nf = stat.get('favorite_count', 0)
                ns = stat.get('share_count', 0)
                ncm = stat.get('comment_count', 0)
                nd = stat.get('danmaku_count', 0)
                emit(f'[{count}] {label}「{title_short}」')
                emit(
                    f'  播放:{nv:,}(+{nv - old_view:,})  点赞:{nl:,}(+{nl - old_like:,})  投币:{nc:,}(+{nc - old_coin:,})  收藏:{nf:,}(+{nf - old_fav:,})'
                )
                emit(
                    f'  转发:{ns:,}(+{ns - old_share:,})  评论:{ncm:,}(+{ncm - old_comment:,})  弹幕:{nd:,}(+{nd - old_danmaku:,})'
                )
                return True

            # Hot 阶段: 发布时间 ≤7 天 — 全部更新，不跳过
            # 排除本次新入库的视频（filled_bvids），它们已经有最新数据
            hot_query = BiliVideo.query.filter(
                BiliVideo.up_id == up.id,
                BiliVideo.pub_datetime >= cutoff_hot,
            )
            if filled_bvids:
                hot_query = hot_query.filter(~BiliVideo.bvid.in_(filled_bvids))
            hot_videos = hot_query.order_by(BiliVideo.pubdate.desc()).all()
            emit(f'Hot 阶段: ≤7天视频共 {len(hot_videos)} 个')
            for v in hot_videos:
                if max_videos is not None and count >= max_videos:
                    break
                ok = _update_video(v, 'Hot', min_age_hours=0)
                if ok is False:
                    continue

            # Warm 阶段: 发布时间 8~30 天（配额未满时执行，最久未更新优先，1h 跳过）
            if max_videos is None or count < max_videos:
                remaining = None if max_videos is None else max_videos - count
                warm_query = BiliVideo.query.filter(
                    BiliVideo.up_id == up.id,
                    BiliVideo.pub_datetime >= cutoff_warm,
                    BiliVideo.pub_datetime < cutoff_hot,
                ).order_by(BiliVideo.updated_at.asc())

                if remaining is not None:
                    warm_query = warm_query.limit(remaining)
                warm_videos = warm_query.all()
                quota_str = '无限制' if remaining is None else str(remaining)
                emit(f'Warm 阶段: 8~30天视频配额 {quota_str}（DB中共 {len(warm_videos)} 个待更新）')
                for v in warm_videos:
                    if remaining is not None and count >= max_videos:
                        break
                    ok = _update_video(v, 'Warm', min_age_hours=1)
                    if ok is False:
                        continue

            # Cold 阶段: 发布时间 >30 天（配额剩余时处理，24h 跳过）
            if max_videos is None or count < max_videos:
                remaining = None if max_videos is None else max_videos - count
                cold_query = BiliVideo.query.filter(
                    BiliVideo.up_id == up.id,
                    BiliVideo.pub_datetime < cutoff_warm,
                ).order_by(BiliVideo.updated_at.asc())
                if remaining is not None:
                    cold_query = cold_query.limit(remaining)
                cold_videos = cold_query.all()
                if cold_videos:
                    quota_str = '无限制' if remaining is None else str(remaining)
                    emit(
                        f'Cold 阶段: >30天视频配额 {quota_str}（DB中共 {len(cold_videos)} 个待更新）'
                    )
                    for v in cold_videos:
                        if remaining is not None and count >= max_videos:
                            break
                        ok = _update_video(v, 'Cold', min_age_hours=24)
                        if ok is False:
                            continue
            # 更新 UP 主的视频总数字段
            up.video_count = BiliVideo.query.filter_by(up_id=up.id).count()
            db.session.commit()
            emit(
                f'刷新完成  Hot={hot_done}  Warm={warm_done}  Cold={cold_done}  共 {count} 个  |  DB 总视频数: {up.video_count}'
            )
            # 完整性检查：对比 API 声明数量与实际入库数量
            if total_in_api:
                db_total = up.video_count
                if db_total >= total_in_api:
                    emit(f'完整性检查: {db_total}/{total_in_api} ✅ 全部视频已入库')
                else:
                    emit(
                        f'完整性检查: {db_total}/{total_in_api} ⚠️ 缺失 {total_in_api - db_total} 个视频'
                    )
            elif total_in_api is not None and total_in_api == 0 and total_in_db > 0:
                emit(f'完整性检查: Cookie 可能过期，API 返回 video_count=0')

            # 检查 B站 API 层是否已检测到 412（可能在 get_video_list 内部处理，未抛异常到此处）
            from blog.bilibili.bili_api import was_recently_blocked
            if was_recently_blocked(cooldown=300) and time.time() >= _circuit_open_until:
                _circuit_open_until = time.time() + _CIRCUIT_COOLDOWN
                logger.error('API 层检测到 412 封禁，全局熔断 %d 分钟', _CIRCUIT_COOLDOWN // 60)

            # 评论爬取：为本 UP 主尚未爬取评论的视频补充数据（限 5 个/次）
            if not was_recently_blocked(cooldown=600):
                from .models import BiliVideoComment
                from sqlalchemy import func

                videos_missing_comments = (
                    BiliVideo.query
                    .outerjoin(BiliVideoComment, BiliVideo.id == BiliVideoComment.video_id)
                    .filter(BiliVideo.up_id == up.id)
                    .group_by(BiliVideo.id)
                    .having(func.count(BiliVideoComment.id) == 0)
                    .order_by(BiliVideo.pubdate.desc())
                    .limit(5)
                    .all()
                )
                for v in videos_missing_comments:
                    if was_recently_blocked():
                        break
                    try:
                        n = _crawl_video_comments(v)
                        if n:
                            emit(f'评论 [{v.bvid[:8]}…] 爬取 {n} 条')
                        time.sleep(3.0 + random.random() * 2.0)
                    except Exception as e:
                        logger.warning('视频 %s 评论爬取失败: %s', v.bvid, e)

        except Exception as e:
            emit(f'爬取失败: {e}')
            logger.exception('爬取失败 mid=%d', mid)
            from blog.bilibili.bili_api import _is_ip_blocked
            if _is_ip_blocked(e):
                _circuit_open_until = time.time() + _CIRCUIT_COOLDOWN
                logger.error('检测到 412 封禁，全局熔断 %d 分钟', _CIRCUIT_COOLDOWN // 60)
        finally:
            # 无论成功还是异常，都必须清理运行状态
            with _scrape_lock:
                _scrape_running.discard(mid)
                _scrape_progress.pop(mid, None)
            db.session.remove()


_BATCH_SIZE = 10  # 每日刷新时每批并行处理的 UP 主数量


def run_daily_scrape(app):
    """每日深扫调度入口 — 供 APScheduler 或其他定时任务框架调用

    分批并发处理所有 UP 主，每批 _BATCH_SIZE（10）个并行，每批内线程
    间间隔 0.5~2 秒。每个线程有 15 分钟超时保护。

    启动前检查：
      - 全局熔断器（_circuit_open_until）：如果处于熔断状态则跳过本次
      - 单个 UP 主是否已在运行中（_scrape_running / _incremental_running）

    Args:
        app (Flask): Flask 应用实例

    注意：
      此函数是同步阻塞的（join 等待所有线程完成），适合调度器直接调用。
    """
    with app.app_context():
        import logging
        import random
        import threading
        import time

        logger = logging.getLogger(__name__)
        from blog.models import BiliUp

        ups = BiliUp.query.all()
        logger.info('B站 每日刷新启动: 共 %d 个 UP 主, 每批 %d 个', len(ups), _BATCH_SIZE)

        # 全局熔断检查
        if time.time() < _circuit_open_until:
            remaining = int(_circuit_open_until - time.time()) // 60
            logger.warning('B站 每日刷新取消: 全局熔断中，剩余 %d 分钟', remaining)
            return

        THREAD_TIMEOUT = 15 * 60  # 每个线程最长等待时间（15 分钟）

        # 筛选出当前不在运行中的 UP 主
        active: list = []
        for up in ups:
            mid = up.mid
            with _scrape_lock:
                if mid in _scrape_running or mid in _incremental_running:
                    continue
                _scrape_progress[mid] = []
                _scrape_running.add(mid)
            active.append(up)

        # 分批并发执行：每批 _BATCH_SIZE 个线程同时运行
        for i in range(0, len(active), _BATCH_SIZE):
            batch = active[i : i + _BATCH_SIZE]
            threads = []
            for up in batch:
                t = threading.Thread(
                    target=_run_scrape,
                    args=(up.mid, up.space_url, app),
                    kwargs={'max_videos': 30},
                    daemon=True,
                )
                t.start()
                threads.append(t)
                time.sleep(random.uniform(0.5, 2.0))  # 错开启动时间
            # 等待该批所有线程完成（或超时）
            for t in threads:
                t.join(timeout=THREAD_TIMEOUT)
                if t.is_alive():
                    logger.warning(
                        'B站 每日刷新: 线程 %s 超时 (>%ds)，跳过', t.name, THREAD_TIMEOUT
                    )

        logger.info('B站 每日刷新完成')
        db.session.remove()


def cleanup_old_history(days=90):
    """删除指定天数前的 B 站视频历史快照记录

    用于定期清理过期数据以控制数据库体积。

    Args:
        days (int): 保留天数，默认 90 天前的历史将被删除

    Returns:
        int: 被删除的记录数
    """
    from blog.models import BiliVideoHistory, db as _db
    import datetime

    cutoff = datetime.datetime.now(CST) - datetime.timedelta(days=days)
    deleted = BiliVideoHistory.query.filter(BiliVideoHistory.recorded_at < cutoff).delete()
    _db.session.commit()
    if deleted:
        logger.info('清理了 %d 条 %d 天前的 B站视频历史快照', deleted, days)
    return deleted


def auto_cleanup_history(app=None):
    """定时任务入口：读取 BiliCleanupConfig 并执行历史数据清理

    从数据库读取 BiliCleanupConfig 配置（是否启用+保留天数），
    如果启用则调用 cleanup_old_history 执行清理。
    供 APScheduler 定时调用。

    Args:
        app (Flask, optional): Flask 应用实例，用于创建应用上下文

    Returns:
        int: 被删除的记录数；0 表示未执行或未启用
    """
    if app is None:
        logger.warning('auto_cleanup_history: 未传入 app 实例')
        return 0
    with app.app_context():
        from blog.models import BiliCleanupConfig, db as _db

        cfg = BiliCleanupConfig.query.first()
        if cfg and cfg.enabled:
            deleted = cleanup_old_history(days=cfg.days)
            if deleted:
                logger.info('自动清理完成: 删除了 %d 条 %d 天前的记录', deleted, cfg.days)
            return deleted
    return 0
