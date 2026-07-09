"""Bilibili 模块配置"""
import os

# 请求间隔（秒）
REQUEST_INTERVAL = 1.0
PAGE_SIZE = 30
MAX_RETRIES = 3
TIMEOUT = 15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
    "Origin": "https://www.bilibili.com",
}
