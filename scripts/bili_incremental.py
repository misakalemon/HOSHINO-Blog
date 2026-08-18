"""B站 增量检查：检查所有 UP 主的新视频并入库

用法：python scripts/bili_incremental.py
退出码：0 = 全部成功；1 = 存在失败（供 cron/CI 感知部分失败）
"""
import logging
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

logger = logging.getLogger(__name__)


def main() -> int:
    from blog.bili_routes import _check_new_videos
    from blog.models import BiliUp
    from app import create_app

    app = create_app()
    failed = 0
    with app.app_context():
        ups = BiliUp.query.all()
        for u in ups:
            try:
                print(f'Checking {u.name}')
                _check_new_videos(u.mid, app)
            except Exception as e:
                failed += 1
                print(f'Error checking {u.name}: {e}')
                logger.exception('Incremental check failed for %s', u.name)
    print(f'完成：{len(ups)} 个 UP，失败 {failed} 个')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
