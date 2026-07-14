"""B站 登录认证 — V2 扫码登录 + Cookie/Credential 持久化

凭证加载优先级（apply_cookies）:
  1. 优先加载 .bili_credential.json → Credential（含 refresh_token，支持自动续期）
  2. 回退加载 .bili_cookies.txt → set_cookies()（纯 Cookie 字符串，向后兼容）
"""

import logging
import os
import time
import urllib.parse
from urllib.parse import unquote

import requests
from bilibili_api import sync
from bilibili_api.login_v2 import QrCodeLogin, QrCodeLoginEvents

from .bili_api import set_cookies, set_credential as _set_api_credential
from .config import COOKIE_FILE, CREDENTIAL_FILE, HEADERS, TIMEOUT

logger = logging.getLogger(__name__)

# 登录状态标志（set_credential 后设置，避免模块间 _credential 引用不一致）
_BILI_LOGGED_IN = False

# ── V2：基于官方库的二维码登录 ──────────────
# 使用 bilibili-api-python 的 QrCodeLogin，自动处理 token 交换和字段填充


def _get_qr_key(qr):
    """兼容获取 QR 内部属性（库版本不同时属性名可能变化）"""
    try:
        return qr.get_qrcode_key()
    except AttributeError:
        pass
    for attr in ('_QrCodeLogin__qr_key', '_QrLogin__qr_key', '_qr_key'):
        val = getattr(qr, attr, None)
        if val is not None:
            return val
    raise RuntimeError('无法获取二维码 key（库版本不兼容）')


def _get_qr_link(qr):
    """兼容获取 QR 链接"""
    try:
        return qr.get_qrcode_link()
    except AttributeError:
        pass
    for attr in ('_QrCodeLogin__qr_link', '_QrLogin__qr_link', '_qr_link'):
        val = getattr(qr, attr, None)
        if val is not None:
            return val
    raise RuntimeError('无法获取二维码链接（库版本不兼容）')


def _set_qr_key(qr, key):
    """兼容设置 QR key"""
    for attr in ('_QrCodeLogin__qr_key', '_QrLogin__qr_key', '_qr_key'):
        if hasattr(qr, attr):
            setattr(qr, attr, key)
            return
    raise RuntimeError('无法设置二维码 key（库版本不兼容）')


def generate_qr_v2() -> dict:
    """使用官方库生成二维码，返回 { qrcode_key, img }"""
    import io, base64, qrcode as qrcode_lib

    qr = QrCodeLogin()
    sync(qr.generate_qrcode())
    qrcode_key = _get_qr_key(qr)
    qr_url = _get_qr_link(qr)
    logger.info('V2 二维码已生成, key=%s', qrcode_key)
    # 生成 base64 PNG 图片
    img = qrcode_lib.make(qr_url)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    b64 = base64.b64encode(buf.getvalue()).decode()
    return {'qrcode_key': qrcode_key, 'img': 'data:image/png;base64,' + b64}


def poll_qr_v2(qrcode_key: str) -> dict:
    """轮询扫码状态，使用官方库"""
    qr = QrCodeLogin()
    _set_qr_key(qr, qrcode_key)
    try:
        status = sync(qr.check_state())
    except Exception as e:
        return {'ok': False, 'error': str(e)}

    if status == QrCodeLoginEvents.DONE:
        logger.info('V2 扫码登录成功')
        global _BILI_LOGGED_IN
        _BILI_LOGGED_IN = True
        cred = qr.get_credential()
        if cred is None:
            logger.error('V2 扫码登录失败: get_credential() 返回 None')
            return {'ok': False, 'error': '无法获取登录凭证，请重试'}
        # 直接设置全局 Credential，保留完整状态（含 refresh_token 等）
        _set_api_credential(cred)
        # 保存完整 Credential JSON（含 refresh_token，支持自动续期）
        save_credential(cred)
        # 同时保存 Cookie 字符串（向后兼容）
        cookie_dict = cred.get_cookies()
        from urllib.parse import unquote

        decoded = {k: unquote(v) for k, v in cookie_dict.items()}
        cookie_str = '; '.join([f'{k}={v}' for k, v in decoded.items()])
        save_cookies(cookie_str)
        logger.info('✅ B站登录成功，Credential 已设置，Cookie 已保存')
        return {'ok': True, 'status': 'success', 'msg': '登录成功'}
    elif status == QrCodeLoginEvents.CONF:
        return {'ok': True, 'status': 'scanned', 'msg': '已扫码，请在手机上确认'}
    elif status == QrCodeLoginEvents.SCAN:
        return {'ok': True, 'status': 'waiting', 'msg': '等待扫码'}
    elif status == QrCodeLoginEvents.TIMEOUT:
        return {'ok': True, 'status': 'expired', 'msg': '二维码已过期'}
    return {'ok': True, 'status': 'unknown'}


def save_cookies(cookie_str: str):
    """保存 Cookie 到文件"""
    path = COOKIE_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(cookie_str)
    logger.info('B站 Cookie 已保存到: %s', path)


def load_cookies() -> str | None:
    """从文件加载 Cookie，如果文件不存在返回 None"""
    path = COOKIE_FILE
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except Exception as e:
        logger.warning('读取 Cookie 文件失败: %s', e)
        return None


def save_credential(cred):
    """保存完整 Credential（含 refresh_token，支持自动续期）"""
    import json

    path = CREDENTIAL_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        data = {k: v for k, v in cred.__dict__.items() if v is not None}
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info('✅ B站 Credential 已保存到: %s', path)
    except Exception as e:
        logger.warning('保存 Credential 失败: %s', e)


def load_credential():
    """从文件加载 Credential（含 refresh_token），失败返回 None"""
    from bilibili_api import Credential
    import json

    path = CREDENTIAL_FILE
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        cred = Credential(
            sessdata=data.get('sessdata'),
            bili_jct=data.get('bili_jct'),
            dedeuserid=data.get('dedeuserid'),
            buvid3=data.get('buvid3'),
            buvid4=data.get('buvid4'),
            ac_time_value=data.get('ac_time_value'),
        )
        logger.info('✅ 已从文件加载 B站 Credential（含 refresh_token）')
        return cred
    except Exception as e:
        logger.warning('加载 Credential 失败: %s', e)
        return None


def apply_cookies():
    """尝试从文件加载 Credential 或 Cookie 并设置到 API 模块"""
    global _BILI_LOGGED_IN
    if _BILI_LOGGED_IN:
        logger.info('✅ 已通过 V2 登录，直接使用')
        return True

    from .bili_api import set_cookies, set_credential, is_logged_in

    if is_logged_in():
        logger.info('✅ 全局 Credential 已存在，直接使用')
        return True

    # 优先加载完整 Credential（含 refresh_token，支持自动续期）
    cred = load_credential()
    if cred is not None:
        set_credential(cred)
        if is_logged_in():
            logger.info('✅ 已从文件加载 B站 Credential（含 refresh_token）')
            return True
        else:
            logger.warning('Credential 已过期，继续尝试 Cookie...')

    # 回退：从 Cookie 文件加载（兼容旧流程，无 refresh_token）
    cookie_str = load_cookies()
    if not cookie_str:
        return False

    logger.debug('读取到的 Cookie 原始字符串 (前100字符): %s ...', cookie_str[:100])
    set_cookies(cookie_str)
    if is_logged_in():
        logger.info('✅ 已从文件加载 B站 登录态 Cookie')
        return True
    else:
        logger.warning('Cookie 已过期，请重新登录')
    return False
