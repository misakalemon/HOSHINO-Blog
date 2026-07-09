"""
HOSHINO Blog — Bilibili 数据模块

提供 B站 UP 主视频数据爬取、扫码登录、数据展示功能。

模块结构:
  config.py     — 请求间隔、Cookie 路径、HTTP 头等配置
  bili_api.py   — bilibili-api-python 封装（视频列表/统计/用户信息）
  login.py      — 扫码登录 + Cookie 持久化
  cookies.txt   — 持久化的登录 Cookie（自动生成）
"""
