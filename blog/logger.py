"""
HOSHINO Blog 日志模块

职责：
  1. 配置 Python logging 系统，统一管理所有模块的日志输出
  2. 提供请求日志中间件 log_request()，记录每次 HTTP 请求

日志输出渠道：
  1. 文件日志     — blog/logs/hoshino.log，每日轮转，保留 30 天
  2. 错误日志     — blog/logs/error.log，仅 ERROR 级别，大小轮转（10MB×5）
  3. 终端日志     — 标准输出，INFO 级别以上，简化格式

集成方式：
  在 create_app() 中先调用 setup_logging(app) 初始化，
  其他模块直接用 logging.getLogger(__name__) 获取 logger 即可。
"""

import logging
import logging.handlers
import os

from flask import request

# 日志目录（位于 blog/logs/）
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

# 日志文件路径
LOG_FILE = os.path.join(LOG_DIR, 'hoshino.log')
ERROR_LOG_FILE = os.path.join(LOG_DIR, 'error.log')

# 日志格式
#   DETAILED_FORMAT — 文件日志：包含时间、级别、模块名、函数名、行号
#   CONSOLE_FORMAT  — 终端日志：精简，仅时间+级别+消息
DETAILED_FORMAT = '[%(asctime)s] %(levelname)-8s [%(name)s:%(funcName)s:%(lineno)d] %(message)s'
CONSOLE_FORMAT = '%(asctime)s  %(levelname)-6s  [%(name)s] %(message)s'
DATE_FORMAT = '%m/%d %H:%M:%S'
CONSOLE_DATE_FORMAT = '%m/%d %H:%M:%S'


def setup_logging(app):
    """配置 Flask 应用的日志系统

    执行顺序：
    1. 获取根日志器，设置 DEBUG 级别
    2. 清空 Flask 默认的 handler（避免重复输出）
    3. 添加 3 个自定义 handler：文件、错误文件、终端
    4. 覆盖 Flask / Werkzeug / SQLAlchemy 的日志配置

    Args:
        app: Flask 应用实例

    Returns:
        logging.Logger: 配置好的根日志器
    """

    # ===== 1. 根日志器 =====
    # 获取根日志器（所有模块的 logger 最终都继承自它）
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    # 清空 Flask 默认的 handler，避免重复
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)

    # ===== 2. 文件 Handler（全部日志，每日轮转，保留30天） =====
    # 使用 TimedRotatingFileHandler 按天轮转，避免单个日志文件过大
    file_handler = logging.handlers.TimedRotatingFileHandler(
        LOG_FILE, when='midnight', interval=1, backupCount=30, encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(DETAILED_FORMAT, DATE_FORMAT))

    # ===== 3. 错误文件 Handler（仅 ERROR 以上，单独文件） =====
    # 使用 RotatingFileHandler 按大小轮转，专门记录错误信息
    error_handler = logging.handlers.RotatingFileHandler(
        ERROR_LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(logging.Formatter(DETAILED_FORMAT, DATE_FORMAT))

    # ===== 4. 终端 Handler（INFO 级别，不显示 DEBUG 噪音） =====
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(CONSOLE_FORMAT, CONSOLE_DATE_FORMAT))

    # 添加到根日志器
    root_logger.addHandler(file_handler)
    root_logger.addHandler(error_handler)
    root_logger.addHandler(console_handler)

    # ===== 5. Flask 自身日志也使用我们的配置 =====
    # 覆盖 Flask、Werkzeug 内置的日志 handler。
    # Werkzeug HTTP 请求日志仅在文件记录（DEBUG），
    # 终端由自定义 log_request() 统一输出，避免重复。
    for logger_name in ('flask.app', 'flask.request', 'werkzeug'):
        log = logging.getLogger(logger_name)
        log.setLevel(logging.DEBUG)
        for h in log.handlers[:]:
            log.removeHandler(h)
        # 终端 handler：仅 WARNING+（抑制 werkzeug HTTP 访问日志）
        console_h = logging.StreamHandler()
        console_h.setLevel(logging.WARNING)
        console_h.setFormatter(logging.Formatter(CONSOLE_FORMAT, CONSOLE_DATE_FORMAT))
        log.addHandler(file_handler)
        log.addHandler(console_h)
        # 禁止 propagate，避免日志重复（父 logger 也会输出）
        log.propagate = False

    # ===== 6. 第三方库日志级别压制 =====
    # Selenium WebDriver 远程调用日志（每条 HTTP 请求/响应都打 DEBUG，太吵）
    for logger_name in (
        'selenium.webdriver.remote.remote_connection',
        'selenium.webdriver.remote',
        'selenium',
    ):
        log = logging.getLogger(logger_name)
        log.setLevel(logging.WARNING)
        log.handlers.clear()
        log.propagate = False

    # urllib3 / requests 的连接池日志
    for logger_name in ('urllib3', 'urllib3.connectionpool', 'requests'):
        log = logging.getLogger(logger_name)
        log.setLevel(logging.WARNING)

    # ===== 7. SQLAlchemy 日志（仅记录 WARNING 以上） =====
    sql_logger = logging.getLogger('sqlalchemy.engine')
    sql_logger.setLevel(logging.WARNING)  # WARNING 以上，减少日志噪音
    sql_logger.addHandler(file_handler)

    # 将根日志器挂载到 app.logger
    app.logger = root_logger
    app.config['LOG_DIR'] = LOG_DIR

    root_logger.info('━' * 60)
    root_logger.info('日志系统初始化完成')
    root_logger.info('日志文件: %s', LOG_FILE)
    root_logger.info('错误日志: %s', ERROR_LOG_FILE)
    root_logger.info('━' * 60)

    return root_logger


def log_request(response):
    """请求日志中间件：记录每次 HTTP 请求 + 统一 UTF-8 编码

    作为 Flask after_request 处理器执行，在每次请求完成后调用。
    同时负责：
      - 给 text/* 类型响应添加 charset=utf-8（统一编码）
      - 添加 X-Content-Type-Options: nosniff（安全头）
      - 按状态码级别记录日志（≥500 → error, ≥400 → warning, 其他 → info）

    Args:
        response: Flask Response 对象

    Returns:
        Flask Response 对象（原样返回）
    """
    # 确保所有响应使用 UTF-8 编码
    content_type = response.content_type or ''
    if 'charset' not in content_type and 'text/' in content_type:
        response.headers['Content-Type'] = content_type + '; charset=utf-8'
    # ── 安全响应头 ──────────────────────────────
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self';"
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net;"
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net;"
        "img-src 'self' data: https:;"
        "font-src 'self' https://fonts.gstatic.com;"
        "connect-src 'self';"
        "frame-ancestors 'none'"
    )

    logger = logging.getLogger()
    # 静态文件和图标不记录，减少日志噪音
    if request.path.startswith('/static/') or request.path == '/favicon.ico':
        return response

    # 收集请求信息
    extra = {
        'ip': request.remote_addr or '-',
        'method': request.method,
        'path': request.path,
        'status': response.status_code,
        'user_agent': request.user_agent.string[:80] if request.user_agent else '-',
    }

    # 格式化的日志消息
    # 终端简洁版（短路径、无 UA、不换行）
    # 文件详细版（完整信息）

    short_path = extra['path'].split('?')[0]
    if len(short_path) > 36:
        short_path = short_path[:33] + '...'
    console_msg = f'{extra["status"]} {extra["method"]:<6} {short_path}'
    file_msg = (
        f'{extra["ip"]:>15} {extra["method"]:<7} '
        f'{extra["status"]}  {extra["path"]:<40} '
        f'{extra["user_agent"]}'
    )

    # 按状态码分级记录
    # 终端：精简版（仅状态+方法+短路径）
    # 文件：详细版（含 IP、UA 等）
    if response.status_code >= 500:
        logger.error(console_msg)
        logger.debug(file_msg)
    elif response.status_code >= 400:
        logger.warning(console_msg)
        logger.debug(file_msg)
    else:
        logger.info(console_msg)
        logger.debug(file_msg)

    return response
