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
import os
import secrets
import time

from flask import Blueprint, current_app, jsonify, render_template, request

from blog.models import BiliSubscription, BiliUp, BiliUpHistory, BiliVideo, BiliVideoHistory, WordCloudData, db
from blog.utils import get_client_ip, RateLimiter, escape_like

logger = logging.getLogger(__name__)

bili_public_bp = Blueprint('bili_public', __name__, url_prefix='/bilibili')


# 订阅速率限制：每 IP 每分钟最多 5 次（内存存储，重启后重置）
_subscribe_limiter = RateLimiter(max_requests=5, window_seconds=60, maxsize=2000)


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
        q_escaped = escape_like(q)
        ups = (
            BiliUp.query.filter(
                db.or_(
                    BiliUp.name.contains(q_escaped, escape='\\'),
                    BiliUp.mid.cast(db.String).contains(q_escaped, escape='\\'),
                )
            )
            .limit(50)
            .all()
        )
        videos = (
            BiliVideo.query.options(db.joinedload(BiliVideo.up))
            .filter(
                BiliVideo.title.contains(q_escaped, escape='\\'),
                BiliVideo.is_deleted == False,
            )
            .order_by(BiliVideo.pubdate.desc())
            .limit(50)
            .all()
        )
        # 构建视频所属 UP 主的映射表，供前端显示（使用预加载的关联）
        up_map = {v.up.id: v.up for v in videos if v.up}
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
        bili_wordcloud_periods = []  # [(period_label, data), ...]
        from .models import WordCloudConfig
        wc_config = WordCloudConfig.get_or_create().to_dict()
        try:
            # 全量词云
            wc = WordCloudData.query.filter_by(post_id=None, source='bili', period='all').first()
            if wc and wc.data:
                bili_wordcloud = wc.data
            # 按月分段词云（供时间轴滑块使用）
            wc_months = (
                WordCloudData.query
                .filter_by(post_id=None, source='bili')
                .filter(WordCloudData.period != 'all')
                .filter(WordCloudData.period.notlike('up_%'))
                .order_by(WordCloudData.period)
                .all()
            )
            for wcm in wc_months:
                if wcm.period and wcm.data:
                    bili_wordcloud_periods.append({'period': wcm.period, 'data': wcm.data})
            # 构建 periods 字典供前端词云时间轴使用
            bili_wc_periods_dict = {p['period']: p['data'] for p in bili_wordcloud_periods}
        except Exception as e:
            logger.warning('读取 B站词云失败: %s', e)
        return render_template(
            'bilibili.html',
            pagination=pagination, q='', all_ups=all_ups,
            bili_wordcloud=bili_wordcloud, wc_config=wc_config,
            bili_wordcloud_periods=bili_wordcloud_periods,
            bili_wc_periods_dict=bili_wc_periods_dict,
        )


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

    query = BiliVideo.query.filter_by(up_id=up_id, is_deleted=False)
    if q:
        q_escaped = escape_like(q)
        query = query.filter(BiliVideo.title.contains(q_escaped, escape='\\'))
    pagination = query.order_by(BiliVideo.pubdate.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    # 粉丝数变化历史（取最近 300 条，逆序后转为 JSON 供前端 Chart.js 图表）
    follower_history = (
        BiliUpHistory.query.filter_by(up_id=up_id)
        .order_by(BiliUpHistory.recorded_at.desc())
        .limit(300)
        .all()
    )
    follower_history.reverse()  # 逆序：时间从早到晚
    # 传原始对象（模板用 |tojson 序列化），避免 |safe 输出 json.dumps 字符串
    # 的 XSS 脆弱模式（一旦字段接入用户可控字符串即可 script 注入）
    follower_chart_data = [
        {'t': h.recorded_at.strftime('%m/%d %H:%M'), 'v': h.follower_count}
        for h in follower_history
    ]
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
    历史数据取所有 BiliVideoHistory 记录，并进行智能采样以提高加载速度：
      - 数据点 ≤ 80：全部返回
      - 数据点 > 80：时间加权采样
        * 最近 30 个点：全部保留（近期变化更详细）
        * 中期数据：每隔 3 个取 1 个
        * 早期数据：每隔 6 个取 1 个

    前端使用 Chart.js 渲染，用户可点击图例单独显示/隐藏某条曲线。

    Args:
        video_id (int): 视频数据库 ID

    Returns:
        HTML 页面，渲染 bilibili_video.html
    """
    video = (
        BiliVideo.query.options(db.joinedload(BiliVideo.up))
        .filter(BiliVideo.id == video_id, BiliVideo.is_deleted == False)
        .first_or_404()
    )
    up = video.up

    # 获取所有历史数据
    all_history = (
        BiliVideoHistory.query.filter_by(video_id=video_id)
        .order_by(BiliVideoHistory.recorded_at.desc())
        .all()
    )
    all_history.reverse()  # 逆序：时间从早到晚
    
    # 智能采样：时间加权，近期数据更密集
    total_points = len(all_history)
    
    if total_points <= 80:
        # 数据点较少，全部返回
        history = all_history
    else:
        # 分段采样
        recent_count = 30  # 最近30个点全部保留
        sampled_indices = set()
        
        # 1. 保留最近的数据点（最详细）
        for i in range(max(0, total_points - recent_count), total_points):
            sampled_indices.add(i)
        
        # 2. 中期数据：每隔3个取1个
        mid_start = max(0, total_points - 150)
        for i in range(mid_start, total_points - recent_count, 3):
            sampled_indices.add(i)
        
        # 3. 早期数据：每隔6个取1个
        for i in range(0, mid_start, 6):
            sampled_indices.add(i)
        
        # 4. 始终保留第一个点
        sampled_indices.add(0)
        
        # 排序并提取数据
        sampled_indices = sorted(sampled_indices)
        history = [all_history[i] for i in sampled_indices]
    
    # 时间标签 & 各指标数值数组，供 Chart.js 渲染（原始对象，模板 |tojson）
    time_labels = [h.recorded_at.strftime('%m/%d %H:%M') for h in history]
    chart_data = {
        'view': [h.view_count for h in history],
        'like': [h.like_count for h in history],
        'coin': [h.coin_count for h in history],
        'favorite': [h.favorite_count for h in history],
        'share': [h.share_count for h in history],
        'comment': [h.comment_count for h in history],
        'danmaku': [h.danmaku_count for h in history],
    }

    metrics = ['view', 'like', 'coin', 'favorite', 'share', 'comment', 'danmaku']
    growth = {}
    if len(all_history) >= 2:
        # 计算总增长（使用全部历史数据的第一个和最后一个）
        first = all_history[0]
        last = all_history[-1]
        prev = all_history[-2]
        for m in metrics:
            attr = m + '_count'
            total = getattr(last, attr) - getattr(first, attr)
            last_change = getattr(last, attr) - getattr(prev, attr)
            growth[m] = {'total': total, 'last': last_change}
    else:
        # 历史不足 2 条时增量均为 0
        growth = {m: {'total': 0, 'last': 0} for m in metrics}

    from .models import BiliDanmaku, BiliVideoComment, WordCloudConfig, WordCloudData

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

    # 弹幕展示：按视频内进度升序，限制数量（数量大时按播放进度分段采样）。
    # 为避免加载全量弹幕（单视频可达数万条），先在 SQL 层限制最多取
    # 一个较大窗口（BILI_DANMAKU_SCAN 默认 2000），再均匀采样出展示条数。
    danmakus = []
    _scan = int(os.environ.get('BILI_DANMAKU_SCAN', '2000'))
    _dm_rows = (
        BiliDanmaku.query.with_entities(
            BiliDanmaku.content, BiliDanmaku.progress, BiliDanmaku.ctime, BiliDanmaku.color
        )
        .filter_by(video_id=video.id)
        .order_by(BiliDanmaku.progress.asc())
        .limit(_scan)
        .all()
    )
    if _dm_rows:
        max_show = int(os.environ.get('BILI_DANMAKU_SHOW', '100'))
        if len(_dm_rows) <= max_show:
            danmakus = _dm_rows
        else:
            # 均匀采样：取到的窗口中按进度均匀抽取 max_show 条
            step = len(_dm_rows) / max_show
            sampled = []
            idx = 0
            while idx < len(_dm_rows) and len(sampled) < max_show:
                sampled.append(_dm_rows[int(idx)])
                idx += step
            danmakus = sampled

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
        danmakus=danmakus,
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

    videos = (
        BiliVideo.query.filter(BiliVideo.id.in_(video_ids), BiliVideo.is_deleted == False)
        .all()
    )
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
    # 构建各视频的指标数据（以 video.id 为 key，指标数组为 value，模板 |tojson）
    chart_data = {}
    for v in videos:
        chart_data[str(v.id)] = [getattr(v, m + '_count') or 0 for m in metrics]
    return render_template(
        'bilibili_compare.html',
        videos=videos,
        up_map=up_map,
        metrics=metrics,
        metric_labels=metric_labels,
        chart_data=chart_data,
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
    ip = get_client_ip()
    if _subscribe_limiter.is_limited(ip):
        logger.warning('订阅请求过频 IP=%s', ip)
        return jsonify({'ok': False, 'error': '操作太频繁，请稍后再试'}), 429

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

    # 构造验证和取消订阅的完整 URL（优先基于 SITE_BASE_URL 生成，worker 线程也正确）
    from blog.utils import build_site_url
    verify_url = build_site_url('bili_public.verify_subscription', token=token)
    unsubscribe_url = build_site_url('bili_public.unsubscribe', token=token)

    from blog.mail import send_verify_email

    # 邮件标题显示：不超过 3 个用顿号分隔，超过 3 个显示总数
    label = '、'.join(up_names) if len(up_names) <= 3 else f'{len(up_names)} 个 UP 主（{"、".join(up_names[:3])}…）'
    try:
        send_verify_email(email, label, verify_url, unsubscribe_url)
    except Exception as e:
        # 邮件发送失败不阻塞订阅入库：记录日志并提示稍后重试。
        # 若用户再次提交，未验证记录会复用/更新 token 重新发信。
        logger.error('发送订阅验证邮件失败 email=%s: %s', email, e)
        return jsonify({
            'ok': False,
            'error': '验证邮件发送失败，请稍后重试或检查邮箱地址',
        }), 500

    msg = f'验证邮件已发送至 {email}，请检查邮箱并确认订阅'
    return jsonify({'ok': True, 'message': msg})


@bili_public_bp.route('/verify/<token>', methods=['GET', 'POST'])
def verify_subscription(token):
    """验证邮件订阅（批量验证同一 token 的所有订阅记录）

    用户点击邮件中的验证链接后，将 token 对应的所有订阅记录
    标记为 verified=True。若所有记录此前已验证，则提示无需重复操作。

    注意：邮件中的验证链接是 <a href>（GET 请求），因此路由必须
    同时接受 GET（不能只允许 POST，否则点击邮件链接会 405）。

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


@bili_public_bp.route('/unsubscribe/<token>', methods=['GET', 'POST'])
def unsubscribe(token):
    """取消订阅（批量删除同一 token 的所有订阅记录）

    用户点击邮件中的取消订阅链接后，删除 token 对应的所有 BiliSubscription 记录。
    提示用户已取消哪些 UP 主的通知。

    注意：邮件中的退订链接是 <a href>（GET 请求），因此路由必须
    同时接受 GET（不能只允许 POST，否则点击邮件链接会 405）。

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
