# CHANGELOG 2026-09-06

## 概要

本次更新完成 **API 能力增强**、**后台模块补齐**、**项目结构深度重构** 三大方向，共 12 个提交。

---

## 一、API 改造（blog/core/api.py）

### 新增端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/posts/<id_or_slug>` | DELETE | 删除文章（级联清理评论+分类关联） |

### 增强项

- **categories 支持 name 查询**：slug 未命中自动按 name 查（如 `"Agent"`）
- **响应增加 `url` 字段**：完整可读 URL，复制即用
- **响应增加 `word_count` 字段**：正文字数
- **schema 校验错误改 422**：与 400（请求体格式错误）区分，客户端可程序判断
- **列表 `?q=` 模糊搜索**：按标题/摘要搜索

### 上传脚本（tools/upload_post.py）

```bash
# 发布新文
python tools/upload_post.py posts/my.md --token TOKEN --site https://... --publish

# 更新已有
python tools/upload_post.py posts/my.md --token TOKEN --update

# 仅预检
python tools/upload_post.py posts/my.md --token TOKEN --dry-run
```

- YAML front matter 解析
- 内置 schema 校验（title/slug/content/categories 长度+格式）
- slug 唯一性预检（先 GET 检查，避免浪费 POST）
- `--update` / `--dry-run` / `--publish` / `--html` 标志
- 指数退避 retry（针对 5xx 和网络超时）
- 响应落盘 + 打印 id/slug/URL/created_at

---

## 二、后台模块补齐

### 分类管理增强（/admin/categories）

- **搜索**：按名称或 slug 模糊搜索
- **排序**：按名称 / 文章数 / 创建时间
- **批量删除**：checkbox 全选 + 批量删除
- **合并分类**：将源分类的所有文章转移到目标分类，删除源分类

### 数据导出（/admin/export）

| 格式 | 说明 |
|------|------|
| 文章 Markdown（ZIP） | 每篇一个 .md，含 YAML front matter，兼容 Hugo/Jekyll |
| 文章 JSON | 结构化 JSON，含全量字段 |
| 全站数据 JSON | 全部数据库表，完整迁移 |
| 分类列表 CSV | Excel 可直接打开 |

### 数据导入（/admin/import）

- 从 JSON 或 Markdown ZIP 导入文章
- 支持预检（dry-run）和覆盖模式
- 作者按 username 匹配，分类按 name 匹配

### 定时备份/清理设置（/admin/backup）

配置从环境变量改为 DB 存储（SiteSetting），后台可视化设置：

- **调度模式**：每天 / 每小时 / 每 N 小时 / 每周
- **执行时间**：时 + 分（5 分钟步进）
- **备份类型**：full / db / uploads
- **自动清理**：保留份数 + 保留天数（取并集，0=不限）

---

## 三、项目结构深度重构

### blog/ 拆分为 4 个子包

```
blog/
├── core/         核心业务（models/admin/routes/api/forms/cache/settings/utils）
├── bilibili/     B站相关（admin_routes/public_routes + 原有 bili_api/config/login）
├── infra/        基础设施（logger/logwatch/mail/task_queue/backup）
├── wordcloud/    词云（generator/runner）
└── __init__.py   包初始化
```

- 17 个文件 `git mv` 到子包
- 76 处相对 import + 135 处绝对 import 批量替换
- 跨包引用修正（`from . import` → `from .. import`）
- 同包引用修正（`from .bilibili.bili_api` → `from .bili_api`）

### 根目录整理

- 合并 `scripts/` → `tools/`（消除目录重叠）
- 15 个 CHANGELOG 归档到 `docs/changelog/`
- `.gitignore` 去重清理
- 删除临时文件（`_tmp_test.db`、`.coverage`）

### 日志目录迁移

- `blog/logs/` → 根目录 `logs/`（方便查看）
- `logger.py` LOG_DIR 改为项目根目录
- `logwatch.py` 路径计算修正

### 清理

- 删除 `launcher.py`（Eel GUI 启动器，不再使用）

---

## 四、测试覆盖

| 模块 | 测试文件 | 测试数 | 覆盖率 |
|------|----------|--------|--------|
| `blog/core/cache.py` | test_cache.py | 28 | 100% |
| `blog/infra/task_queue.py` | test_task_queue.py | 64 | 100% |
| `blog/infra/backup.py` | test_backup.py | 54 | 88% |
| `blog/core/settings.py` | test_settings.py | 47 | 100% |
| `blog/core/api.py` | test_api.py | 114 | 98% |
| **总计** | | **307** | **94%** |

- 支持 SQLite 测试后端（`TEST_DB_BACKEND=sqlite`），无需 MySQL
- `pure` marker 隔离纯函数测试与 DB 依赖测试

---

## 五、提交记录

| 提交 | 内容 |
|------|------|
| `459470d` | test: cache.py + task_queue.py 单元测试 |
| `ababa65` | feat(admin): 增强分类管理——搜索/排序/批量删除/合并 |
| `fdbea83` | feat(admin): 数据导出/导入模块 |
| `b9e2abf` | test: backup/settings/api 单元测试 |
| `0e50f02` | feat(api): DELETE 端点 + categories name + 响应增强 + upload_post.py |
| `f4e6020` | feat(backup): 可自定义定时备份和定时清理 |
| `6217d01` | refactor: 深度重构 blog/ 为 core/infra/wordcloud/bilibili 子包 |
| `07bcc3c` | chore: 整理项目根目录 |
| `50dcea0` | chore: 日志目录移到根目录 logs/ + 删除 launcher.py |