"""B站 全量刷新：对所有 UP 主执行完整爬取"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from blog.bili_routes import _run_scrape
from blog.models import BiliUp
from app import create_app

app = create_app()
with app.app_context():
    ups = BiliUp.query.all()
    for u in ups:
        try:
            print(f'Scraping {u.name}')
            _run_scrape(u.mid, u.space_url, app)
        except Exception as e:
            print(f'Error scraping {u.name}: {e}')
            import logging
            logging.getLogger(__name__).exception('Scrape failed for %s', u.name)
