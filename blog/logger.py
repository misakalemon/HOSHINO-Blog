"""
HOSHINO Blog 日志模块
记录请求、数据库操作、错误详细信息到文件和终端
"""
import os
import logging
import logging.handlers
from flask import request

# 日志目录
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

# 日志文件路径
LOG_FILE = os.path.join(LOG_DIR, 'hoshino.log')
ERROR_LOG_FILE = os.path.join(LOG_DIR, 'error.log')

# 日志格式
DETAILED_FORMAT = (
    '[%(asctime)s] %(levelname)-8s '
    '[%(name)s:%(funcName)s:%(lineno)d] '
    '%(message)s'
)
CONSOLE_FORMAT = '[%(asctime)s] %(levelname)-8s %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


def setup_logging(app):
    """配置 Flask 应用的日志系统"""

    # ===== 1. 根日志器 =====
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    # 清空 Flask 默认的 handler，避免重复
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)

    # ===== 2. 文件 Handler（全部日志，每日轮转，保留30天） =====
    file_handler = logging.handlers.TimedRotatingFileHandler(
        LOG_FILE, when='midnight', interval=1, backupCount=30,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(DETAILED_FORMAT, DATE_FORMAT))

    # ===== 3. 错误文件 Handler（仅 ERROR 以上，单独文件） =====
    error_handler = logging.handlers.RotatingFileHandler(
        ERROR_LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(logging.Formatter(DETAILED_FORMAT, DATE_FORMAT))

    # ===== 4. 终端 Handler（INFO 以上，彩色简化格式） =====
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(CONSOLE_FORMAT, DATE_FORMAT))

    # 添加到根日志器
    root_logger.addHandler(file_handler)
    root_logger.addHandler(error_handler)
    root_logger.addHandler(console_handler)

    # ===== 5. Flask 自身日志也使用我们的配置 =====
    for logger_name in ('flask.app', 'flask.request', 'werkzeug'):
        log = logging.getLogger(logger_name)
        log.setLevel(logging.INFO)
        for h in log.handlers[:]:
            log.removeHandler(h)
        log.addHandler(file_handler)
        log.addHandler(console_handler)
        log.propagate = False

    # ===== 6. SQLAlchemy 日志（方便追踪数据库问题） =====
    sql_logger = logging.getLogger('sqlalchemy.engine')
    sql_logger.setLevel(logging.WARNING)  # 只记录 WARNING 以上，避免 SQL 刷屏
    sql_logger.addHandler(file_handler)

    app.logger = root_logger
    app.config['LOG_DIR'] = LOG_DIR

    root_logger.info('━' * 60)
    root_logger.info('日志系统初始化完成')
    root_logger.info('日志文件: %s', LOG_FILE)
    root_logger.info('错误日志: %s', ERROR_LOG_FILE)
    root_logger.info('━' * 60)

    return root_logger


def log_request(response):
    """请求日志中间件：记录每次 HTTP 请求"""
    logger = logging.getLogger()
    if request.path.startswith('/static/') or request.path == '/favicon.ico':
        return response  # 静态文件不记录

    extra = {
        'ip': request.remote_addr or '-',
        'method': request.method,
        'path': request.path,
        'status': response.status_code,
        'user_agent': request.user_agent.string[:80] if request.user_agent else '-',
    }

    msg = (
        f"{extra['ip']:>15} "
        f"{extra['method']:<7} "
        f"{extra['status']} "
        f"{extra['path']:<40} "
        f"{extra['user_agent']}"
    )

    if response.status_code >= 500:
        logger.error(msg)
    elif response.status_code >= 400:
        logger.warning(msg)
    else:
        logger.info(msg)

    return response
