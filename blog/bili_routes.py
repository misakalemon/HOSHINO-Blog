"""Bilibili 后台管理路由"""
import logging
import threading

from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)
from flask_login import login_required

from blog.models import BiliUp, BiliVideo, db

logger = logging.getLogger(__name__)

bili_bp = Blueprint('bili', __name__, url_prefix='/admin/bilibili')


@bili_bp.route('/')
@login_required
def index():
    """UP 主管理列表"""
    ups = BiliUp.query.order_by(BiliUp.updated_at.desc()).all()
    return render_template('admin/bili_index.html', ups=ups)


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
_scrape_lock = threading.Lock()

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

    # 在后台线程中执行爬取
    t = threading.Thread(target=_run_scrape, args=(mid, space_url), daemon=True)
    t.start()
    flash(f'已开始爬取 mid={mid} 的视频数据，请稍后刷新查看', 'success')
    return redirect(url_for('bili.index'))


def _run_scrape(mid: int, space_url: str):
    """后台爬取线程"""
    with _scrape_lock:
        try:
            from blog.bilibili.bili_api import get_video_list, get_video_stat
            import time

            # 确保 UP 主存在
            up = BiliUp.query.filter_by(mid=mid).first()
            if not up:
                up = BiliUp(mid=mid, space_url=space_url)
                db.session.add(up)
                db.session.commit()

            # 爬取视频列表
            count = 0
            for video_info in get_video_list(mid):
                bvid = video_info['bvid']
                exists = BiliVideo.query.filter_by(bvid=bvid).first()
                if exists:
                    continue

                # 获取详细统计
                try:
                    stat = get_video_stat(bvid)
                    video_info.update(stat)
                    time.sleep(1.0)
                except Exception:
                    time.sleep(2.0)

                video = BiliVideo(up_id=up.id, **video_info)
                db.session.add(video)
                db.session.commit()
                count += 1

            up.video_count = BiliVideo.query.filter_by(up_id=up.id).count()
            db.session.commit()
            logger.info('爬取完成：mid=%d, 新增 %d 个视频', mid, count)

        except Exception as e:
            logger.error('爬取失败: %s', e)
