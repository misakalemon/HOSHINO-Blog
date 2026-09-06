# HOSHINO Blog 开发日志 —— 2026-07-23

> 词云系统完整升级 — 异步队列 / ZLIB 压缩 / 自定义图片形状 / 线程安全审计 / 内存优化

---

## 词云自定义形状

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/23 | feat | **新增 `shape_image` 字段** — `WordCloudConfig` 模型增加自定义形状图片支持 |
| 07/23 | feat | **上传 PNG/WebP/JPEG 定义词云边界** — 上传区复用项目中 `icon-upload` 样式，Magic Bytes + PIL 双重校验 |
| 07/23 | feat | **`_isInsideCustom` 像素级形状检测** — `wordcloud.js` 离屏 Canvas 加载图片后提取 alpha 通道，词条放置时逐像素判断 |
| 07/23 | feat | **自动切换形状** — 上传图片时强制 `shape='custom'`，无需手动切下拉 |
| 07/23 | feat | **迁移自动补列** — `_migrate_wordcloud_config_fields` 逐列检查 10 个字段 + `shape_image` |

## 词云面积优化

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/23 | fix | **字号改为 `max`** — `maxFont = Math.max(refMax, h*0.18)`，500px 画布最大词从 50px → 90px |
| 07/23 | fix | **螺旋参数加大** — `radiusStep 2→3`、`angleStep 0.3→0.25`、`maxAttempts 3000→5000` |
| 07/23 | fix | **`v=5` 强制清缓存** — 所有模板中 `wordcloud.js?v=2/4 → v=5` |

## 线程安全审计

| 文件 | 修复项 |
|------|--------|
| `bili_routes.py` | `_circuit_open_until` 加 `_circuit_lock` 保护 7 处读写 |
| `bili_routes.py` | `run_daily_scrape` 超时线程清理 `_scrape_running` |
| `mail.py` | `t.join()` 移至 `_mail_lock` 外 |
| `app.py` | 增量检查超时后清理 `_incremental_running` |
| `app.py` | MySQL 不可达时 30 秒快速重试 + `❌` 级别日志 |

## 死代码清理

| 文件 | 删除内容 |
|------|----------|
| `admin.py` | `from collections import defaultdict`（未使用） |
| `forms.py` | 冗余 `from wtforms.validators import Regexp` |
| `models.py` | `ExchangeRate` 类（0 引用） |
| `cache.py` | `cache_scan()` 函数（0 调用） |
| `apify_client.py` | `set_proxy()` 方法（0 调用） |

---

## 涉及文件完整列表

| 文件 | 改动 |
|------|------|
| `blog/models.py` | +`shape_image` 列、`to_dict()` 加 `shapeImage`、删除 `ExchangeRate` 类 |
| `blog/admin.py` | `wordcloud_config` 路由加图片上传/验证/存储 |
| `blog/forms.py` | 形状下拉加 `custom` 选项 |
| `blog/__init__.py` | 迁移补 `shape_image` 列 + 其他 10 个字段 |
| `blog/bili_routes.py` | `_circuit_lock` 保护、超时线程清理 |
| `blog/wordcloud.py` | 移除 `jieba.enable_parallel`、分批处理、GC/内存监控 |
| `blog/mail.py` | `join` 移出锁外 |
| `blog/cache.py` | 删除 `cache_scan()` |
| `blog/apify_client.py` | 删除 `set_proxy()` |
| `app.py` | 增量超时清理 + MySQL 熔断 |
| `static/js/wordcloud.js` | `_loadShapeImage` / `_isInsideCustom`、字号缩放、螺旋参数 |
| `static/js/base.js` | 导航栏滚动阈值 |
| `templates/admin/wordcloud_config.html` | 上传区 UI + JS |
| `templates/index.html`/`.html` | `wordcloud.js?v=5` |