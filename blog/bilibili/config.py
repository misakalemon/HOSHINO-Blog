"""Bilibili 爬取模块配置 — 请求参数 / 路径 / Header"""

import os

# 当前文件所在目录（bilibili/）
BILI_DIR = os.path.dirname(os.path.abspath(__file__))
# 项目根目录（向上两级，从 blog/bilibili/ 到项目根）
PROJECT_ROOT = os.path.abspath(os.path.join(BILI_DIR, '..', '..'))

# ── API 请求参数 ────────────────────────────────
REQUEST_INTERVAL = 5.0          # 翻页间隔（秒）
PAGE_SIZE = 15                  # 每页视频数
MAX_RETRIES = 3                 # 最大重试次数（预留，当前逻辑用指数退避）
TIMEOUT = 15                    # HTTP 请求超时（秒，login.py 使用；API 调用另有 _API_TIMEOUT=30s）

# ── 凭证持久化路径 ────────────────────────────────
COOKIE_FILE = os.path.join(PROJECT_ROOT, ".bili_cookies.txt")           # 纯 Cookie 字符串文件（向后兼容）
CREDENTIAL_FILE = os.path.join(PROJECT_ROOT, ".bili_credential.json")   # 完整 Credential JSON（含 refresh_token，支持自动续期）

# ── 通用请求头 ──────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
    "Origin": "https://www.bilibili.com",
}
