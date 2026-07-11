"""Bilibili 公开页面路由"""
import logging

from flask import Blueprint, render_template, request, abort

from blog.models import BiliUp, BiliUpHistory, BiliVideo, BiliVideoHistory, db

logger = logging.getLogger(__name__)

bili_public_bp = Blueprint('bili_public', __name__, url_prefix='/bilibili')


@bili_public_bp.route('/')
def index():
    """公开的 UP 主列表页 / 全局搜索"""
    page = request.args.get('page', 1, type=int)
    per_page = 20
    q = request.args.get('q', '').strip()

    if q:
        # 统一搜索：同时匹配 UP 主和视频
        ups = BiliUp.query.filter(
            db.or_(BiliUp.name.contains(q), BiliUp.mid.cast(db.String).contains(q))
        ).all()
        videos = BiliVideo.query.filter(BiliVideo.title.contains(q))\
            .order_by(BiliVideo.pubdate.desc()).all()
        up_ids = {v.up_id for v in videos}
        up_map = {u.id: u for u in BiliUp.query.filter(BiliUp.id.in_(up_ids)).all()}
        return render_template('bilibili.html', ups=ups, videos=videos,
                               q=q, total=len(ups) + len(videos), up_map=up_map)
    else:
        # 无搜索：显示所有 UP 主
        pagination = BiliUp.query.order_by(BiliUp.follower_count.desc())\
            .paginate(page=page, per_page=per_page, error_out=False)
        return render_template('bilibili.html', pagination=pagination, q='')


@bili_public_bp.route('/up/<int:up_id>')
def up_videos(up_id):
    """公开的 UP 主视频列表（支持搜索）"""
    up = BiliUp.query.get_or_404(up_id)
    page = request.args.get('page', 1, type=int)
    per_page = 30
    q = request.args.get('q', '').strip()

    query = BiliVideo.query.filter_by(up_id=up_id)
    if q:
        query = query.filter(BiliVideo.title.contains(q))
    pagination = query.order_by(BiliVideo.pubdate.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)
    # 粉丝数变化历史（最近 40 条 + JSON 供图表）
    import json
    follower_history = BiliUpHistory.query.filter_by(up_id=up_id)\
        .order_by(BiliUpHistory.recorded_at.desc()).limit(300).all()
    follower_history.reverse()
    follower_chart_data = json.dumps([
        {'t': h.recorded_at.strftime('%m/%d %H:%M'), 'v': h.follower_count}
        for h in follower_history
    ])
    return render_template('bilibili_up.html', up=up, pagination=pagination, q=q,
                           follower_history=follower_history,
                           follower_chart_data=follower_chart_data)


@bili_public_bp.route('/video/<int:video_id>')
def video_detail(video_id):
    """视频详情页"""
    video = BiliVideo.query.get_or_404(video_id)
    up = BiliUp.query.get_or_404(video.up_id)
    # 播放量变化历史（最近 300 条 + JSON 供图表）
    import json
    view_history = BiliVideoHistory.query.filter_by(video_id=video_id)\
        .order_by(BiliVideoHistory.recorded_at.desc()).limit(300).all()
    view_history.reverse()
    view_chart_data = json.dumps([
        {'t': h.recorded_at.strftime('%m/%d %H:%M'), 'v': h.view_count}
        for h in view_history
    ])
    return render_template('bilibili_video.html', video=video, up=up,
                           view_history=view_history,
                           view_chart_data=view_chart_data)
