"""B站 全量刷新：对所有 UP 主执行完整爬取

用法：python scripts/bili_daily_scrape.py
退出码：0 = 全部成功；1 = 存在失败（供 cron/CI 感知部分失败）
"""
import logging
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

logger = logging.getLogger(__name__)


def main() -> int:
    from blog.bili_routes import _run_scrape
    from blog.models import BiliUp
    from app import create_app

    app = create_app()
    failed = 0
    with app.app_context():
        ups = BiliUp.query.all()
        for u in ups:
            try:
                print(f'Scraping {u.name}')
                _run_scrape(u.mid, u.space_url, app)
            except Exception as e:
                failed += 1
                print(f'Error scraping {u.name}: {e}')
                logger.exception('Scrape failed for %s', u.name)
    print(f'完成：{len(ups)} 个 UP，失败 {failed} 个')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
