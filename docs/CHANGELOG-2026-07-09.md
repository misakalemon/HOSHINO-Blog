# HOSHINO Blog 开发日志 —— 2026-07-09

> B站 数据集成、Canvas 取色器、移动端裁剪修复、项目文档整理

---

## 目录

- [Bilibili 数据集成](#bilibili-数据集成)
- [Bilibili 公开页面与搜索](#bilibili-公开页面与搜索)
- [Bilibili 扫码登录与爬取优化](#bilibili-扫码登录与爬取优化)
- [Bilibili 历史追踪与可视化](#bilibili-历史追踪与可视化)
- [移动端裁剪弹窗修复](#移动端裁剪弹窗修复)
- [取色器重构](#取色器重构)
- [项目配置与文档](#项目配置与文档)
- [待办](#待办)

---

## Bilibili 数据集成

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/09 14:15 | feat | 集成 bilibili_find — B站 UP 主视频数据爬取与管理后台 |
| 07/09 14:20 | fix | bili_routes.py 导入路径错误（relative import beyond top-level package） |
| 07/09 14:24 | fix | Bilibili 表单缺少 CSRF token 导致 POST 400 |
| 07/09 14:27 | fix | bilibili 模块缺少 config.py，配置误放在 `__init__.py` 中 |
| 07/09 14:30 | fix | 后台爬取线程缺少 Flask app context，缩进错误 |
| 07/09 14:35 | feat | 整合 B站 扫码登录（QR code 弹窗 + Cookie 持久化） |
| 07/09 14:45 | feat | 爬取进度实时展示（类似终端日志输出） |
| 07/09 14:59 | feat | UP主名称爬取、粉丝数、日期格式修复、登录状态修复、顶栏链接 |
| 07/09 15:03 | fix | 移除首页顶栏 B站 公开链接（仅保留后台侧边栏） |
| 07/09 15:11 | feat | B站公开页面 — 导航栏直达 UP 主列表/视频详情 |
| 07/09 15:16 | fix | BiliUp 表缺少 follower_count 列 — 添加自动迁移 |

新增文件：
- `blog/bili_routes.py` — Bilibili 后台管理路由
- `blog/bili_public_routes.py` — Bilibili 公开页面路由
- `blog/bilibili/__init__.py` — 模块包标记
- `blog/bilibili/config.py` — 模块配置
- `blog/bilibili/bili_api.py` — B站 API 封装
- `blog/bilibili/login.py` — 扫码登录 + Cookie 持久化
- `templates/admin/bili_index.html` — 后台 UP 主管理
- `templates/admin/bili_videos.html` — 后台视频数据表格
- `templates/bilibili.html` — 公开 UP 主列表
- `templates/bilibili_up.html` — 公开 UP 主视频页

### Bilibili 数据库模型

| 模型 | 说明 |
|------|------|
| `BiliUp` | UP 主信息（mid/name/avatar/follower_count/video_count） |
| `BiliVideo` | 视频数据（bvid/aid/title/description/各类统计数据） |
| `BiliUpHistory` | 粉丝数历史快照 |
| `BiliVideoHistory` | 视频统计数据历史快照 |

---

## Bilibili 公开页面与搜索

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/09 15:25 | feat | B站数据历史追踪 — 粉丝/播放量变化 + 视频详情页 |
| 07/09 15:34 | feat | ECharts 折线图 — 播放量/粉丝数变化可视化 |
| 07/09 15:40 | feat | BV 号可点击跳转到 B站 原视频 |
| 07/09 15:52 | perf | 多 UP 主并行爬取（移除全局锁，使用 per-mid 追踪） |
| 07/09 16:04 | feat | B站 UP 主搜索 + 页码改用首页样式（iter_pages/省略号/跳转） |
| 07/09 16:08 | feat | UP 主视频页面添加搜索功能（按标题模糊匹配） |
| 07/09 16:16 | feat | `/bilibili` 全局视频搜索（UP主/视频双模式切换） |
| 07/09 16:26 | feat | 定时任务 — 每天 02:00 自动刷新所有 B站 UP 主数据 |
| 07/09 16:32 | feat | B站后台 — 刷新单 UP 主按钮 + 删除二次确认增强 |
| 07/09 16:38 | feat | 列表项添加锚点 ID，返回时自动定位到原来位置 |
| 07/09 16:51 | fix | 视频发布时间显示 00:00 — 新增 pub_datetime 字段 |
| 07/09 16:57 | perf | 降低爬取速度 + 随机延迟，防止被 B站 风控拦截 |
| 07/09 21:31 | fix | bilibili-api-python 版本要求过高（>=18.0.0 不存在） |

新增文件：
- `templates/bilibili_video.html` — 视频详情页（简介/统计数据卡片/播放量折线图）

### Bilibili 路由表

**公开页面（`/bilibili`）**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/bilibili` | UP 主列表（支持搜索、UP主/视频双模式） |
| GET | `/bilibili/up/<id>` | UP 主视频列表 + 粉丝趋势图 |
| GET | `/bilibili/video/<id>` | 视频详情 + 播放量趋势图 |

**后台管理（`/admin/bilibili`）**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/bilibili/` | UP 主管理列表（含扫码登录） |
| GET | `/admin/bilibili/up/<id>` | UP 主视频数据表格 |
| POST | `/admin/bilibili/scrape` | 启动爬取（Ajax） |
| GET | `/admin/bilibili/scrape-status?mid=` | 爬取进度 JSON |
| GET | `/admin/bilibili/qr-gen` | 生成二维码（base64 PNG） |
| GET | `/admin/bilibili/qr-poll?key=` | 轮询扫码状态 |
| POST | `/admin/bilibili/logout-bili` | 清除 B站 Cookie |
| POST | `/admin/bilibili/refresh/<up_id>` | 刷新单 UP 主数据 |
| POST | `/admin/bilibili/delete/<up_id>` | 删除 UP 主 |
| POST | `/admin/bilibili/delete-video/<id>` | 删除视频记录 |

---

## 移动端裁剪弹窗修复

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/09 20:27 | fix | 裁剪弹窗审查修复 |
| 07/09 (补) | fix | file input `display:none` → iOS Safari 无法弹出 |
| 07/09 (补) | fix | `rteImageUpload` 动态 input 未挂载 DOM |
| 07/09 (补) | fix | resize 手柄 `min-width:480px` → 手机动态适配 |
| 07/09 (补) | fix | 裁剪视口添加 `touch-action:none` |

---

## 取色器重构

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/09 (补) | refactor | 取色面板改为 glow-select 统一样式 |
| 07/09 (补) | refactor | 点击直接弹出 Canvas 取色面板（移除原生 input[type=color]） |
| 07/09 (补) | feat | Canvas SV 饱和度/明度 + 色相条取色交互 |
| 07/09 (补) | feat | 鼠标拖动 + 触摸支持选色 |

---

## 项目配置与文档

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/08 22:14 | chore | 添加 environment.yml Conda 环境配置 |
| 07/09 21:26 | refactor | 优化导入和清理无用代码 |
| 07/09 21:45 | docs | 整理项目文档 — README/ARCHITECTURE/模块注释 |
| 07/09 21:51 | docs | README 安装步骤改为 Conda + environment.yml 补充 Bilibili 依赖 |

---

## 待办

- [ ] 部署后验证扫码登录 Cookie 持久化是否正常工作
- [ ] 确认每天 02:00 定时刷新生效
- [ ] 监控 B站 API 412 风控频率，必要时进一步调慢请求间隔
- [ ] 考虑添加 UP 主数据导出功能
