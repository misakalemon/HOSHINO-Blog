# HOSHINO Blog 开发日志 —— 2026-08-31

> 三类故障根治：深扫饿死增量 / 词云阻塞 GIL 卡死服务 / 无业务日志静默事故

---

## 深扫饿死增量（02:00~04:00 增量全被跳过）

| 类型 | 说明 |
|------|------|
| fix | **增量互斥从「任意 UP 让路」改为「同 mid 让路」** — `_check_new_videos` 仅在 `mid in _scrape_running` 时跳过本次增量；深扫 UP-A 期间，UP-B/C/D 订阅者的新视频通知照常发送 |
| fix | **Worker 批次级协调同步调整** — `_run_bili_incremental_check` 不再因任意深扫跳过整批，提交阶段仅跳过正在深扫的同一 mid（`_check_new_videos` 内部亦有同 mid 互斥兜底） |
| security | **并发安全性论证** — 全局令牌桶 `BILI_GLOBAL_RATE_CAP=1` 已将 B站 请求全局串行（同一时刻仅 1 个请求在途），不同 UP 并发不增加请求频率，不会触发 -352 风控 |

## 深扫提速 + 整体硬 deadline

| 类型 | 说明 |
|------|------|
| perf | **`_BATCH_SIZE` 默认 1 → 3**（`BILI_BATCH`，上限 4）：深扫由逐个 UP 串行改为 3 个 UP 并行，令牌桶兜底限速不增加风控压力 |
| fix | **新增整体硬 deadline** — `BILI_DAILY_DEADLINE`（默认 90 分钟）：`run_daily_scrape` 到达 deadline 后不再启动新批次。02:00 深扫最迟约 03:30 结束，绝不撞 04:00/04:30 词云窗口，也不把增量饿死到 04:00 |

## 词云独立子进程（GIL 彻底隔离）

| 类型 | 说明 |
|------|------|
| feat | **新增 `blog/wordcloud_runner.py`** — 独立解释器进程入口（`python -m blog.wordcloud_runner --all | --bili`），`create_app()`（WORKER_PROCESS=1 跳过迁移）后调用 `precompute_all_wordclouds()` / `precompute_bili_wordclouds()` |
| fix | **Worker 调度改为 spawn 子进程** — 04:00 全站词云、04:30 B站词云改为 `subprocess.Popen([sys.executable, '-m', 'blog.wordcloud_runner', ...])`。jieba 全量分词在独立解释器内运行，与爬虫进程彻底隔离 GIL/内存（根治 04:54 后日志戛然而止的进程级卡死） |
| chore | **B站词云改为周更** — `BILI_BILI_WC_CRON`（默认 `30 4 * * 1` = 每周一 04:30；留空=每日 04:30） |

## 独立日志看门狗（告警 + 可选重启 + 邮件）

| 类型 | 说明 |
|------|------|
| feat | **新增 `blog/logwatch.py`** — 随 app.py 启动的独立守护子进程，监听 Worker 业务心跳文件 `blog/logs/.activity`（时间戳 + 最近业务活动类型，只写文件、不写日志，与「移除刷屏心跳日志」兼容） |
| feat | **Worker 心跳写入** — `record_activity()`：增量/深扫/词云/任务完成任一业务活动即时更新心跳；主循环每 `BILI_ACTIVITY_INTERVAL`（默认 5 分钟）兜底刷新 |
| feat | **僵死判定与告警** — 心跳 mtime 超 `BILI_WATCHDOG_MINUTES`（默认 30）分钟未更新 → 写 ERROR 日志 + `send_email` 告警邮件（主题 `[BILI Watchdog] 业务无活动超 XXX 分钟`，正文含最近心跳时间戳；收件人 `BILI_WATCHDOG_EMAILS`，留空用 `ADMIN_EMAIL`） |
| feat | **可选重启** — `BILI_WATCHDOG_RESTART`：0=仅告警；1=kill 旧 Worker（PID 记录于 `blog/logs/worker.pid`）+ Popen 拉起；2=整个进程组 SIGTERM（Web+Worker，外部守护接管）。附带告警/重启冷却，避免重复轰炸与重启风暴 |
| feat | **自愈容错** — 看门狗主循环独立 try/except，任一异常不终止本守门进程；告警邮件懒加载 `create_app()`，初始化/发送失败只记日志不影响判定 |

## 新增环境变量

```ini
# ── 爬取调度 ──
BILI_BATCH=3                    # 深扫并行 UP 数（默认 3，上限 4）
BILI_DAILY_DEADLINE=90          # 深扫整体硬 deadline（分钟），超时不再启动新批
# ── 词云调度 ──
BILI_BILI_WC_CRON='30 4 * * 1'  # B站词云周更（标准5段crontab，默认每周一04:30；留空=每日）
# ── 日志看门狗 ──
BILI_ACTIVITY_INTERVAL=5        # Worker 心跳文件刷新间隔（分钟）
BILI_WATCHDOG_MINUTES=30        # 无业务活动判定阈值（分钟）
BILI_WATCHDOG_RESTART=1         # 0=仅告警 1=重启Worker 2=重启进程组
BILI_WATCHDOG_EMAILS=           # 告警邮件收件人（留空=用 ADMIN_EMAIL）
BILI_WATCHDOG_CHECK=60          # 看门狗判定循环间隔（秒，调试可调小）
```

---

## 技术细节

### 心跳链路

```
Worker 业务活动（增量/深扫/词云/任务完成）
        │ record_activity(type)
        ▼
blog/logs/.activity ──► logwatch.py 判定循环
  时间戳 + 业务类型      │ mtime 超 BILI_WATCHDOG_MINUTES
                        ▼
              ERROR 日志 + 告警邮件
                        │ BILI_WATCHDOG_RESTART
                        ├─ 0: 仅告警
                        ├─ 1: kill worker.pid + 重新 Popen
                        └─ 2: 进程组 SIGTERM（外部守护接管）
```

### 词云子进程链路

```
Worker APScheduler (04:00 / BILI_BILI_WC_CRON)
        │ subprocess.Popen
        ▼
python -m blog.wordcloud_runner --all | --bili ← 独立解释器
        │ create_app(WORKER_PROCESS=1) + app_context
        ▼
precompute_all_wordclouds() / precompute_bili_wordclouds()
        → 与爬虫进程彻底隔离 GIL/内存，失败退出码非 0 不影响主进程
```

### 验证手段

1. `python -m py_compile` 全部改动文件（bili_routes.py / worker.py / app.py / wordcloud_runner.py / logwatch.py）
2. 增量互斥模拟：深扫 mid=A 时，A 的增量让路、B 的增量放行
3. 看门狗冒烟：`BILI_WATCHDOG_MINUTES=1` + 打桩告警邮件，确认 心跳→超时→告警 链路

---

## 启动修复（Windows 实测）

| 类型 | 说明 |
|------|------|
| fix | **logwatch/wordcloud_runner 子进程 ModuleNotFoundError** — 直接执行 `python blog/logwatch.py` 时 `sys.path[0]=blog/`，`import blog.logger` 失败。app.py 改为 `python -m blog.logwatch`（cwd=项目根）拉起；两个模块顶部均注入项目根到 `sys.path` 兜底 |