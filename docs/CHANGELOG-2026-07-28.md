# HOSHINO Blog 开发日志 —— 2026-07-28

> Tiptap 编辑器工具栏固定修复 / B站单个视频爬取功能 / 数据库迁移优化

---

## Tiptap 编辑器工具栏固定

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/28 | fix | **工具栏在 `backdrop-filter` 容器内无法固定** — `.admin-card` 有 `backdrop-filter: blur(14px)` 创建新的包含块，导致 `position: fixed` 不相对于视口定位 |
| 07/28 | fix | **将工具栏移到 body 下** — 固定时将工具栏 DOM 移至 `document.body`，脱离 `backdrop-filter` 的影响 |
| 07/28 | fix | **添加占位符防止布局跳动** — 创建 `.rte-toolbar-placeholder` 保持原位置高度 |
| 07/28 | fix | **PostCSS 压缩删除 `.is-fixed` 样式** — 在模板中直接添加 `.rte-toolbar.is-fixed` 样式确保生效 |
| 07/28 | style | **固定工具栏添加底部圆角** — `border-radius: 0 0 12px 12px` |

## B站单个视频爬取功能

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/28 | feat | **新增 `get_video_full_info()` 函数** — 获取单个视频完整信息（标题、播放量、封面等） |
| 07/28 | feat | **新增 `/add-video` 路由** — 处理单个视频添加请求 |
| 07/28 | feat | **支持多种输入格式** — BV 号（`BV1xx411c7mD`）、AV 号（`av2`）、视频链接 |
| 07/28 | feat | **AV 号转 BV 号算法** — 实现 AV 到 BV 的转换算法 |
| 07/28 | feat | **检查视频是否已存在** — 已存在时弹出确认框，询问用户是否更新统计数据 |
| 07/28 | feat | **自动创建 UP 主记录** — 只保存基本信息（mid、名称、头像），不爬取完整信息 |
| 07/28 | feat | **保存视频封面** — `BiliVideo` 添加 `pic` 字段存储封面 URL |
| 07/28 | feat | **创建视频历史记录** — 自动创建 `BiliVideoHistory` 记录用于数据追踪 |

## 前端界面优化

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/28 | ui | **分区显示** — UP 主管理（👤）和单个视频（🎬）分成两个独立区域 |
| 07/28 | ui | **添加单个视频输入框** — 支持 BV 号、AV 号、视频链接输入 |
| 07/28 | ui | **确认对话框** — 视频已存在时显示详细信息并询问是否更新 |

## 数据库迁移

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/28 | db | **新增 `pic` 字段** — `BiliVideo` 模型添加 `pic` 列存储视频封面 URL |
| 07/28 | db | **迁移脚本** — `a1b2c3d4e5f6_add_bili_video_pic.py` |

---

## 技术细节

### 工具栏固定原理

```
问题：backdrop-filter 创建新的包含块
      ↓
position: fixed 不再相对于视口定位
      ↓
解决：将工具栏移到 body 下
      ↓
脱离 backdrop-filter 的影响
      ↓
position: fixed 正常工作
```

### 单个视频爬取流程

```
用户输入 BV 号/AV 号/链接
      ↓
解析并转换为 BV 号
      ↓
检查数据库是否已存在
      ↓
是 → 弹出确认框 → 用户确认 → 更新统计
否 → 获取视频完整信息 → 创建记录
      ↓
创建/更新 UP 主（仅基本信息）
      ↓
创建视频历史记录
      ↓
返回成功提示
```

---

## 涉及文件完整列表

| 文件 | 改动 |
|------|------|
| `src/editor/full.js` | 工具栏移到 body 下、占位符逻辑、destroy 清理 |
| `templates/admin/post-form.html` | 添加 `.is-fixed` 样式、底部圆角 |
| `blog/bilibili/bili_api.py` | 新增 `get_video_full_info()` 函数 |
| `blog/bili_routes.py` | 新增 `/add-video` 路由、检查已存在、AV 转 BV |
| `blog/models.py` | `BiliVideo` 添加 `pic` 字段 |
| `templates/admin/bili_index.html` | 分区显示、单个视频输入框、确认对话框 |
| `migrations/versions/a1b2c3d4e5f6_add_bili_video_pic.py` | 数据库迁移脚本 |
| `static/js/tiptap-editor.js` | 构建产物更新 |
| `static/css/tiptap-editor.css` | 构建产物更新 |