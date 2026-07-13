import logging
import smtplib
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import current_app, render_template

logger = logging.getLogger(__name__)


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


def send_email(to: str, subject: str, html_body: str):
    """发送邮件（非阻塞，后台线程执行）"""
    app = current_app._get_current_object()
    config = app.config
    if not config['MAIL_SERVER'] or not config['MAIL_USERNAME']:
        logger.warning('SMTP 未配置，跳过邮件发送 → %s', to)
        return

    msg = MIMEMultipart('alternative')
    msg['From'] = config['MAIL_DEFAULT_SENDER'] or config['MAIL_USERNAME']
    msg['To'] = to
    msg['Subject'] = subject
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))

    t = threading.Thread(target=_send_email_async, args=(app, msg), daemon=True)
    t.start()


def send_verify_email(to: str, up_name: str, verify_url: str, unsubscribe_url: str):
    """发送订阅验证邮件"""
    html = render_template('mail/verify_subscription.html',
                           up_name=up_name,
                           verify_url=verify_url,
                           unsubscribe_url=unsubscribe_url)
    send_email(to, f'确认订阅 UP 主「{up_name}」的新视频通知', html)


def send_new_video_notify(to: str, up_name: str, videos: list, unsubscribe_url: str):
    """发送新视频通知邮件"""
    html = render_template('mail/new_video_notify.html',
                           up_name=up_name,
                           videos=videos,
                           unsubscribe_url=unsubscribe_url)
    count = len(videos)
    send_email(to, f'[{up_name}] 发布了 {count} 个新视频', html)
