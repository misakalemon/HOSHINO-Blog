# Hoshino Blog 开发日志

## 2026-06-30 本次改版

### 全站主题改版（Hoshino）
- 博客标题全面改为「Hoshino」，副标题「—— 星野、参上！——」
- 粉紫色系全新 UI：光晕粉色 `#ff6b9d` + 紫色 `#a855f7`，渐变粉紫
- 英雄区文案改为「最喜欢小鸟游星野」，粉色高亮
- 删除旧版 `harmonyos.css` / `tech.css`
- 新增 `glow-design.css` 光感设计系统（1180+ 行）
- 新增 `glow-controller.js` 交互控制（340+ 行）
- 删除 `harmonyos.css` / `tech.css`（3612 行 + 619 行）
- 所有后台模板样式适配粉紫主题

### 特色卡片系统
- 新增 `FeaturedCard` 数据模型（icon/tag/link/sort_order 等字段）
- 后台 CRUD：列表/新建/编辑/删除（`/admin/featured-cards/*`）
- 标签下拉框从 `Category` 表动态读取，共用分类数据库
- 图标支持 emoji 或图片上传，前台自动判断渲染方式
- 卡片可点击跳转（link 字段）
- 图片点击灯箱查看全图

### 分类与种子数据
- 新增分类：二次元（anime）/ 数码（digital）/ 军事（military）
- 保留原有 10 个技术分类不变
- 创建 6 张特色卡片（小鸟游星野/手办收藏/圣地巡礼/外设鉴赏/数码好物/军事模型）

### 前端交互优化
- 鼠标追踪光效（CSS custom property 方案）
- 自定义下拉框 glow-select-wrap（全站 select 自动转换）
- 图片灯箱（点击查看全图，深色遮罩 + 高斯模糊背景）
- 移动端抽屉导航（点击标题弹出左侧滑出侧栏）
- 移除汉堡按钮，仅保留标题点击触发

### 样式增强
- 所有卡片统一 `backdrop-filter: blur(10px)` 高斯模糊
- 内容区加宽 1200px → 1320px
- 侧边栏收窄 320px → 260px
- 文章图片移除固定 200px 高度，支持横图/竖图自适应
- 新增 `.tag-digital` 青色标签配色
- 搜索框颜色改为粉紫主题

### 修复
- 首页无限刷新（自定义下拉初始化不触发 change 事件）
- 模板路径 `.` → `/` 导致 500 错误
- 图标字段 `String(16)` → `String(256)` 存不下图片路径
- 无分类时创建卡片卡死（跳转到分类创建页 + 表单验证闪现）
- 移动端侧栏按钮被 z-index 遮挡（抽屉移出 navbar 独立层级）
- 桌面端导航栏消失（恢复 nav-links 到 navbar 内）

### 可配置化
- `BLOG_SUBTITLE` 环境变量：首页英雄区副标题可配置

### 代码注释 + 文档
- 全部 Python 文件添加中文注释（app.py / config.py / blog/*.py）
- 全部 JS/CSS 文件添加中文注释
- 全部 24 个 Jinja2 模板添加中文注释
- 新增 `docs/ARCHITECTURE.md` 技术架构文档
- 新增 `docs/CHANGELOG.md` 开发日志

---

## 历史记录

### 2026-06-29
- 全站图标替换为 HarmonyOS Icons（字体图标）
- admin 表格按钮文字可见性修复
- Secret Key 轮换跳过 `.env` 显式设置
- SESSION_COOKIE_SECURE 可通过 .env 覆盖
- CSRF / XSS / Rate-limit / Session 安全加固

### 2026-06-10 ~ 2026-06-28 功能迭代
- 多对多分类迁移（v1 → v2）
- 价格追踪系统（Amazon 爬虫 + Exa API）
- 汇率查询与实时汇率 API
- 图片缩略图生成 + 上传自动压缩
- RSS / Sitemap 输出
- 全量后台管理面板（用户/分类/评论 CRUD）
- 评论系统与审核流程
- Secret Key 自动轮换机制
- 安全加固（CSRF / XSS / Rate-limit / Session）

### 2026-06-05 初始发布
- HOSHINO Blog 暗色科技风个人博客系统
- 暗色科技风 UI + 鼠标跟随光效系统
- 三步创建流程 + 富文本编辑器
- 多分类支持 + 封面图片自适应
- 登录/注册/个人资料
- 详细日志系统（文件 + 终端轮转）
