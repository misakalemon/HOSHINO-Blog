"""B站 登录认证 — V2 扫码登录 + Cookie/Credential 持久化

凭证加载优先级（apply_cookies）:
  1. 优先加载 .bili_credential.json → Credential（含 refresh_token，支持自动续期）
  2. 回退加载 .bili_cookies.txt → set_cookies()（纯 Cookie 字符串，向后兼容）
"""

import logging
import os
import time
import urllib.parse

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
    """兼容获取 QR 内部属性（库版本不同时属性名可能变化）

    因 bilibili-api-python 不同版本中 QrCodeLogin 的内部属性名不一致，
    此函数逐一尝试常见属性名以确保兼容性。

        qr:       QrCodeLogin 实例。
        returns:  二维码 key（字符串）。
        raises:   RuntimeError — 所有已知属性名均不匹配。
    """
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
    """兼容获取 QR 链接

        qr:       QrCodeLogin 实例。
        returns:  二维码完整 URL（字符串）。
        raises:   RuntimeError — 所有已知属性名均不匹配。
    """
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
    """兼容设置 QR key

    轮询阶段需要将之前生成的 key 设回新的 QrCodeLogin 实例。

        qr:        QrCodeLogin 实例。
        key:       二维码 key 字符串。
        raises:    RuntimeError — 所有已知属性名均不匹配。
    """
    for attr in ('_QrCodeLogin__qr_key', '_QrLogin__qr_key', '_qr_key'):
        if hasattr(qr, attr):
            setattr(qr, attr, key)
            return
    raise RuntimeError('无法设置二维码 key（库版本不兼容）')


def generate_qr_v2() -> dict:
    """使用官方库生成二维码，返回 { qrcode_key, img }

    内部流程：
      1. 创建 QrCodeLogin 实例并调用 generate_qrcode()
      2. 提取 qrcode_key（用于轮询）和 qr_url（用于生成图片）
      3. 使用 qrcode 库生成 base64 编码的 PNG 图片

        returns: {
                    'qrcode_key': str,      # 二维码 key，供 poll_qr_v2 轮询
                    'img': str,              # base64 data URI 格式的二维码图片
                  }
    """
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
    """轮询扫码状态，使用官方库

    每 1-2 秒由调用方定期调用此函数，根据返回的 status 决定下一步操作。

        qrcode_key: generate_qr_v2 返回的二维码 key。
        returns:    {
                      'ok': bool,              # 是否正常完成轮询（无异常）
                      'status': str,           # 'success' | 'scanned' | 'waiting' | 'expired' | 'unknown'
                      'msg': str,              # 人类可读的状态描述
                      'error': str (可选),     # 异常时存在，包含错误信息
                    }
    """
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
        # Cookie 值可能被 URL 编码，统一 decode 后再保存
        decoded = {k: urllib.parse.unquote(v) for k, v in cookie_dict.items()}
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
    """保存 Cookie 到文件

    向后兼容存储：仅保存纯 Cookie 字符串，用于旧流程加载。

        cookie_str: 形如 "SESSDATA=xxx; bili_jct=xxx; buvid3=xxx" 的 Cookie 字符串。
    """
    path = COOKIE_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(cookie_str)
    logger.info('B站 Cookie 已保存到: %s', path)


def load_cookies() -> str | None:
    """从文件加载 Cookie，如果文件不存在返回 None

        returns: Cookie 字符串，文件不存在或读取失败返回 None。
    """
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
    """保存完整 Credential（含 refresh_token，支持自动续期）

    优先存储方式：JSON 序列化 Credential 对象的所有非空字段，
    包括 refresh_token、ac_time_value 等关键字段。

        cred: bilibili_api.Credential 实例。
    """
    import json

    path = CREDENTIAL_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        # 仅序列化非 None 字段，减少冗余
        data = {k: v for k, v in cred.__dict__.items() if v is not None}
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info('✅ B站 Credential 已保存到: %s', path)
    except Exception as e:
        logger.warning('保存 Credential 失败: %s', e)


def load_credential():
    """从文件加载 Credential（含 refresh_token），失败返回 None

        returns: bilibili_api.Credential 实例，失败返回 None。
    """
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
    """尝试从文件加载 Credential 或 Cookie 并设置到 API 模块

    加载优先级：
      1. 如果已通过 V2 登录（_BILI_LOGGED_IN），直接返回 True
      2. 如果全局 _credential 已验证有效，直接返回 True
      3. 尝试加载完整 Credential JSON（含 refresh_token，可自动续期）
         - 有效 → 设置并返回 True
         - 过期 → 日志警告，继续尝试 Cookie
      4. 回退加载纯 Cookie 字符串（向后兼容）
         - 有效 → 设置并返回 True
         - 过期 → 返回 False（提示用户重新登录）

        returns: True 表示已成功设置有效凭证，False 表示无可用凭证。
    """
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
