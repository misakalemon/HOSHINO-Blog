"""Bilibili 模块配置"""
import os

BILI_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BILI_DIR, '..', '..'))

# 请求间隔（秒）— 爬慢一点防止被 B站 风控
REQUEST_INTERVAL = 5.0
PAGE_SIZE = 15
MAX_RETRIES = 3
TIMEOUT = 15

# Cookie 保存路径（在项目根目录，不随部署覆盖）
COOKIE_FILE = os.path.join(PROJECT_ROOT, ".bili_cookies.txt")
# Credential 完整状态（含 refresh_token，支持自动续期）
CREDENTIAL_FILE = os.path.join(PROJECT_ROOT, ".bili_credential.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
    "Origin": "https://www.bilibili.com",
}
