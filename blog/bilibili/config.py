"""Bilibili 爬取模块配置 — 请求参数 / 凭证路径 / 通用 Header

集中管理 B站爬取相关的所有配置常量，包括：
  - API 请求参数：翻页间隔、每页数量、超时时间
  - 凭证持久化路径：Cookie 文件（向后兼容）和 Credential JSON（V2 登录）
  - 通用请求头：User-Agent / Referer / Origin（模拟浏览器访问）

这些参数被 bili_api.py 和 login.py 引用，
修改此文件可统一调整爬取行为（如降低频率避免风控）。
"""

import os

# 当前文件所在目录（bilibili/）
BILI_DIR = os.path.dirname(os.path.abspath(__file__))
# 项目根目录（向上两级，从 blog/bilibili/ 到项目根）
PROJECT_ROOT = os.path.abspath(os.path.join(BILI_DIR, '..', '..'))

# ── API 请求参数 ────────────────────────────────
# 这些参数控制 B站 API 请求的频率和数量，影响爬取速度和风控风险
# 核心原则：低频 + 随机抖动，模拟人类浏览行为
REQUEST_INTERVAL = 8.0          # 翻页间隔基础值（秒）— 最终值 = 基础值 + random(0, JITTER)
REQUEST_INTERVAL_JITTER = 4.0   # 翻页间隔随机抖动范围（秒），避免固定频率被检测
PAGE_SIZE = 15                  # 每页视频数 — B站 API 单次返回的最大视频条目数
MAX_RETRIES = 3                 # 最大重试次数（预留，当前逻辑用指数退避）
TIMEOUT = 15                    # HTTP 请求超时（秒，login.py 使用；API 调用另有 _API_TIMEOUT=30s）

# ── 凭证持久化路径 ────────────────────────────────
# V2 扫码登录后，凭证保存到本地文件，下次启动自动加载
# 优先级：CREDENTIAL_FILE > COOKIE_FILE（见 login.py apply_cookies）
COOKIE_FILE = os.path.join(PROJECT_ROOT, ".bili_cookies.txt")           # 纯 Cookie 字符串文件（向后兼容）
CREDENTIAL_FILE = os.path.join(PROJECT_ROOT, ".bili_credential.json")   # 完整 Credential JSON（含 refresh_token，支持自动续期）

# ── User-Agent 轮换池 ─────────────────────────────
# 多个不同浏览器版本的 UA，每次请求随机选取，模拟真实浏览器访问
# B站对同一 UA 做频率统计，轮换 UA 可降低被识别为爬虫的风险
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:120.0) Gecko/20100101 Firefox/120.0",
]

# ── 通用请求头 ──────────────────────────────────
# 模拟 Chrome 浏览器访问，避免 B站 API 返回 403
# Referer 和 Origin 是 B站 API 防盗链校验的必要字段
HEADERS = {
    "User-Agent": USER_AGENTS[0],    # 默认 UA，bili_api.py 中会被随机轮换
    "Referer": "https://www.bilibili.com/",
    "Origin": "https://www.bilibili.com",
}
