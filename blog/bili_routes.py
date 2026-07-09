"""Bilibili 后台管理路由"""
import logging
import threading

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
    from blog.bilibili.bili_api import is_logged_in
    apply_cookies()
    logged_in = is_logged_in()
    return render_template('admin/bili_index.html', ups=ups, bili_logged_in=logged_in)


# ── B站 扫码登录 ────────────────────────────────

@bili_bp.route('/qr-gen')
@login_required
def qr_generate():
    """生成登录二维码（含 base64 图片）"""
    import io, base64
    from blog.bilibili.login import generate_qr
    try:
        data = generate_qr()
        # 用 qrcode 库生成 base64 PNG
        import qrcode
        img = qrcode.make(data['url'])
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        b64 = base64.b64encode(buf.getvalue()).decode()
        return {'ok': True, 'qrcode_key': data['qrcode_key'], 'img': 'data:image/png;base64,' + b64}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@bili_bp.route('/qr-poll')
@login_required
def qr_poll():
    """轮询扫码状态"""
    import json
    qrcode_key = request.args.get('key', '')
    if not qrcode_key:
        return {'ok': False, 'error': 'missing key'}

    from blog.bilibili.login import poll_qr, parse_cookies_from_url, fetch_cookies_via_redirect, save_cookies
    from blog.bilibili.bili_api import set_cookies
    try:
        result = poll_qr(qrcode_key)
        data = result.get('data', {})
        code = data.get('code', -1)

        if code == 0:  # 登录成功
            redirect_url = data.get('url', '')
            cookie_str = parse_cookies_from_url(redirect_url)
            if not cookie_str:
                cookie_str = fetch_cookies_via_redirect(redirect_url)
            if cookie_str:
                set_cookies(cookie_str)
                save_cookies(cookie_str)
                return {'ok': True, 'status': 'success', 'msg': '登录成功'}
            return {'ok': True, 'status': 'success', 'msg': '登录成功但无法获取Cookie'}
        elif code == 86090:
            return {'ok': True, 'status': 'scanned', 'msg': '已扫码，请在手机上确认'}
        elif code == 86101:
            return {'ok': True, 'status': 'waiting', 'msg': '等待扫码'}
        elif code == 86038:
            return {'ok': True, 'status': 'expired', 'msg': '二维码已过期'}
        return {'ok': True, 'status': 'unknown', 'code': code}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@bili_bp.route('/logout-bili', methods=['POST'])
@login_required
def logout_bili():
    """清除 B站 Cookie"""
    import os
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
    t = threading.Thread(target=_run_scrape, args=(up.mid, up.space_url, app), daemon=True)
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


@bili_bp.route('/scrape', methods=['GET'])
@login_required
def scrape_page():
    """爬取管理页面（原 index 也保留本页，但此处用于 Ajax 调试）"""
    return redirect(url_for('bili.index'))


def _run_scrape(mid: int, space_url: str, app):
    """后台爬取线程"""
    prog = _scrape_progress.get(mid, [])
    def emit(line: str):
        prog.append(f'[{time.strftime("%H:%M:%S")}] {line}')
        logger.info('%s', line)

    with app.app_context():
        try:
            from blog.bilibili.bili_api import get_video_list, get_video_stat
            import time

            emit('初始化数据库...')
            # 确保 UP 主存在 + 获取 UP 主信息
            from blog.bilibili.bili_api import get_video_list, get_video_stat, get_user_info
            import time

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

            # 爬取视频列表
            count = 0
            for idx, video_info in enumerate(get_video_list(mid), start=1):
                    bvid = video_info['bvid']
                    exists = BiliVideo.query.filter_by(bvid=bvid).first()
                    if exists:
                        continue

                    # 获取详细统计（带随机延迟防封）
                    try:
                        stat = get_video_stat(bvid)
                        video_info.update(stat)
                        import random
                        time.sleep(2.0 + random.random() * 2.0)
                    except Exception:
                        time.sleep(4.0)

                    video = BiliVideo(up_id=up.id, **video_info)
                    db.session.add(video)
                    db.session.commit()
                    # 记录视频数据历史快照
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

                    title = (video_info.get('title') or '')[:30]
                    emit(
                        f'[{idx}] {title} | '
                        f'播放: {video_info.get("view_count", "?"):,} | '
                        f'点赞: {video_info.get("like_count", "?"):,} | '
                        f'投币: {video_info.get("coin_count", "?"):,} | '
                        f'收藏: {video_info.get("favorite_count", "?"):,} | '
                        f'转发: {video_info.get("share_count", "?"):,} | '
                        f'评论: {video_info.get("comment_count", "?"):,}'
                    )

            up.video_count = BiliVideo.query.filter_by(up_id=up.id).count()
            db.session.commit()
            emit(f'爬取完成，共获取 {count} 个视频数据')

        except Exception as e:
                emit(f'爬取失败: {e}')
                logger.error('爬取失败: %s', e)
        finally:
            _scrape_running.discard(mid)
