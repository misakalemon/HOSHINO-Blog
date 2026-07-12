"""Bilibili 管理路由 — UP 主管理 / 爬取调度 / 扫码登录

爬取架构概要：
  增量检查（每 30min）→ _check_new_videos
    arc/search 翻前 10 页 + 动态流兜底 + 最新 3 视频跟踪
  每日深扫（02:00）    → _run_scrape
    补全缺失视频 + 动态流兜底 + Hot/Warm/Cold 三层统计更新
  手动刷新             → refresh_up / refresh_up_all → _run_scrape

线程安全：
  _scrape_running / _incremental_running / _scrape_progress
  三者受 _scrape_lock 保护，深扫与增量可并行但同一 UP 互斥。
"""
import json
import logging
import os
import random
import threading
import time

from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, url_for)
from flask_login import login_required

from blog.models import BiliUp, BiliUpHistory, BiliVideo, BiliVideoHistory, db
from .admin import editor_required

logger = logging.getLogger(__name__)

bili_bp = Blueprint('bili', __name__, url_prefix='/admin/bilibili')


@bili_bp.route('/')
@editor_required
def index():
    """UP 主管理列表"""
    ups = BiliUp.query.order_by(BiliUp.updated_at.desc()).all()
    # 检查 B站 登录状态
    from blog.bilibili.login import apply_cookies
    logged_in = apply_cookies()
    return render_template('admin/bili_index.html', ups=ups, bili_logged_in=logged_in)


# ── B站 扫码登录 ────────────────────────────────

@bili_bp.route('/qr-gen')
@editor_required
def qr_generate():
    """生成登录二维码（使用官方库，含 base64 图片）"""
    from blog.bilibili.login import generate_qr_v2
    try:
        data = generate_qr_v2()
        return {'ok': True, 'qrcode_key': data['qrcode_key'], 'img': data['img']}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@bili_bp.route('/qr-poll')
@editor_required
def qr_poll():
    """轮询扫码状态（使用官方库）"""
    qrcode_key = request.args.get('key', '')
    if not qrcode_key:
        return {'ok': False, 'error': 'missing key'}

    from blog.bilibili.login import poll_qr_v2
    return poll_qr_v2(qrcode_key)


@bili_bp.route('/logout-bili', methods=['POST'])
@editor_required
def logout_bili():
    """清除 B站 Cookie"""
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
    """查看单个 UP 主的视频列表"""
    page = request.args.get('page', 1, type=int)
    per_page = 30
    up = BiliUp.query.get_or_404(up_id)
    pagination = BiliVideo.query.filter_by(up_id=up_id)\
        .order_by(BiliVideo.pubdate.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)
    return render_template('admin/bili_videos.html', up=up, pagination=pagination)


@bili_bp.route('/refresh/<int:up_id>', methods=['POST'])
@editor_required
def refresh_up(up_id):
    """重新爬取单个 UP 主的数据"""
    up = BiliUp.query.get_or_404(up_id)
    # 检查是否正在爬取
    with _scrape_lock:
        if up.mid in _scrape_running:
            flash('该 UP 主正在爬取中', 'error')
            return redirect(url_for('bili.up_detail', up_id=up_id))
        _scrape_progress[up.mid] = []
        _scrape_running.add(up.mid)
    app = current_app._get_current_object()
    t = threading.Thread(target=_run_scrape, args=(up.mid, up.space_url, app), kwargs={'max_videos': 30}, daemon=True)
    t.start()
    flash(f'已开始刷新「{up.name or up.mid}」的数据', 'success')
    return redirect(url_for('bili.up_detail', up_id=up_id))


@bili_bp.route('/refresh-all/<int:up_id>', methods=['POST'])
@editor_required
def refresh_up_all(up_id):
    """重新爬取单个 UP 主的所有视频数据（无配额限制）"""
    up = BiliUp.query.get_or_404(up_id)
    with _scrape_lock:
        if up.mid in _scrape_running:
            flash('该 UP 主正在爬取中', 'error')
            return redirect(url_for('bili.up_detail', up_id=up_id))
        _scrape_progress[up.mid] = []
        _scrape_running.add(up.mid)
    app = current_app._get_current_object()
    t = threading.Thread(target=_run_scrape, args=(up.mid, up.space_url, app), kwargs={'force': True}, daemon=True)
    t.start()
    flash(f'已开始强制刷新「{up.name or up.mid}」的所有视频', 'success')
    return redirect(url_for('bili.up_detail', up_id=up_id))


@bili_bp.route('/delete/<int:up_id>', methods=['POST'])
@editor_required
def delete_up(up_id):
    """删除 UP 主及其所有视频数据"""
    up = BiliUp.query.get_or_404(up_id)
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
    """删除单条视频记录"""
    video = BiliVideo.query.get_or_404(video_id)
    up_id = video.up_id
    db.session.delete(video)
    db.session.commit()
    flash(f'已删除视频 {video.bvid}', 'success')
    return redirect(url_for('bili.up_detail', up_id=up_id))


@bili_bp.route('/check-missing')
@editor_required
def check_missing():
    """检查所有 UP 主视频是否有遗漏（对比 API video_count 与 DB 实际数）"""
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
            results.append(dict(
                name=up.name, mid=up.mid, up_id=up.id,
                db=db_count, api='?', missing='?',
                percent='-', error=str(e),
            ))
            continue

        if api_count > 0:
            missing = max(0, api_count - db_count)
            pct = f'{db_count / api_count * 100:.1f}%'
        else:
            missing = '?'
            pct = '-'
        results.append(dict(
            name=up.name, mid=up.mid, up_id=up.id,
            db=db_count, api=api_count,
            missing=missing, percent=pct, error=None,
        ))

    return {'ok': True, 'results': results, 'total': len(results)}


# ── 爬取任务共享状态 ────────────────────────────
# 深扫运行中的 mid（每日刷新 / 手动触发）
_scrape_running: set[int] = set()
# 增量检查运行中的 mid（与深扫互斥：启动前同时检查两者）
_incremental_running: set[int] = set()
# 实时爬取日志 {mid: [str, ...]} 供 AJAX scrape-status 轮询
_scrape_progress: dict[int, list[str]] = {}
# 上述三个共享状态的互斥锁
_scrape_lock = threading.Lock()
# 每视频请求后的睡眠（防风控）— BASE + [0, JITTER) 秒
_VIDEO_SLEEP_BASE = 7.0
_VIDEO_SLEEP_JITTER = 3.0


def _check_new_videos(mid: int, app):
    """增量检查 — 每 30 分钟执行，只发现新视频。

    流程：
      1. 加载 DB 已知 bvid/aid 集合
      2. arc/search 翻前 10 页（按 pubdate 倒序，最多 150 条）
         → 已知跳过，新视频入库 + 写 BiliVideoHistory
      3. 动态流兜底（始终执行，捕获 shorts/短视频）
         → 同上过滤 + 入库
      4. 追踪最新 3 个视频的统计数据（30min 快照）
    """
    with _scrape_lock:
        prog = _scrape_progress.get(mid, [])
    _up_name = ['?']
    def emit(line: str):
        prog.append(f'[{time.strftime("%H:%M:%S")}] [{_up_name[0]}] {line}')
        logger.info('[%s] %s', _up_name[0], line)

    with app.app_context():
        try:
            import datetime
            import time
            from blog.bilibili.bili_api import get_video_list, get_video_stat

            up = BiliUp.query.filter_by(mid=mid).first()
            if not up:
                return
            _up_name[0] = up.name or str(mid)

            # 取数据库已有的 bvid 和 aid 集合
            existing_bvids = {r[0] for r in BiliVideo.query.with_entities(BiliVideo.bvid).filter_by(up_id=up.id).all()}
            existing_aids = {r[0] for r in BiliVideo.query.with_entities(BiliVideo.aid).filter_by(up_id=up.id).all()}

            count = 0
            for video_info in get_video_list(mid, max_pages=10):
                bvid = video_info['bvid']
                aid = video_info['aid']
                title_short = (video_info.get('title') or '')[:30]
                is_known = bvid in existing_bvids or aid in existing_aids
                logger.info("增量检查: bvid=%s aid=%s title=%s known=%s",
                            bvid, aid, title_short, is_known)
                if is_known:
                    continue

                try:
                    stat = get_video_stat(bvid)
                    video_info.update(stat)
                    time.sleep(_VIDEO_SLEEP_BASE + random.random() * _VIDEO_SLEEP_JITTER)
                except Exception as e:
                    logger.warning("视频 %s 统计获取失败: %s", bvid, e)
                    time.sleep(12.0)
                    continue

                try:
                    video = BiliVideo(up_id=up.id, **video_info)
                    db.session.add(video)
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    logger.warning("视频 %s 入库失败（可能重复）: %s", bvid, e)
                    continue

                try:
                    db.session.add(BiliVideoHistory(
                        video_id=video.id,
                        view_count=video_info.get('view_count', 0),
                        like_count=video_info.get('like_count', 0),
                        coin_count=video_info.get('coin_count', 0),
                        favorite_count=video_info.get('favorite_count', 0),
                        share_count=video_info.get('share_count', 0),
                        comment_count=video_info.get('comment_count', 0),
                        danmaku_count=video_info.get('danmaku_count', 0),
                    ))
                    db.session.commit()
                except Exception:
                    db.session.rollback()

                count += 1
                existing_bvids.add(bvid)
                existing_aids.add(aid)
                title_short = (video_info.get('title') or '')[:30]
                emit(f'发现新视频 [{count}] {title_short}')

            # 动态发现兜底：arc/search 可能遗漏 shorts/新视频
            from blog.bilibili.bili_api import get_video_list_from_dynamics
            try:
                dyn_videos = get_video_list_from_dynamics(mid)
            except Exception as e:
                logger.warning("动态发现失败 mid=%d: %s", mid, e)
                dyn_videos = []
            for video_info in dyn_videos:
                bvid = video_info['bvid']
                aid = video_info['aid']
                title_short = (video_info.get('title') or '')[:30]
                if bvid in existing_bvids or aid in existing_aids:
                    continue
                try:
                    video = BiliVideo(up_id=up.id, **video_info)
                    db.session.add(video)
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    logger.warning("动态视频 %s 入库失败: %s", bvid, e)
                    continue
                try:
                    db.session.add(BiliVideoHistory(
                        video_id=video.id,
                        view_count=video_info.get('view_count', 0),
                        like_count=video_info.get('like_count', 0),
                        coin_count=video_info.get('coin_count', 0),
                        favorite_count=video_info.get('favorite_count', 0),
                        share_count=video_info.get('share_count', 0),
                        comment_count=video_info.get('comment_count', 0),
                        danmaku_count=video_info.get('danmaku_count', 0),
                    ))
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                count += 1
                existing_bvids.add(bvid)
                existing_aids.add(aid)
                emit(f'[动态发现] 新视频 [{count}] {title_short}')
            if dyn_videos:
                emit(f'动态发现完成，共扫描 {len(dyn_videos)} 个视频')

            up.video_count = BiliVideo.query.filter_by(up_id=up.id).count()
            db.session.commit()
            if count:
                emit(f'增量完成，新增 {count} 个视频')

            # ── 追踪最新 3 个视频的统计（每 30 分钟快照）──
            try:
                latest = BiliVideo.query.filter_by(up_id=up.id)\
                    .order_by(BiliVideo.pubdate.desc()).limit(3).all()
                if latest:
                    emit(f'追踪最新 {len(latest)} 个视频统计')
                for v in latest:
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
                    db.session.commit()
                    db.session.add(BiliVideoHistory(
                        video_id=v.id,
                        view_count=stat.get('view_count', 0),
                        like_count=stat.get('like_count', 0),
                        coin_count=stat.get('coin_count', 0),
                        favorite_count=stat.get('favorite_count', 0),
                        share_count=stat.get('share_count', 0),
                        comment_count=stat.get('comment_count', 0),
                        danmaku_count=stat.get('danmaku_count', 0),
                    ))
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
                    emit(f'  播放:{nv:,}(+{nv-old_view:,})  点赞:{nl:,}(+{nl-old_like:,})  投币:{nc:,}(+{nc-old_coin:,})  收藏:{nf:,}(+{nf-old_fav:,})')
                    emit(f'  转发:{ns:,}(+{ns-old_share:,})  评论:{ncm:,}(+{ncm-old_comment:,})  弹幕:{nd:,}(+{nd-old_danmaku:,})')
                    time.sleep(_VIDEO_SLEEP_BASE + random.random() * _VIDEO_SLEEP_JITTER)
            except Exception as e:
                logger.error('最新视频追踪失败 mid=%d: %s', mid, e)
        except Exception as e:
            logger.error('增量检查失败 mid=%d: %s', mid, e)
        finally:
            with _scrape_lock:
                _incremental_running.discard(mid)
                _scrape_progress.pop(mid, None)
            db.session.remove()


@bili_bp.route('/scrape-status')
@editor_required
def scrape_status():
    """返回爬取进度（JSON）"""
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
    """启动爬取任务"""
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

    流程：
      A. 获取/更新 UP 主信息（名称/头像/粉丝数）
      B. 补全缺失视频（should_fill=True 时）
         → arc/search 翻全量，已知跳过，新视频入库 + BiliVideoHistory
      C. 动态流兜底（始终执行，不受 should_fill 影响）
      D. 三层统计更新（Hot ≤7d / Warm 8~30d / Cold >30d）
         → 跳过本次新入库的视频（fill_new_bvids）
         → 新视频每个 7~10s 间隔，防风控 + 指数退避重试
         → max_videos 控制总更新数上限

    Args:
        mid:         B站 mid
        space_url:   空间页链接
        app:         Flask app 实例（线程内 app_context 用）
        max_videos:  最多更新视频数，None=不限
        force:       True 时跳过 should_fill 条件，强制翻全量；跳过 age 检查
    """
    prog = _scrape_progress.get(mid, [])
    _up_name = ['?']
    def emit(line: str):
        prog.append(f'[{time.strftime("%H:%M:%S")}] [{_up_name[0]}] {line}')
        logger.info('[%s] %s', _up_name[0], line)

    with app.app_context():
        try:
            import datetime
            import time
            from blog.bilibili.bili_api import _is_risk_control, get_video_stat, get_user_info

            up = BiliUp.query.filter_by(mid=mid).first()
            total_in_api = None
            try:
                ui = get_user_info(mid)
                total_in_api = ui.get('video_count', 0)
                if up:
                    up.name = ui.get('name', up.name)
                    up.avatar = ui.get('avatar', up.avatar)
                    up.follower_count = ui.get('follower_count', 0)
                else:
                    up = BiliUp(
                        mid=mid, space_url=space_url,
                        name=ui.get('name', ''),
                        avatar=ui.get('avatar', ''),
                        follower_count=ui.get('follower_count', 0),
                    )
                    db.session.add(up)
                db.session.commit()
                try:
                    db.session.add(BiliUpHistory(up_id=up.id, follower_count=up.follower_count))
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                _up_name[0] = ui.get('name', str(mid))
                emit(f'UP主信息  |  粉丝: {ui.get("follower_count", 0):,}  |  视频总数: {ui.get("video_count", 0)}')
            except Exception as e:
                emit(f'获取 UP 主信息失败: {e}')
                if not up:
                    up = BiliUp(mid=mid, space_url=space_url)
                    db.session.add(up)
                    db.session.commit()
                _up_name[0] = up.name or str(mid)

            emit('初始化数据库...')

            # 检查是否有视频未入库，从 API 补全
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
            existing_ids = {
                r[0] for r in BiliVideo.query.with_entities(BiliVideo.bvid).filter_by(up_id=up.id).all()
            }
            existing_aids = {
                r[0] for r in BiliVideo.query.with_entities(BiliVideo.aid).filter_by(up_id=up.id).all()
            }
            if should_fill:
                from blog.bilibili.bili_api import get_video_list as _get_video_list
                need = (total_in_api - total_in_db) if total_in_api > 0 else -1
                if need > 0:
                    emit(f'[补全] 发现 {need} 个缺失视频，开始补齐...')
                else:
                    emit(f'[补全] DB 有 {total_in_db} 个视频，开始从 API 补齐...')

                for video_info in _get_video_list(mid):
                        bvid = video_info['bvid']
                        aid = video_info['aid']
                        title_short = (video_info.get('title') or '')[:30]
                        is_known = bvid in existing_ids or aid in existing_aids
                        logger.info("补全循环: bvid=%s title=%s known=%s", bvid, title_short, is_known)
                        if is_known:
                            continue
                        try:
                            stat = get_video_stat(bvid)
                            video_info.update(stat)
                            time.sleep(_VIDEO_SLEEP_BASE + random.random() * _VIDEO_SLEEP_JITTER)
                        except Exception:
                            logger.warning("视频 %s 「%s」补全时统计获取失败", bvid, title_short)
                            time.sleep(12.0)
                            continue
                        try:
                            video = BiliVideo(up_id=up.id, **video_info)
                            db.session.add(video)
                            db.session.commit()
                        except Exception as e:
                            db.session.rollback()
                            logger.warning("视频 %s 「%s」入库失败: %s", bvid, title_short, e)
                            continue
                        try:
                            db.session.add(BiliVideoHistory(
                                video_id=video.id,
                                view_count=video_info.get('view_count', 0),
                                like_count=video_info.get('like_count', 0),
                                coin_count=video_info.get('coin_count', 0),
                                favorite_count=video_info.get('favorite_count', 0),
                                share_count=video_info.get('share_count', 0),
                                comment_count=video_info.get('comment_count', 0),
                                danmaku_count=video_info.get('danmaku_count', 0),
                            ))
                            db.session.commit()
                        except Exception:
                            db.session.rollback()
                        fill_count += 1
                        existing_ids.add(bvid)
                        existing_aids.add(aid)
                        fill_new_bvids.add(bvid)
                        emit(f'[补全] ({fill_count}) 「{title_short}」')
                        if need > 0 and fill_count >= need:
                            break

            # 动态发现兜底：始终执行，捕获 arc/search 可能遗漏的 shorts/新视频
            from blog.bilibili.bili_api import get_video_list_from_dynamics
            try:
                dyn_videos = get_video_list_from_dynamics(mid)
            except Exception as e:
                logger.warning("补全动态发现失败 mid=%d: %s", mid, e)
                dyn_videos = []
            for video_info in dyn_videos:
                bvid = video_info['bvid']
                aid = video_info['aid']
                title_short = (video_info.get('title') or '')[:30]
                if bvid in existing_ids or aid in existing_aids:
                    continue
                try:
                    video = BiliVideo(up_id=up.id, **video_info)
                    db.session.add(video)
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    logger.warning("补全动态视频 %s 入库失败: %s", bvid, e)
                    continue
                try:
                    db.session.add(BiliVideoHistory(
                        video_id=video.id,
                        view_count=video_info.get('view_count', 0),
                        like_count=video_info.get('like_count', 0),
                        coin_count=video_info.get('coin_count', 0),
                        favorite_count=video_info.get('favorite_count', 0),
                        share_count=video_info.get('share_count', 0),
                        comment_count=video_info.get('comment_count', 0),
                        danmaku_count=video_info.get('danmaku_count', 0),
                    ))
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                fill_count += 1
                existing_ids.add(bvid)
                existing_aids.add(aid)
                fill_new_bvids.add(bvid)
                emit(f'[补全/动态] ({fill_count}) 「{title_short}」')
            if dyn_videos:
                emit(f'补全动态扫描完成，共 {len(dyn_videos)} 个')

            if fill_count:
                emit(f'[补全] 完成，新增 {fill_count} 个视频')

            # ── 三层统计更新 ────────────────────────
            # fill_new_bvids: 本次新入库的视频 BVID — Hot 阶段排除这些（已有新鲜数据）
            filled_bvids = fill_new_bvids
            count = 0
            hot_done = 0
            warm_done = 0
            cold_done = 0
            retry_delay = 30
            now = datetime.datetime.utcnow()
            cutoff_hot = now - datetime.timedelta(days=7)
            cutoff_warm = now - datetime.timedelta(days=30)

            def _update_video(v, label='', min_age_hours=1):
                """更新单个视频的统计数据并写 BiliVideoHistory。

                Returns:
                    True  — 成功或 min-age 跳过
                    False — 风控/失败，需要外层 retry（continue 跳到下一个视频，本视频下次再试）
                """
                nonlocal count, retry_delay, hot_done, warm_done, cold_done
                bvid = v.bvid

                if not force and v.updated_at and (datetime.datetime.utcnow() - v.updated_at).total_seconds() < min_age_hours * 3600:
                    title_short = (v.title or '')[:30]
                    emit(f'  跳过「{title_short}」— 最近 {min_age_hours} 小时内已更新')
                    return True

                old_view = v.view_count or 0
                old_like = v.like_count or 0
                old_coin = v.coin_count or 0
                old_fav = v.favorite_count or 0
                old_share = v.share_count or 0
                old_comment = v.comment_count or 0
                old_danmaku = v.danmaku_count or 0

                try:
                    stat = get_video_stat(bvid)
                    retry_delay = 30
                    time.sleep(_VIDEO_SLEEP_BASE + random.random() * _VIDEO_SLEEP_JITTER)
                except Exception as e:
                    if _is_risk_control(e):
                        logger.warning("触发风控，等待 %ds 后重试...", retry_delay)
                        time.sleep(retry_delay)
                        retry_delay = min(retry_delay * 2, 600)
                        return False
                    logger.warning("视频 %s 统计获取失败: %s", bvid, e)
                    time.sleep(8.0)
                    return False

                for key, val in stat.items():
                    setattr(v, key, val)
                v.updated_at = datetime.datetime.utcnow()
                db.session.commit()
                count += 1
                if label.startswith('Hot'):
                    hot_done += 1
                elif label.startswith('Warm'):
                    warm_done += 1
                elif label.startswith('Cold'):
                    cold_done += 1

                try:
                    db.session.add(BiliVideoHistory(
                        video_id=v.id,
                        view_count=stat.get('view_count', 0),
                        like_count=stat.get('like_count', 0),
                        coin_count=stat.get('coin_count', 0),
                        favorite_count=stat.get('favorite_count', 0),
                        share_count=stat.get('share_count', 0),
                        comment_count=stat.get('comment_count', 0),
                        danmaku_count=stat.get('danmaku_count', 0),
                    ))
                    db.session.commit()
                except Exception:
                    db.session.rollback()

                title_short = (v.title or '')[:30]
                nv = stat.get('view_count', 0)
                nl = stat.get('like_count', 0)
                nc = stat.get('coin_count', 0)
                nf = stat.get('favorite_count', 0)
                ns = stat.get('share_count', 0)
                ncm = stat.get('comment_count', 0)
                nd = stat.get('danmaku_count', 0)
                emit(f'[{count}] {label}「{title_short}」')
                emit(f'  播放:{nv:,}(+{nv-old_view:,})  点赞:{nl:,}(+{nl-old_like:,})  投币:{nc:,}(+{nc-old_coin:,})  收藏:{nf:,}(+{nf-old_fav:,})')
                emit(f'  转发:{ns:,}(+{ns-old_share:,})  评论:{ncm:,}(+{ncm-old_comment:,})  弹幕:{nd:,}(+{nd-old_danmaku:,})')
                return True

            # ── Hot 阶段: ≤7 天 —— 全部更新，不跳过 ──
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

            # Warm: 8~30天（配额未满时，最久未更新优先，1h 跳过）
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

            # Cold: >30天（配额剩余时处理，24h 跳过）
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
                    emit(f'Cold 阶段: >30天视频配额 {quota_str}（DB中共 {len(cold_videos)} 个待更新）')
                    for v in cold_videos:
                        if remaining is not None and count >= max_videos:
                            break
                        ok = _update_video(v, 'Cold', min_age_hours=24)
                        if ok is False:
                            continue
            up.video_count = BiliVideo.query.filter_by(up_id=up.id).count()
            db.session.commit()
            emit(f'刷新完成  Hot={hot_done}  Warm={warm_done}  Cold={cold_done}  共 {count} 个  |  DB 总视频数: {up.video_count}')
            if total_in_api:
                db_total = up.video_count
                if db_total >= total_in_api:
                    emit(f'完整性检查: {db_total}/{total_in_api} ✅ 全部视频已入库')
                else:
                    emit(f'完整性检查: {db_total}/{total_in_api} ⚠️ 缺失 {total_in_api - db_total} 个视频）')
            elif total_in_api is not None and total_in_api == 0 and total_in_db > 0:
                emit(f'完整性检查: Cookie 可能过期，API 返回 video_count=0')

        except Exception as e:
                emit(f'爬取失败: {e}')
                logger.exception('爬取失败 mid=%d', mid)
        finally:
            with _scrape_lock:
                _scrape_running.discard(mid)
                _scrape_progress.pop(mid, None)
            db.session.remove()
