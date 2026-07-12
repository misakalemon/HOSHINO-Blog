"""HOSHINO Blog — Bilibili 数据模块

B站 UP 主视频数据爬取、V2 扫码登录、双路径视频发现。

模块结构:
  config.py     — 请求间隔 / 页大小 / Cookie 路径 / UA
  bili_api.py   — 核心 API 封装（视频列表 / 动态发现 / 统计 / 粉丝数 / 并发控制）
  login.py      — V2 扫码登录 + Credential/Cookie 持久化 + 启动自动加载
"""
