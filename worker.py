"""
HOSHINO Blog — 后台工作进程 (Worker)

与 Flask Web 进程分离运行，专门处理后台耗时任务。
避免爬虫、定时任务阻塞 HTTP 请求。

职责：
  1. APScheduler 定时任务（B站深扫/增量/密钥轮换/词云）
  2. 从 Redis 队列消费手动触发的爬取任务

线程模型：
  消费循环主线程从 Redis 拉取任务，提交到 ThreadPoolExecutor，
  最多 WORKER_THREADS（默认 3）个任务并行执行。
  APScheduler 使用自己的线程池（默认 10 线程），两套线程互不干扰。

启动方式：
  python worker.py

环境变量：
  WORKER_THREADS — 并行任务数（默认 3）
"""

import json
import logging
import os
import random
import signal
import subprocess

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

load_dotenv()

_startup_time = time.time()

# 爬取线程数，可通过环境变量 WORKER_THREADS 覆盖
MAX_WORKER_THREADS = int(os.environ.get('WORKER_THREADS', '3'))
# 词云线程数，可通过环境变量 WC_THREADS 覆盖
MAX_WC_THREADS = int(os.environ.get('WC_THREADS', '3'))
# 评论/字幕刷新视频并发数，可通过环境变量 BILI_COMMENT_WORKERS 覆盖
MAX_COMMENT_WORKERS = int(os.environ.get('BILI_COMMENT_WORKERS', '3'))


# ── 业务心跳（供 logwatch 看门狗判定僵死）──────────────────────
# Worker 周期性刷新 blog/logs/.activity（内容：Unix时间戳 + 最近业务活动
# 类型，只写文件、不写日志——与「移除刷屏心跳日志」的决策兼容）。
# 任何业务活动（增量/深扫/词云/任务完成）即时更新；主循环每
# BILI_ACTIVITY_INTERVAL（默认 5 分钟）兜底刷新一次，
# logwatch 据此判定「无业务活动超阈值」是否僵死。
_ACTIVITY_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'blog', 'logs', '.activity'
)
_ACTIVITY_LOCK = threading.Lock()
_last_activity_refresh = [0.0]
_last_activity_type = ['startup']
_ACTIVITY_INTERVAL = max(30, int(float(os.environ.get('BILI_ACTIVITY_INTERVAL', '5')) * 60))


def record_activity(activity_type: str):
    """更新业务心跳文件（时间戳 + 最近业务活动类型）。"""
    with _ACTIVITY_LOCK:
        _last_activity_type[0] = activity_type
        _last_activity_refresh[0] = time.time()
        try:
            os.makedirs(os.path.dirname(_ACTIVITY_FILE), exist_ok=True)
            with open(_ACTIVITY_FILE, 'w') as _af:
                _af.write(f'{time.time():.0f} {activity_type}\n')
        except Exception as e:
            logging.getLogger(__name__).warning('业务心跳写入失败: %s', e)


def _refresh_activity_periodic():
    """主循环兜底心跳：超过 BILI_ACTIVITY_INTERVAL 未更新则刷新一次。"""
    if time.time() - _last_activity_refresh[0] >= _ACTIVITY_INTERVAL:
        record_activity(_last_activity_type[0] or 'heartbeat')


def _setup_signal_handlers(shutdown_flag):
    """注册 SIGTERM/SIGINT 处理函数，设置退出标志。"""
    logger = logging.getLogger(__name__)

    def _handler(signum, frame):
        logger.info('收到信号 %s，正在退出...', signum)
        shutdown_flag[0] = True

    try:
        signal.signal(signal.SIGTERM, _handler)
    except (ValueError, AttributeError):
        pass
    try:
        signal.signal(signal.SIGINT, _handler)
    except (ValueError, AttributeError):
        pass


# ── 增量检查共享线程池 ──────────────────────────────────────────
# 每 15 分钟一次的增量检查若每次新建 ThreadPoolExecutor，其线程各自创建
# asyncio 事件循环 + HTTP session（bilibili_api 按 loop 缓存且不清空），
# 长时间运行会泄漏套接字（WinError 10048/10055）。改为模块级共享池复用线程。
_INCREMENTAL_POOL: ThreadPoolExecutor | None = None
_INCREMENTAL_POOL_LOCK = threading.Lock()


def _get_incremental_pool() -> ThreadPoolExecutor:
    global _INCREMENTAL_POOL
    if _INCREMENTAL_POOL is None:
        with _INCREMENTAL_POOL_LOCK:
            if _INCREMENTAL_POOL is None:
                n = min(int(os.environ.get('BILI_INCREMENTAL_THREADS', '2')), 2)
                _INCREMENTAL_POOL = ThreadPoolExecutor(
                    max_workers=n, thread_name_prefix='bili-incremental'
                )
                logging.getLogger(__name__).info(
                    '共享增量检查线程池已创建: max_workers=%d', n
                )
                import atexit

                def _shutdown_pool():
                    global _INCREMENTAL_POOL
                    if _INCREMENTAL_POOL is not None:
                        try:
                            _INCREMENTAL_POOL.shutdown(wait=False)
                        except Exception:
                            pass
                        _INCREMENTAL_POOL = None

                atexit.register(_shutdown_pool)
    return _INCREMENTAL_POOL


def _run_task(task, app):
    """在线程池中执行单个任务，确保 mark_done 始终被调用。"""
    from blog import db
    from blog.task_queue import mark_done, ack_task

    task_type = task.get('type')
    data = task.get('data', {})
    task_id = task.get('id', '?')

    logger = logging.getLogger(__name__)
    logger.info('[Worker] 任务到达: %s type=%s', task_id, task_type)

    try:
        with app.app_context():
            if task_type == 'refresh_up':
                from blog.bili_routes import _run_scrape
                _run_scrape(
                    mid=data['mid'],
                    space_url=data['space_url'],
                    app=app,
                    max_videos=data.get('max_videos'),
                )
            elif task_type == 'refresh_all':
                from blog.bili_routes import _run_scrape
                _run_scrape(
                    mid=data['mid'],
                    space_url=data['space_url'],
                    app=app,
                    force=True,
                )
            elif task_type == 'bili_wordcloud':
                from blog.wordcloud import precompute_up_wordclouds
                precompute_up_wordclouds(data['up_id'])
            elif task_type == 'bili_wordcloud_single':
                from blog.wordcloud import _compute_single_video_wordcloud
                from blog.models import BiliVideo
                video = BiliVideo.query.filter_by(id=data.get('video_id')).first()
                if not video and data.get('bvid'):
                    video = BiliVideo.query.filter_by(bvid=data['bvid']).first()
                if video:
                    _compute_single_video_wordcloud(video)
                else:
                    logger.warning('bili_wordcloud_single: 视频不存在 id=%s bvid=%s',
                                   data.get('video_id'), data.get('bvid'))
            elif task_type == 'comment_refresh':
                from blog.bili_routes import _crawl_video_comments
                from blog.models import BiliVideo
                video = BiliVideo.query.filter_by(bvid=data['bvid']).first()
                if video:
                    _crawl_video_comments(video)
                else:
                    logger.warning('comment_refresh: 视频不存在 bvid=%s', data['bvid'])
            elif task_type == 'refresh_up_comments':
                from blog.bili_routes import _crawl_video_comments
                from blog.models import BiliVideo
                from concurrent.futures import ThreadPoolExecutor, as_completed
                up_id = data['up_id']
                video_ids = [r[0] for r in BiliVideo.query.filter_by(
                    up_id=up_id, is_deleted=False
                ).order_by(BiliVideo.pubdate.desc()).with_entities(BiliVideo.id).limit(int(os.environ.get('BILI_REFRESH_LIMIT', '50'))).all()]
                total = len(video_ids)
                logger.info('评论刷新: UP %s 共 %d 个视频, 并发 %d', up_id, total, MAX_COMMENT_WORKERS)

                def _crawl_one(vid):
                    v = db.session.get(BiliVideo, vid)
                    if not v:
                        return 0
                    try:
                        n = _crawl_video_comments(v)
                        if n:
                            logger.info('%s ✅ %d 条', v.bvid[:8], n)
                        return n
                    except Exception as e:
                        logger.warning('%s 评论失败: %s', v.bvid, e)
                        return 0
                    finally:
                        db.session.remove()

                with ThreadPoolExecutor(max_workers=MAX_COMMENT_WORKERS) as executor:
                    futures = {executor.submit(_crawl_one, vid): vid for vid in video_ids}
                    for future in as_completed(futures):
                        try:
                            future.result()
                        except Exception as e:
                            logger.warning('评论爬取线程异常: %s', e)
                from blog.task_queue import submit_task
                submit_task('bili_wordcloud', up_id=up_id)
            elif task_type == 'danmaku_refresh':
                from blog.bili_routes import _crawl_video_danmakus
                from blog.models import BiliVideo
                video = BiliVideo.query.filter_by(bvid=data['bvid']).first()
                if video:
                    # 新视频弹幕：不强制，若已爬过（如重复入库）则跳过
                    _crawl_video_danmakus(video, force=False)
                else:
                    logger.warning('danmaku_refresh: 视频不存在 bvid=%s', data['bvid'])
            elif task_type == 'refresh_up_danmakus':
                from blog.bili_routes import _crawl_video_danmakus
                from blog.models import BiliVideo
                from concurrent.futures import ThreadPoolExecutor, as_completed
                up_id = data['up_id']
                video_ids = [r[0] for r in BiliVideo.query.filter_by(
                    up_id=up_id, is_deleted=False
                ).order_by(BiliVideo.pubdate.desc()).with_entities(BiliVideo.id).limit(int(os.environ.get('BILI_REFRESH_LIMIT', '50'))).all()]
                total = len(video_ids)
                logger.info('弹幕刷新: UP %s 共 %d 个视频, 并发 %d', up_id, total, MAX_COMMENT_WORKERS)

                def _crawl_danmaku(vid):
                    v = db.session.get(BiliVideo, vid)
                    if not v:
                        return 0
                    try:
                        # 手动刷新整 UP 弹幕：强制重新爬取
                        n = _crawl_video_danmakus(v, force=True)
                        if n:
                            logger.info('%s ✅ %d 条', v.bvid[:8], n)
                        return n
                    except Exception as e:
                        logger.warning('%s 弹幕失败: %s', v.bvid, e)
                        return 0
                    finally:
                        db.session.remove()

                with ThreadPoolExecutor(max_workers=MAX_COMMENT_WORKERS) as executor:
                    futures = {executor.submit(_crawl_danmaku, vid): vid for vid in video_ids}
                    for future in as_completed(futures):
                        try:
                            future.result()
                        except Exception as e:
                            logger.warning('弹幕爬取线程异常: %s', e)
                from blog.task_queue import submit_task
                submit_task('bili_wordcloud', up_id=up_id)
            elif task_type == 'refresh_up_subtitles':
                from blog.models import BiliVideo
                from concurrent.futures import ThreadPoolExecutor, as_completed
                up_id = data['up_id']
                video_ids = [r[0] for r in BiliVideo.query.filter_by(
                    up_id=up_id, is_deleted=False
                ).order_by(BiliVideo.pubdate.desc()).with_entities(BiliVideo.id).limit(int(os.environ.get('BILI_REFRESH_LIMIT', '50'))).all()]
                total = len(video_ids)
                logger.info('字幕刷新: UP %s 共 %d 个视频, 并发 %d', up_id, total, MAX_COMMENT_WORKERS)

                def _fetch_subtitle(vid):
                    v = db.session.get(BiliVideo, vid)
                    if not v:
                        return 0
                    try:
                        from blog.bilibili.bili_api import get_video_subtitle
                        subtitle = get_video_subtitle(v.bvid)
                        if subtitle:
                            v.subtitle_text = subtitle
                            db.session.commit()
                            return 1
                        return 0
                    except Exception as e:
                        db.session.rollback()
                        logger.warning('%s 字幕失败: %s', v.bvid, e)
                        return 0
                    finally:
                        db.session.remove()

                ok = 0
                with ThreadPoolExecutor(max_workers=MAX_COMMENT_WORKERS) as executor:
                    futures = {executor.submit(_fetch_subtitle, vid): vid for vid in video_ids}
                    for future in as_completed(futures):
                        try:
                            ok += future.result() or 0
                        except Exception as e:
                            logger.warning('字幕爬取线程异常: %s', e)
                logger.info('字幕刷新完成: UP %s 成功 %d/%d', up_id, ok, total)
                from blog.task_queue import submit_task
                submit_task('bili_wordcloud', up_id=up_id)
            else:
                logger.warning('未知任务类型: %s', task_type)
                return

            db.session.remove()

        logger.info('任务完成 id=%s type=%s', task_id, task_type)
        # 业务心跳：任务完成即视为一次业务活动
        record_activity(f'task:{task_type}')

    except Exception as e:
        logger.error('任务失败 id=%s type=%s: %s', task_id, task_type, e, exc_info=True)
        # 可重试任务重新入队（最多重试 2 次），避免失败任务静默丢失
        _RETRYABLE_TYPES = (
            'refresh_up', 'refresh_all', 'refresh_up_comments',
            'refresh_up_danmakus', 'refresh_up_subtitles',
            'bili_wordcloud_single', 'comment_refresh', 'danmaku_refresh',
        )
        retries = int(task.get('data', {}).get('_retries', 0) or 0)
        if task_type in _RETRYABLE_TYPES and retries < 2:
            from blog.task_queue import requeue_task
            original_raw = json.dumps(task)
            task.setdefault('data', {})['_retries'] = retries + 1
            if requeue_task(task, original_raw):
                logger.warning('任务将重试 id=%s type=%s (第 %d 次)', task_id, task_type, retries + 1)
            else:
                from blog.task_queue import ack_task as _ack
                _ack(task)
        else:
            from blog.task_queue import ack_task as _ack
            _ack(task)
    finally:
        # 无论成功还是异常，都归还 DB 连接，防止连接池被长任务泄漏
        try:
            db.session.remove()
        except Exception:
            pass
        # 无论成功还是异常，都清除 Redis 中的运行标记
        if task_type in ('refresh_up', 'refresh_all', 'refresh_up_comments',
                         'refresh_up_danmakus', 'refresh_up_subtitles',
                         'bili_wordcloud_single', 'comment_refresh', 'danmaku_refresh'):
            mid = data.get('mid') or data.get('up_id')
            if mid:
                mark_done(mid)
        # 确认任务完成：从备份列表移除（防止 Worker 崩溃导致任务永久丢失）
        ack_task(task)


def _run_bili_incremental_check(app):
    """增量检查调度入口 — 每 30 分钟对所有 UP 主执行增量检查。

    使用线程池并行检查多个 UP 主（默认 3 并发），
    避免大量 UP 主时串行执行超过 30 分钟周期。
    """
    from concurrent.futures import as_completed

    max_workers = min(int(os.environ.get('BILI_INCREMENTAL_THREADS', '2')), 2)
    from blog.bilibili.bili_api import ensure_semaphore
    ensure_semaphore(max_workers)

    import logging as _logging
    _logger = _logging.getLogger(__name__)

    # 整体增量检查硬超时（秒）：防止个别 UP 卡死在网络重试导致整个实例永不结束，
    # 进而 APScheduler 因 max_instances=1 跳过后续调度、线程/连接累积耗尽资源。
    overall_timeout = int(os.environ.get('BILI_INCREMENTAL_TIMEOUT', '900'))  # 默认 15 分钟

    # 用线程守护包装整个函数：若主流程异常/超时，始终释放 DB 连接，
    # 避免 BiliUp.query.all() 或提交循环卡死导致连接池被长期占用（08-06 事故根因）。
    try:
        with app.app_context():
            from blog.models import BiliUp
            from blog.bili_routes import _check_new_videos, _incremental_running, _scrape_lock, _scrape_running
            # 批次级协调：与深扫不再“整批让路”。深扫期间其他 UP 的增量照常执行，
            # 只有「正在深扫的同一 mid」让路（_check_new_videos 内部同样做同 mid 互斥）。
            # 安全性：全局令牌桶 BILI_GLOBAL_RATE_CAP=1 已将 B站 请求全局串行，
            # 不同 UP 并发不增加请求频率，不会触发 -352 风控。
            # 收益：深扫期间其他 UP 订阅者的新视频通知不再被饿死 2 小时。
            ups = BiliUp.query.all()
            if not ups:
                return

            _logger.info('增量检查启动: %d 个 UP 主, %d 并发', len(ups), max_workers)
            record_activity('incremental')

            def _check_one(up):
                try:
                    _check_new_videos(up.mid, app)
                finally:
                    with _scrape_lock:
                        _incremental_running.discard(up.mid)

            start_t = time.time()
            executor = _get_incremental_pool()
            futures = {}
            # 一次性提交所有 UP（不再逐个 sleep）：全局令牌桶已串行化 B站 API 请求，
            # 无需在提交循环里额外错峰，避免 93 个 UP × 2~5s 串行阻塞 APScheduler 线程数分钟。
            for up in ups:
                with _scrape_lock:
                    # 仅跳过正在深扫的同一 mid（跨进程运行锁由路由层 try_acquire 兜底）
                    if up.mid in _incremental_running or up.mid in _scrape_running:
                        continue
                    _incremental_running.add(up.mid)
                futures[executor.submit(_check_one, up)] = up
                if time.time() - start_t > overall_timeout:
                    _logger.warning('增量检查提交阶段已超 %ds，跳过剩余 UP', overall_timeout)
                    break

            deadline = start_t + overall_timeout
            try:
                for future in as_completed(futures, timeout=overall_timeout):
                    up = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        _logger.warning('增量检查 mid=%d 异常: %s', up.mid, e)
                    if time.time() > deadline:
                        _logger.warning('增量检查达到 %ds 硬超时，停止等待剩余 %d 个 UP',
                                        overall_timeout, len(futures) - len([f for f in futures if f.done()]))
                        break
            except TimeoutError:
                _logger.warning('增量检查整体超时 %ds，未完成 %d 个 UP',
                                overall_timeout, len(futures))
    except Exception:
        _logger.exception('增量检查调度异常')
    finally:
        # 无论成功、异常还是超时，都要归还 DB 连接，防止连接池被长期占用
        from blog import db
        try:
            db.session.remove()
        except Exception:
            pass


def _init_worker_scheduler(app):
    """初始化 Worker 专用调度器 — 注册所有后台定时任务。

    Worker 进程独占所有爬取/词云/清理/密钥轮换任务，
    Web 进程不运行任何调度器。
    """
    import atexit

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from config import rotate_secret_key

        scheduler = BackgroundScheduler()

        # 03:00 密钥轮换
        scheduler.add_job(
            func=lambda: rotate_secret_key(app),
            trigger='cron',
            hour=3,
            minute=0,
            id='rotate_secret_key',
            replace_existing=True,
        )

        # 02:00 每日深扫 — 分钟数随机（每次进程启动重新随机），
        # 避免固定时刻执行被 B站 行为画像识别为定时任务
        from blog.bili_routes import run_daily_scrape
        _daily_minute = random.randint(0, 29)

        def _job_daily_scrape():
            # 业务心跳：深扫开始即视为业务活动，结束再记一次
            record_activity('daily_scrape')
            try:
                run_daily_scrape(app)
            finally:
                record_activity('daily_scrape_done')

        scheduler.add_job(
            func=_job_daily_scrape,
            trigger='cron',
            hour=2,
            minute=_daily_minute,
            id='daily_scrape',
            replace_existing=True,
        )

        # 增量检查：每 N 分钟自调度（默认 30 分钟，可用 BILI_INCREMENTAL_MINUTES 覆盖）
        _inc_minutes = int(os.environ.get('BILI_INCREMENTAL_MINUTES', '30'))
        scheduler.add_job(
            func=lambda: _run_bili_incremental_check(app),
            trigger='interval',
            minutes=_inc_minutes,
            id='bili_incremental_check',
            replace_existing=True,
            # coalesce=True：若上一轮未完成，跳过堆积的触发（避免排队连锁）
            # max_instances=2：允许少量重叠，防止单个卡死任务永久阻塞后续调度
            coalesce=True,
            max_instances=2,
        )

        # 03:30 历史数据自动清理（与深扫/词云错开，避免资源竞争）
        from blog.bili_routes import auto_cleanup_history
        scheduler.add_job(
            func=lambda: auto_cleanup_history(app),
            trigger='cron',
            hour=3,
            minute=30,
            id='auto_cleanup_history',
            replace_existing=True,
        )

        # 新视频通知批量发送：默认每 15 分钟聚合一次。
        # 发现新视频时先暂存 Redis 队列，此处统一按收件人发送一封聚合邮件，
        # 避免"每个 UP 一封邮件"刷屏订阅者邮箱。
        from blog.mail import send_batched_video_notify
        _notify_minutes = int(os.environ.get('BILI_NOTIFY_MINUTES', '15'))
        scheduler.add_job(
            func=lambda: send_batched_video_notify(app),
            trigger='interval',
            minutes=_notify_minutes,
            id='batched_video_notify',
            replace_existing=True,
            coalesce=True,
            max_instances=2,
        )

        # ── 词云改为独立子进程 ────────────────────────────
        # jieba 对 6.3 万视频全量分词是纯 CPU 密集任务，若在 Worker 进程内直接跑
        # 会长占 GIL，饿死同进程内爬虫的 asyncio 事件循环（历史上 04:54 后日志
        # 戛然而止即此故障）。改为 spawn 独立解释器进程运行 blog/wordcloud_runner，
        # 与爬虫进程彻底隔离 GIL 与内存；子进程自带 WORKER_PROCESS=1 跳过迁移。
        def _spawn_wordcloud(*args):
            _root = os.path.dirname(os.path.abspath(__file__))
            cmd = [sys.executable, '-m', 'blog.wordcloud_runner'] + list(args)
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=_root,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=sys.stderr,
                    env={**os.environ, 'WORKER_PROCESS': '1'},
                )
            except Exception as e:
                app.logger.error('词云子进程启动失败 %s: %s', args, e)
                return None
            app.logger.info('词云子进程已启动 (PID=%d) args=%s', proc.pid, args)
            # 业务心跳：词云调度触发即视为业务活动（子进程自身为 CPU 密集、无需再写心跳）
            record_activity('wordcloud_subproc')
            return proc

        # 04:00 全站词云预计算（每日 1 次）
        scheduler.add_job(
            func=lambda: _spawn_wordcloud('--all'),
            trigger='cron',
            hour=4,
            minute=0,
            id='precompute_all_wordclouds',
            replace_existing=True,
            max_instances=1,
        )

        # 04:30 B站词云预计算 — 默认每周一 04:30（BILI_BILI_WC_CRON 为标准
        # 5 段 crontab：分 时 日 月 周，留空=每日 04:30）
        from apscheduler.triggers.cron import CronTrigger as _CronTrigger
        _bili_wc_cron = (os.environ.get('BILI_BILI_WC_CRON', '30 4 * * 1') or '').strip()
        _bili_wc_trigger = (
            _CronTrigger(hour=4, minute=30) if not _bili_wc_cron
            else _CronTrigger.from_crontab(_bili_wc_cron)
        )
        scheduler.add_job(
            func=lambda: _spawn_wordcloud('--bili'),
            trigger=_bili_wc_trigger,
            id='precompute_bili_wordclouds',
            replace_existing=True,
            max_instances=1,
        )

        scheduler.start()
        app.scheduler = scheduler

        def _shutdown_scheduler():
            try:
                scheduler.shutdown(wait=False)
            except Exception:
                pass
        atexit.register(_shutdown_scheduler)

        import signal
        import sys

        def _scheduler_sigterm(signum, frame):
            _shutdown_scheduler()
            sys.exit(0)

        try:
            signal.signal(signal.SIGTERM, _scheduler_sigterm)
        except (ValueError, AttributeError):
            pass

        app.logger.info(
            'Worker 定时任务: 02:00深扫(deadline=%dmin,并发=%d) 03:00密钥轮换 '
            '03:30历史清理 04:00全站词云(子进程) B站词云(子进程,%s) '
            '每%dmin增量检查 每%dmin批量视频通知',
            int(os.environ.get('BILI_DAILY_DEADLINE', '90')),
            int(os.environ.get('BILI_BATCH', '3')),
            _bili_wc_cron or '每日04:30',
            _inc_minutes,
            _notify_minutes,
        )
    except Exception as e:
        app.logger.warning('定时任务启动失败（不影响运行）: %s', e)


def main():
    from app import create_app

    # 标记为 Worker 进程（让 create_app 跳过数据库迁移，避免与 Flask 并发 DDL）
    os.environ['WORKER_PROCESS'] = '1'
    app = create_app()
    logger = app.logger

    _init_worker_scheduler(app)
    logger.info('定时任务调度器已启动')

    from blog.task_queue import init_task_queue, get_task
    from blog import db

    # Worker 进程同样执行弹幕表列类型修复迁移（幂等）。
    # 原因：danmaku_refresh 任务在 Worker 进程写 bili_danmakus 表，
    # 若仅重启 Worker 而未重启 Flask 主进程，cid 列仍为 INT 会导致 1264 溢出。
    # 该迁移只做幂等的 MODIFY COLUMN，与主进程的 DDL 不会冲突（都改到相同类型）。
    try:
        with app.app_context():
            from blog import _migrate_bili_danmakus_table
            _migrate_bili_danmakus_table(app)
    except Exception as e:
        logger.warning('Worker 弹幕表迁移失败（忽略）: %s', e)

    init_task_queue(app)

    # 恢复上次崩溃遗留的备份任务（Worker 在 brpoplpush 之后、ack 之前
    # 崩溃的任务会滞留在 backup 列表，此处重新入队避免永久丢失）
    from blog.task_queue import recover_backup_tasks
    recover_backup_tasks()

    # 记录本进程 PID 供 logwatch 看门狗（BILI_WATCHDOG_RESTART=1 时按此重启）
    _pid_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'blog', 'logs')
    try:
        os.makedirs(_pid_dir, exist_ok=True)
        with open(os.path.join(_pid_dir, 'worker.pid'), 'w') as _pf:
            _pf.write(str(os.getpid()))
    except Exception as e:
        logger.warning('Worker PID 文件写入失败: %s', e)

    elapsed = time.time() - _startup_time
    logger.info('Worker 启动完成 (%.2fs) 并行任务数=%d', elapsed, MAX_WORKER_THREADS)

    shutdown_flag = [False]
    _setup_signal_handlers(shutdown_flag)

    # --- 双线程池：爬取 3 线程 + 词云 3 线程，完全独立 ---
    scrape_executor = ThreadPoolExecutor(max_workers=MAX_WORKER_THREADS)
    wc_executor = ThreadPoolExecutor(max_workers=MAX_WC_THREADS)
    scrape_futures: dict = {}
    wc_futures: dict = {}

    # 周期性内存回收：Worker 长期运行 + 大量爬取/词云任务会产生对象碎片，
    # 定期强制 GC 并把内存归还给解释器池，防止跨任务累积导致 OOM。
    _mem_check_interval = 0
    _mem_check_period = int(os.environ.get('WORKER_MEM_GC_SECONDS', '300'))  # 默认 5 分钟
    try:
        import gc as _gc
        import psutil as _psutil_mem
        _HAS_PSUTIL = True
    except ImportError:
        _gc = None
        _psutil_mem = None
        _HAS_PSUTIL = False

    while not shutdown_flag[0]:
        # 业务心跳兜底：超过 BILI_ACTIVITY_INTERVAL 未更新时刷新一次，
        # 让 logwatch 看门狗始终能看到 Worker 存活（不写日志、无刷屏）
        _refresh_activity_periodic()

        # 周期内存回收：每 _mem_check_period 秒检查一次 RSS，
        # 超阈值（默认 1.5GB）时强制 gc.collect()
        _now = time.time()
        if _now - _mem_check_interval >= _mem_check_period:
            _mem_check_interval = _now
            if _gc is not None:
                try:
                    _rss_mb = _psutil_mem.Process().memory_info().rss / 1024 / 1024
                    _limit_mb = float(os.environ.get('WORKER_MEM_LIMIT', '1500'))
                    if _rss_mb > _limit_mb:
                        _freed = _gc.collect()
                        logger.warning(
                            '内存水位 %.0fMB 超过阈值 %.0fMB，强制 GC 回收 %d 个对象',
                            _rss_mb, _limit_mb, _freed,
                        )
                    else:
                        _gc.collect(0)
                except Exception:
                    pass
        try:
            # 清理已完成的任务
            def _cleanup(futures_map):
                done = [f for f in futures_map if f.done()]
                for f in done:
                    try:
                        f.result()
                    except Exception:
                        pass
                    del futures_map[f]

            _cleanup(scrape_futures)
            _cleanup(wc_futures)

            task = get_task()
            if task is None:
                time.sleep(1)
                continue

            task_type = task.get('type', '?')

            # 任务签名校验：防止 Redis 被投毒时执行伪造任务（如任意 space_url 爬取）
            from blog.task_queue import verify_task_signature, ack_task as _ack_task
            if not verify_task_signature(task):
                logger.warning('任务签名校验失败，丢弃 id=%s type=%s', task.get('id'), task_type)
                _ack_task(task)
                continue

            # 按任务类型分发到对应线程池
            if task_type in ('refresh_up', 'refresh_all', 'comment_refresh',
                             'refresh_up_comments', 'refresh_up_danmakus',
                             'danmaku_refresh', 'refresh_up_subtitles'):
                future = scrape_executor.submit(_run_task, task, app)
                scrape_futures[future] = task
            elif task_type in ('bili_wordcloud', 'bili_wordcloud_single'):
                future = wc_executor.submit(_run_task, task, app)
                wc_futures[future] = task
            else:
                # 未知任务类型：任务已从队列移到备份列表，必须 ack，
                # 否则永久滞留 backup（且无人回收）
                logger.warning('未知任务类型: %s，丢弃 id=%s', task_type, task.get('id'))
                _ack_task(task)
                continue

            logger.info('派发任务 id=%s type=%s (爬取队列=%d 词云队列=%d)',
                        task.get('id'), task_type, len(scrape_futures), len(wc_futures))

        except KeyboardInterrupt:
            shutdown_flag[0] = True
            break
        except Exception as e:
            logger.error('任务循环异常: %s', e, exc_info=True)
            time.sleep(5)

    logger.info('正在等待 %d 个爬取任务 + %d 个词云任务完成...',
                len(scrape_futures), len(wc_futures))
    wc_executor.shutdown(wait=True)
    scrape_executor.shutdown(wait=True)
    logger.info('Worker 已正常退出')


if __name__ == '__main__':
    main()