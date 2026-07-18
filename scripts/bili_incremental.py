"""B站 增量检查：检查所有 UP 主的新视频并入库"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from blog.bili_routes import _check_new_videos
from blog.models import BiliUp
from app import create_app

app = create_app()
with app.app_context():
    ups = BiliUp.query.all()
    for u in ups:
        print(f'Checking {u.name}')
        _check_new_videos(u.mid, app)
