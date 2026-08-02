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

import logging
import os
import signal
import sys
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
                    up_id=up_id
                ).order_by(BiliVideo.pubdate.desc()).with_entities(BiliVideo.id).limit(50).all()]
                total = len(video_ids)
                logger.info('评论刷新: UP %s 共 %d 个视频, 并发 %d', up_id, total, MAX_COMMENT_WORKERS)

                def _crawl_one(vid):
                    v = BiliVideo.query.get(vid)
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
            elif task_type == 'refresh_up_subtitles':
                from blog.models import BiliVideo
                from concurrent.futures import ThreadPoolExecutor, as_completed
                up_id = data['up_id']
                video_ids = [r[0] for r in BiliVideo.query.filter_by(
                    up_id=up_id
                ).order_by(BiliVideo.pubdate.desc()).with_entities(BiliVideo.id).limit(50).all()]
                total = len(video_ids)
                logger.info('字幕刷新: UP %s 共 %d 个视频, 并发 %d', up_id, total, MAX_COMMENT_WORKERS)

                def _fetch_subtitle(vid):
                    v = BiliVideo.query.get(vid)
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

    except Exception as e:
        logger.error('任务失败 id=%s type=%s: %s', task_id, task_type, e, exc_info=True)
    finally:
        # 无论成功还是异常，都清除 Redis 中的运行标记
        if task_type in ('refresh_up', 'refresh_all', 'refresh_up_comments',
                         'refresh_up_subtitles', 'bili_wordcloud_single',
                         'comment_refresh'):
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
    from concurrent.futures import ThreadPoolExecutor, as_completed

    max_workers = min(int(os.environ.get('BILI_INCREMENTAL_THREADS', '2')), 2)
    from blog.bilibili.bili_api import ensure_semaphore
    ensure_semaphore(max_workers)

    with app.app_context():
        from blog.models import BiliUp
        from blog.bili_routes import _check_new_videos, _incremental_running, _scrape_lock
        ups = BiliUp.query.all()
        if not ups:
            return

        logger = logging.getLogger(__name__)
        logger.info('增量检查启动: %d 个 UP 主, %d 并发', len(ups), max_workers)

        def _check_one(up):
            try:
                _check_new_videos(up.mid, app)
            finally:
                with _scrape_lock:
                    _incremental_running.discard(up.mid)

        import random
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for up in ups:
                with _scrape_lock:
                    if up.mid in _incremental_running:
                        continue
                    _incremental_running.add(up.mid)
                futures[executor.submit(_check_one, up)] = up
                # 错峰启动：避免前 N 个线程同一秒发出第 1 页请求触发风控
                time.sleep(random.uniform(2.0, 5.0))

            for future in as_completed(futures):
                up = futures[future]
                try:
                    future.result()
                except Exception as e:
                    logger.warning('增量检查 mid=%d 异常: %s', up.mid, e)


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

        # 02:00 每日深扫
        from blog.bili_routes import run_daily_scrape
        scheduler.add_job(
            func=lambda: run_daily_scrape(app),
            trigger='cron',
            hour=2,
            minute=0,
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

        # 04:00 全站词云预计算（深扫完成后，且与 B站词云错开）
        from blog.wordcloud import precompute_all_wordclouds
        def _job_all_wc():
            with app.app_context():
                precompute_all_wordclouds()
        scheduler.add_job(
            func=_job_all_wc,
            trigger='cron',
            hour=4,
            minute=0,
            id='precompute_all_wordclouds',
            replace_existing=True,
        )

        # 04:30 B站词云预计算（全站词云完成后再跑，避免两个大遍历并发）
        from blog.wordcloud import precompute_bili_wordclouds
        def _job_bili_wc():
            with app.app_context():
                precompute_bili_wordclouds()
        scheduler.add_job(
            func=_job_bili_wc,
            trigger='cron',
            hour=4,
            minute=30,
            id='precompute_bili_wordclouds',
            replace_existing=True,
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
            'Worker 定时任务: 02:00深扫 03:00密钥轮换 03:30历史清理 '
            '04:00全站词云 04:30B站词云 每15min增量检查'
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

    init_task_queue(app)

    elapsed = time.time() - _startup_time
    logger.info('Worker 启动完成 (%.2fs) 并行任务数=%d', elapsed, MAX_WORKER_THREADS)

    shutdown_flag = [False]
    _setup_signal_handlers(shutdown_flag)

    # --- 双线程池：爬取 3 线程 + 词云 3 线程，完全独立 ---
    scrape_executor = ThreadPoolExecutor(max_workers=MAX_WORKER_THREADS)
    wc_executor = ThreadPoolExecutor(max_workers=MAX_WC_THREADS)
    scrape_futures: dict = {}
    wc_futures: dict = {}

    heartbeat_interval = 0

    while not shutdown_flag[0]:
        # 心跳信号：每 5 秒输出一次
        now = time.time()
        if now - heartbeat_interval >= 5:
            logger.debug('[Worker ♥] %s 爬取=%d 词云=%d', time.strftime("%H:%M:%S"), len(scrape_futures), len(wc_futures))
            heartbeat_interval = now

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

            # 按任务类型分发到对应线程池
            if task_type in ('refresh_up', 'refresh_all', 'comment_refresh',
                             'refresh_up_comments', 'refresh_up_subtitles'):
                future = scrape_executor.submit(_run_task, task, app)
                scrape_futures[future] = task
            elif task_type in ('bili_wordcloud', 'bili_wordcloud_single'):
                future = wc_executor.submit(_run_task, task, app)
                wc_futures[future] = task
            else:
                logger.warning('未知任务类型: %s，跳过', task_type)
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