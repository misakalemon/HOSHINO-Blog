"""Bilibili 后台管理路由"""
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

logger = logging.getLogger(__name__)

bili_bp = Blueprint('bili', __name__, url_prefix='/admin/bilibili')


@bili_bp.route('/')
@login_required
def index():
    """UP 主管理列表"""
    ups = BiliUp.query.order_by(BiliUp.updated_at.desc()).all()
    # 检查 B站 登录状态
    from blog.bilibili.login import apply_cookies
    logged_in = apply_cookies()
    return render_template('admin/bili_index.html', ups=ups, bili_logged_in=logged_in)


# ── B站 扫码登录 ────────────────────────────────

@bili_bp.route('/qr-gen')
@login_required
def qr_generate():
    """生成登录二维码（使用官方库，含 base64 图片）"""
    from blog.bilibili.login import generate_qr_v2
    try:
        data = generate_qr_v2()
        return {'ok': True, 'qrcode_key': data['qrcode_key'], 'img': data['img']}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@bili_bp.route('/qr-poll')
@login_required
def qr_poll():
    """轮询扫码状态（使用官方库）"""
    qrcode_key = request.args.get('key', '')
    if not qrcode_key:
        return {'ok': False, 'error': 'missing key'}

    from blog.bilibili.login import poll_qr_v2
    return poll_qr_v2(qrcode_key)


@bili_bp.route('/logout-bili', methods=['POST'])
@login_required
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
@login_required
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
@login_required
def refresh_up(up_id):
    """重新爬取单个 UP 主的数据"""
    up = BiliUp.query.get_or_404(up_id)
    # 检查是否正在爬取
    if up.mid in _scrape_running:
        flash('该 UP 主正在爬取中', 'error')
        return redirect(url_for('bili.up_detail', up_id=up_id))
    # 启动爬取
    from blog.bilibili.bili_api import extract_mid
    _scrape_progress[up.mid] = []
    _scrape_running.add(up.mid)
    app = current_app._get_current_object()
    t = threading.Thread(target=_run_scrape, args=(up.mid, up.space_url, app), kwargs={'max_videos': 30}, daemon=True)
    t.start()
    flash(f'已开始刷新「{up.name or up.mid}」的数据', 'success')
    return redirect(url_for('bili.up_detail', up_id=up_id))


@bili_bp.route('/delete/<int:up_id>', methods=['POST'])
@login_required
def delete_up(up_id):
    """删除 UP 主及其所有视频数据"""
    up = BiliUp.query.get_or_404(up_id)
    db.session.delete(up)
    db.session.commit()
    flash(f'已删除 UP 主「{up.name or up.mid}」及其视频数据', 'success')
    return redirect(url_for('bili.index'))


@bili_bp.route('/delete-video/<int:video_id>', methods=['POST'])
@login_required
def delete_video(video_id):
    """删除单条视频记录"""
    video = BiliVideo.query.get_or_404(video_id)
    up_id = video.up_id
    db.session.delete(video)
    db.session.commit()
    flash(f'已删除视频 {video.bvid}', 'success')
    return redirect(url_for('bili.up_detail', up_id=up_id))


# ── 爬取任务（后台线程）────────────────────────
# 正在爬取中的 mid 集合（防止重复爬同一个 UP 主）
_scrape_running: set[int] = set()
# 爬取进度存储 { mid: [line, line, ...] }
_scrape_progress: dict[int, list[str]] = {}


def _check_new_videos(mid: int, app):
    """轻量增量检查：只爬取数据库中还不存在的新视频"""
    prog = _scrape_progress.get(mid, [])
    def emit(line: str):
        prog.append(f'[{time.strftime("%H:%M:%S")}] {line}')
        logger.info('[增量] %s', line)

    with app.app_context():
        try:
            from blog.bilibili.bili_api import get_video_list, get_video_stat
            import time

            up = BiliUp.query.filter_by(mid=mid).first()
            if not up:
                return

            # 取数据库已有的 bvid 和 aid 集合
            existing_bvids = {r[0] for r in BiliVideo.query.with_entities(BiliVideo.bvid).filter_by(up_id=up.id).all()}
            existing_aids = {r[0] for r in BiliVideo.query.with_entities(BiliVideo.aid).filter_by(up_id=up.id).all()}

            count = 0
            for idx, video_info in enumerate(get_video_list(mid), start=1):
                bvid = video_info['bvid']
                aid = video_info['aid']
                if bvid in existing_bvids or aid in existing_aids:
                    continue  # 已有则跳过
                # 仅处理第一页（前 15 条），新视频永远在最前面
                if idx > 15:
                    emit('增量检查完成（仅检测最新 15 条）')
                    break

                # 新视频：获取详细统计
                try:
                    stat = get_video_stat(bvid)
                    video_info.update(stat)
                    time.sleep(7.0 + random.random() * 3.0)
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
                emit(f'发现新视频 [{count}] {video_info.get("title", "")[:30]}')

            up.video_count = BiliVideo.query.filter_by(up_id=up.id).count()
            db.session.commit()
            if count:
                emit(f'增量完成，新增 {count} 个视频')
        except Exception as e:
            logger.error('增量检查失败 mid=%d: %s', mid, e)
        finally:
            _scrape_running.discard(mid)
            db.session.remove()


@bili_bp.route('/scrape-status')
@login_required
def scrape_status():
    """返回爬取进度（JSON）"""
    mid = request.args.get('mid', type=int)
    if not mid:
        return {'running': False, 'lines': []}
    from copy import deepcopy
    lines = deepcopy(_scrape_progress.get(mid, []))
    # 检查是否还在运行
    running = any('爬取完成' not in l and '爬取中断' not in l for l in lines[-3:]) if lines else False
    return {'running': running, 'lines': lines}


@bili_bp.route('/scrape', methods=['POST'])
@login_required
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

    # 初始化进度存储
    _scrape_progress[mid] = []

    # 检查是否已在爬取
    if mid in _scrape_running:
        return {'ok': False, 'error': '该 UP 主正在爬取中，请等待完成'}
    _scrape_running.add(mid)

    # 在后台线程中执行爬取（传入 app 实例以建立应用上下文）
    app = current_app._get_current_object()
    t = threading.Thread(target=_run_scrape, args=(mid, space_url, app), daemon=True)
    t.start()
    return {'ok': True, 'mid': mid}


def _run_scrape(mid: int, space_url: str, app, max_videos: int | None = None):
    """后台爬取线程
    
    Args:
        mid: B站 mid
        space_url: UP 主空间链接
        app: Flask 应用实例
        max_videos: 最多爬取视频数，None 表示全部
    """
    prog = _scrape_progress.get(mid, [])
    def emit(line: str):
        prog.append(f'[{time.strftime("%H:%M:%S")}] {line}')
        logger.info('%s', line)

    with app.app_context():
        try:
            from blog.bilibili.bili_api import get_video_list, get_video_stat, get_user_info

            emit('初始化数据库...')
            # 确保 UP 主存在 + 获取 UP 主信息

            up = BiliUp.query.filter_by(mid=mid).first()
            try:
                ui = get_user_info(mid)
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
                # 记录粉丝数历史快照
                try:
                    db.session.add(BiliUpHistory(up_id=up.id, follower_count=up.follower_count))
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                emit(f'UP 主: {ui.get("name", "?")}  |  粉丝: {ui.get("follower_count", 0):,}  |  视频: {ui.get("video_count", 0)}')
            except Exception as e:
                emit(f'获取 UP 主信息失败: {e}')
                if not up:
                    up = BiliUp(mid=mid, space_url=space_url)
                    db.session.add(up)
                    db.session.commit()

            # 爬取视频列表（优先级分层：P0新视频→P1轮转）
            import datetime
            count = 0
            processed_bvids = set()
            retry_delay = 30  # 指数退避起始值（秒）
            from blog.bilibili.bili_api import _is_risk_control
            now = datetime.datetime.utcnow()
            cutoff_p0 = now - datetime.timedelta(days=3)
            cutoff_p1 = now - datetime.timedelta(days=30)

            def _process_video(video_info, api_label=''):
                nonlocal count, retry_delay
                bvid = video_info['bvid']
                if bvid in processed_bvids:
                    return True
                processed_bvids.add(bvid)
                try:
                    stat = get_video_stat(bvid)
                    video_info.update(stat)
                    retry_delay = 30
                    time.sleep(7.0 + random.random() * 3.0)
                except Exception as e:
                    if _is_risk_control(e):
                        logger.warning("触发风控，等待 %ds 后重试...", retry_delay)
                        time.sleep(retry_delay)
                        retry_delay = min(retry_delay * 2, 600)
                        return False
                    logger.warning("视频 %s 统计获取失败: %s", bvid, e)
                    time.sleep(12.0)
                    return True
                exists = BiliVideo.query.filter_by(bvid=bvid).first()
                if exists:
                    for key, value in video_info.items():
                        setattr(exists, key, value)
                    video = exists
                    db.session.commit()
                else:
                    video = BiliVideo(up_id=up.id, **video_info)
                    db.session.add(video)
                    db.session.commit()
                count += 1
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
                title = (video_info.get('title') or '')[:30]
                emit(f'[{count}] {api_label}{title} | 播放: {video_info.get("view_count", "?"):,}')
                return True

            # Phase 1: API 新视频（P0 ≤3天优先）
            for video_info in get_video_list(mid):
                pubdate_ts = video_info.get('pubdate', 0)
                pub_dt = datetime.datetime.fromtimestamp(pubdate_ts, tz=datetime.timezone.utc).replace(tzinfo=None) if pubdate_ts else None
                if max_videos is not None:
                    if pub_dt and pub_dt >= cutoff_p0:
                        if count >= max_videos:
                            break
                        ok = _process_video(video_info, 'P0 ')
                        if ok is False:
                            continue
                else:
                    ok = _process_video(video_info)
                    if ok is False:
                        continue

            # Phase 2: 配额未满时补 P1（3~30天，最久未更新优先）
            if max_videos is not None and count < max_videos:
                remaining = max_videos - count
                stale_videos = BiliVideo.query.filter(
                    BiliVideo.up_id == up.id,
                    BiliVideo.pub_datetime >= cutoff_p1,
                    BiliVideo.pub_datetime < cutoff_p0,
                ).order_by(BiliVideo.updated_at.asc()).limit(remaining).all()
                for v in stale_videos:
                    api_info = {'bvid': v.bvid, 'aid': v.aid, 'title': v.title,
                                'description': v.description, 'duration': v.duration,
                                'pubdate': v.pubdate, 'pub_date': v.pub_date, 'pub_datetime': v.pub_datetime}
                    try:
                        stat = get_video_stat(v.bvid)
                        api_info.update(stat)
                        retry_delay = 30
                        time.sleep(7.0 + random.random() * 3.0)
                    except Exception as e:
                        if _is_risk_control(e):
                            logger.warning("触发风控，等待 %ds 后重试...", retry_delay)
                            time.sleep(retry_delay)
                            retry_delay = min(retry_delay * 2, 600)
                            continue
                        logger.warning("视频 %s 统计获取失败: %s", v.bvid, e)
                        time.sleep(12.0)
                        continue
                    for key, value in api_info.items():
                        setattr(v, key, value)
                    db.session.commit()
                    count += 1
                    processed_bvids.add(v.bvid)
                    try:
                        db.session.add(BiliVideoHistory(video_id=v.id,
                            view_count=api_info.get('view_count', 0),
                            like_count=api_info.get('like_count', 0),
                            coin_count=api_info.get('coin_count', 0),
                            favorite_count=api_info.get('favorite_count', 0),
                            share_count=api_info.get('share_count', 0),
                            comment_count=api_info.get('comment_count', 0),
                            danmaku_count=api_info.get('danmaku_count', 0),
                        ))
                        db.session.commit()
                    except Exception:
                        db.session.rollback()
                    title = (api_info.get('title') or '')[:30]
                    emit(f'[{count}] P1 {title} | 播放: {api_info.get("view_count", "?"):,}')

            if max_videos is not None:
                emit(f'本轮刷新完成，共处理 {count} 个视频')

            up.video_count = BiliVideo.query.filter_by(up_id=up.id).count()
            db.session.commit()
            emit(f'爬取完成，共获取 {count} 个视频数据')

        except Exception as e:
                emit(f'爬取失败: {e}')
                logger.error('爬取失败: %s', e)
        finally:
            _scrape_running.discard(mid)
            db.session.remove()
