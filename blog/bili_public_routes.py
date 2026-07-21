"""Bilibili 公开页面路由 — 无需登录的 UP 主页 / 视频详情 / 对比 / 邮件订阅

提供面向所有访客的公开页面：
  - /bilibili/             — UP 主列表 & 全局搜索（同时搜索 UP 主和视频）
  - /bilibili/up/<id>      — 单个 UP 主的视频列表 + 粉丝数变化趋势图
  - /bilibili/video/<id>   — 视频详情 + 7 项指标历史折线图（可开关曲线）
  - /bilibili/compare      — 多视频跨 UP 主横向对比（雷达/柱状图）
  - /bilibili/subscribe    — 邮件订阅新视频通知（支持批量选择多个 UP 主）
  - /bilibili/verify/<token>   — 验证订阅邮箱地址
  - /bilibili/unsubscribe/<token> — 一键取消订阅

速率限制：
  _RateLimitDict 基于 OrderedDict 实现 FIFO 淘汰
  订阅接口每 IP 每分钟最多 5 次
"""

import logging
import secrets
import time

from collections import OrderedDict

from flask import Blueprint, current_app, jsonify, render_template, request, url_for

from blog.models import BiliSubscription, BiliUp, BiliUpHistory, BiliVideo, BiliVideoHistory, WordCloudData, db

logger = logging.getLogger(__name__)

bili_public_bp = Blueprint('bili_public', __name__, url_prefix='/bilibili')


class _RateLimitDict(OrderedDict):
    """固定大小的速率限制字典，超出容量时自动淘汰最久未访问的条目（FIFO）。

    基于 OrderedDict 实现 LRU 风格淘汰：
      当条目数超过 maxsize 时，popitem(last=False) 从头部删除最早插入的键值对。
    OrderedDict 在 Python 3.7+ 中保证了插入顺序，因此最早插入的即为最久未访问的条目。

    Attributes:
        maxsize (int): 最大条目数，默认 2000
    """
    def __init__(self, maxsize=2000):
        self.maxsize = maxsize
        super().__init__()

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        # 超出容量时淘汰最早插入的条目
        if len(self) > self.maxsize:
            self.popitem(last=False)


# 订阅速率限制：每 IP 每分钟最多 5 次（内存存储，重启后重置）
_subscribe_limits = _RateLimitDict(maxsize=2000)
_SUBSCRIBE_MAX_PER_MIN = 5


@bili_public_bp.route('/')
def index():
    """公开的 UP 主列表页 / 全局搜索

    支持分页浏览全部 UP 主（按粉丝数倒序，每页 20 条），
    也支持关键词搜索（同时搜索 UP 主名称/mid 和视频标题，各自限制 50 条防爆）。

    Query Params:
        page (int): 页码，默认 1
        q (str):    搜索关键词（可选），同时匹配 UP 主和视频标题

    Returns:
        HTML 页面，渲染 bilibili.html
    """
    page = request.args.get('page', 1, type=int)
    per_page = 20
    q = request.args.get('q', '').strip()
    # 预加载粉丝数前 200 的 UP 主，供前端导航栏快捷跳转
    all_ups = BiliUp.query.order_by(BiliUp.follower_count.desc()).limit(200).all()

    if q:
        # 统一搜索：同时匹配 UP 主和视频（各自限制 50 条避免爆表）
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
        # 构建视频所属 UP 主的映射表，供前端显示
        up_ids = {v.up_id for v in videos}
        up_map = {u.id: u for u in BiliUp.query.filter(BiliUp.id.in_(up_ids)).all()}
        bili_wordcloud = None
        return render_template(
            'bilibili.html',
            ups=ups,
            videos=videos,
            q=q,
            total=len(ups) + len(videos),
            up_map=up_map,
            all_ups=all_ups,
            bili_wordcloud=bili_wordcloud,
        )
    else:
        # 无搜索：分页显示全部 UP 主
        pagination = BiliUp.query.order_by(BiliUp.follower_count.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        # 读取 B站词云（兼容旧表缺少 period/source 列的情况）
        bili_wordcloud = None
        from .models import WordCloudConfig
        wc_config = WordCloudConfig.get_or_create().to_dict()
        try:
            wc = WordCloudData.query.filter_by(post_id=None, source='bili', period='all').first()
            if wc and wc.data:
                bili_wordcloud = wc.data
        except Exception as e:
            logger.warning('读取 B站词云失败: %s', e)
        return render_template('bilibili.html', pagination=pagination, q='', all_ups=all_ups, bili_wordcloud=bili_wordcloud, wc_config=wc_config)


@bili_public_bp.route('/up/<int:up_id>')
def up_videos(up_id):
    """公开的 UP 主视频列表页

    展示视频分页列表（每页 30 条，按发布日期倒序）以及粉丝数变化历史折线图。
    粉丝数据取最近 300 条 BiliUpHistory 记录，前端用 Chart.js 渲染趋势图。

    Args:
        up_id (int): UP 主数据库 ID

    Query Params:
        page (int): 页码
        q (str):    视频标题搜索关键词（可选），支持模糊匹配

    Returns:
        HTML 页面，渲染 bilibili_up.html
    """
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
    # 粉丝数变化历史（取最近 300 条，逆序后转为 JSON 供前端 Chart.js 图表）
    import json

    follower_history = (
        BiliUpHistory.query.filter_by(up_id=up_id)
        .order_by(BiliUpHistory.recorded_at.desc())
        .limit(300)
        .all()
    )
    follower_history.reverse()  # 逆序：时间从早到晚
    follower_chart_data = json.dumps(
        [
            {'t': h.recorded_at.strftime('%m/%d %H:%M'), 'v': h.follower_count}
            for h in follower_history
        ]
    )
    # 读取该 UP 主的专属词云
    bili_wordcloud = None
    from .models import WordCloudConfig
    wc_config = WordCloudConfig.get_or_create().to_dict()
    try:
        wc = WordCloudData.query.filter_by(post_id=None, source='bili', period=f'up_{up_id}').first()
        if wc and wc.data:
            bili_wordcloud = wc.data
    except Exception as e:
        logger.warning('读取 UP主词云失败(up_videos): %s', e)
    return render_template(
        'bilibili_up.html',
        up=up,
        pagination=pagination,
        q=q,
        follower_history=follower_history,
        follower_chart_data=follower_chart_data,
        bili_wordcloud=bili_wordcloud,
        wc_config=wc_config,
    )


@bili_public_bp.route('/video/<int:video_id>')
def video_detail(video_id):
    """视频详情页 — 多指标折线图（用户可点击图例开关曲线）

    展示播放/点赞/投币/收藏/转发/评论/弹幕 7 项指标的历史变化曲线。
    历史数据取最近 170 条 BiliVideoHistory 记录，同时计算每项指标的
    总增长量和最近一次变化量。

    前端使用 Chart.js 渲染，用户可点击图例单独显示/隐藏某条曲线。

    Args:
        video_id (int): 视频数据库 ID

    Returns:
        HTML 页面，渲染 bilibili_video.html
    """
    video = BiliVideo.query.options(db.joinedload(BiliVideo.up)).get_or_404(video_id)
    up = video.up
    import json

    history = (
        BiliVideoHistory.query.filter_by(video_id=video_id)
        .order_by(BiliVideoHistory.recorded_at.desc())
        .limit(170)  # 限制最多 170 条历史记录
        .all()
    )
    history.reverse()  # 逆序：时间从早到晚
    # 时间标签 & 各指标数值数组，供 Chart.js 渲染
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
        # 计算总增长（最后一个值 - 第一个值）和最近一次变化（最后一个值 - 倒数第二个值）
        first = history[0]
        last = history[-1]
        prev = history[-2]
        for m in metrics:
            attr = m + '_count'
            total = getattr(last, attr) - getattr(first, attr)
            last_change = getattr(last, attr) - getattr(prev, attr)
            growth[m] = {'total': total, 'last': last_change}
    else:
        # 历史不足 2 条时增量均为 0
        growth = {m: {'total': 0, 'last': 0} for m in metrics}

    from .models import BiliVideoComment, WordCloudConfig, WordCloudData

    wc_record = WordCloudData.query.filter_by(
        post_id=None, source='bili_video', period=f'bvid_{video.bvid}'
    ).first()
    wc_data = wc_record.data if wc_record and wc_record.data else []
    wc_config = WordCloudConfig.get_or_create().to_dict()

    comments = (
        BiliVideoComment.query.filter_by(video_id=video.id)
        .order_by(BiliVideoComment.ctime.desc())
        .limit(50)
        .all()
    )

    return render_template(
        'bilibili_video.html',
        video=video,
        up=up,
        history=history,
        time_labels=time_labels,
        chart_data=chart_data,
        growth=growth,
        wc_data=wc_data,
        wc_config=wc_config,
        comments=comments,
    )


@bili_public_bp.route('/compare')
def compare():
    """视频对比页面 — 支持跨 UP 主横向对比

    将多个视频的当前统计数据以柱状图/雷达图形式进行对比。
    最多支持 10 个视频同时对比，不足 2 个时返回错误提示。

    Query Params:
        ids (str): 逗号分隔的视频数据库 ID 列表（如 "1,3,5"）

    Returns:
        HTML 页面，渲染 bilibili_compare.html
    """
    ids = request.args.get('ids', '')
    video_ids = [int(x) for x in ids.split(',') if x.strip().isdigit()]
    if len(video_ids) < 2:
        return render_template(
            'message.html', title='对比失败', message='请至少选择 2 个视频', type='error'
        )
    if len(video_ids) > 10:
        video_ids = video_ids[:10]  # 超过 10 个时截断
    import json

    videos = BiliVideo.query.filter(BiliVideo.id.in_(video_ids)).all()
    # 构建视频所属 UP 主的映射表
    up_ids = {v.up_id for v in videos}
    up_map = {u.id: u for u in BiliUp.query.filter(BiliUp.id.in_(up_ids)).all()}
    # 7 项指标的中英文对照
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
    # 构建各视频的指标数据（以 video.id 为 key，指标数组为 value）
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

    流程：
      1. IP 速率限制校验（每 IP 每分钟最多 5 次）
      2. 邮箱格式校验（长度 + email_validator 库）
      3. 过滤已订阅且已验证的 UP 主
      4. 生成 token，批量写入 BiliSubscription 记录
      5. 发送验证邮件（含验证链接和取消订阅链接）

    POST Params:
        email (str):    订阅者邮箱
        up_ids[] (list): 要订阅的 UP 主数据库 ID 列表

    Returns:
        JSON: {ok: True, message: str}
              或 {ok: False, error: str} + 对应 HTTP 状态码
    """
    # IP 速率限制：滑窗 60 秒，最多 5 次
    ip = request.remote_addr or 'unknown'
    now = time.time()
    entries = _subscribe_limits.get(ip, [])
    # 过滤掉超过 60 秒的历史记录
    entries = [t for t in entries if now - t < 60]
    _subscribe_limits[ip] = entries
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

    # 邮箱基本格式校验：非空 + 最长 254 字符
    if not email or len(email) > 254:
        return jsonify({'ok': False, 'error': '请输入有效的邮箱地址'}), 400
    try:
        from email_validator import validate_email as _validate_email
        _validate_email(email, check_deliverability=False)
    except Exception:
        return jsonify({'ok': False, 'error': '邮箱格式不正确'}), 400
    if not up_ids:
        return jsonify({'ok': False, 'error': '请至少选择一个 UP 主'}), 400

    # 查询现有订阅记录，区分已验证和未验证的
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
                new_up_ids.append(uid)  # 未验证的视为可重新订阅
        else:
            new_up_ids.append(uid)

    if not new_up_ids:
        if already_verified:
            return jsonify({'ok': False, 'error': '部分 UP 主已被订阅，请前往邮箱查收确认邮件'}), 400
        return jsonify({'ok': False, 'error': '没有可订阅的 UP 主'}), 400

    # 生成新 token，同一批次共用
    token = secrets.token_urlsafe(32)
    for uid in new_up_ids:
        if uid in existing_map:
            # 更新已有未验证记录的 token
            sub = existing_map[uid]
            sub.token = token
        else:
            # 创建新订阅记录
            sub = BiliSubscription(email=email, up_id=uid, token=token)
            db.session.add(sub)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': f'订阅失败: {e}'}), 500

    selected_ups = BiliUp.query.filter(BiliUp.id.in_(new_up_ids)).all()
    up_names = [u.name or str(u.mid) for u in selected_ups]

    # 构造验证和取消订阅的完整 URL
    verify_url = url_for('bili_public.verify_subscription', token=token, _external=True)
    unsubscribe_url = url_for('bili_public.unsubscribe', token=token, _external=True)

    from blog.mail import send_verify_email

    # 邮件标题显示：不超过 3 个用顿号分隔，超过 3 个显示总数
    label = '、'.join(up_names) if len(up_names) <= 3 else f'{len(up_names)} 个 UP 主（{"、".join(up_names[:3])}…）'
    send_verify_email(email, label, verify_url, unsubscribe_url)

    msg = f'验证邮件已发送至 {email}，请检查邮箱并确认订阅'
    return jsonify({'ok': True, 'message': msg})


@bili_public_bp.route('/verify/<token>')
def verify_subscription(token):
    """验证邮件订阅（批量验证同一 token 的所有订阅记录）

    用户点击邮件中的验证链接后，将 token 对应的所有订阅记录
    标记为 verified=True。若所有记录此前已验证，则提示无需重复操作。

    Args:
        token (str): 订阅验证令牌（URL-safe 随机字符串）

    Returns:
        HTML 页面，渲染 message.html
    """
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
    """取消订阅（批量删除同一 token 的所有订阅记录）

    用户点击邮件中的取消订阅链接后，删除 token 对应的所有 BiliSubscription 记录。
    提示用户已取消哪些 UP 主的通知。

    Args:
        token (str): 订阅验证令牌

    Returns:
        HTML 页面，渲染 message.html
    """
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
