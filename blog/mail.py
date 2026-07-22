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
            server.quit()
            logger.info('邮件发送成功 → %s', msg['To'])
        except smtplib.SMTPAuthenticationError:
            logger.error('邮件发送失败 → %s: 认证失败，请检查用户名/密码', msg['To'])
        except smtplib.SMTPException as e:
            logger.error('邮件发送失败 → %s: SMTP错误 %s', msg['To'], e)
        except Exception as e:
            logger.error('邮件发送失败 → %s: %s', msg['To'], e)


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

    # 构建 MIME multipart/alternative 邮件：支持 HTML 正文，
    # 客户端优先显示 HTML 版本，不支持时回退纯文本（此处未提供纯文本版本）
    msg = MIMEMultipart('alternative')
    msg['From'] = _parse_sender(config['MAIL_DEFAULT_SENDER']) or config['MAIL_USERNAME']
    if to_name:
        # 收件人显示名同样需要 Header 编码以支持中文
        from email.header import Header
        msg['To'] = f'{Header(to_name, "utf-8").encode()} <{to}>'
    else:
        msg['To'] = to
    msg['Subject'] = subject
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
