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
    from blog.task_queue import mark_done

    task_type = task.get('type')
    data = task.get('data', {})
    task_id = task.get('id', '?')

    # 直接写终端，绕过 logging 缓存层（Windows 兼容）
    sys.stderr.write(f'[Worker] 任务到达: {task_id} type={task_type}\n')
    sys.stderr.flush()

    logger = logging.getLogger(__name__)
    logger.info('开始处理任务 id=%s type=%s', task_id, task_type)

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
            elif task_type == 'comment_refresh':
                from blog.bili_routes import _crawl_video_comments
                _crawl_video_comments(data['bvid'])
            else:
                logger.warning('未知任务类型: %s', task_type)
                return

        logger.info('任务完成 id=%s type=%s', task_id, task_type)

    except Exception as e:
        logger.error('任务失败 id=%s type=%s: %s', task_id, task_type, e, exc_info=True)
    finally:
        # 无论成功还是异常，都清除 Redis 中的运行标记
        if task_type in ('refresh_up', 'refresh_all'):
            mark_done(data['mid'])
        db.session.remove()


def main():
    from app import create_app, _init_scheduler

    app = create_app()
    logger = app.logger

    _init_scheduler(app)
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
            sys.stderr.write(f'[Worker ♥] {time.strftime("%H:%M:%S")} 爬取={len(scrape_futures)} 词云={len(wc_futures)}\n')
            sys.stderr.flush()
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
            if task_type in ('refresh_up', 'refresh_all'):
                future = scrape_executor.submit(_run_task, task, app)
                scrape_futures[future] = task
            elif task_type in ('bili_wordcloud',):
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
    wc_executor.shutdown(wait=True, timeout=30)
    scrape_executor.shutdown(wait=True, timeout=30)
    logger.info('Worker 已正常退出')


if __name__ == '__main__':
    main()