"""Bilibili 公开页面路由"""
import logging
import secrets

from flask import Blueprint, jsonify, render_template, request, url_for

from blog.models import BiliSubscription, BiliUp, BiliUpHistory, BiliVideo, BiliVideoHistory, db

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
    """视频详情页 — 多指标折线图（点击卡片开关曲线）"""
    video = BiliVideo.query.get_or_404(video_id)
    up = BiliUp.query.get_or_404(video.up_id)
    import json
    history = BiliVideoHistory.query.filter_by(video_id=video_id)\
        .order_by(BiliVideoHistory.recorded_at.desc()).limit(300).all()
    history.reverse()
    time_labels = json.dumps([h.recorded_at.strftime('%m/%d %H:%M') for h in history])
    chart_data = json.dumps({
        'view':     [h.view_count     for h in history],
        'like':     [h.like_count      for h in history],
        'coin':     [h.coin_count      for h in history],
        'favorite': [h.favorite_count  for h in history],
        'share':    [h.share_count     for h in history],
        'comment':  [h.comment_count   for h in history],
        'danmaku':  [h.danmaku_count   for h in history],
    })
    return render_template('bilibili_video.html', video=video, up=up,
                           history=history,
                           time_labels=time_labels,
                           chart_data=chart_data)


@bili_public_bp.route('/subscribe', methods=['POST'])
def subscribe():
    """订阅 UP 主新视频邮件通知

    需提供 email + up_id，创建未验证的订阅记录，
    发送验证邮件，用户点击链接确认后激活。
    """
    email = (request.form.get('email') or '').strip().lower()
    up_id = request.form.get('up_id', type=int)

    if not email or '@' not in email:
        return jsonify({'ok': False, 'error': '请输入有效的邮箱地址'}), 400
    if not up_id:
        return jsonify({'ok': False, 'error': '缺少 UP 主 ID'}), 400

    up = BiliUp.query.get(up_id)
    if not up:
        return jsonify({'ok': False, 'error': 'UP 主不存在'}), 404

    existing = BiliSubscription.query.filter_by(email=email, up_id=up_id).first()
    if existing:
        if existing.verified:
            return jsonify({'ok': False, 'error': '已订阅该 UP 主'}), 400
        token = existing.token
    else:
        token = secrets.token_urlsafe(32)
        sub = BiliSubscription(email=email, up_id=up_id, token=token)
        db.session.add(sub)
        db.session.commit()

    verify_url = url_for('bili_public.verify_subscription', token=token, _external=True)
    unsubscribe_url = url_for('bili_public.unsubscribe', token=token, _external=True)

    from blog.mail import send_verify_email
    send_verify_email(email, up.name or str(up.mid), verify_url, unsubscribe_url)

    return jsonify({'ok': True, 'message': '验证邮件已发送，请检查邮箱并点击确认链接'})


@bili_public_bp.route('/verify/<token>')
def verify_subscription(token):
    """验证邮件订阅"""
    sub = BiliSubscription.query.filter_by(token=token).first()
    if not sub:
        return render_template('message.html', title='验证失败',
                               message='链接无效或已过期', type='error')
    if sub.verified:
        return render_template('message.html', title='已验证',
                               message='该邮箱已验证，无需重复操作', type='info')
    sub.verified = True
    db.session.commit()
    up = BiliUp.query.get(sub.up_id)
    up_name = up.name or str(up.mid) if up else 'UP 主'
    return render_template('message.html', title='订阅成功',
                           message=f'您已成功订阅 {up_name} 的新视频通知',
                           type='success')


@bili_public_bp.route('/unsubscribe/<token>')
def unsubscribe(token):
    """取消订阅（通过邮件中的链接）"""
    sub = BiliSubscription.query.filter_by(token=token).first()
    if not sub:
        return render_template('message.html', title='取消失败',
                               message='链接无效或已过期', type='error')
    up = BiliUp.query.get(sub.up_id)
    up_name = up.name or str(up.mid) if up else 'UP 主'
    db.session.delete(sub)
    db.session.commit()
    return render_template('message.html', title='已取消订阅',
                           message=f'您已取消订阅 {up_name} 的通知',
                           type='success')
