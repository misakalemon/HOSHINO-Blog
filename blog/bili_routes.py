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



import logging
import os


import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import queue as _queue_mod

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
from .utils import now_cst, CST, get_client_ip, escape_like
from .bilibili.bili_api import thread_sleep, ensure_semaphore

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
    """清除 B 站登录凭证文件与内存状态

    删除本地 CREDENTIAL_FILE + COOKIE_FILE，并清除内存中的全局 Credential
    与登录标志，确保下次 apply_cookies 返回 False。

    Returns:
        HTTP 重定向到 bili.index
    """
    from blog.bilibili.config import COOKIE_FILE, CREDENTIAL_FILE
    from blog.bilibili import login as _bili_login
    from blog.bilibili.bili_api import set_credential

    try:
        for f in (CREDENTIAL_FILE, COOKIE_FILE):
            if os.path.exists(f):
                os.remove(f)
        # 清除内存中的登录态（否则当前进程仍保持登录）
        set_credential(None)
        _bili_login._BILI_LOGGED_IN = False
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
    watched_ids = {w.video_id for w in BiliWatchedVideo.query.join(BiliVideo).filter(BiliVideo.up_id == up_id).all()}
    return render_template(
        'admin/bili_videos.html', up=up, pagination=pagination, watched_ids=watched_ids
    )


@bili_bp.route('/refresh/<int:up_id>', methods=['POST'])
@editor_required
def refresh_up(up_id):
    """重新爬取单个 UP 主的数据（最多 30 个新视频）

    通过 Redis 任务队列投递到 worker.py 执行，不阻塞 HTTP 请求。

    Args:
        up_id (int): UP 主数据库 ID

    Returns:
        HTTP 重定向到 up_detail 页
    """
    up = BiliUp.query.get_or_404(up_id)
    from blog.task_queue import submit_task, try_acquire, mark_done, is_queue_available
    # 原子占位：并发请求只有一个能抢到运行锁，杜绝重复提交
    if not try_acquire(up.mid):
        flash('该 UP 主正在爬取中（Worker 进程）', 'error')
        return redirect(url_for('bili.up_detail', up_id=up_id))
    with _scrape_lock:
        if up.mid in _scrape_running or up.mid in _incremental_running:
            mark_done(up.mid)
            flash('该 UP 主正在爬取中', 'error')
            return redirect(url_for('bili.up_detail', up_id=up_id))
    if not is_queue_available():
        mark_done(up.mid)
        flash('任务队列不可用（Redis 未连接），无法执行刷新', 'error')
        return redirect(url_for('bili.up_detail', up_id=up_id))
    task_id = submit_task('refresh_up', mid=up.mid, space_url=up.space_url,
                          max_videos=int(os.environ.get('BILI_REFRESH_MAX_VIDEOS', '30')))
    if task_id:
        flash(f'已开始刷新「{up.name or up.mid}」的数据', 'success')
    else:
        mark_done(up.mid)  # 提交失败释放占位，允许稍后重试
        flash('任务提交失败，请稍后重试', 'error')
    return redirect(url_for('bili.up_detail', up_id=up_id))


@bili_bp.route('/refresh-all/<int:up_id>', methods=['POST'])
@editor_required
def refresh_up_all(up_id):
    """重新爬取单个 UP 主的所有视频数据（无配额限制，force=True）

    通过 Redis 任务队列投递到 worker.py 执行。

    Args:
        up_id (int): UP 主数据库 ID

    Returns:
        HTTP 重定向到 up_detail 页
    """
    up = BiliUp.query.get_or_404(up_id)
    from blog.task_queue import submit_task, try_acquire, mark_done, is_queue_available
    if not try_acquire(up.mid):
        flash('该 UP 主正在爬取中（Worker 进程）', 'error')
        return redirect(url_for('bili.up_detail', up_id=up_id))
    with _scrape_lock:
        if up.mid in _scrape_running or up.mid in _incremental_running:
            mark_done(up.mid)
            flash('该 UP 主正在爬取中', 'error')
            return redirect(url_for('bili.up_detail', up_id=up_id))
    if not is_queue_available():
        mark_done(up.mid)
        flash('任务队列不可用（Redis 未连接），无法执行刷新', 'error')
        return redirect(url_for('bili.up_detail', up_id=up_id))
    task_id = submit_task('refresh_all', mid=up.mid, space_url=up.space_url)
    if task_id:
        flash(f'已开始强制刷新「{up.name or up.mid}」的所有视频', 'success')
    else:
        mark_done(up.mid)
        flash('任务提交失败，请稍后重试', 'error')
    return redirect(url_for('bili.up_detail', up_id=up_id))


@bili_bp.route('/up/<int:up_id>/refresh-comments', methods=['POST'])
@editor_required
def refresh_up_comments(up_id):
    """刷新指定 UP 主的评论并重新生成词云。

    通过 Redis 任务队列投递到 worker.py 执行。

    Args:
        up_id (int): UP 主数据库 ID

    Returns:
        HTTP 重定向到 up_detail 页
    """
    up = BiliUp.query.get_or_404(up_id)
    from blog.task_queue import submit_task, try_acquire, mark_done, is_queue_available
    if not try_acquire(up.mid):
        flash('该 UP 主正在爬取中（Worker 进程）', 'error')
        return redirect(url_for('bili.up_detail', up_id=up_id))
    with _scrape_lock:
        if up.mid in _scrape_running or up.mid in _incremental_running:
            mark_done(up.mid)
            flash('该 UP 主正在爬取中，请等待完成', 'error')
            return redirect(url_for('bili.up_detail', up_id=up_id))
    if not is_queue_available():
        mark_done(up.mid)
        flash('任务队列不可用（Redis 未连接），无法执行刷新', 'error')
        return redirect(url_for('bili.up_detail', up_id=up_id))
    task_id = submit_task('refresh_up_comments', up_id=up_id, mid=up.mid)
    if task_id:
        flash(f'已开始刷新「{up.name or up.mid}」的评论与词云', 'success')
    else:
        mark_done(up.mid)
        flash('任务提交失败，请稍后重试', 'error')
    return redirect(url_for('bili.up_detail', up_id=up_id))


@bili_bp.route('/up/<int:up_id>/refresh-danmakus', methods=['POST'])
@editor_required
def refresh_up_danmakus(up_id):
    """刷新指定 UP 主的弹幕并重新生成词云。

    通过 Redis 任务队列投递到 worker.py 执行。

    Args:
        up_id (int): UP 主数据库 ID

    Returns:
        HTTP 重定向到 up_detail 页
    """
    up = BiliUp.query.get_or_404(up_id)
    from blog.task_queue import submit_task, try_acquire, mark_done, is_queue_available
    if not try_acquire(up.mid):
        flash('该 UP 主正在爬取中（Worker 进程）', 'error')
        return redirect(url_for('bili.up_detail', up_id=up_id))
    with _scrape_lock:
        if up.mid in _scrape_running or up.mid in _incremental_running:
            mark_done(up.mid)
            flash('该 UP 主正在爬取中，请等待完成', 'error')
            return redirect(url_for('bili.up_detail', up_id=up_id))
    if not is_queue_available():
        mark_done(up.mid)
        flash('任务队列不可用（Redis 未连接），无法执行刷新', 'error')
        return redirect(url_for('bili.up_detail', up_id=up_id))
    task_id = submit_task('refresh_up_danmakus', up_id=up_id, mid=up.mid)
    if task_id:
        flash(f'已开始刷新「{up.name or up.mid}」的弹幕与词云', 'success')
    else:
        mark_done(up.mid)
        flash('任务提交失败，请稍后重试', 'error')
    return redirect(url_for('bili.up_detail', up_id=up_id))


@bili_bp.route('/refresh-subtitles/<int:up_id>', methods=['POST'])
@editor_required
def refresh_up_subtitles(up_id):
    """刷新指定 UP 主视频的 AI 字幕。

    通过 Redis 任务队列投递到 worker.py 执行。
    """
    up = BiliUp.query.get_or_404(up_id)
    from blog.task_queue import submit_task, try_acquire, mark_done, is_queue_available
    if not try_acquire(up.mid):
        flash('该 UP 主正在爬取中（Worker 进程）', 'error')
        return redirect(url_for('bili.up_detail', up_id=up_id))
    with _scrape_lock:
        if up.mid in _scrape_running or up.mid in _incremental_running:
            mark_done(up.mid)
            flash('该 UP 主正在爬取中，请等待完成', 'error')
            return redirect(url_for('bili.up_detail', up_id=up_id))
    if not is_queue_available():
        mark_done(up.mid)
        flash('任务队列不可用（Redis 未连接），无法执行刷新', 'error')
        return redirect(url_for('bili.up_detail', up_id=up_id))
    task_id = submit_task('refresh_up_subtitles', up_id=up_id, mid=up.mid)
    if task_id:
        flash(f'已开始刷新「{up.name or up.mid}」的 AI 字幕', 'success')
    else:
        mark_done(up.mid)
        flash('任务提交失败，请稍后重试', 'error')
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
    from blog.task_queue import is_running
    if is_running(up.mid) or up.mid in _scrape_running or up.mid in _incremental_running:
        flash('该 UP 主正在爬取中，请等待完成后再删除', 'error')
        return redirect(url_for('bili.index'))
    # 手动按依赖顺序删除，避免 ORM 级联置 NULL 触发 video_id NOT NULL 冲突：
    # 先删历史快照 → 再删视频 → 最后删 UP 主
    video_ids = [v.id for v in up.videos]
    if video_ids:
        BiliVideoHistory.query.filter(BiliVideoHistory.video_id.in_(video_ids)).delete(synchronize_session=False)
    BiliVideo.query.filter(BiliVideo.up_id == up.id).delete(synchronize_session=False)
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
    # 先删历史快照，再删视频（避免 ORM 级联置 NULL 触发 NOT NULL 冲突）
    BiliVideoHistory.query.filter(BiliVideoHistory.video_id == video.id).delete(synchronize_session=False)
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

    性能说明：受全局令牌桶限速（默认 0.33 req/s），全量检查约需数分钟，
    结果缓存 5 分钟（?refresh=1 强制重算），避免重复点击重复等待。

    Returns:
        JSON: {
            ok: True,
            results: [{name, mid, up_id, db, api, missing, percent, error}],
            total: int
        }
    """
    from flask import request as _req

    force_refresh = _req.args.get('refresh') == '1'
    from blog.cache import cache_get, cache_set

    if not force_refresh:
        cached = cache_get('admin:check_missing')
        if cached is not None:
            return cached

    from blog.bilibili.login import apply_cookies
    from blog.bilibili.bili_api import get_user_info

    apply_cookies()

    results = []
    ups = BiliUp.query.order_by(BiliUp.updated_at.desc()).all()

    # 批量统计所有 UP 主的视频数（排除已删除墓碑，与实际可见数一致）
    from sqlalchemy import func
    video_counts = dict(
        db.session.query(BiliVideo.up_id, func.count(BiliVideo.id))
        .filter(BiliVideo.is_deleted == False)
        .group_by(BiliVideo.up_id)
        .all()
    )
    
    for up in ups:
        db_count = video_counts.get(up.id, 0)
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

    payload = {'ok': True, 'results': results, 'total': len(results)}
    # 缓存 5 分钟（令牌桶限速下全量检查需数分钟，缓存避免重复等待）
    try:
        cache_set('admin:check_missing', payload, 300)
    except Exception:
        pass
    return payload


# ── 爬取任务共享状态 ────────────────────────────
# 深扫运行中的 mid 集合（每日刷新 / 手动触发），启动前需先检查
_scrape_running: set[int] = set()
# 增量检查运行中的 mid 集合（与深扫互斥：启动前同时检查两者）
_incremental_running: set[int] = set()
# 实时爬取日志 {mid: [str, ...]} 供 AJAX scrape-status 轮询
_scrape_progress: dict[int, list[str]] = {}
# 上述三个共享状态的互斥锁 — 读写均需持有
_scrape_lock = threading.Lock()

_UPDATE_THREADS = min(int(os.environ.get('BILI_UPDATE_THREADS', '2')), 4)
# 全局熔断器 — 检测到 412 IP封禁后自动暂停所有爬取直到此时间戳（Unix 秒）
_circuit_open_until: float = 0.0
_circuit_lock = threading.Lock()
# 全局熔断时长（秒）：检测到 412 封禁后暂停所有爬取 1 小时
_CIRCUIT_COOLDOWN = int(os.environ.get('BILI_COOLDOWN', '3600'))
# 412 违规计数（近 1h 内次数），用于阶梯退避
_circuit_attempts: list[float] = []
_circuit_attempts_lock = threading.Lock()
_CIRCUIT_MAX_COOLDOWN = int(os.environ.get('BILI_MAX_COOLDOWN', '3600'))  # 最大冷却 60 分钟


def _circuit_compute_cooldown() -> float:
    """阶梯退避：记录一次 412 并返回本次冷却秒数。
    第1次 5min，第2次 10min，第3次 20min，第4次+ 60min（封顶）。
    近 1 小时无新 412 自动重置计数器。
    """
    now = time.time()
    with _circuit_attempts_lock:
        _circuit_attempts[:] = [t for t in _circuit_attempts if now - t < 3600]
        count = len(_circuit_attempts) + 1
        _circuit_attempts.append(now)
    # 封顶用 _CIRCUIT_COOLDOWN（环境变量 BILI_COOLDOWN 可配），
    # 同时受 _CIRCUIT_MAX_COOLDOWN（1h）硬上限约束
    return min(_CIRCUIT_MAX_COOLDOWN, _CIRCUIT_COOLDOWN, (2 ** (count - 1)) * 300)


# ── 稿件墓碑机制 ──────────────────────────────
# API 连续返回"稿件不可见"(62002/62012) 达到阈值后，将视频标记 is_deleted：
# 前台隐藏、增量/深扫跳过、避免每次周期重复请求已删除稿件。
_INVISIBLE_FAIL_COUNTS: dict[str, int] = {}
_invisible_fail_lock = threading.Lock()
# 不可见失败计数上限：连续 _INVISIBLE_FAIL_THRESHOLD 次（跨增量周期）判定为删除
_INVISIBLE_FAIL_THRESHOLD = int(os.environ.get('BILI_DELETE_THRESHOLD', '3'))
# 计数表最大容量，防止恶意 bvid 刷爆内存
_INVISIBLE_FAIL_MAX = 5000


def _record_invisible_videos(deleted_bvids):
    """累计"稿件不可见"失败计数，达到阈值标记 is_deleted 并清计数。

    当视频后续成功获取统计时（_insert_or_update_video / _update_video），
    会自动重置 is_deleted 并清除计数（稿件可能恢复可见）。
    """
    if not deleted_bvids:
        return
    with _invisible_fail_lock:
        # 容量保护：超限时清空（墓碑判定会重新累积，可接受）
        if len(_INVISIBLE_FAIL_COUNTS) > _INVISIBLE_FAIL_MAX:
            _INVISIBLE_FAIL_COUNTS.clear()
        to_mark = set()
        for bvid in deleted_bvids:
            n = _INVISIBLE_FAIL_COUNTS.get(bvid, 0) + 1
            if n >= _INVISIBLE_FAIL_THRESHOLD:
                to_mark.add(bvid)
                _INVISIBLE_FAIL_COUNTS.pop(bvid, None)
            else:
                _INVISIBLE_FAIL_COUNTS[bvid] = n
    if not to_mark:
        return
    try:
        videos = BiliVideo.query.filter(BiliVideo.bvid.in_(to_mark)).all()
        for v in videos:
            if not v.is_deleted:
                v.is_deleted = True
                v.deleted_at = now_cst()
                logger.warning(
                    '视频标记为已删除（稿件不可见×%d）: %s 「%s」',
                    _INVISIBLE_FAIL_THRESHOLD, v.bvid, (v.title or '')[:30],
                )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.warning('墓碑标记失败: %s', e)


def _clear_invisible_count(bvid):
    """视频成功获取统计后清除其不可见计数。"""
    with _invisible_fail_lock:
        _INVISIBLE_FAIL_COUNTS.pop(bvid, None)


def _insert_or_update_video(up, video_info, aid, bvid, title_short):
    """插入新视频或更新已有视频的统计数据。

    事务策略（08-06 连接池事故教训）：
      - 新视频先 add + commit 落主记录，立即归还 DB 连接；
      - 标签/字幕等网络抓取在**独立小事务**中执行，不再于一个长事务内
        持有连接（原先 flush 后同步抓 tags/字幕，最长 60s 占用连接）；
      - 统计历史快照单独提交。

    先尝试插入新记录；若 aid 唯一性冲突（IntegrityError），
    则查询已有记录并仅更新统计数字段（view/like/coin 等），
    不覆盖标题、发布时间等元信息。
    每次成功插入或更新后，同时写入一条 BiliVideoHistory 快照。
    成功获取到统计数据的视频会重置 is_deleted 墓碑（稿件可能恢复可见）。

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
    # 预检当前 aid 是否已存在（防止跨线程同时插入同一视频）
    existing = BiliVideo.query.filter_by(aid=aid).first()
    if existing:
        for key in (
            'view_count', 'like_count', 'coin_count',
            'favorite_count', 'share_count', 'comment_count',
            'danmaku_count',
        ):
            if key in video_info:
                setattr(existing, key, video_info[key])
        existing.updated_at = now_cst()
        if existing.is_deleted:
            # API 又能取到该稿件 → 恢复可见，清除墓碑
            existing.is_deleted = False
            existing.deleted_at = None
            _clear_invisible_count(bvid)
            logger.info('视频恢复可见，清除墓碑: %s', bvid)
        db.session.commit()
        # 写入统计历史快照
        try:
            _prev_h = BiliVideoHistory.query.filter(
                BiliVideoHistory.video_id == existing.id,
                BiliVideoHistory.recorded_at >= now_cst() - datetime.timedelta(seconds=30)
            ).first()
            if _prev_h:
                for k in ('view_count', 'like_count', 'coin_count', 'favorite_count',
                          'share_count', 'comment_count', 'danmaku_count'):
                    setattr(_prev_h, k, video_info.get(k, 0))
            else:
                db.session.add(BiliVideoHistory(
                    video_id=existing.id,
                    view_count=video_info.get('view_count', 0),
                    like_count=video_info.get('like_count', 0),
                    coin_count=video_info.get('coin_count', 0),
                    favorite_count=video_info.get('favorite_count', 0),
                    share_count=video_info.get('share_count', 0),
                    comment_count=video_info.get('comment_count', 0),
                    danmaku_count=video_info.get('danmaku_count', 0),
                ))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.warning('视频 %s 历史快照写入失败（已有记录更新）: %s', bvid, e)
        return existing, False

    is_new = True
    try:
        # 插入新视频记录并立即提交（先落主记录、归还连接）
        video = BiliVideo(up_id=up.id, **video_info)
        db.session.add(video)
        db.session.commit()
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
            existing.updated_at = now_cst()
            if existing.is_deleted:
                existing.is_deleted = False
                existing.deleted_at = None
                _clear_invisible_count(bvid)
            video = existing
            is_new = False
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
        else:
            return None, False
    except Exception as e:
        # 非预期的数据库异常
        db.session.rollback()
        logger.warning('视频 %s 「%s」入库失败: %s', bvid, title_short, e)
        return None, False

    # 主记录已提交：标签/字幕在独立小事务中抓取（不再持有长事务）
    try:
        from blog.bilibili.bili_api import get_video_tags
        tags = get_video_tags(bvid)
        if tags:
            video.tags = tags
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.warning('视频 %s 标签获取失败: %s', bvid, e)

    try:
        from blog.bilibili.bili_api import get_video_subtitle
        subtitle = get_video_subtitle(bvid)
        if subtitle:
            video.subtitle_text = subtitle
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.warning('视频 %s 字幕获取失败: %s', bvid, e)

    # 写入统计历史快照（独立提交）
    try:
        # 预检避免重复数据点；now_cst()（aware）参与 SQL 比较，
        # PyMySQL 会统一转 UTC 存储，与 DB 时基一致
        _prev_h = BiliVideoHistory.query.filter(
            BiliVideoHistory.video_id == video.id,
            BiliVideoHistory.recorded_at >= now_cst() - datetime.timedelta(seconds=30)
        ).first()
        if _prev_h:
            _prev_h.view_count = video_info.get('view_count', 0)
            _prev_h.like_count = video_info.get('like_count', 0)
            _prev_h.coin_count = video_info.get('coin_count', 0)
            _prev_h.favorite_count = video_info.get('favorite_count', 0)
            _prev_h.share_count = video_info.get('share_count', 0)
            _prev_h.comment_count = video_info.get('comment_count', 0)
        else:
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
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.warning('视频 %s 历史快照写入失败（视频已入库）: %s', bvid, e)
    if is_new:
        try:
            from blog.task_queue import submit_task
            submit_task('bili_wordcloud_single', video_id=video.id, bvid=bvid)
            # 新视频入库后异步投递弹幕爬取（受全局令牌桶串行限速保护）
            submit_task('danmaku_refresh', bvid=bvid)
        except Exception as e:
            logger.warning('词云/弹幕任务投递失败: %s', e)
    return video, is_new


_COMMENT_HOT_PAGES = int(os.environ.get('BILI_COMMENT_HOT_PAGES', '5'))
_COMMENT_NEWEST_PAGES = int(os.environ.get('BILI_COMMENT_NEWEST_PAGES', '5'))
_COMMENT_SLEEP_BASE = float(os.environ.get('BILI_COMMENT_SLEEP', '4.0'))
_COMMENT_SLEEP_JITTER = float(os.environ.get('BILI_COMMENT_JITTER', '3.0'))


def _crawl_video_comments(video, hot_pages: int = _COMMENT_HOT_PAGES, newest_pages: int = _COMMENT_NEWEST_PAGES):
    """爬取单个视频的评论（热门 + 最新两种排序）。

    先爬 5 页热门评论（按点赞排序），再爬 5 页最新评论（按时间排序），
    去重后写入 BiliVideoComment 表。每页间隔随机延时防风控。

    每页处理完毕后主动 db.session.remove() 归还 DB 连接至连接池，
    使得中间的风控等待 / B 站 API 调用不占用连接。

    Args:
        video (BiliVideo):  视频 ORM 对象（需有 id 和 aid）
        hot_pages (int):    热门评论页数（默认 5 页）
        newest_pages (int): 最新评论页数（默认 5 页）
    Returns:
        int: 爬取的评论总数
    """
    from bilibili_api.comment import OrderType
    from blog.bilibili.bili_api import get_video_comments, _is_risk_control, was_recently_blocked
    from .models import BiliVideoComment

    # 在闭包外保存原始值，避免 db.session.remove() 后 ORM 对象 detached
    _aid = video.aid
    _bvid = video.bvid
    _video_id = video.id

    # 一次性加载该视频已有评论的 (ctime, content) 集合到内存，
    # 在内存中判重，避免逐条 filter_by 查库（每视频上千条时性能关键）
    _existing_comments = set(
        (r[0], r[1])
        for r in BiliVideoComment.query.with_entities(
            BiliVideoComment.ctime, BiliVideoComment.content
        ).filter_by(video_id=_video_id).all()
    )

    def _crawl_page(page, order):
        if was_recently_blocked():
            return 0
        try:
            comments = get_video_comments(_aid, page, order=order)
        except Exception as e:
            if _is_risk_control(e):
                logger.warning('视频 %s 评论触发风控，第 %d 页跳过', _bvid, page)
                time.sleep(float(os.environ.get('BILI_COMMENT_RISK_SLEEP', '15.0')))
                return 0
            logger.warning('视频 %s 第 %d 页评论失败: %s', _bvid, page, e)
            return -1

        if not comments:
            return 0

        count = 0
        for c in comments:
            ctime = c.get('ctime', 0)
            content = (c.get('content') or '')[:2000]
            if not content:
                continue
            if (ctime, content) in _existing_comments:
                continue
            db.session.add(BiliVideoComment(
                video_id=_video_id,
                content=content,
                author=(c.get('author') or '')[:64],
                ctime=ctime,
                like_count=c.get('like_count', 0),
            ))
            _existing_comments.add((ctime, content))
            count += 1

        db.session.commit()
        db.session.remove()

        if len(comments) < 20:
            return -1

        time.sleep(_COMMENT_SLEEP_BASE + random.random() * _COMMENT_SLEEP_JITTER)
        return count

    total = 0
    completed = True
    # 1. 热门评论（按点赞）
    for page in range(1, hot_pages + 1):
        n = _crawl_page(page, OrderType.LIKE)
        if n < 0:
            completed = False  # 风控/失败中断，评论不完整，不标记已爬取
            break
        total += n

    # 2. 最新评论（按时间）
    if completed:
        for page in range(1, newest_pages + 1):
            n = _crawl_page(page, OrderType.TIME)
            if n < 0:
                completed = False
                break
            total += n

    # 仅完整爬完才标记评论已爬取；否则保留 comments_crawled_at 为空，
    # 让后续任务能重新投递该视频的评论爬取，避免评论永久缺页
    if completed:
        v = db.session.get(BiliVideo, _video_id)
        if v:
            v.comments_crawled_at = now_cst()
            db.session.commit()

    return total


# 弹幕爬取间隔基础值（秒）+ 抖动，防风控
_DANMAKU_SLEEP_BASE = float(os.environ.get('BILI_DANMAKU_SLEEP', '2.0'))
_DANMAKU_SLEEP_JITTER = float(os.environ.get('BILI_DANMAKU_JITTER', '2.0'))


def _crawl_video_danmakus(video, force: bool = False):
    """全量爬取单个视频的弹幕（分 P + 每 6 分钟一段）。

    策略：
      1. get_video_pages() 取全部分 P（含 cid 与时长）
      2. 对每个分 P，按 ceil(duration / 360) 计算段数，逐段 get_video_danmakus()
      3. 内存判重（cid, progress, content），分批提交，每段后 db.session.remove()
      4. 仅完整爬完才标记 danmaku_crawled_at；风控/失败中断则保留为空以便重投

    Args:
        video (BiliVideo): 视频 ORM 对象（需有 id、bvid、duration）
        force (bool):      是否强制重新爬取（默认 False：已爬取过则跳过）
    Returns:
        int: 爬取的弹幕总数
    """
    from blog.bilibili.bili_api import (
        get_video_danmakus, get_video_pages, _is_risk_control, was_recently_blocked,
    )
    from .models import BiliDanmaku

    # 已完整爬取过且非强制刷新则跳过（避免每次刷新重复全量拉取）
    if not force and video.danmaku_crawled_at:
        return 0

    # 在闭包外保存原始值，避免 db.session.remove() 后 ORM 对象 detached
    _bvid = video.bvid
    _video_id = video.id

    # 一次性加载该视频已有弹幕的 (cid, progress, content) 集合到内存判重
    _existing = set(
        (r[0], r[1], r[2])
        for r in BiliDanmaku.query.with_entities(
            BiliDanmaku.cid, BiliDanmaku.progress, BiliDanmaku.content
        ).filter_by(video_id=_video_id).all()
    )

    def _crawl_seg(cid, from_seg, to_seg):
        # 全局熔断/冷却检查：最近触发过 412 IP 封禁则直接跳过（不再请求，避免雪上加霜）
        if was_recently_blocked(cooldown=float(os.environ.get('BILI_BLOCK_WINDOW', '300'))):
            return -1, 0
        # 风控指数退避：触发风控后首次等待 _DANMAKU_RETRY_DELAY，之后翻倍
        _retry_delay = float(os.environ.get('BILI_DANMAKU_RETRY_DELAY', '15.0'))
        _max_retries = int(os.environ.get('BILI_DANMAKU_RETRIES', '2'))
        danmakus = None
        for _attempt in range(_max_retries + 1):
            try:
                danmakus = get_video_danmakus(_bvid, cid, from_seg=from_seg, to_seg=to_seg)
                break
            except Exception as e:
                if _is_risk_control(e):
                    if _attempt < _max_retries:
                        logger.warning('视频 %s 弹幕触发风控，等待 %.0fs 后重试 (第 %d/%d 次)...',
                                       _bvid, _retry_delay, _attempt + 1, _max_retries)
                        time.sleep(_retry_delay)
                        _retry_delay = min(_retry_delay * 2,
                                           float(os.environ.get('BILI_DANMAKU_RETRY_CAP', '120.0')))
                        continue
                    logger.warning('视频 %s 弹幕段 %d~%d 风控重试耗尽，中断本次弹幕爬取',
                                   _bvid, from_seg, to_seg)
                    return -1, 0
                logger.warning('视频 %s 弹幕段 %d~%d 获取失败: %s', _bvid, from_seg, to_seg, e)
                return -1, 0
        if danmakus is None:
            return -1, 0

        if not danmakus:
            return 0, 0

        count = 0
        for d in danmakus:
            content = (d.get('content') or '').strip()
            if not content:
                continue
            content = content[:500]
            prog = d.get('progress', 0)
            key = (cid, prog, content)
            if key in _existing:
                continue
            db.session.add(BiliDanmaku(
                video_id=_video_id,
                cid=cid,
                content=content,
                ctime=d.get('ctime', 0),
                progress=prog,
                mode=d.get('mode', 0),
                color=d.get('color', 'ffffff')[:16],
                author=(d.get('author') or '')[:64],
            ))
            _existing.add(key)
            count += 1

        db.session.commit()
        db.session.remove()
        time.sleep(_DANMAKU_SLEEP_BASE + random.random() * _DANMAKU_SLEEP_JITTER)
        return 0, count

    total = 0
    completed = True
    try:
        pages = get_video_pages(_bvid)
    except Exception as e:
        logger.warning('视频 %s 获取分P失败: %s', _bvid, e)
        return 0
    if not pages:
        # 无法获取分P（无有效 cid），弹幕无法定位，跳过
        logger.warning('视频 %s 无分P数据，跳过弹幕爬取', _bvid)
        return 0

    import math
    for page_info in pages:
        cid = page_info.get('cid') or 0
        if not cid:
            continue
        dur = page_info.get('duration') or 0
        seg_count = math.ceil(dur / 360) if dur > 0 else 1
        if seg_count <= 0:
            seg_count = 1
        # 分 P 超过 3 段时限制单 P 段数，避免一次任务过长（可配）
        max_seg_per_page = int(os.environ.get('BILI_DANMAKU_MAX_SEG', '0'))
        if max_seg_per_page > 0:
            seg_count = min(seg_count, max_seg_per_page)
        for from_seg in range(0, seg_count, 1):
            n_code, n = _crawl_seg(cid, from_seg, from_seg)
            if n_code < 0:
                completed = False
                break
            total += n
        if not completed:
            break

    # 仅完整爬完才标记弹幕已爬取；否则保留 danmaku_crawled_at 为空以便重投
    if completed:
        v = db.session.get(BiliVideo, _video_id)
        if v:
            v.danmaku_crawled_at = now_cst()
            db.session.commit()

    # 全局熔断联动：若本任务期间 B站 API 层检测到 412 IP 封禁，
    # 打开全局熔断器，让深扫/增量/评论等其他爬取一并暂停，避免连锁触发风控
    # 注意：必须用 BILI_BLOCK_WINDOW 冷却窗口判断（cooldown=0 意味着"只要有
    # 过 412 记录就 True"，会误触发熔断永不关闭）
    from blog.bilibili.bili_api import was_recently_blocked as _wrb
    if _wrb(cooldown=float(os.environ.get('BILI_BLOCK_WINDOW', '300'))):
        with _circuit_lock:
            if time.time() >= _circuit_open_until:
                _cooldown = _circuit_compute_cooldown()
                _circuit_open_until = time.time() + _cooldown
                logger.error('弹幕爬取检测到 412 封禁，全局熔断 %d 分钟', _cooldown // 60)

    # 释放判重集合（大视频弹幕可达数万条）
    try:
        _existing.clear()
    except Exception:
        pass

    return total


def _load_recent_hist_map(video_ids, cutoff):
    """批量加载 video_ids 在 cutoff 之后最近的一条历史快照。

    按 video_id 分组取 recorded_at 最新的一条，返回
    {video_id: BiliVideoHistory}。仅可在同一线程的 session 中
    使用返回的 ORM 对象（避免跨线程共享 session）。
    """
    if not video_ids:
        return {}
    rows = (
        BiliVideoHistory.query.filter(
            BiliVideoHistory.video_id.in_(video_ids),
            BiliVideoHistory.recorded_at >= cutoff,
        )
        .order_by(BiliVideoHistory.recorded_at.desc())
        .all()
    )
    hist_map: dict[int, BiliVideoHistory] = {}
    for h in rows:
        hist_map.setdefault(h.video_id, h)
    return hist_map


def _load_recent_hist_ids(video_ids, cutoff):
    """批量加载 video_ids 在 cutoff 之后最近一条历史快照的主键 ID。

    返回 {video_id: history_id}（纯标量），可安全跨线程传递；
    子线程可通过 query.get(history_id) 获取 ORM 对象。
    """
    if not video_ids:
        return {}
    rows = (
        BiliVideoHistory.query.with_entities(
            BiliVideoHistory.video_id, BiliVideoHistory.id
        )
        .filter(
            BiliVideoHistory.video_id.in_(video_ids),
            BiliVideoHistory.recorded_at >= cutoff,
        )
        .order_by(BiliVideoHistory.recorded_at.desc())
        .all()
    )
    hist_id_map: dict[int, int] = {}
    for vid, hid in rows:
        hist_id_map.setdefault(vid, hid)
    return hist_id_map


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
    with _circuit_lock:
        if time.time() < _circuit_open_until:
            logger.warning('全局熔断中，跳过增量检查 mid=%d', mid)
            return

    # 深扫互斥检查：仅「同一 mid 正在深扫/刷新」才让路，其他 UP 的增量照常执行。
    # 安全性：全局令牌桶 BILI_GLOBAL_RATE_CAP=1 已将 B站 请求全局串行
    # （同一时刻仅 1 个 B站 请求在途），不同 UP 并发不增加请求频率，
    # 不会触发 -352 风控；深扫期间其他 UP 订阅者的新视频通知不再被饿死。
    with _scrape_lock:
        if mid in _scrape_running:
            logger.warning('本 UP 深扫中(mid=%d)，跳过本次增量', mid)
            return

    # 获取该 mid 的进度日志列表（引用，后续直接 append）
    with _scrape_lock:
        prog = _scrape_progress.get(mid, [])
    _up_name = ['?']

    def emit(line: str, typ: str = ''):
        """向进度日志追加一行并同时输出到日志系统

        Args:
            line: 日志内容
            typ: 类型标签（NEW/SNAP/HOT/FILL/ERR 等），用于前端着色区分
        """
        tag = f'[{typ}] ' if typ else ''
        prog.append(f'[{time.strftime("%H:%M:%S")}] [{_up_name[0]}] {tag}{line}')
        logger.info('[%s] %s%s', _up_name[0], tag, line)
        try:
            from blog.task_queue import update_progress
            update_progress(mid, prog[:])
        except Exception:
            pass

    with app.app_context():
        try:

            from blog.bilibili.bili_api import get_video_list, get_video_stats_batch

            up = BiliUp.query.filter_by(mid=mid).first()
            if not up:
                return
            _up_name[0] = up.name or str(mid)

            # 取数据库已有的 bvid 和 aid 集合 — 用于快速判重（一次查询取两列）
            existing_rows = (
                BiliVideo.query.with_entities(BiliVideo.bvid, BiliVideo.aid)
                .filter_by(up_id=up.id)
                .all()
            )
            existing_bvids = {r[0] for r in existing_rows}
            existing_aids = {r[1] for r in existing_rows}

            _t_start = time.time()
            emit(f'开始增量检查 (DB 已有 {len(existing_bvids)} 个视频)', 'SYS')

            count = 0
            consecutive_known = 0  # 连续已知视频计数 — 超阈值说明已无新视频
            _batch_count = 0
            # 本 run 新插入视频的 bvid 集合：快照阶段排除，避免重复拉取统计
            _run_new_bvids: set[str] = set()
            # 连续 30 个视频全部已知 → 认为已经扫描到已入库的尾部，提前停止
            MAX_CONSECUTIVE_KNOWN = int(os.environ.get('BILI_INCREMENTAL_CONSECUTIVE', '30'))
            # arc/search 返回的统计缓存（bvid → view/comment/danmaku/favorite）
            # 供统计快照复用，避免为最新视频再发独立统计请求（不增加风控压力）
            _page_stats: dict[str, dict] = {}
            # ── 动态流优先：先检查动态流是否有新视频 ──
            # B站动态接口 1 个请求即可获取最近 ~12 条动态，
            # 大多数 UP 主无新视频时只需这 1 个请求，跳过 arc/search 翻页（节省 2-5 个请求）
            from blog.bilibili.bili_api import get_video_list_from_dynamics

            _dyn_error = False  # 动态流接口是否异常（区别于正常返回空）
            try:
                dyn_videos = get_video_list_from_dynamics(mid)
            except Exception as e:
                logger.warning('动态发现失败 mid=%d: %s', mid, e)
                dyn_videos = []
                _dyn_error = True
            _dyn_new = [v for v in dyn_videos
                        if v['bvid'] not in existing_bvids and v['aid'] not in existing_aids]

            # arc/search 翻页收集新视频
            # 默认仅依赖动态流（1 个请求即可覆盖最近活跃视频），
            # 历史视频首次入库时已全量抓取，增量阶段无需翻页补历史。
            # arc/search 翻页接口（get_video_list）是风控 412 的高发点，
            # 因此默认完全跳过；仅当显式设置 BILI_INCREMENTAL_ARC_SEARCH=1 时才启用。
            _new_videos: list = []
            _inc_max_pages = int(os.environ.get('BILI_INCREMENTAL_PAGES', '2'))
            _inc_arc_search = int(os.environ.get('BILI_INCREMENTAL_ARC_SEARCH', '0'))
            # 仅当动态流接口异常（_dyn_error）或显式启用开关时翻页；
            # 动态流正常返回（即使为空）也跳过 arc/search —— 历史视频已在 DB，
            # 翻页接口 get_video_list 是风控 412 高发点，应尽量规避。
            _need_arc_search = bool(_dyn_error) or bool(_inc_arc_search)
            if _need_arc_search:
                for video_info in get_video_list(mid, max_pages=_inc_max_pages):
                    bvid = video_info['bvid']
                    aid = video_info['aid']
                    title_short = (video_info.get('title') or '')[:30]
                    # 缓存本页已返回的统计字段，供统计快照复用
                    _page_stats[bvid] = {
                        'view_count': video_info.get('view_count', 0),
                        'comment_count': video_info.get('comment_count', 0),
                        'danmaku_count': video_info.get('danmaku_count', 0),
                        'favorite_count': video_info.get('favorite_count', 0),
                    }
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
                    _new_videos.append(video_info)

                # 并发批量获取新视频统计（替代逐视频串行 API + sleep）
                if _new_videos:
                    _stat_batch, _stat_deleted = get_video_stats_batch([v['bvid'] for v in _new_videos])
                    # 新视频统计失败且明确"稿件不可见"的，不参与墓碑（尚未入库），仅记日志
                    if _stat_deleted:
                        logger.info('增量检查: %d 个新视频稿件不可见，跳过入库', len(_stat_deleted))
                        _new_videos = [v for v in _new_videos if v['bvid'] not in set(_stat_deleted)]
                    for video_info in _new_videos:
                        bvid = video_info['bvid']
                        aid = video_info['aid']
                        title_short = (video_info.get('title') or '')[:30]
                        stat = _stat_batch.get(bvid)
                        if stat:
                            video_info.update(stat)
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
                        _run_new_bvids.add(bvid)
                        title_short = (video_info.get('title') or '')[:30]
                        emit(f'发现新视频 [{count}] {title_short}', 'NEW')
            else:
                emit(f'动态流无新视频，跳过 arc/search 翻页（节省 {_inc_max_pages} 个 API 请求）', 'SYS')

            # 处理动态发现的新视频（复用上面的 dyn_videos / _dyn_new）
            # 动态流返回的 video_info 已含完整 7 项统计（get_info），无需再整批拉取，
            # 避免同一视频在同一次增量内被重复请求（降低风控压力）。
            _batch_count = 0
            for video_info in _dyn_new:
                bvid = video_info['bvid']
                aid = video_info['aid']
                title_short = (video_info.get('title') or '')[:30]
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
                _run_new_bvids.add(bvid)
                emit(f'[动态发现] 新视频 [{count}] {title_short}', 'DYN')
            if dyn_videos:
                emit(f'动态发现完成，共扫描 {len(dyn_videos)} 个视频', 'DYN')
            db.session.commit()

            # 更新 UP 主的视频总数（排除已删除墓碑，与实际可见数一致）
            up.video_count = BiliVideo.query.filter_by(up_id=up.id, is_deleted=False).count()
            db.session.commit()
            if count:
                emit(f'增量完成，新增 {count} 个视频，耗时 {time.time() - _t_start:.0f}s', 'OK')
                # ── 发送邮件通知给已订阅的用户 ──────────
                try:
                    new_videos = (
                        BiliVideo.query.filter_by(up_id=up.id)
                        .order_by(BiliVideo.pubdate.desc())
                        .limit(count)
                        .all()
                    )
                    # 构造邮件模板所需的数据（含简介，不含播放量等统计）
                    new_videos_data = [
                        {
                            'title': v.title or '',
                            'bvid': v.bvid,
                            'url': f'https://www.bilibili.com/video/{v.bvid}',
                            'pub_date': v.pub_date.strftime('%Y-%m-%d') if v.pub_date else '',
                            'duration': f'{v.duration // 60}:{v.duration % 60:02d}'
                            if v.duration
                            else '',
                            'description': v.description or '',
                        }
                        for v in new_videos
                    ]
                    # 查询已通过邮箱验证的订阅者
                    subs = BiliSubscription.query.filter_by(up_id=up.id, verified=True).all()
                    if subs:
                        # 批量通知：先写入 Redis 暂存队列，由 Worker 定时聚合发送。
                        # 避免"每个 UP 每次增量一封邮件"导致订阅多个 UP 时邮箱刷屏。
                        from blog.mail import queue_video_notify

                        emit(f'新视频通知已暂存（等待定时批量发送）给 {len(subs)} 个订阅者', 'MAIL')
                        from blog.utils import build_site_url
                        for sub in subs:
                            # worker 后台线程无请求上下文，用 SITE_BASE_URL 生成退订链接
                            unsub_url = build_site_url(
                                'bili_public.unsubscribe', token=sub.token
                            )
                            up_display = up.name or str(up.mid)
                            for v in new_videos_data:
                                queue_video_notify(sub.email, up_display, v, unsub_url)
                except Exception as e:
                    logger.error('发送新视频通知失败 mid=%d: %s', mid, e)

            # ── 追踪最新 N 个视频 + 重点视频的统计（每轮快照，并发批量获取）──
            tracked_ids: set[int] = set()
            snap_videos: list = []  # 需要更新统计的视频 ORM 对象
            try:
                from blog.bilibili.config import TRACK_LATEST_VIDEOS
                latest = (
                    BiliVideo.query.filter_by(up_id=up.id, is_deleted=False)
                    .order_by(BiliVideo.pubdate.desc())
                    .limit(TRACK_LATEST_VIDEOS)
                    .all()
                )
                for v in latest:
                    tracked_ids.add(v.id)
                    snap_videos.append(v)
                if latest:
                    emit(f'追踪最新 {len(latest)} 个视频统计', 'SNAP')

                watched_q = (
                    BiliVideo.query.join(BiliWatchedVideo)
                    .filter(BiliVideo.up_id == up.id, BiliVideo.is_deleted == False)
                )
                if tracked_ids:
                    watched_q = watched_q.filter(BiliVideo.id.notin_(tracked_ids))
                watched = watched_q.all()
                if watched:
                    emit(f'追踪 {len(watched)} 个重点视频', 'SNAP')
                    count += len(watched)
                snap_videos.extend(watched)

                # 排除本 run 刚入库的新视频（其统计已在 arc/dyn 路径拉取过，
                # 避免同一视频同一次增量内被重复 get_video_stat）
                if _run_new_bvids:
                    snap_videos = [v for v in snap_videos if v.bvid not in _run_new_bvids]

                if snap_videos:
                    # 并发批量获取完整 7 项统计（播放/点赞/投币/收藏/转发/评论/弹幕）
                    from blog.bilibili.bili_api import get_video_stats_batch
                    _batch, _deleted_bvids = get_video_stats_batch([v.bvid for v in snap_videos])
                    # 墓碑：连续多轮"稿件不可见"的视频标记 is_deleted（下次起不再请求）
                    if _deleted_bvids:
                        _record_invisible_videos(_deleted_bvids)
                    # 一次性批量加载近 30s 窗口内的历史快照（按 video_id 取最新一条），
                    # 避免循环内为每个视频单独执行一次窗口查询（N+1）
                    _snap_cutoff = now_cst() - datetime.timedelta(seconds=30)
                    _hist_map = _load_recent_hist_map(
                        [v.id for v in snap_videos], _snap_cutoff
                    )
                    for v in snap_videos:
                        stat = _batch.get(v.bvid)
                        if not stat:
                            continue
                        # 成功取到统计 → 清除不可见计数；若曾被标记删除则恢复
                        _clear_invisible_count(v.bvid)
                        if v.is_deleted:
                            v.is_deleted = False
                            v.deleted_at = None
                            logger.info('视频恢复可见，清除墓碑: %s', v.bvid)
                        for key, val in stat.items():
                            setattr(v, key, val)
                        # 记录历史快照（预检避免重复数据点）
                        _prev_h = _hist_map.get(v.id)
                        if _prev_h:
                            _prev_h.view_count = stat.get('view_count', 0)
                            _prev_h.like_count = stat.get('like_count', 0)
                            _prev_h.coin_count = stat.get('coin_count', 0)
                            _prev_h.favorite_count = stat.get('favorite_count', 0)
                            _prev_h.share_count = stat.get('share_count', 0)
                            _prev_h.comment_count = stat.get('comment_count', 0)
                            _prev_h.danmaku_count = stat.get('danmaku_count', 0)
                        else:
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
                        title_short = (v.title or '')[:30]
                        emit(f'[快照] 「{title_short}」', 'SNAP')
                    # 合并为一次提交，减少事务开销
                    db.session.commit()
                    emit(f'快照完成，共更新 {len(snap_videos)} 个视频', 'SNAP')
            except Exception as e:
                logger.error('视频统计快照失败 mid=%d: %s', mid, e)

            # 检查 B站 API 层是否已检测到 412（可能在 get_video_list 内部处理，未抛异常到此处）
            from blog.bilibili.bili_api import was_recently_blocked
            with _circuit_lock:
                if was_recently_blocked(cooldown=float(os.environ.get('BILI_BLOCK_WINDOW', '300'))) and time.time() >= _circuit_open_until:
                    _cooldown = _circuit_compute_cooldown()
                    _circuit_open_until = time.time() + _cooldown
                    logger.error('API 层检测到 412 封禁，全局熔断 %d 分钟', _cooldown // 60)

        except Exception as e:
            logger.error('增量检查失败 mid=%d: %s', mid, e)
            from blog.bilibili.bili_api import _is_ip_blocked
            if _is_ip_blocked(e):
                with _circuit_lock:
                    _cooldown = _circuit_compute_cooldown()
                    _circuit_open_until = time.time() + _cooldown
                    logger.error('检测到 412 封禁，全局熔断 %d 分钟', _cooldown // 60)
        finally:
            # 无论成功还是异常，都必须清理运行状态
            with _scrape_lock:
                _incremental_running.discard(mid)
                _scrape_progress.pop(mid, None)
            # 显式释放本函数持有的大集合，避免跨周期内存累积（增量每 30 分钟一次）
            for _nm in ('existing_bvids', 'existing_aids', '_run_new_bvids',
                        'snap_videos', '_batch', '_hist_map', 'existing_rows',
                        '_page_stats', 'tracked_ids'):
                if _nm in locals() and locals()[_nm]:
                    try:
                        locals()[_nm].clear()
                    except Exception:
                        pass
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

    from blog.task_queue import get_progress
    redis_lines, redis_running = get_progress(mid)

    with _scrape_lock:
        local_lines = deepcopy(_scrape_progress.get(mid, []))
        local_running = (mid in _scrape_running) or (mid in _incremental_running)

    return {
        'running': redis_running or local_running,
        'lines': redis_lines if redis_lines else local_lines,
    }


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

    # 冷却检查：若最近检测到 B站 412 IP 封禁，拒绝立即添加新 UP。
    # 新UP添加走 wbi/acc/info + arc/search 敏感接口，刚被封禁时立即重试必触发 -352/412。
    from blog.bilibili.bili_api import was_recently_blocked, get_blocked_remaining
    _cool_seconds = int(os.environ.get('BILI_ADD_COOLDOWN', '300'))
    if was_recently_blocked(cooldown=_cool_seconds):
        _remain = get_blocked_remaining(_cool_seconds)
        return {'ok': False,
                'error': f'B站 IP 风控冷却中（最近触发过 412 封禁），请等待约 {_remain} 秒后再添加'}

    from blog.task_queue import try_acquire, mark_done, submit_task, is_queue_available
    # 原子占位：并发添加同一 UP 只允许一个请求通过
    if not try_acquire(mid):
        return {'ok': False, 'error': '该 UP 主正在爬取中'}
    with _scrape_lock:
        if mid in _scrape_running or mid in _incremental_running:
            mark_done(mid)
            return {'ok': False, 'error': '该 UP 主正在爬取中'}
        _scrape_progress[mid] = []
    if not is_queue_available():
        mark_done(mid)
        return {'ok': False, 'error': '任务队列不可用（Redis 未连接）'}
    task_id = submit_task('refresh_up', mid=mid, space_url=space_url)
    if task_id:
        return {'ok': True, 'mid': mid, 'task_id': task_id}
    mark_done(mid)
    return {'ok': False, 'error': '任务提交失败，请稍后重试'}


@bili_bp.route('/add-video', methods=['POST'])
@editor_required
def add_single_video():
    """添加单个视频（通过 BV 号）

    支持输入：
        - BV 号（如 BV1xx411c7mD）
        - 视频链接（如 https://www.bilibili.com/video/BV1xx411c7mD）
        - AV 号（如 av2，会自动转换为 BV 号）

    自动获取视频信息并入库，同时自动创建或更新对应的 UP 主记录。

    Returns:
        JSON: {ok: True, video: {...}, up: {...}}
              或 {ok: False, error: str}
              或 {exists: True, video: {...}}  # 视频已存在，需用户确认
    """
    video_input = request.form.get('video_input', '').strip()
    force_update = request.form.get('force_update', '0') == '1'  # 强制更新标记
    
    if not video_input:
        return {'ok': False, 'error': '请输入 BV 号或视频链接'}

    # 提取 BV 号
    import re
    bvid = None

    # 尝试匹配 BV 号
    bv_match = re.search(r'(BV[a-zA-Z0-9]{10})', video_input)
    if bv_match:
        bvid = bv_match.group(1)

    # 尝试匹配 AV 号并转换为 BV 号
    if not bvid:
        av_match = re.search(r'av(\d+)', video_input, re.IGNORECASE)
        if av_match:
            aid = int(av_match.group(1))
            # AV 转 BV 算法
            table = 'fZodR9XQDSUm21yCkr6zBqiveYah8bt4xsWpHnJE7jL5VG3guMTNNPAcF'
            tr = {c: i for i, c in enumerate(table)}
            aid = (aid ^ 177456) // 100
            arr = [0] * 9
            for i in range(9):
                arr[i] = table[aid // 58**i % 58]
            bvid = 'BV' + ''.join(arr[::-1])

    if not bvid:
        return {'ok': False, 'error': '无法识别 BV 号或视频链接'}

    # 检查视频是否已存在
    existing_video = BiliVideo.query.filter_by(bvid=bvid).first()
    if existing_video and not force_update:
        # 返回已存在提示，让前端确认是否更新
        up = db.session.get(BiliUp, existing_video.up_id)
        return {
            'exists': True,
            'video': {
                'bvid': bvid,
                'title': existing_video.title,
                'view_count': existing_video.view_count,
            },
            'up': {
                'mid': up.mid if up else 0,
                'name': up.name if up else '未知',
            },
        }

    # 获取视频完整信息
    try:
        from blog.bilibili.bili_api import get_video_full_info
        video_info = get_video_full_info(bvid)
    except Exception as e:
        logger.error('获取视频 %s 信息失败: %s', bvid, e)
        return {'ok': False, 'error': f'获取视频信息失败: {str(e)}'}

    owner_mid = video_info['owner_mid']
    if not owner_mid:
        return {'ok': False, 'error': '视频信息中缺少 UP 主 ID'}

    # 查找或创建 UP 主（只保存基本信息：mid、名称、头像）
    up = BiliUp.query.filter_by(mid=owner_mid).first()
    if not up:
        # 创建 UP 主记录，不爬取完整信息
        up = BiliUp(
            mid=owner_mid,
            name=video_info['owner_name'],
            avatar=video_info['owner_face'],
            video_count=0,  # 不统计，需要时单独爬取
            follower_count=0,  # 不统计，需要时单独爬取
        )
        db.session.add(up)
        db.session.flush()
    else:
        # 只更新名称和头像，不更新其他统计信息
        if video_info['owner_name']:
            up.name = video_info['owner_name']
        if video_info['owner_face']:
            up.avatar = video_info['owner_face']

    # 查找或创建视频记录
    video = BiliVideo.query.filter_by(bvid=bvid).first()
    is_new = not video

    if video and video.is_deleted:
        # 手动添加能成功获取完整信息 → 稿件已恢复可见，清除墓碑
        video.is_deleted = False
        video.deleted_at = None
        _clear_invisible_count(bvid)
        logger.info('视频恢复可见，清除墓碑（手动添加）: %s', bvid)

    if not video:
        video = BiliVideo(
            up_id=up.id,
            aid=video_info['aid'],
            bvid=bvid,
            title=video_info['title'],
            description=video_info['description'],
            duration=video_info['duration'],
            pub_date=video_info['pub_date'],
            pub_datetime=video_info['pub_datetime'],
            view_count=video_info['view_count'],
            like_count=video_info['like_count'],
            coin_count=video_info['coin_count'],
            favorite_count=video_info['favorite_count'],
            share_count=video_info['share_count'],
            comment_count=video_info['comment_count'],
            danmaku_count=video_info['danmaku_count'],
            pic=video_info['pic'],
        )
        db.session.add(video)
        db.session.flush()

        # 创建初始历史记录
        history = BiliVideoHistory(
            video_id=video.id,
            view_count=video_info['view_count'],
            like_count=video_info['like_count'],
            coin_count=video_info['coin_count'],
            favorite_count=video_info['favorite_count'],
            share_count=video_info['share_count'],
            comment_count=video_info['comment_count'],
            danmaku_count=video_info['danmaku_count'],
        )
        db.session.add(history)
    else:
        # 更新现有视频的统计
        video.view_count = video_info['view_count']
        video.like_count = video_info['like_count']
        video.coin_count = video_info['coin_count']
        video.favorite_count = video_info['favorite_count']
        video.share_count = video_info['share_count']
        video.comment_count = video_info['comment_count']
        video.danmaku_count = video_info['danmaku_count']
        video.title = video_info['title']
        video.pic = video_info['pic']

        # 创建新的历史记录
        history = BiliVideoHistory(
            video_id=video.id,
            view_count=video_info['view_count'],
            like_count=video_info['like_count'],
            coin_count=video_info['coin_count'],
            favorite_count=video_info['favorite_count'],
            share_count=video_info['share_count'],
            comment_count=video_info['comment_count'],
            danmaku_count=video_info['danmaku_count'],
        )
        db.session.add(history)

    up.updated_at = now_cst()
    db.session.commit()

    return {
        'ok': True,
        'is_new': is_new,
        'video': {
            'bvid': bvid,
            'title': video_info['title'],
            'view_count': video_info['view_count'],
        },
        'up': {
            'mid': owner_mid,
            'name': video_info['owner_name'],
        },
    }


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
    if not force:
        with _circuit_lock:
            if time.time() < _circuit_open_until:
                logger.warning('全局熔断中，跳过深扫 mid=%d', mid)
                with _scrape_lock:
                    _scrape_running.discard(mid)
                    _scrape_progress.pop(mid, None)
                return

    # 重入保护 — 本地检查（防止同一mid被多线程同时爬取）
    # 注意：不在此处检查 is_running(mid)：路由层提交任务时已通过
    # try_acquire() 原子占位运行锁，Worker 内再查会看到自己设的锁导致任务空跑。
    # 跨进程互斥由路由层的 try_acquire 运行锁 + 本地 _scrape_running 检查保证。
    if not force:
        with _scrape_lock:
            if mid in _scrape_running or mid in _incremental_running:
                logger.warning('mid=%d 已在运行中,跳过本次深扫', mid)
                return
            _scrape_running.add(mid)
    else:
        with _scrape_lock:
            _scrape_running.add(mid)

    # 与正在进行的增量检查协调：若已有任意 UP 正在增量检查，等待其收尾再开始请求。
    # 深扫（尤其新UP全量爬取）与增量检查并发，会让多线程用不同 UA 同时打同一 IP，
    # 触发 B站 -352 风控。等待上限 60s：增量检查单 UP 通常 30s 内完成，避免长阻塞。
    if not force:
        wait_start = time.time()
        while time.time() - wait_start < 60:
            with _scrape_lock:
                if not _incremental_running:
                    break
            time.sleep(1.0)
        with _scrape_lock:
            if _incremental_running:
                logger.warning('增量检查仍在进行(%d个)，深扫 mid=%d 继续执行（受全局串行限速保护）',
                               len(_incremental_running), mid)

    # 获取该 mid 的进度日志列表引用
    prog = _scrape_progress.get(mid, [])
    _up_name = ['?']

    def emit(line: str, typ: str = ''):
        """向进度日志追加一行并同时输出到日志系统

        Args:
            line: 日志内容
            typ: 类型标签（NEW/SNAP/HOT/FILL/ERR 等），用于前端着色区分
        """
        tag = f'[{typ}] ' if typ else ''
        prog.append(f'[{time.strftime("%H:%M:%S")}] [{_up_name[0]}] {tag}{line}')
        logger.info('[%s] %s%s', _up_name[0], tag, line)
        try:
            from blog.task_queue import update_progress
            update_progress(mid, prog[:])
        except Exception:
            pass

    with app.app_context():
        try:

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
                    f'UP主信息  |  粉丝: {ui.get("follower_count", 0):,}  |  视频总数: {ui.get("video_count", 0)}',
                    'UP',
                )
            except Exception as e:
                emit(f'获取 UP 主信息失败: {e}', 'ERR')
                if not up:
                    # 最低限度创建 UP 主记录
                    up = BiliUp(mid=mid, space_url=space_url)
                    db.session.add(up)
                    db.session.commit()
                _up_name[0] = up.name or str(mid)

            _t_start = time.time()
            emit('初始化数据库...', 'SYS')

            # B. 补全缺失视频 — 判断是否需要从 API 拉取
            total_in_db = BiliVideo.query.filter_by(up_id=up.id, is_deleted=False).count()
            should_fill = (
                total_in_db == 0
                or total_in_api is None
                or (total_in_api > 0 and total_in_db < total_in_api)
                or (total_in_api == 0 and total_in_db > 0)
                or force
            )
            fill_count = 0
            fill_new_bvids: set[str] = set()
            # 预加载现有 BVID/AID 集合用于判重（一次查询取两列）
            existing_rows = (
                BiliVideo.query.with_entities(BiliVideo.bvid, BiliVideo.aid)
                .filter_by(up_id=up.id)
                .all()
            )
            existing_ids = {r[0] for r in existing_rows}
            existing_aids = {r[1] for r in existing_rows}
            if should_fill:
                from blog.bilibili.bili_api import get_video_list as _get_video_list

                # 计算需补数量：-1 表示数量未知，翻全量
                need = (total_in_api - total_in_db) if total_in_api is not None and total_in_api > 0 else -1
                if need > 0:
                    emit(f'[补全] 发现 {need} 个缺失视频，开始补齐...', 'FILL')
                else:
                    emit(f'[补全] DB 有 {total_in_db} 个视频，开始从 API 补齐...', 'FILL')

                _batch_count = 0

                # 补全页数上限（412 风控核心缓解）：
                # - 显式设置 BILI_FILL_MAX_PAGES → 按其值
                # - 存量 UP（已有视频记录）且非 force → 默认限 _FILL_DEFAULT_PAGES 页
                #   （默认 3 页 ≈ 最近 45 个视频，覆盖日常新增；历史缺失由手动全量刷新补齐）
                # - 全新 UP（total_in_db==0）或手动强制刷新（force）→ 不限页（全量）
                # 背景：arc/search 全量翻页是 412 高发点，每日深扫对所有 UP 全量翻页
                # 是每天 02:00 触发风控的根因（日志 08/15~08/19 连续 412）。
                _fill_max_pages = None
                if os.environ.get('BILI_FILL_MAX_PAGES'):
                    _fill_max_pages = max(1, int(os.environ['BILI_FILL_MAX_PAGES']))
                elif not force and total_in_db > 0:
                    _fill_max_pages = max(
                        1, int(os.environ.get('BILI_FILL_MAX_PAGES_DEFAULT', '3'))
                    )
                if _fill_max_pages:
                    emit(f'[补全] arc/search 限翻 {_fill_max_pages} 页（风控保护）', 'FILL')

                def _fill_fetch_stat(vi):
                    with app.app_context():
                        _fbvid = vi['bvid']
                        _fts = (vi.get('title') or '')[:30]
                        try:
                            _fstat = get_video_stat(_fbvid)
                            vi.update(_fstat)
                            thread_sleep()
                            return True
                        except Exception:
                            logger.warning('视频 %s 「%s」补全时统计获取失败', _fbvid, _fts)
                            time.sleep(float(os.environ.get('BILI_FILL_FAIL_SLEEP', '12.0')))
                            return False

                _fill_q = _queue_mod.Queue(maxsize=_UPDATE_THREADS * 2)
                _fill_stop_evt = threading.Event()

                def _fill_producer():
                    with app.app_context():
                        try:
                            for video_info in _get_video_list(mid, max_pages=_fill_max_pages):
                                if _fill_stop_evt.is_set():
                                    break
                                _pbvid = video_info['bvid']
                                _paid = video_info['aid']
                                _pts = (video_info.get('title') or '')[:30]
                                _pknown = _pbvid in existing_ids or _paid in existing_aids
                                logger.info('补全循环: bvid=%s title=%s known=%s', _pbvid, _pts, _pknown)
                                if _pknown:
                                    continue
                                _fill_q.put(video_info)
                        except Exception as _pfe:
                            logger.warning('补全生成器异常: %s', _pfe)
                        finally:
                            _fill_q.put(None)

                _producer_t = threading.Thread(target=_fill_producer, daemon=True)
                _producer_t.start()

                with ThreadPoolExecutor(max_workers=_UPDATE_THREADS) as _fill_pool:
                    _fill_futs = {}
                    # 已提交处理的数量（含处理中）；need/max_videos 均作为硬上限
                    _fill_submitted = 0
                    _fill_quota = need if need > 0 else (max_videos or 0)
                    while True:
                        try:
                            _item = _fill_q.get(timeout=0.5)
                        except _queue_mod.Empty:
                            if not _producer_t.is_alive() and _fill_q.empty():
                                break
                            continue
                        if _item is None:
                            break
                        # 达到配额上限（need 或 max_videos）时停止消费并通知生产者
                        if _fill_quota and _fill_submitted >= _fill_quota:
                            _fill_stop_evt.set()
                            break
                        _fill_futs[_fill_pool.submit(_fill_fetch_stat, _item)] = _item
                        _fill_submitted += 1

                    for _ff in as_completed(_fill_futs):
                        _vi = _fill_futs[_ff]
                        try:
                            _ok_stat = _ff.result()
                        except Exception:
                            continue
                        if not _ok_stat:
                            continue
                        _fbvid = _vi['bvid']
                        _faid = _vi['aid']
                        _fts = (_vi.get('title') or '')[:30]
                        video, ok = _insert_or_update_video(up, _vi, _faid, _fbvid, _fts)
                        if not ok:
                            continue
                        _batch_count += 1
                        if _batch_count >= 20:
                            db.session.commit()
                            _batch_count = 0
                        fill_count += 1
                        existing_ids.add(_fbvid)
                        existing_aids.add(_faid)
                        fill_new_bvids.add(_fbvid)
                        emit(f'[补全] ({fill_count}) 「{_fts}」', 'FILL')

                _producer_t.join(timeout=30)

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
                emit(f'[补全/动态] ({fill_count}) 「{title_short}」', 'FILL')
            if dyn_videos:
                emit(f'补全动态扫描完成，共 {len(dyn_videos)} 个', 'DYN')
            db.session.commit()

            if fill_count:
                emit(f'[补全] 完成，新增 {fill_count} 个视频', 'OK')

            # ── D. 三层统计更新 ──────────────────────
            # 将视频按发布时间分为三层，优先更新近期热门视频：
            #
            #   Hot  (≤7天)  → 全部更新，min_age_hours=0（不跳过）
            #                    排除本次新入库的视频（filled_bvids，已有最新数据）
            #   Warm (8~30天) → 配额剩余时更新，min_age_hours=1（1小时内已更新则跳过）
            #                    按 updated_at ASC 排序（最久未更新的优先）
            #   Cold (>30天)  → 配额剩余时处理，min_age_hours=24（24小时内已更新则跳过）
            #                    同样按 updated_at ASC 排序
            #
            # max_videos 参数控制每个 UP 主的总更新上限（手动刷新时为 30，每日深扫时为 None）
            # force=True 时跳过 min_age_hours 检查和 should_fill 判断
            #
            # fill_new_bvids: 本次新入库的视频 BVID — Hot 阶段排除这些（已有最新数据）
            filled_bvids = fill_new_bvids
            count = 0
            hot_done = 0
            warm_done = 0
            cold_done = 0
            now = now_cst()
            cutoff_hot = now - datetime.timedelta(days=int(os.environ.get('BILI_HOT_DAYS', '7')))
            cutoff_warm = now - datetime.timedelta(days=int(os.environ.get('BILI_WARM_DAYS', '30')))

            def _update_video(video_id, label='', min_age_hours=1, hist_id_map=None):
                with app.app_context():
                    try:
                        v = db.session.get(BiliVideo, video_id)
                        if not v:
                            return {'status': 'skip', 'label': label, 'bvid': '', 'title_short': ''}
                        bvid = v.bvid
                        title_short = (v.title or '')[:30]

                        if (
                            not force
                            and v.updated_at
                            and (now_cst().astimezone(datetime.timezone.utc).replace(tzinfo=None) - v.updated_at).total_seconds()
                            < min_age_hours * 3600
                        ):
                            emit(f'  跳过「{title_short}」— 最近 {min_age_hours} 小时内已更新', 'SKIP')
                            return {'status': 'skip', 'label': label, 'bvid': bvid, 'title_short': title_short}


                        local_retry_delay = float(os.environ.get('BILI_RETRY_DELAY', '30.0'))
                        try:
                            stat = get_video_stat(bvid)
                            thread_sleep()
                        except Exception as e:
                            from blog.bilibili.bili_api import _is_video_invisible as _is_gone
                            if _is_risk_control(e):
                                logger.warning('触发风控，等待 %ds 后跳过...', local_retry_delay)
                                emit(f'⚠ 触发风控，等待 {local_retry_delay}s 后跳过「{title_short}」', 'RISK')
                                time.sleep(local_retry_delay)
                                return {'status': 'risk', 'label': label, 'bvid': bvid, 'title_short': title_short}
                            if _is_gone(e):
                                # 稿件不可见：累计失败，达到阈值标记 is_deleted 墓碑
                                _record_invisible_videos([bvid])
                                emit(f'「{title_short}」稿件不可见，累计标记删除', 'WARN')
                                return {'status': 'deleted', 'label': label, 'bvid': bvid, 'title_short': title_short}
                            logger.warning('视频 %s 统计获取失败: %s', bvid, e)
                            emit(f'「{title_short}」统计获取失败: {e}', 'WARN')
                            time.sleep(float(os.environ.get('BILI_FAIL_SLEEP', '8.0')))
                            return {'status': 'fail', 'label': label, 'bvid': bvid, 'title_short': title_short}

                        # 成功获取统计 → 清除不可见计数/墓碑
                        _clear_invisible_count(bvid)
                        if v.is_deleted:
                            v.is_deleted = False
                            v.deleted_at = None
                            logger.info('视频恢复可见，清除墓碑: %s', bvid)
                        for key, val in stat.items():
                            setattr(v, key, val)
                        v.updated_at = now_cst()

                        # 历史快照：主线程已批量预加载 video_id → 最近历史记录 ID，
                        # 子线程按主键查询（避免逐视频 30s 窗口二级索引查询）
                        _hist_id = (hist_id_map or {}).get(v.id)
                        _prev_h = db.session.get(BiliVideoHistory, _hist_id) if _hist_id else None
                        if _prev_h is not None and (
                            # DB 存的是 UTC naive，这里也用 UTC naive 比较，避免 8h 时区偏差
                            now_cst().astimezone(datetime.timezone.utc).replace(tzinfo=None) - _prev_h.recorded_at
                        ).total_seconds() > 30:
                            _prev_h = None
                        if _prev_h:
                            _prev_h.view_count = stat.get('view_count', 0)
                            _prev_h.like_count = stat.get('like_count', 0)
                            _prev_h.coin_count = stat.get('coin_count', 0)
                            _prev_h.favorite_count = stat.get('favorite_count', 0)
                            _prev_h.share_count = stat.get('share_count', 0)
                            _prev_h.comment_count = stat.get('comment_count', 0)
                            _prev_h.danmaku_count = stat.get('danmaku_count', 0)
                        else:
                            try:
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
                            except Exception:
                                db.session.rollback()
                        try:
                            db.session.commit()
                        except Exception:
                            db.session.rollback()

                        return {'status': 'ok', 'label': label, 'bvid': bvid, 'title_short': title_short}
                    except Exception as _uve:
                        logger.warning('_update_video 异常: %s', _uve)
                        return {'status': 'fail', 'label': label, 'bvid': '', 'title_short': ''}
                    finally:
                        try:
                            db.session.remove()
                        except Exception:
                            pass

            # Hot 阶段: 发布时间 ≤7 天 — 全部更新，不跳过
            ensure_semaphore(_UPDATE_THREADS)
            hot_query = BiliVideo.query.filter(
                BiliVideo.up_id == up.id,
                BiliVideo.pub_datetime >= cutoff_hot,
                BiliVideo.is_deleted == False,
            )
            if filled_bvids:
                hot_query = hot_query.filter(~BiliVideo.bvid.in_(filled_bvids))
            # 只取 id 列，避免大 UP（如央视频上万视频）全量加载 ORM 对象导致内存峰值
            hot_ids = [r for (r,) in hot_query.with_entities(BiliVideo.id).order_by(BiliVideo.pubdate.desc()).all()]
            emit(f'Hot 阶段: ≤7天视频共 {len(hot_ids)} 个', 'HOT')
            if max_videos is not None:
                hot_ids = hot_ids[:max(0, max_videos - count)]
            _hot_hist = (
                _load_recent_hist_ids(hot_ids, now - datetime.timedelta(seconds=30))
                if hot_ids
                else {}
            )
            with ThreadPoolExecutor(max_workers=_UPDATE_THREADS) as _hot_pool:
                _hot_futs = {
                    _hot_pool.submit(_update_video, _vid, 'Hot', 0, _hot_hist): _vid
                    for _vid in hot_ids
                }
                for _hf in as_completed(_hot_futs):
                    try:
                        _hr = _hf.result()
                        if _hr['status'] == 'ok':
                            count += 1
                            hot_done += 1
                            emit(f'[{count}] {_hr["label"]}「{_hr["title_short"]}」', 'HOT')
                    except Exception:
                        pass

            # Warm 阶段: 发布时间 8~30 天（配额未满时执行，最久未更新优先，1h 跳过）
            if max_videos is None or count < max_videos:
                remaining = None if max_videos is None else max_videos - count
                warm_query = BiliVideo.query.filter(
                    BiliVideo.up_id == up.id,
                    BiliVideo.pub_datetime >= cutoff_warm,
                    BiliVideo.pub_datetime < cutoff_hot,
                    BiliVideo.is_deleted == False,
                ).order_by(BiliVideo.updated_at.asc())

                if remaining is not None:
                    warm_query = warm_query.limit(remaining)
                warm_ids = [r for (r,) in warm_query.with_entities(BiliVideo.id).all()]
                quota_str = '无限制' if remaining is None else str(remaining)
                emit(f'Warm 阶段: 8~30天视频配额 {quota_str}（DB中共 {len(warm_ids)} 个待更新）', 'WARM')
                _warm_hist = (
                    _load_recent_hist_ids(warm_ids, now - datetime.timedelta(seconds=30))
                    if warm_ids
                    else {}
                )
                with ThreadPoolExecutor(max_workers=_UPDATE_THREADS) as _warm_pool:
                    _warm_futs = {
                        _warm_pool.submit(_update_video, _vid, 'Warm', 1, _warm_hist): _vid
                        for _vid in warm_ids
                    }
                    for _wf in as_completed(_warm_futs):
                        try:
                            _wr = _wf.result()
                            if _wr['status'] == 'ok':
                                count += 1
                                warm_done += 1
                                emit(f'[{count}] {_wr["label"]}「{_wr["title_short"]}」', 'WARM')
                        except Exception:
                            pass

            # Cold 阶段: 发布时间 >30 天（配额剩余时处理，24h 跳过）
            if max_videos is None or count < max_videos:
                remaining = None if max_videos is None else max_videos - count
                cold_query = BiliVideo.query.filter(
                    BiliVideo.up_id == up.id,
                    BiliVideo.pub_datetime < cutoff_warm,
                    BiliVideo.is_deleted == False,
                ).order_by(BiliVideo.updated_at.asc())
                if remaining is not None:
                    cold_query = cold_query.limit(remaining)
                cold_ids = [r for (r,) in cold_query.with_entities(BiliVideo.id).all()]
                if cold_ids:
                    quota_str = '无限制' if remaining is None else str(remaining)
                    emit(
                        f'Cold 阶段: >30天视频配额 {quota_str}（DB中共 {len(cold_ids)} 个待更新）',
                        'COLD',
                    )
                    _cold_hist = (
                        _load_recent_hist_ids(cold_ids, now - datetime.timedelta(seconds=30))
                        if cold_ids
                        else {}
                    )
                    with ThreadPoolExecutor(max_workers=_UPDATE_THREADS) as _cold_pool:
                        _cold_futs = {
                            _cold_pool.submit(_update_video, _vid, 'Cold', 24, _cold_hist): _vid
                            for _vid in cold_ids
                        }
                        for _cf in as_completed(_cold_futs):
                            try:
                                _cr = _cf.result()
                                if _cr['status'] == 'ok':
                                    count += 1
                                    cold_done += 1
                                    emit(f'[{count}] {_cr["label"]}「{_cr["title_short"]}」', 'COLD')
                            except Exception:
                                pass
            # 更新 UP 主的视频总数字段
            db.session.expire_all()
            up.video_count = BiliVideo.query.filter_by(up_id=up.id, is_deleted=False).count()
            db.session.commit()
            emit(
                f'刷新完成  Hot={hot_done}  Warm={warm_done}  Cold={cold_done}  共 {count} 个  |  DB 总视频数: {up.video_count}  |  耗时 {time.time() - _t_start:.0f}s',
                'OK',
            )
            # 完整性检查：对比 API 声明数量与实际入库数量
            if total_in_api:
                db_total = up.video_count
                if db_total >= total_in_api:
                    emit(f'完整性检查: {db_total}/{total_in_api} ✅ 全部视频已入库', 'OK')
                else:
                    emit(
                        f'完整性检查: {db_total}/{total_in_api} ⚠️ 缺失 {total_in_api - db_total} 个视频',
                        'WARN',
                    )
            elif total_in_api is not None and total_in_api == 0 and total_in_db > 0:
                emit(f'完整性检查: Cookie 可能过期，API 返回 video_count=0', 'WARN')

            # 检查 B站 API 层是否已检测到 412（可能在 get_video_list 内部处理，未抛异常到此处）
            from blog.bilibili.bili_api import was_recently_blocked
            with _circuit_lock:
                if was_recently_blocked(cooldown=float(os.environ.get('BILI_BLOCK_WINDOW', '300'))) and time.time() >= _circuit_open_until:
                    _cooldown = _circuit_compute_cooldown()
                    _circuit_open_until = time.time() + _cooldown
                    logger.error('API 层检测到 412 封禁，全局熔断 %d 分钟', _cooldown // 60)

            # 评论爬取：为本 UP 主尚未爬取评论的视频补充数据（限 5 个/次）
            # 投递到 Redis 任务队列，由 worker.py 异步处理。
            if not was_recently_blocked(cooldown=float(os.environ.get('BILI_BLOCK_WINDOW', '300'))):
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
                    try:
                        from blog.task_queue import submit_task
                        submit_task('comment_refresh', bvid=v.bvid)
                        emit(f'评论 [{v.bvid[:8]}…] 已投递到任务队列', 'CMT')
                    except Exception as e:
                        logger.warning('视频 %s 评论任务投递失败: %s', v.bvid, e)

        except Exception as e:
            emit(f'爬取失败: {e}', 'ERR')
            logger.exception('爬取失败 mid=%d', mid)
            from blog.bilibili.bili_api import _is_ip_blocked
            if _is_ip_blocked(e):
                with _circuit_lock:
                    _cooldown = _circuit_compute_cooldown()
                    _circuit_open_until = time.time() + _cooldown
                    logger.error('检测到 412 封禁，全局熔断 %d 分钟', _cooldown // 60)
        finally:
            # 无论成功还是异常，都必须清理运行状态
            with _scrape_lock:
                _scrape_running.discard(mid)
                _scrape_progress.pop(mid, None)
            # 显式释放本函数持有的大集合（deep-scan 的大 UP 可达数千视频），
            # 避免每日深扫 + 手动刷新多次运行后内存累积
            for _nm in ('existing_ids', 'existing_aids', 'fill_new_bvids',
                        'dyn_videos', 'existing_rows', 'hot_ids', 'warm_ids',
                        'cold_ids', '_hot_hist', '_warm_hist'):
                if _nm in locals() and locals()[_nm]:
                    try:
                        locals()[_nm].clear()
                    except Exception:
                        pass
            db.session.remove()


_BATCH_SIZE = min(int(os.environ.get('BILI_BATCH', '3')), 4)


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
        try:

            from blog.models import BiliUp

            ups = BiliUp.query.all()

            # 整体硬 deadline（分钟，默认 90）：超过后不再启动新批次。
            # 保证 02:00 深扫最迟约 03:30 结束，绝不撞 04:00/04:30 词云窗口，
            # 也不把增量检查饿死到 04:00（此前默认串行 BILI_BATCH=1 拖到 ~04:00）。
            _deadline_minutes = int(os.environ.get('BILI_DAILY_DEADLINE', '90'))
            _deadline_ts = time.time() + _deadline_minutes * 60
            logger.info('B站 每日刷新启动: 共 %d 个 UP 主, 每批 %d 个, deadline %d 分钟',
                        len(ups), _BATCH_SIZE, _deadline_minutes)

            with _circuit_lock:
                if time.time() < _circuit_open_until:
                    remaining = int(_circuit_open_until - time.time()) // 60
                    logger.warning('B站 每日刷新取消: 全局熔断中，剩余 %d 分钟', remaining)
                    return

            THREAD_TIMEOUT = int(os.environ.get('BILI_SCRAPE_TIMEOUT', '900'))  # 每个线程最长等待时间（默认 15 分钟）

            # 筛选出当前不在运行中的 UP 主
            # 注意：不在 run_daily_scrape 中 add _scrape_running，
            # 由 _run_scrape 的重入保护自行管理 add/discard，
            # 否则 _run_scrape 检测到 mid in _scrape_running 会直接 return，
            # 且 return 在 try/finally 之外导致 mid 永久锁定。
            active: list = []
            for up in ups:
                mid = up.mid
                with _scrape_lock:
                    if mid in _scrape_running or mid in _incremental_running:
                        continue
                    _scrape_progress[mid] = []
                active.append(up)

            # 分批并发执行：每批 _BATCH_SIZE 个线程同时运行。
            # 硬 deadline：到达后不再启动新批次（已在批内的线程让其自然收尾）。
            for i in range(0, len(active), _BATCH_SIZE):
                if time.time() >= _deadline_ts:
                    logger.warning('B站 每日刷新达到硬 deadline（%d 分钟），不再启动新批次（剩余 %d 个 UP）',
                                   _deadline_minutes, len(active) - i)
                    break
                batch = active[i : i + _BATCH_SIZE]
                thread_mids: list[tuple[threading.Thread, int]] = []
                for up in batch:
                    t = threading.Thread(
                        target=_run_scrape,
                        args=(up.mid, up.space_url, app),
                        kwargs={'max_videos': 30},
                        daemon=True,
                    )
                    t.start()
                    thread_mids.append((t, up.mid))
                    time.sleep(random.uniform(0.5, 2.0))  # 错开启动时间
                # 等待该批所有线程完成（或超时）
                for t, mid in thread_mids:
                    t.join(timeout=THREAD_TIMEOUT)
                    if t.is_alive():
                        with _scrape_lock:
                            _scrape_running.discard(mid)
                            _scrape_progress.pop(mid, None)
                        logger.warning(
                            'B站 每日刷新: mid=%d 线程超时 (>%ds)，已清理运行状态',
                            mid, THREAD_TIMEOUT
                        )

            logger.info('B站 每日刷新完成')
        finally:
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


    cutoff = now_cst() - datetime.timedelta(days=days)
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
        try:
            from blog.models import BiliCleanupConfig, db as _db

            cfg = BiliCleanupConfig.query.first()
            if cfg and cfg.enabled:
                deleted = cleanup_old_history(days=cfg.days)
                if deleted:
                    logger.info('自动清理完成: 删除了 %d 条 %d 天前的记录', deleted, cfg.days)
                return deleted
        finally:
            _db.session.remove()
    return 0
