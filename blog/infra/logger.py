"""
HOSHINO Blog 日志模块

职责：
   1. 配置 Python logging 系统，统一管理所有模块的日志输出
   2. 提供请求日志中间件 log_request()，记录每次 HTTP 请求

日志输出渠道：
   1. 文件日志     — blog/logs/hoshino-YYYY-MM-DD.log，按日期拆分，保留 30 天
   2. 错误日志     — blog/logs/error-YYYY-MM-DD.log，仅 ERROR 级别，按日期拆分
   3. 终端日志     — 标准输出，INFO 级别以上，简化格式

集成方式：
   在 create_app() 中先调用 setup_logging(app) 初始化，
   其他模块直接用 logging.getLogger(__name__) 获取 logger 即可。
"""

import datetime as _datetime
import logging
import logging.handlers
import os
import threading
import time

from flask import request

try:
    import portalocker  # concurrent-log-handler 的依赖，用于跨进程文件锁
    _HAS_PORTALOCKER = True
except ImportError:
    _HAS_PORTALOCKER = False

# 日志目录（位于 blog/logs/）
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
try:
    os.makedirs(LOG_DIR, exist_ok=True)
except OSError as e:
    # 日志目录创建失败时直接打印到 stderr，避免在日志系统初始化前丢失信息
    import sys
    print(f'无法创建日志目录 {LOG_DIR}: {e}', file=sys.stderr)
    raise

# 日志保留天数（超过自动清理）
LOG_KEEP_DAYS = int(os.environ.get('LOG_KEEP_DAYS', '30'))


def _today_log_path(prefix: str) -> str:
    """返回今天的日志文件路径（<prefix>-YYYY-MM-DD.log）。"""
    day = _datetime.datetime.now().strftime('%Y-%m-%d')
    return os.path.join(LOG_DIR, f'{prefix}-{day}.log')


class DailyFileHandler(logging.Handler):
    """按日期拆分的多进程安全日志文件处理器。

    文件名格式：<prefix>-YYYY-MM-DD.log（如 hoshino-2026-08-19.log），
    每天自动切换到新文件；Web/Worker 双进程通过 portalocker 文件锁
    保证写入与轮转的原子性；自动清理 keep_days 天前的旧文件。

    与 ConcurrentRotatingFileHandler（按大小轮转）的区别：
      - 按自然日拆分，单日日志可读性好、便于按日归档/排查；
      - 每天使用新文件名，跨日只切换 stream，无 rename 竞态。
    """

    def __init__(self, log_dir: str, prefix: str = 'hoshino',
                 level: int = logging.NOTSET, encoding: str = 'utf-8',
                 keep_days: int = LOG_KEEP_DAYS):
        super().__init__(level)
        self.log_dir = log_dir
        self.prefix = prefix
        self.encoding = encoding
        self.keep_days = keep_days
        os.makedirs(log_dir, exist_ok=True)
        self._thread_lock = threading.RLock()      # 进程内线程锁
        # 跨进程锁文件（常开句柄，每次写入时加锁）
        self._lock_fh = open(
            os.path.join(log_dir, f'.{prefix}.lock'), 'a+', encoding='utf-8'
        )
        self._stream = None
        self._current_path = None
        # 初始打开今天的文件
        self._ensure_stream_locked()

    # ── 内部工具（须在持有跨进程锁时调用） ──
    def _build_path(self) -> str:
        day = _datetime.datetime.now().strftime('%Y-%m-%d')
        return os.path.join(self.log_dir, f'{self.prefix}-{day}.log')

    def _ensure_stream_locked(self):
        """确保 stream 指向今天的文件（跨日时自动切换）。"""
        path = self._build_path()
        if self._stream is not None and path == self._current_path:
            return
        if self._stream is not None:
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._stream = open(path, 'a', encoding=self.encoding)
        self._current_path = path
        self._cleanup_old_locked()

    def _cleanup_old_locked(self):
        """删除 keep_days 天前的本前缀日志文件（锁内执行）。"""
        if self.keep_days <= 0:
            return
        try:
            cutoff = (_datetime.datetime.now()
                      - _datetime.timedelta(days=self.keep_days)).date()
            prefix = self.prefix + '-'
            for fname in os.listdir(self.log_dir):
                if not (fname.startswith(prefix) and fname.endswith('.log')):
                    continue
                day_str = fname[len(prefix):-4]
                try:
                    day = _datetime.datetime.strptime(day_str, '%Y-%m-%d').date()
                except ValueError:
                    continue
                if day < cutoff:
                    try:
                        os.remove(os.path.join(self.log_dir, fname))
                    except OSError:
                        pass
        except OSError:
            pass

    # ── logging.Handler 接口 ──
    def emit(self, record):
        try:
            with self._thread_lock:
                if _HAS_PORTALOCKER:
                    portalocker.lock(self._lock_fh, portalocker.LOCK_EX)
                    try:
                        self._ensure_stream_locked()
                        self._stream.write(self.format(record) + '\n')
                        self._stream.flush()
                    finally:
                        portalocker.unlock(self._lock_fh)
                else:
                    # 降级：仅进程内线程安全（多进程场景需安装 concurrent-log-handler）
                    self._ensure_stream_locked()
                    self._stream.write(self.format(record) + '\n')
                    self._stream.flush()
        except Exception:
            self.handleError(record)

    def close(self):
        with self._thread_lock:
            # getattr 防御：__init__ 中途失败时（如锁文件打不开）对象不完整，
            # logging.shutdown 的 atexit 仍会调用 close()
            if getattr(self, '_stream', None) is not None:
                try:
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            if getattr(self, '_lock_fh', None) is not None:
                try:
                    self._lock_fh.close()
                except Exception:
                    pass
        super().close()


# 日志格式
#   DETAILED_FORMAT — 文件日志：包含时间、级别、进程标签、模块名、函数名、行号、线程名
#   CONSOLE_FORMAT  — 终端日志：精简，时间+级别+进程标签+消息
# 进程标签：%(proc_tag)s — Web / Worker / WordCloud / Watchdog，
# 由 ProcessTagFilter 注入，各进程（Web/Worker/词云子进程/看门狗）写入同一批每日
# 文件时可通过该字段轻松区分来源。
DETAILED_FORMAT = (
    '[%(asctime)s] %(levelname)-8s [%(proc_tag)9s] [%(name)s:%(funcName)s:%(lineno)d] '
    '[%(threadName)s] %(message)s'
)
CONSOLE_FORMAT = '%(asctime)s  %(levelname)-6s  [%(proc_tag)9s]  [%(name)s] %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
CONSOLE_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


# ── 进程标签（多进程日志文件中区分来源）────────────────────
# Web / Worker / WordCloud(独立词云子进程) / Watchdog(独立看门狗)
# 全部写入同一批每日文件（hoshino-*.log / error-*.log），
# 挂载 ProcessTagFilter 后格式串 %(proc_tag)s 即可输出来源。
def _detect_process_tag() -> str:
    """按环境变量判断当前进程类型（优先级：Watchdog > WordCloud > Worker > Web）。"""
    if os.environ.get('LOGWATCH_PROCESS') == '1':
        return 'Watchdog'
    if os.environ.get('WORDCLOUD_PROCESS') == '1':
        return 'WordCloud'
    if os.environ.get('WORKER_PROCESS') == '1':
        return 'Worker'
    return 'Web'


class ProcessTagFilter(logging.Filter):
    """给每条日志记录附加 proc_tag 属性，供格式串 %(proc_tag)s 使用。

    进程内标签固定不变（构造时按环境变量判定一次）。
    注意：所有用到含 %(proc_tag)s 格式串的 handler 都必须挂载本过滤器，
    否则缺字段会触发 KeyError（logging 会吞掉该记录并打印错误信息）。
    """

    def __init__(self, tag: str | None = None):
        super().__init__()
        self.tag = tag or _detect_process_tag()

    def filter(self, record):
        record.proc_tag = self.tag
        return True


class _ColorFormatter(logging.Formatter):
    """终端彩色格式化器 — 按日志级别为级别名着色（ERROR 红 / WARNING 黄 / INFO 绿 / DEBUG 灰）"""

    _COLORS = {
        logging.DEBUG: '\033[90m',
        logging.INFO: '\033[32m',
        logging.WARNING: '\033[33m',
        logging.ERROR: '\033[31m',
        logging.CRITICAL: '\033[35m',
    }
    _RESET = '\033[0m'

    def __init__(self, fmt=None, datefmt=None, enable_color: bool = True):
        super().__init__(fmt, datefmt)
        self._enable_color = enable_color

    def format(self, record):
        if not self._enable_color:
            return super().format(record)
        color = self._COLORS.get(record.levelno)
        if color:
            origin = record.levelname
            record.levelname = f'{color}{origin}{self._RESET}'
            try:
                return super().format(record)
            finally:
                record.levelname = origin
        return super().format(record)


def _enable_ansi():
    """Windows 下启用 ANSI VT 转义支持（Python 3.6+ / Win10+）"""
    if os.name == 'nt':
        try:
            os.system('')
        except Exception:
            pass


def _record_request_start():
    """请求开始钩子 — 记录起始时间戳，供 log_request 计算处理耗时"""
    request.environ['_ts_start'] = time.time()


def setup_logging(app):
    """配置 Flask 应用的日志系统。

    执行顺序：
    1. 获取根日志器，设置 DEBUG 级别
    2. 清空 Flask 默认的 handler（避免重复输出）
    3. 添加 3 个自定义 handler：文件（每日轮转）、错误文件（大小轮转）、终端
    4. 覆盖 Flask / Werkzeug / SQLAlchemy 的日志配置
    5. 压制第三方库（selenium、urllib3、requests）的调试噪音

    Args:
        app: Flask 应用实例

    Returns:
        logging.Logger: 配置好的根日志器
    """
    import os as _os
    _is_worker = _os.environ.get('WORKER_PROCESS') == '1'

    # ===== 1. 根日志器 =====
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    # 清空已有 handler，避免重复
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)

    # ===== 2. 文件 Handler（全部日志，按日期拆分，保留30天） =====
    # DailyFileHandler 多进程安全（portalocker 跨进程锁），
    # 文件名 hoshino-YYYY-MM-DD.log，每天自动切换并清理过期文件
    file_handler = DailyFileHandler(LOG_DIR, prefix='hoshino', level=logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(DETAILED_FORMAT, DATE_FORMAT))

    # ===== 3. 错误文件 Handler（仅 ERROR 以上，按日期拆分） =====
    error_handler = DailyFileHandler(LOG_DIR, prefix='error', level=logging.ERROR)
    error_handler.setFormatter(logging.Formatter(DETAILED_FORMAT, DATE_FORMAT))

    # ===== 4. 终端 Handler（INFO 级别，不显示 DEBUG 噪音） =====
    _enable_ansi()
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    _console_stream = console_handler.stream
    _color_enabled = bool(
        _console_stream is not None
        and getattr(_console_stream, 'isatty', None)
        and _console_stream.isatty()
    )
    # 终端 Handler：统一使用带进程标签的 CONSOLE_FORMAT（[Web]/[Worker]/[...]），
    # 替代旧的手工 [W] 前缀——标签信息更完整，且文件日志与终端输出一致
    console_handler.setFormatter(
        _ColorFormatter(CONSOLE_FORMAT, CONSOLE_DATE_FORMAT, _color_enabled)
    )

    # 进程标签过滤器：所有 handler 统一挂载，供格式串 %(proc_tag)s 输出
    # 来源（Web / Worker / WordCloud / Watchdog），多进程共享日志文件时
    # 每条记录可一眼区分所属进程
    _proc_tag_filter = ProcessTagFilter()
    file_handler.addFilter(_proc_tag_filter)
    error_handler.addFilter(_proc_tag_filter)
    console_handler.addFilter(_proc_tag_filter)

    # 添加到根日志器
    root_logger.addHandler(file_handler)
    root_logger.addHandler(error_handler)
    root_logger.addHandler(console_handler)

    # ===== 5. Flask 自身日志也使用我们的配置 =====
    for logger_name in ('flask.app', 'flask.request', 'werkzeug'):
        log = logging.getLogger(logger_name)
        log.setLevel(logging.DEBUG)
        for h in log.handlers[:]:
            log.removeHandler(h)
        console_h = logging.StreamHandler()
        console_h.setLevel(logging.WARNING)
        console_h.setFormatter(
            _ColorFormatter(CONSOLE_FORMAT, CONSOLE_DATE_FORMAT, _color_enabled)
        )
        console_h.addFilter(_proc_tag_filter)
        log.addHandler(file_handler)
        log.addHandler(console_h)
        log.propagate = False

    # ===== 6. 第三方库日志级别压制 =====
    for logger_name in (
        'selenium.webdriver.remote.remote_connection',
        'selenium.webdriver.remote',
        'selenium',
    ):
        log = logging.getLogger(logger_name)
        log.setLevel(logging.WARNING)
        log.handlers.clear()
        log.propagate = False

    for logger_name in ('urllib3', 'urllib3.connectionpool', 'requests'):
        log = logging.getLogger(logger_name)
        log.setLevel(logging.WARNING)

    # ===== 7. SQLAlchemy 日志（仅记录 WARNING 以上） =====
    sql_logger = logging.getLogger('sqlalchemy.engine')
    sql_logger.setLevel(logging.WARNING)
    # 防止经根 logger 二次输出（自身 handler 已覆盖文件日志）
    sql_logger.propagate = False
    sql_logger.addHandler(file_handler)

    # 将根日志器挂载到 app.logger
    app.logger = root_logger
    app.config['LOG_DIR'] = LOG_DIR

    # 记录每个请求的开始时间，供 log_request 计算处理耗时
    try:
        app.before_request(_record_request_start)
    except Exception:
        pass

    # 输出日志初始化分隔线（Worker 进程简化，不重复打印 banner）
    if not _is_worker:
        root_logger.info('━' * 60)
        root_logger.info('日志系统初始化完成')
        root_logger.info('日志目录: %s（按日期拆分，保留 %d 天）', LOG_DIR, LOG_KEEP_DAYS)
        root_logger.info('今日文件: %s', _today_log_path('hoshino'))
        root_logger.info('错误文件: %s', _today_log_path('error'))
        root_logger.info('━' * 60)
    else:
        root_logger.info('Worker 日志系统已就绪（今日文件: %s）', _today_log_path('hoshino'))

    return root_logger


def log_request(response):
    """请求日志中间件：记录每次 HTTP 请求 + 统一 UTF-8 编码。

    作为 Flask after_request 处理器执行，在每次请求完成后调用。
    同时负责：
      - 给 text/* 类型响应添加 charset=utf-8（统一编码）
      - 按状态码级别记录日志（≥500 → error, ≥400 → warning, 其他 → info）
      - 对终端和文件分别输出简版和详版日志（终端简洁、文件完整）
      - 自动过滤 URL 中的敏感参数（token, secret, key, password, api_key）

    安全响应头由 app.py 的 add_security_headers 统一设置。

    Args:
        response: Flask Response 对象

    Returns:
        Flask Response 对象（原样返回，供 Flask 框架继续传递）
    """
    # 确保所有 text/* 类型的响应使用 UTF-8 编码
    content_type = response.content_type or ''
    if 'charset' not in content_type and 'text/' in content_type:
        response.headers['Content-Type'] = content_type + '; charset=utf-8'

    logger = logging.getLogger()
    # 静态文件（/static/）和网站图标（/favicon.ico）不记录日志，减少噪音
    if request.path.startswith('/static/') or request.path == '/favicon.ico':
        return response

    # 收集请求信息，为两种日志格式准备数据
    # User-Agent 消毒：移除 CR/LF，防止伪造 UA 向日志注入伪造行
    _ua_raw = request.user_agent.string if request.user_agent else '-'
    extra = {
        'ip': request.remote_addr or '-',
        'method': request.method,
        'path': request.path,
        'status': response.status_code,
        'user_agent': _ua_raw.replace('\r', '').replace('\n', '')[:80] if _ua_raw != '-' else '-',
    }

    # 请求耗时（毫秒）
    _ts_start = request.environ.get('_ts_start')
    _elapsed = f'{int((time.time() - _ts_start) * 1000)}ms' if _ts_start else '-'

    # ---- 终端日志：精简版 ----
    # 只显示状态码、方法、短路径（超过 36 字符截断）、耗时，不包含 IP 和 UA
    short_path = extra['path'].split('?')[0]
    if len(short_path) > 36:
        short_path = short_path[:33] + '...'
    console_msg = f'{extra["status"]} {extra["method"]:<6} {short_path}  ({_elapsed})'

    # ---- 文件日志：详细版 ----
    # 清理敏感信息：移除 URL 中的凭据类参数，防止泄露到日志文件
    _SENSITIVE_PARAM_NAMES = (
        'token', 'secret', 'key', 'password', 'passwd', 'api_key', 'apikey',
        'access_token', 'auth', 'sign', 'signature', 'credential', 'code',
        'session', 'sid', 'csrf_token', 'csrfmiddlewaretoken',
    )
    safe_path = extra['path']
    if '?' in safe_path:
        base, qs = safe_path.split('?', 1)
        kept = []
        for p in qs.split('&'):
            name = p.split('=', 1)[0].lower().strip()
            if name in _SENSITIVE_PARAM_NAMES:
                continue
            kept.append(p)
        safe_qs = '&'.join(kept)
        safe_path = base + ('?' + safe_qs if safe_qs else '')
    file_msg = (
        f'{extra["ip"]:>15} {extra["method"]:<7} '
        f'{extra["status"]}  {safe_path:<40} {_elapsed:<8} '
        f'{extra["user_agent"]}'
    )

    # 按状态码分级记录
    # 终端：精简版（仅状态+方法+短路径）→ 适合实时查看
    # 文件：详细版（含 IP、UA 等）→ 用于事后分析排查
    if response.status_code >= 500:
        # 服务端错误：终端 ERROR，文件也按 ERROR 输出（error-YYYY-MM-DD.log 需含 IP/UA 供排查）
        logger.error(console_msg)
        logger.error(file_msg)
    elif response.status_code >= 400:
        # 客户端错误：终端输 WARNING（黄色提示），文件输 DEBUG
        logger.warning(console_msg)
        logger.debug(file_msg)
    else:
        # 正常请求（2xx/3xx）：终端输 INFO，文件输 DEBUG
        logger.info(console_msg)
        logger.debug(file_msg)

    return response
