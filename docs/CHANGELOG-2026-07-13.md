# HOSHINO Blog 开发日志 —— 2026-07-13

> B站 爬取稳定性修复 — 动态发现兜底 / 事件循环泄漏 / 粉丝数 fallback / 互斥保护

---

## 新增功能

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/13 | feat | **动态发现兜底** — `get_video_list_from_dynamics(mid)` 从用户动态流提取 BVID，捕获 `arc/search` 遗漏的 shorts/新视频 |
| 07/13 | feat | 动态发现输出 `[动态发现]` 前缀标识，日志中可见具体视频标题和来源 |

### 动态发现工作原理

```
get_dynamics_new()  → 用户动态流（最近 ~12 条）
    ↓
遍历 items:
  DYNAMIC_TYPE_AV → 直接提取 archive.bvid
  DYNAMIC_TYPE_FORWARD → 提取 orig 中的 archive.bvid
    ↓
Video.get_info(bvid) → 获取完整元数据
    ↓
验证 owner_mid == 目标 UP 主 → 排除转发视频
    ↓
返回视频列表（去重后）
```

**集成路径：**

- `_check_new_videos`（30 分钟增量检查）→ 动态兜底**始终执行**，在 arc/search 之后
- `_run_scrape`（每日深扫 / 手动刷新）→ 动态兜底**始终执行**，在补全阶段之后

---

## Bug 修复

| 时间 | 类型 | 严重度 | 说明 |
|------|------|--------|------|
| 07/13 | fix | **严重** | `filled_bvids` 包含全部 DB 视频导致 Hot/Warm/Cold 统计更新静默跳过 |
| 07/13 | fix | **严重** | `_sync` 超时后事件循环未正确关闭，导致 fd/线程资源持续泄漏 |
| 07/13 | fix | **严重** | 深扫与增量检查无互斥 — 同时检查 `_scrape_running` + `_incremental_running` |
| 07/13 | fix | **严重** | 调度器 `t.join()` 无超时，API 卡死导致调度器永久阻塞 |
| 07/13 | fix | **高** | 粉丝数 Cookie 过期后恒为 0 — `get_user_info` 匿名不返回 `follower` 字段 |
| 07/13 | fix | **高** | `get_video_list` 当 API 返回 `count=0` 时只翻 1 页就停止 |
| 07/13 | fix | **中** | `_check_new_videos` 早期返回时 `db.session.remove()` 被跳过 |
| 07/13 | fix | **中** | `_update_video` 统计获取失败返回 True（当作成功），改为返回 False 重试 |
| 07/13 | fix | **中** | `_parse_duration` 无异常保护 — 非法时长字符串导致整页迭代中断 |
| 07/13 | fix | **中** | `get_video_list_from_dynamics` 每视频无日志静默跳过，无重试等待 |
| 07/13 | fix | **低** | `_scrape_progress` 爬取完成后未清理 — 缓慢内存泄漏 |
| 07/13 | fix | **低** | 硬编码睡眠间隔不一致 — 改为模块常量 `_VIDEO_SLEEP_BASE/JITTER` |
| 07/13 | fix | **低** | `poll_qr_v2` 中 `get_credential()` 返回 None 未做 null 检查 |

### 粉丝数修复详情

**根因：** 当 Cookie 过期/匿名时，`x/space/wbi/acc/info` 返回的 JSON **不包含 `follower` 键**。代码 `info.get('follower') or 0` → `None or 0` → 粉丝数恒为 0。

**修复：** 加 fallback 到 `x/relation/stat`（`User.get_relation_info()`），该 API 在匿名模式下仍返回完整粉丝数。

### 统计更新静默跳过修复详情

**根因：** `filled_bvids = set(existing_ids) if fill_count else set()` 中 `existing_ids` 包含全部 DB 视频（如 650 个），`~BiliVideo.bvid.in_(filled_bvids)` 排除了所有视频，导致 Hot/Warm/Cold 阶段什么都不做。

**修复：** 用独立 set `fill_new_bvids` 只记录本次新增的视频，`filled_bvids = fill_new_bvids`。

---

## 代码变更量

| 文件 | + | - | 说明 |
|------|---|---|------|
| `blog/bilibili/bili_api.py` | +121 | -14 | 新增动态发现函数、事件循环修复、粉丝数 fallback、duration 保护、翻页修复 |
| `blog/bili_routes.py` | +150 | -25 | 动态兜底集成、filled_bvids 修复、睡眠常量、进度清理、会话移除 |
| `app.py` | +27 | -5 | 互斥保护、join 超时 |
| `blog/bilibili/login.py` | +3 | -0 | null 检查 |
| **合计** | **+301** | **-44** | |

---

## 测试验证

### 动态发现（生产环境日志 — 2026-07-13 01:07）

```
[笔吧评测室] [动态发现] 新视频 [1] RTX Spark亮相BW2026！...
[笔吧评测室] [动态发现] 新视频 [2] BW2026我来ROG展台了...
笔吧评测室: 增量完成，新增 2 个视频 — 动态兜底成功发现 arc/search 漏掉的视频
```

同一轮增量检查中，极客湾发现 1 个、TESTV 发现 2 个、影视飓风发现 4 个，全部由动态兜底捕获。

### 粉丝数验证

```
B站 API (x/space/acc/info): follower=None (匿名不返回)
x/relation/stat fallback:    follower=2,721,380
```

---

## 待办

- [ ] 考虑 `get_video_list_from_dynamics` 分页支持（当前只取第一页 ~12 条）
- [ ] 考虑视频数为 0 的 UP 主完整加时策略（动态发现 + 手动搜索）
- [ ] 评估 `refresh_token` 自动续期可行性（`Credential.refresh()`）
- [ ] 考虑 APScheduler 初始化失败时添加 Sentry/告警通知
