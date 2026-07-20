"""Bilibili 公开页面路由"""

import logging
import secrets
import time

from flask import Blueprint, current_app, jsonify, render_template, request, url_for

from blog.models import BiliSubscription, BiliUp, BiliUpHistory, BiliVideo, BiliVideoHistory, db

logger = logging.getLogger(__name__)

bili_public_bp = Blueprint('bili_public', __name__, url_prefix='/bilibili')

# 订阅速率限制：每 IP 每分钟最多 5 次
_subscribe_limits: dict[str, list[float]] = {}
_SUBSCRIBE_MAX_PER_MIN = 5


@bili_public_bp.route('/')
def index():
    """公开的 UP 主列表页 / 全局搜索"""
    page = request.args.get('page', 1, type=int)
    per_page = 20
    q = request.args.get('q', '').strip()
    all_ups = BiliUp.query.order_by(BiliUp.follower_count.desc()).limit(200).all()

    if q:
        # 统一搜索：同时匹配 UP 主和视频（限制各 50 条防爆）
        ups = (
            BiliUp.query.filter(
                db.or_(BiliUp.name.contains(q), BiliUp.mid.cast(db.String).contains(q))
            )
            .limit(50)
            .all()
        )
        videos = (
            BiliVideo.query.filter(BiliVideo.title.contains(q))
            .order_by(BiliVideo.pubdate.desc())
            .limit(50)
            .all()
        )
        up_ids = {v.up_id for v in videos}
        up_map = {u.id: u for u in BiliUp.query.filter(BiliUp.id.in_(up_ids)).all()}
        return render_template(
            'bilibili.html',
            ups=ups,
            videos=videos,
            q=q,
            total=len(ups) + len(videos),
            up_map=up_map,
            all_ups=all_ups,
        )
    else:
        # 无搜索：显示所有 UP 主
        pagination = BiliUp.query.order_by(BiliUp.follower_count.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        return render_template('bilibili.html', pagination=pagination, q='', all_ups=all_ups)


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
    pagination = query.order_by(BiliVideo.pubdate.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    # 粉丝数变化历史（最近 40 条 + JSON 供图表）
    import json

    follower_history = (
        BiliUpHistory.query.filter_by(up_id=up_id)
        .order_by(BiliUpHistory.recorded_at.desc())
        .limit(300)
        .all()
    )
    follower_history.reverse()
    follower_chart_data = json.dumps(
        [
            {'t': h.recorded_at.strftime('%m/%d %H:%M'), 'v': h.follower_count}
            for h in follower_history
        ]
    )
    return render_template(
        'bilibili_up.html',
        up=up,
        pagination=pagination,
        q=q,
        follower_history=follower_history,
        follower_chart_data=follower_chart_data,
    )


@bili_public_bp.route('/video/<int:video_id>')
def video_detail(video_id):
    """视频详情页 — 多指标折线图（点击卡片开关曲线）"""
    video = BiliVideo.query.options(db.joinedload(BiliVideo.up)).get_or_404(video_id)
    up = video.up
    import json

    history = (
        BiliVideoHistory.query.filter_by(video_id=video_id)
        .order_by(BiliVideoHistory.recorded_at.desc())
        .limit(170)
        .all()
    )
    history.reverse()
    time_labels = json.dumps([h.recorded_at.strftime('%m/%d %H:%M') for h in history])
    chart_data = json.dumps(
        {
            'view': [h.view_count for h in history],
            'like': [h.like_count for h in history],
            'coin': [h.coin_count for h in history],
            'favorite': [h.favorite_count for h in history],
            'share': [h.share_count for h in history],
            'comment': [h.comment_count for h in history],
            'danmaku': [h.danmaku_count for h in history],
        }
    )

    metrics = ['view', 'like', 'coin', 'favorite', 'share', 'comment', 'danmaku']
    growth = {}
    if len(history) >= 2:
        first = history[0]
        last = history[-1]
        prev = history[-2]
        for m in metrics:
            attr = m + '_count'
            total = getattr(last, attr) - getattr(first, attr)
            last_change = getattr(last, attr) - getattr(prev, attr)
            growth[m] = {'total': total, 'last': last_change}
    else:
        growth = {m: {'total': 0, 'last': 0} for m in metrics}

    return render_template(
        'bilibili_video.html',
        video=video,
        up=up,
        history=history,
        time_labels=time_labels,
        chart_data=chart_data,
        growth=growth,
    )


@bili_public_bp.route('/compare')
def compare():
    """视频对比页面 — 可跨 UP 主"""
    ids = request.args.get('ids', '')
    video_ids = [int(x) for x in ids.split(',') if x.strip().isdigit()]
    if len(video_ids) < 2:
        return render_template(
            'message.html', title='对比失败', message='请至少选择 2 个视频', type='error'
        )
    if len(video_ids) > 10:
        video_ids = video_ids[:10]
    import json

    videos = BiliVideo.query.filter(BiliVideo.id.in_(video_ids)).all()
    up_ids = {v.up_id for v in videos}
    up_map = {u.id: u for u in BiliUp.query.filter(BiliUp.id.in_(up_ids)).all()}
    metrics = ['view', 'like', 'coin', 'favorite', 'share', 'comment', 'danmaku']
    metric_labels = {
        'view': '播放',
        'like': '点赞',
        'coin': '投币',
        'favorite': '收藏',
        'share': '转发',
        'comment': '评论',
        'danmaku': '弹幕',
    }
    chart_data = {}
    for v in videos:
        chart_data[str(v.id)] = [getattr(v, m + '_count') or 0 for m in metrics]
    return render_template(
        'bilibili_compare.html',
        videos=videos,
        up_map=up_map,
        metrics=metrics,
        metric_labels=metric_labels,
        chart_data=json.dumps(chart_data),
    )


@bili_public_bp.route('/subscribe', methods=['POST'])
def subscribe():
    """订阅 UP 主新视频邮件通知（支持批量选择多个 UP 主）

    前端传入 email + up_ids[]，同一个批次内所有订阅共用
    一个 token，验证/取消订阅时整批操作。
    """
    # 每 IP 速率限制：最多 5 次/分钟
    ip = request.remote_addr or 'unknown'
    now = time.time()
    _subscribe_limits.setdefault(ip, [])
    _subscribe_limits[ip] = [t for t in _subscribe_limits[ip] if now - t < 60]
    # 定期清理过期 IP 条目
    if len(_subscribe_limits) > 100:
        cutoff = now - 120
        stale = [k for k, v in _subscribe_limits.items() if not v or max(v) < cutoff]
        for k in stale:
            del _subscribe_limits[k]
    if len(_subscribe_limits[ip]) >= _SUBSCRIBE_MAX_PER_MIN:
        logger.warning('订阅请求过频 IP=%s', ip)
        return jsonify({'ok': False, 'error': '操作太频繁，请稍后再试'}), 429
    _subscribe_limits[ip].append(now)

    email = (request.form.get('email') or '').strip().lower()
    raw_ids = request.form.getlist('up_ids[]')
    up_ids = []
    for rid in raw_ids:
        try:
            up_ids.append(int(rid))
        except (ValueError, TypeError):
            continue

    if not email or '@' not in email or len(email) > 254:
        return jsonify({'ok': False, 'error': '请输入有效的邮箱地址'}), 400
    if not up_ids:
        return jsonify({'ok': False, 'error': '请至少选择一个 UP 主'}), 400

    # 过滤掉已订阅且已验证的 UP 主
    existing_subs = BiliSubscription.query.filter(
        BiliSubscription.email == email,
        BiliSubscription.up_id.in_(up_ids),
    ).all()
    existing_map = {s.up_id: s for s in existing_subs}

    new_up_ids = []
    already_verified = []
    for uid in up_ids:
        if uid in existing_map:
            if existing_map[uid].verified:
                already_verified.append(uid)
            else:
                new_up_ids.append(uid)
        else:
            new_up_ids.append(uid)

    if not new_up_ids:
        if already_verified:
            return jsonify({'ok': False, 'error': '部分 UP 主已被订阅，请前往邮箱查收确认邮件'}), 400
        return jsonify({'ok': False, 'error': '没有可订阅的 UP 主'}), 400

    token = secrets.token_urlsafe(32)
    for uid in new_up_ids:
        if uid in existing_map:
            sub = existing_map[uid]
            sub.token = token
        else:
            sub = BiliSubscription(email=email, up_id=uid, token=token)
            db.session.add(sub)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': f'订阅失败: {e}'}), 500

    selected_ups = BiliUp.query.filter(BiliUp.id.in_(new_up_ids)).all()
    up_names = [u.name or str(u.mid) for u in selected_ups]

    verify_url = url_for('bili_public.verify_subscription', token=token, _external=True)
    unsubscribe_url = url_for('bili_public.unsubscribe', token=token, _external=True)

    from blog.mail import send_verify_email

    label = '、'.join(up_names) if len(up_names) <= 3 else f'{len(up_names)} 个 UP 主（{"、".join(up_names[:3])}…）'
    send_verify_email(email, label, verify_url, unsubscribe_url)

    msg = f'验证邮件已发送至 {email}，请检查邮箱并确认订阅'
    return jsonify({'ok': True, 'message': msg})


@bili_public_bp.route('/verify/<token>')
def verify_subscription(token):
    """验证邮件订阅（批量验证同一 token 的所有订阅）"""
    subs = BiliSubscription.query.filter_by(token=token).options(db.joinedload(BiliSubscription.up)).all()
    if not subs:
        return render_template(
            'message.html', title='验证失败', message='链接无效或已过期', type='error'
        )
    all_verified = all(s.verified for s in subs)
    if all_verified:
        return render_template(
            'message.html', title='已验证', message='已订阅，无需重复操作', type='info'
        )
    for sub in subs:
        sub.verified = True
    db.session.commit()
    up_names = []
    for sub in subs:
        if sub.up:
            up_names.append(sub.up.name or str(sub.up.mid))
    label = '、'.join(up_names)
    return render_template(
        'message.html',
        title='订阅成功',
        message=f'您已成功订阅 {label} 的新视频通知',
        type='success',
    )


@bili_public_bp.route('/unsubscribe/<token>')
def unsubscribe(token):
    """取消订阅（批量取消同一 token 的所有订阅）"""
    subs = BiliSubscription.query.filter_by(token=token).options(db.joinedload(BiliSubscription.up)).all()
    if not subs:
        return render_template(
            'message.html', title='取消失败', message='链接无效或已过期', type='error'
        )
    up_names = []
    for sub in subs:
        if sub.up:
            up_names.append(sub.up.name or str(sub.up.mid))
        db.session.delete(sub)
    db.session.commit()
    label = '、'.join(up_names) if up_names else '所有 UP 主'
    return render_template(
        'message.html', title='已取消订阅', message=f'您已取消订阅 {label} 的通知', type='success'
    )
