# HOSHINO Blog 开发日志 —— 2026-07-12

> B站 爬取架构重构 — 性能优化、健壮性提升、凭证持久化

---

## 目录

- [新增功能](#新增功能)
- [性能优化](#性能优化)
- [Bug 修复](#bug-修复)
- [架构重构](#架构重构)
- [样式优化](#样式优化)
- [配置变更](#配置变更)
- [待办](#待办)

---

## 新增功能

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/12 | feat | 增量检查追加最新 3 视频追踪 — 每30分钟快照播放/点赞/投币等统计（原为2条） |
| 07/11 | feat | 添加「刷新全部」按钮，无配额限制爬取UP主所有视频 |
| 07/11 | feat | 「刷新全部」增加 force 模式，跳过1h检查 + 无视Cookie过期 |
| 07/11 | feat | 遗漏检查工具 — 对比 API video_count vs DB 实际数 |
| 07/11 | feat | 每日刷新前检查DB视频数 < API总数时从 get_video_list 补全入库 |
| 07/10 | feat | 文章页添加打印按钮 |

### 三层更新策略（Hot/Warm/Cold）

| 分层 | 时间范围 | 年龄跳过 | 配额行为 |
|------|---------|---------|---------|
| **Hot** | ≤7天 | 不跳过 | 全部处理 |
| **Warm** | 8~30天 | 1小时内跳过 | 配额内，最久未更新优先 |
| **Cold** | >30天 | 24小时内跳过 | 配额内，最久未更新优先 |

---

## 性能优化

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/12 | perf | 共享事件循环 + 并发信号量（Semaphore 5）+ 线程错峰 + 连接池调优 |
| 07/12 | perf | 追踪不写 updated_at / 补全快速检测 / Hot/Warm/Cold三层 / 历史清理 / 调度合并 |
| 07/11 | perf | BiliVideo/BiliVideoHistory 复合索引优化查询 |
| 07/11 | perf | _update_video 跳过最近1小时内已更新的视频，减少无效API调用 |

---

## Bug 修复

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/12 | fix | P1 遗留死代码导致每日深扫必定以 NameError 崩溃（未定义变量 q） |
| 07/12 | fix | save_credential() 函数缺失导致 V2 扫码登录成功时 NameError |
| 07/12 | fix | apply_cookies() 从不加载 .bili_credential.json（含 refresh_token），重启后凭证丢失 |
| 07/12 | fix | 调度器并发防护 + 增量检查并行 + get_user_info 结果可靠性修复 |
| 07/11 | fix | 补全阶段多项隐性问题 |
| 07/11 | fix | 补全阶段插入加 try/except，避免 IntegrityError 导致整个爬取崩溃 |
| 07/11 | fix | 补全阶段支持崩溃恢复 — continue 代替 break + 精确 need 终止 |
| 07/11 | fix | _check_new_videos 翻页无限循环 — break 移到 continue 之前 |
| 07/11 | fix | 新UP主首次爬取不补全视频 + 初始化日志[?]前缀 |
| 07/11 | fix | 增量检查日志不可见问题 + 改进爬取日志输出格式 |
| 07/11 | fix | import time 移到函数顶层避免 emit 报 NameError |
| 07/11 | fix | P0≤10天 + P1 10~40天补旧（现已合并为 Hot/Warm/Cold三层） |
| 07/11 | fix | B站模块审查修复 — 每日刷新并行/P1超期break/delete_up防冲突/Cookie路径外移/status改用running集合/模板死代码 |
| 07/11 | fix | _check_new_videos 仅处理第一页15条 + 同时检查 aid 防重复 |
| 07/10 | fix | 数据库锁超时 — 连接池配置 + teardown 清理 + 线程 session 释放 |
| 07/10 | fix | 裁剪确认改用 st 状态避免 CSS 过渡导致坐标错乱 |

---

## 架构重构

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/12 | refactor | 增量检查遇到已知视频立即停止，不再固定翻2页 |
| 07/12 | refactor | Cookie过期自动降级 — get_video_list/get_video_stat/get_user_info 匿名重试 |
| 07/12 | refactor | 增量检查独立互斥集 _incremental_running，不再被每日深扫阻塞 |
| 07/12 | refactor | 每日刷新改为从DB查发布时间确定视频列表，不再调 get_video_list 翻页 |
| 07/11 | refactor | Phase1 改为处理≤30天视频，移除Phase2 |
| 07/11 | refactor | 增量检查遇到已知视频立即停止，不再固定翻2页 |

### 凭证持久化流程

```
V2扫码登录成功
  → save_credential(cred)    写入 .bili_credential.json（含refresh_token）
  → save_cookies(cookie_str) 写入 .bili_cookies.txt（兼容旧流程）

应用启动
  → apply_cookies()
      ├─ 优先加载 .bili_credential.json → Credential（支持自动续期）
      └─ 回退加载 .bili_cookies.txt → set_cookies()

API调用（Cookie过期时）
  → get_video_list / get_video_stat / get_user_info
      ├─ 尝试有凭证访问
      └─ 检测到 -401/未登录 → 自动降级为匿名重试
```

### 互斥集拆分

```
改造前:
  _scrape_running ← 每日深扫 + 增量检查共用 → 深扫10h阻塞增量20次

改造后:
  _scrape_running     ← 每日深扫 / 手动触发
  _incremental_running ← 增量检查（独立，不互斥）
```

---

## 样式优化

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/11 | style | 终端日志增加模块名/函数名/行号，与文件日志一致 |
| 07/11 | style | 日志格式优化 — 更紧凑易读 |
| 07/10 | style | 文章打印样式 — 隐藏导航栏/页脚，白底黑字清晰字体 |

---

## 配置变更

| 变更 | 说明 |
|------|------|
| `CREDENTIAL_FILE` | 新增 `.bili_credential.json` 路径配置（含 refresh_token 的完整 Credential） |
| `BiliVideoHistory` 清理周期 | 90天 → **365天** |
| 复合索引 | BiliVideo: `(up_id, pub_datetime)` + `(up_id, updated_at)` / BiliVideoHistory: `(video_id, recorded_at)` |

---

## 待办

- [ ] 部署后验证 V2 扫码登录 → 重启后 credential 自动加载是否正常
- [ ] 监控 B站 API 412 风控频率，必要时进一步调慢请求间隔
- [ ] 考虑添加 UP 主数据导出功能
- [ ] 考虑前端展示 BiliVideoHistory 趋势图（播放量/点赞 时序折线）
