"""价格爬虫：手动触发价格数据爬取"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from blog.crawler import crawl_all_active_sources
from app import create_app

create_app()
crawl_all_active_sources()
