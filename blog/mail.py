import logging
import re
import smtplib
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import current_app, render_template

logger = logging.getLogger(__name__)


def _parse_sender(sender: str) -> str:
    """解析发信人配置，返回 RFC 5322 格式的 From 地址。

    支持格式：
      - email@example.com
      - Display Name <email@example.com>
    """
    if not sender:
        return ''
    m = re.match(r'^(.+?)\s*<([^>]+)>$', sender.strip())
    if m:
        name = m.group(1).strip().strip('"').strip("'")
        email = m.group(2).strip()
        if name:
            from email.header import Header
            return f'{Header(name, "utf-8").encode()} <{email}>'
        return email
    return sender.strip()


def _send_email_async(app, msg: MIMEMultipart):
    """在后台线程中发送邮件"""
    with app.app_context():
        try:
            config = app.config
            use_ssl = config.get('MAIL_USE_SSL', False)
            timeout = config.get('MAIL_TIMEOUT', 10)

            if use_ssl:
                server = smtplib.SMTP_SSL(config['MAIL_SERVER'], config['MAIL_PORT'], timeout=timeout)
            else:
                server = smtplib.SMTP(config['MAIL_SERVER'], config['MAIL_PORT'], timeout=timeout)
                if config['MAIL_USE_TLS']:
                    server.starttls()

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


def send_email(to: str, subject: str, html_body: str, to_name: str = ''):
    """发送邮件（非阻塞，后台线程执行）

    Args:
        to: 收件人邮箱
        subject: 邮件主题
        html_body: HTML 正文
        to_name: 收件人显示名称（可选）
    """
    app = current_app._get_current_object()
    config = app.config
    if not config['MAIL_SERVER'] or not config['MAIL_USERNAME']:
        logger.warning('SMTP 未配置，跳过邮件发送 → %s', to)
        return

    msg = MIMEMultipart('alternative')
    msg['From'] = _parse_sender(config['MAIL_DEFAULT_SENDER']) or config['MAIL_USERNAME']
    if to_name:
        from email.header import Header
        msg['To'] = f'{Header(to_name, "utf-8").encode()} <{to}>'
    else:
        msg['To'] = to
    msg['Subject'] = subject
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))

    site_name = config.get('SITE_NAME', 'Hoshino')
    logger.info('邮件队列: %s → %s【%s】: %s', msg['From'], to_name or to, site_name, subject)

    t = threading.Thread(target=_send_email_async, args=(app, msg), daemon=True)
    t.start()


def send_verify_email(to: str, up_name: str, verify_url: str, unsubscribe_url: str, to_name: str = ''):
    """发送订阅验证邮件"""
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
    """发送新视频通知邮件"""
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
