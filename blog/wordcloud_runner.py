"""HOSHINO Blog — 独立词云子进程入口

以独立解释器进程运行全站 / B站 词云预计算，与爬虫 Worker 进程
彻底隔离 GIL 与内存。jieba 对 6.3 万视频全量分词是纯 CPU 密集
任务，若在 Worker 进程内直接跑会长期霸占 GIL，饿死同进程内的
爬虫 asyncio 事件循环（历史上 04:54 后日志戛然而止即此故障）。

用法：
    python -m blog.wordcloud_runner --all   # 全站词云（每日 04:00）
    python -m blog.wordcloud_runner --bili  # B站词云  (每周一 04:30)

内部流程：create_app()（WORKER_PROCESS=1，跳过迁移 DDL）
→ precompute_all_wordclouds() / precompute_bili_wordclouds() → 结束
"""

import argparse
import os
import sys

# 兼容直接执行 python blog/wordcloud_runner.py：注入项目根目录到 sys.path，
# 否则 sys.path[0]=blog/ 目录，from app import create_app 会 ModuleNotFoundError。
# 官方启动路径是 python -m blog.wordcloud_runner（worker.py 已保证 cwd=项目根）。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()


def main():
    parser = argparse.ArgumentParser(description='独立词云子进程入口')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--all', action='store_true', help='全站词云预计算')
    group.add_argument('--bili', action='store_true', help='B站词云预计算')
    args = parser.parse_args()

    # 独立进程跳过建表/迁移（与 Worker 相同），读取同一 .env 配置
    os.environ['WORKER_PROCESS'] = '1'

    from app import create_app

    app = create_app()
    logger = app.logger
    logger.info('词云子进程启动: args=%s', sys.argv[1:])

    with app.app_context():
        try:
            if args.all:
                from blog.wordcloud import precompute_all_wordclouds
                logger.info('开始全站词云预计算')
                precompute_all_wordclouds()
                logger.info('全站词云预计算完成')
            elif args.bili:
                from blog.wordcloud import precompute_bili_wordclouds
                logger.info('开始 B站词云预计算')
                precompute_bili_wordclouds()
                logger.info('B站词云预计算完成')
        except Exception as e:
            logger.error('词云子进程执行失败: %s', e, exc_info=True)
            # 词云失败不拖垮主进程：以非零码退出，供看门狗/守护感知
            sys.exit(1)


if __name__ == '__main__':
    main()