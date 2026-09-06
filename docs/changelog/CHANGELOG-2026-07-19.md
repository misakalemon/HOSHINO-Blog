# HOSHINO Blog 开发日志 —— 2026-07-19

> 首页粒子画像系统 / 移除价格爬取 / 启动性能优化 / 全站注释

---

## 新增功能

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/19 | feat | **首页 Hero 粒子画像系统** — 后台上传 PNG（透明背景），首页 Canvas 采样 2 万粒子生成动态画像 |
| 07/19 | feat | **粒子鼠标交互** — 鼠标拨开粒子流 + 点击涟漪散射 + 滚动渐进散开 + 移动端减半自适应 |
| 07/19 | feat | **粒子散开/汇聚切换** — 点击按钮粒子向外爆散，8 秒后自动汇聚回原形 |
| 07/19 | feat | **后台 Hero 画像 CRUD** — 多张上传、排序、启禁用、列表预览 |
| 07/19 | feat | **粒子加载过渡** — 粒子从画面外飞入汇聚，加载过程显示 Loading 动画 |
| 07/19 | perf | **WebGL GPU 渲染粒子** — 从 Canvas 2D fillRect 迁移到 WebGL gl.POINTS，单次 drawcall 提交全部粒子 |
| 07/19 | feat | **背景浮游光点独立 2D Canvas 叠加层** — 保持原有 lighter 混合视觉效果，不占用主 GPU 渲染资源 |
| 07/19 | refactor | **移除价格爬取功能** — 删除 9 个文件、4 个模型、4 张表、CSS、导航链接、配置项 |
| 07/19 | perf | **启动时间从 ~9.8s 降至 ~2.0s** — ExaClient 汇率爬取改为后台线程惰性加载 |

### Hero 粒子画像

```
后台上传 PNG（建议透明背景、400-800px 宽）
    ↓ 每次刷新首页随机选择一张激活的画像
    ↓ Image 解码 → 采样 RGBA（步长自适应 2~8）
    ↓ 生成 2 万粒子（移动端 1.6 万）
    ↓ 从画面外飞入 → 汇聚成画像轮廓
    ↓ 鼠标拨开 / 点击涟漪 / 滚动散开 / 按钮切换散开汇聚
```

### 代码注释

- `blog/models.py`、`blog/forms.py`、`blog/routes.py`、`blog/admin.py`：完善所有路由和模型的 docstring
- `static/js/particle-hero.js`：新增文件头注释 + 各函数注释
- `templates/index.html`、`templates/admin/hero_image_*.html`：新增模板注释
- `README.md`：移除价格爬取相关说明，新增粒子画像系统介绍

### 启动性能优化

- `ExaClient._fetch_exchange_rates()` 改为 `threading.Thread(target=..., daemon=True).start()`
- 应用启动不再等待汇率接口响应
- 结合价格爬取整体移除，启动时间从 ~9.8s 降至 ~2.0s

---

## 移除的功能

| 功能 | 影响范围 |
|------|----------|
| 价格看板（商品/价格/汇率） | `price_routes.py`、`crawler.py`、`exa_client.py`、`scripts/price_crawl.py` + .bak |
| 商品/价格/汇率数据模型 | `Product`、`ProductSource`、`PriceRecord`、`ExchangeRate`（4 张表 DROP） |
| 价格前端页面 | 4 个价格模板、价格导航链接 |
| 价格后台配置 | `config.py` 中价格调度相关配置 |
| 汇率 API | Exa 搜索集成整体移除 |
| 计划任务 | 价格定时爬取 APScheduler 任务 |
