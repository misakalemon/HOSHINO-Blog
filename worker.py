"""
HOSHINO Blog — 后台工作进程 (Worker)

与 Flask Web 进程分离运行，专门处理后台耗时任务。
避免爬虫、定时任务阻塞 HTTP 请求。

职责：
  1. APScheduler 定时任务（B站深扫/增量/密钥轮换/词云）
  2. 从 Redis 队列消费手动触发的爬取任务

启动方式：
  python worker.py

通过 Supervisor / systemd / launcher.py 管理生命周期。
"""

import logging
import os
import signal
import sys
import time

from dotenv import load_dotenv

load_dotenv()

_startup_time = time.time()


def _setup_signal_handlers(shutdown_flag):
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


def main():
    from app import create_app, _init_scheduler

    app = create_app()

    logger = app.logger

    _init_scheduler(app)
    logger.info('定时任务调度器已启动')

    from blog.task_queue import init_task_queue, get_task
    from blog import db

    init_task_queue(app)
    logger.info('后台 Worker 就绪，等待任务...')

    elapsed = time.time() - _startup_time
    logger.info('Worker 启动完成 (%.2fs)', elapsed)

    shutdown_flag = [False]
    _setup_signal_handlers(shutdown_flag)

    while not shutdown_flag[0]:
        try:
            task = get_task()
            if task is None:
                time.sleep(1)
                continue

            task_type = task.get('type')
            data = task.get('data', {})
            task_id = task.get('id', '?')

            logger.info('处理任务 id=%s type=%s', task_id, task_type)

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

                from blog.task_queue import mark_done
                if task_type in ('refresh_up', 'refresh_all'):
                    mark_done(data['mid'])

                logger.info('任务完成 id=%s type=%s', task_id, task_type)

            except Exception as e:
                logger.error('任务失败 id=%s type=%s: %s',
                             task_id, task_type, e, exc_info=True)
            finally:
                db.session.remove()

        except KeyboardInterrupt:
            shutdown_flag[0] = True
            break
        except Exception as e:
            logger.error('任务循环异常: %s', e, exc_info=True)
            time.sleep(5)

    logger.info('Worker 已正常退出')


if __name__ == '__main__':
    main()