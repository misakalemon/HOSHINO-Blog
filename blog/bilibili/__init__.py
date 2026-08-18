"""HOSHINO Blog — Bilibili 数据模块

B站 UP 主视频数据爬取、V2 扫码登录、双路径视频发现。

模块结构:
  config.py     — 请求间隔 / 页大小 / Cookie 路径 / UA
  bili_api.py   — 核心 API 封装（视频列表 / 动态发现 / 统计 / 粉丝数 / 并发控制）
  login.py      — V2 扫码登录 + Credential/Cookie 持久化 + 启动自动加载
"""

import os

# ── 代理支持（必须在 bilibili_api / requests 发起任何请求之前设置）──
# BILI_PROXY 设置后：
#   - bilibili-api-python 的 httpx 客户端（trust_env=True）自动走代理
#   - login.py 的 requests 自动走代理
# 海外服务器访问 B站 建议配置；国内直连无需设置。
_PROXY = os.environ.get('BILI_PROXY', '').strip()
if _PROXY:
    os.environ.setdefault('HTTP_PROXY', _PROXY)
    os.environ.setdefault('HTTPS_PROXY', _PROXY)
    os.environ.setdefault('http_proxy', _PROXY)
    os.environ.setdefault('https_proxy', _PROXY)
