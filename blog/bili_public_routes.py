"""Bilibili 公开页面路由"""
import logging

from flask import Blueprint, render_template, request, abort

from blog.models import BiliUp, BiliVideo

logger = logging.getLogger(__name__)

bili_public_bp = Blueprint('bili_public', __name__, url_prefix='/bilibili')


@bili_public_bp.route('/')
def index():
    """公开的 UP 主列表页"""
    ups = BiliUp.query.order_by(BiliUp.follower_count.desc()).all()
    page = request.args.get('page', 1, type=int)
    per_page = 20
    total = len(ups)
    start = (page - 1) * per_page
    end = start + per_page
    page_ups = ups[start:end]
    pages = (total + per_page - 1) // per_page
    return render_template('bilibili.html', ups=page_ups, page=page, pages=pages, total=total)


@bili_public_bp.route('/up/<int:up_id>')
def up_videos(up_id):
    """公开的 UP 主视频列表"""
    up = BiliUp.query.get_or_404(up_id)
    page = request.args.get('page', 1, type=int)
    per_page = 30
    pagination = BiliVideo.query.filter_by(up_id=up_id)\
        .order_by(BiliVideo.pubdate.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)
    return render_template('bilibili_up.html', up=up, pagination=pagination)
