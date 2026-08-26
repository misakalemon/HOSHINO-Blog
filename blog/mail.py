"""
HOSHINO Blog — 邮件发送模块

职责：
   1. 提供统一的邮件发送接口，支持 SMTP 与 SMTP_SSL
   2. 支持带中文显示名的发件人/收件人（RFC 5322 Header 编码）
   3. 后台线程异步发送，不阻塞请求响应
   4. 提供订阅验证和新视频通知两种预定义模板邮件

配置项（app.config）：
   MAIL_SERVER          — SMTP 服务器地址
   MAIL_PORT            — SMTP 端口
   MAIL_USE_SSL         — 是否使用 SSL（默认 False）
   MAIL_USE_TLS         — 是否使用 TLS（非 SSL 时有效）
   MAIL_USERNAME        — SMTP 登录用户名
   MAIL_PASSWORD        — SMTP 登录密码
   MAIL_DEFAULT_SENDER  — 默认发件人地址（支持 "名称 <email>" 格式）
   MAIL_TIMEOUT         — SMTP 超时秒数（默认 10）
   SITE_NAME            — 站点名称，用于邮件标题

使用方式：
   from blog.mail import send_email, send_verify_email, send_new_video_notify

   send_email('user@example.com', '主题', '<html>内容</html>')
   send_verify_email('user@example.com', 'UP主名', '验证链接', '退订链接')
"""

import logging
import re
import smtplib
import threading
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import current_app, render_template

logger = logging.getLogger(__name__)

# 邮件发送专用锁，用于保护活动线程列表的并发访问
_mail_lock = threading.Lock()


def _sanitize_header_value(value: str) -> str:
    """消毒邮件头值：移除 CR/LF，防止邮件头注入（伪造 Bcc/Cc 等）。"""
    if not value:
        return value or ''
    return str(value).replace('\r', ' ').replace('\n', ' ').strip()


def _plain_text_from_html(html: str) -> str:
    """从 HTML 正文生成纯文本版本（供 multipart/alternative 降级显示）。"""
    import re as _re

    text = _re.sub(r'<br\s*/?>', '\n', html or '')
    text = _re.sub(r'</(p|div|li|h[1-6]|tr)>', '\n', text)
    text = _re.sub(r'<[^>]+>', '', text)
    return _re.sub(r'\n{3,}', '\n\n', text).strip()


def _parse_sender(sender: str) -> str:
    """解析发信人配置，返回 RFC 5322 格式的 From 地址。

    支持两种格式：
      - email@example.com                           → 纯邮箱
      - Display Name <email@example.com>            → 显示名 + 邮箱（中文名会自动进行 MIME Header 编码）

    Args:
        sender: 发件人配置字符串

    Returns:
        str: RFC 5322 合规的 From 地址
    """
    if not sender:
        return ''
    # 匹配 "显示名 <邮箱>" 格式：捕获显示名和邮箱地址两部分
    m = re.match(r'^(.+?)\s*<([^>]+)>$', sender.strip())
    if m:
        name = m.group(1).strip().strip('"').strip("'")
        email = m.group(2).strip()
        if name:
            # 中文显示名需要使用 Header 编码（base64 或 quoted-printable），避免非 ASCII 字符在邮件头中乱码
            from email.header import Header
            return f'{Header(name, "utf-8").encode()} <{email}>'
        return email
    return sender.strip()


def _send_email_async(app, msg: MIMEMultipart):
    """在后台线程中异步发送邮件。

    根据配置选择 SMTP 或 SMTP_SSL，处理认证和发送。
    所有异常被捕获并记录日志，不会传播到调用者。

    Args:
        app: Flask 应用实例（用于获取配置和创建应用上下文）
        msg: 已构建好的 MIME 邮件对象
    """
    # 后台线程中 Flask 上下文不可用，需要手动推送
    with app.app_context():
        server = None
        try:
            config = app.config
            use_ssl = config.get('MAIL_USE_SSL', False)
            timeout = config.get('MAIL_TIMEOUT', 10)

            if use_ssl:
                # SSL 模式：SMTP_SSL 在连接时就建立加密通道
                server = smtplib.SMTP_SSL(config['MAIL_SERVER'], config['MAIL_PORT'], timeout=timeout)
            else:
                # 非 SSL 模式：先建立明文连接，再根据需要启用 TLS
                server = smtplib.SMTP(config['MAIL_SERVER'], config['MAIL_PORT'], timeout=timeout)
                if config['MAIL_USE_TLS']:
                    server.starttls()   # 升级为 TLS 加密连接

            server.login(config['MAIL_USERNAME'], config['MAIL_PASSWORD'])
            server.send_message(msg)
            logger.info('邮件发送成功 → %s', msg['To'])
        except smtplib.SMTPAuthenticationError:
            logger.error('邮件发送失败 → %s: 认证失败，请检查用户名/密码', msg['To'])
        except smtplib.SMTPException as e:
            logger.error('邮件发送失败 → %s: SMTP错误 %s', msg['To'], e)
        except Exception as e:
            logger.error('邮件发送失败 → %s: %s', msg['To'], e)
        finally:
            # 无论成败都关闭连接，防止 socket 泄漏
            if server is not None:
                try:
                    server.quit()
                except Exception:
                    try:
                        server.close()
                    except Exception:
                        pass


# 活动邮件线程列表及最大并发数控制
_active_mail_threads: list[threading.Thread] = []
_MAX_MAIL_THREADS = 10


def send_email(to: str, subject: str, html_body: str, to_name: str = ''):
    """发送邮件（非阻塞，后台线程执行）。

    将邮件放入后台线程发送，主线程立即返回。
    当并发线程数达到上限（_MAX_MAIL_THREADS=10）时，
    会等待最旧的线程结束，避免资源耗尽。
    如果 SMTP 未完整配置则跳过发送并记录警告。

    Args:
        to: 收件人邮箱地址
        subject: 邮件主题
        html_body: HTML 格式的邮件正文
        to_name: 收件人显示名称（可选），提供后会生成 "显示名 <邮箱>" 格式
    """
    # _get_current_object() 获取真正的 Flask app 实例而非代理对象，
    # 确保后台线程仍可访问配置（通过 app.app_context()）
    app = current_app._get_current_object()
    config = app.config
    # 检查 SMTP 配置是否完整：服务器地址、用户名和密码三项缺一不可
    if not config['MAIL_SERVER'] or not config['MAIL_USERNAME'] or not config['MAIL_PASSWORD']:
        logger.warning('SMTP 未完整配置，跳过邮件发送 → %s', to)
        return

    # 构建 MIME multipart/alternative 邮件：HTML + 纯文本双版本
    msg = MIMEMultipart('alternative')
    msg['From'] = _parse_sender(config['MAIL_DEFAULT_SENDER']) or config['MAIL_USERNAME']
    if to_name:
        # 收件人显示名同样需要 Header 编码以支持中文
        from email.header import Header
        msg['To'] = f'{Header(to_name, "utf-8").encode()} <{_sanitize_header_value(to)}>'
    else:
        # 收件人必须消毒，防止注入 Bcc/Cc 头
        msg['To'] = _sanitize_header_value(to)
    # 主题经 Header 编码（兼容中文）并消毒换行，防止头注入
    from email.header import Header
    msg['Subject'] = Header(_sanitize_header_value(subject), 'utf-8')
    msg.attach(MIMEText(_plain_text_from_html(html_body), 'plain', 'utf-8'))
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))

    site_name = config.get('SITE_NAME', 'Hoshino')
    logger.info('邮件队列: %s → %s【%s】: %s', msg['From'], to_name or to, site_name, subject)

    # 限制并发邮件线程数（最多 _MAX_MAIL_THREADS 个），超出时等待
    global _active_mail_threads
    old_thread = None
    with _mail_lock:
        # 先清理已结束的线程，防止线程列表无限增长
        _active_mail_threads[:] = [
            t for t in _active_mail_threads if t.is_alive()
        ]
        # 如果并发数已达上限，取出最旧的线程（锁外 join 避免阻塞其他发送者）
        if len(_active_mail_threads) >= _MAX_MAIL_THREADS:
            old_thread = _active_mail_threads.pop(0)
    if old_thread:
        old_thread.join(timeout=30)

    # 启动后台线程发送邮件（daemon=True 确保主线程退出时不阻塞）
    t = threading.Thread(target=_send_email_async, args=(app, msg), daemon=True)
    t.start()
    with _mail_lock:
        _active_mail_threads.append(t)


def send_verify_email(to: str, up_name: str, verify_url: str, unsubscribe_url: str, to_name: str = ''):
    """发送订阅验证邮件。

    渲染 mail/verify_subscription.html 模板生成 HTML 正文，
    邮件主题包含站点名称和目标 UP 主。

    Args:
        to: 收件人邮箱
        up_name: 目标 UP 主名称（用于邮件正文和标题）
        verify_url: 验证确认链接
        unsubscribe_url: 退订链接（用于邮件底部）
        to_name: 收件人显示名称（可选）
    """
    html = render_template(
        'mail/verify_subscription.html',
        to_name=to_name,
        up_name=up_name,
        verify_url=verify_url,
        unsubscribe_url=unsubscribe_url,
    )
    app = current_app._get_current_object()
    site_name = app.config.get('SITE_NAME', 'Hoshino')
    send_email(to, f'[{site_name}] 确认订阅 UP 主「{up_name}」的新视频通知', html, to_name=to_name)


def send_new_video_notify(to: str, up_name: str, videos: list, unsubscribe_url: str, to_name: str = ''):
    """发送新视频通知邮件。

    渲染 mail/new_video_notify.html 模板，邮件标题包含 UP 主名和视频数量。

    Args:
        to: 收件人邮箱
        up_name: UP 主名称
        videos: 视频信息列表（传递给模板渲染）
        unsubscribe_url: 退订链接
        to_name: 收件人显示名称（可选）
    """
    html = render_template(
        'mail/new_video_notify.html',
        to_name=to_name,
        up_name=up_name,
        videos=videos,
        unsubscribe_url=unsubscribe_url,
    )
    app = current_app._get_current_object()
    site_name = app.config.get('SITE_NAME', 'Hoshino')
    count = len(videos)
    send_email(to, f'[{site_name}] {up_name} 发布了 {count} 个新视频', html, to_name=to_name)


# ═══════════════════════════════════════════════
# 新视频通知 — 批量暂存 + 定时聚合发送
# ═══════════════════════════════════════════════
# 背景：此前每个 UP 每次增量发现新视频就单独发一封邮件，
#       订阅多个 UP 时邮箱会被"刷屏"。改为：
#       1. 发现新视频时先写入 Redis 暂存队列（按收件人分组，视频去重）
#       2. Worker 定时任务（默认每 15 分钟）聚合所有暂存视频，
#          每个收件人只收一封邮件（按 UP 分组列出全部新视频），然后清空队列
#
# Redis 键结构：
#   hblog:notify:meta:{email}  → JSON {"unsub_url": "...", "updated_at": ts}
#   hblog:notify:list:{email}  → Hash {bvid: JSON(video), ...}   （bvid 天然去重）

_NOTIFY_PREFIX = 'notify'


def _notify_redis():
    """获取通知暂存用的 Redis 客户端（不可用时返回 None）。"""
    try:
        from blog.cache import _redis_client
        return _redis_client
    except Exception:
        return None


def queue_video_notify(email: str, up_name: str, video: dict, unsubscribe_url: str):
    """将一条新视频通知加入暂存队列（不立即发邮件）。

    同一收件人同一视频（按 bvid 去重）只保留一份；视频数据若已存在则更新。

    Args:
        email: 收件人邮箱
        up_name: UP 主名称
        video: 视频信息 dict（title/bvid/url/pub_date/duration/view_count/like_count）
        unsubscribe_url: 退订链接（每个收件人一份，存储于 meta）
    """
    if not email or not video:
        return
    try:
        import json as _json
        r = _notify_redis()
        if r is None:
            # Redis 不可用时降级为立即发送（保底不丢通知）
            logger.warning('Redis 不可用，降级为立即发送视频通知 → %s', email)
            send_new_video_notify(email, up_name, [video], unsubscribe_url or '')
            return
        bvid = video.get('bvid') or ''
        if not bvid:
            return
        key = f'{_NOTIFY_PREFIX}:list:{email}'
        meta_key = f'{_NOTIFY_PREFIX}:meta:{email}'
        # 视频信息补 up_name，聚合发送时按 UP 分组
        v = dict(video)
        v['up_name'] = up_name
        r.hset(key, bvid, _json.dumps(v, ensure_ascii=False))
        r.hset(meta_key, 'unsub_url', unsubscribe_url or '')
        r.hset(meta_key, 'updated_at', str(time.time()))
        # 暂存队列保留 7 天，防止长期未发送导致堆积
        r.expire(key, 7 * 24 * 3600)
        r.expire(meta_key, 7 * 24 * 3600)
    except Exception as e:
        logger.warning('视频通知暂存失败 email=%s: %s', email, e)


def send_batched_video_notify(app):
    """聚合发送所有暂存的新视频通知（Worker 定时任务调用）。

    扫描 Redis 中所有 notify:list:* 队列，对每个收件人：
      1. 读取其全部暂存视频（按 up_name 分组）
      2. 渲染聚合邮件模板（batched_video_notify.html）
      3. 后台发送一封邮件
      4. 发送成功后删除该收件人的队列

    无暂存数据时直接返回；失败的单条通知保留在队列等待下轮重试。

    Args:
        app: Flask 应用实例（用于渲染模板与配置）
    """
    try:
        import json as _json
        r = _notify_redis()
        if r is None:
            return
        with app.app_context():
            # 扫描所有暂存队列键
            cursor = 0
            emails = []
            while True:
                cursor, keys = r.scan(cursor, match=f'{_NOTIFY_PREFIX}:list:*', count=100)
                for k in keys:
                    emails.append(k.split(':')[-1])
                if cursor == 0:
                    break
            emails = list(dict.fromkeys(emails))  # 去重保序
            if not emails:
                return
            logger.info('批量视频通知: %d 个收件人待聚合', len(emails))
            for email in emails:
                try:
                    key = f'{_NOTIFY_PREFIX}:list:{email}'
                    meta_key = f'{_NOTIFY_PREFIX}:meta:{email}'
                    items = r.hgetall(key)
                    if not items:
                        continue
                    # 按 UP 分组
                    groups = {}
                    for bvid, raw in items.items():
                        try:
                            v = _json.loads(raw)
                        except (TypeError, ValueError):
                            continue
                        up_name = v.pop('up_name', 'UP主')
                        groups.setdefault(up_name, []).append(v)
                    if not groups:
                        r.delete(key)
                        continue
                    unsub_url = (r.hget(meta_key, 'unsub_url') or b'').decode('utf-8', 'ignore')
                    # 渲染聚合邮件（按 UP 分组列表）
                    groups_list = [
                        {'up_name': up_name, 'videos': videos}
                        for up_name, videos in groups.items()
                    ]
                    html = render_template(
                        'mail/batched_video_notify.html',
                        groups=groups_list,
                        unsubscribe_url=unsub_url,
                        total_videos=sum(len(v) for v in groups.values()),
                    )
                    site_name = app.config.get('SITE_NAME', 'Hoshino')
                    subject = f'[{site_name}] {len(groups_list)} 个 UP 发布了 {sum(len(v) for v in groups.values())} 个新视频'
                    send_email(email, subject, html)
                    # 发送成功（入队）后清空该收件人队列
                    r.delete(key)
                    r.delete(meta_key)
                except Exception as e:
                    logger.warning('批量视频通知发送失败 email=%s: %s', email, e)
    except Exception as e:
        logger.warning('批量视频通知聚合失败: %s', e)
