# HOSHINO Blog 开发日志 —— 2026-07-23

> 词云系统架构重铸 — 异步队列 + ZLIB 压缩 + UP 主页聚合词云

---

## 词云异步改造

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/23 | feat | **新增 `submit_task()` 后台任务队列** — `blog/wordcloud.py` 新增 `_task_queue` + `_worker_loop` 单线程消费者 |
| 07/23 | refactor | **所有用户触发词云计算改为异步投递** — 发布/编辑/删除文章、手动重算、刷新UP评论/字幕后，不再同步执行 jieba 分词，HTTP 请求即时返回 |
| 07/23 | feat | `admin.py` 4 处同步调用 → `submit_task('post')` / `submit_task('site')` / `submit_task('all')` |
| 07/23 | feat | `bili_routes.py` 2 处同步调用 → `submit_task('bili_up', up_id=...)` |

### 队列设计

```
                submit_task('post', post_id=x)
                submit_task('site')
                submit_task('all')                ┌─────────────────┐
                submit_task('bili_up', up_id=x)   │  _worker_loop   │
                  ↓                               │  单线程守护线程  │
              _task_queue ──────────────────────→ │  with app_ctx:  │
                (Queue)                           │   分发到预计算函数│
                                                  └─────────────────┘
```

- 定时任务（02:10 / 02:15）不走队列，仍直接调用预计算函数
- `_wc_queue`（新视频入库词云）保持不变，仍由 `_wc_worker` 直接消费

## ZLIB 压缩存储

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/23 | feat | **新增 `CompressedJSON` TypeDecorator** — `blog/models.py`，写入自动 `zlib.compress()`，读取自动 `zlib.decompress()`，对业务代码完全透明 |
| 07/23 | feat | **自动迁移** — `blog/__init__.py` `_migrate_wordcloud_data_compress()`，启动时检查并压缩已有数据（MySQL COMPRESS → 标准 zlib 格式） |

## UP 主页聚合词云修复

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/23 | fix | **`precompute_up_wordclouds` 新增 UP 主聚合词云** — 刷新评论/字幕时，不仅更新单视频词云 (`source='bili_video'`)，还汇总全部文本刷新 UP 主页聚合词云 (`source='bili', period='up_{id}'`) |

此前刷新评论/字幕后，UP 主页词云仅在全量定时任务 02:15 更新，评论刷新不生效。

## 词云架构全貌

```
文本来源权重：字幕×5 > 标题×3 > 评论×2 > 标签×2 > 简介×1
存储格式：zlib 压缩 BLOB，每条 1~3KB
聚合维度：视频 → UP 主 → 月度 → 全站
计算入口：
  ├─ 定时 02:10  precompute_all_wordclouds()         博客全站+单篇
  ├─ 定时 02:15  precompute_bili_wordclouds()         B站全站+按月+按UP+单视频
  ├─ 后台队列    submit_task(type, **kwargs)          用户触发（4 种类型）
  └─ 视频队列    _wc_queue → _wc_worker              新视频入库增量
```

---

## 涉及文件

| 文件 | 改动 |
|------|------|
| `blog/models.py` | +CompressedJSON TypeDecorator（zlib 透明压缩） |
| `blog/wordcloud.py` | +_task_queue / _ensure_worker / _worker_loop / submit_task；precompute_up_wordclouds 末尾追加 UP 聚合词云 |
| `blog/__init__.py` | +_migrate_wordcloud_data_compress 迁移函数 |
| `blog/admin.py` | 4 处 submit_task 替换同步调用 |
| `blog/bili_routes.py` | 2 处 submit_task 替换同步调用 |
