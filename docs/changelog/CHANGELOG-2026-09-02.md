# HOSHINO Blog 开发日志 —— 2026-09-02

> 全站视觉升级 v3.0 / B站时间轴滑块 / 鸿蒙设备适配 / 按钮交互直觉化 / 导航逻辑优化 / 流畅性优化 / 词云数据泄漏根治

---

## 全站视觉升级 v3.0（commit `50e83f8`）

| 类型 | 说明 |
|------|------|
| ui | **Critical CSS 内联 + 主样式表同步加载** — `templates/_critical_css.html` 内联首屏样式，`glow-design.css` 同步加载彻底消除 FOUC（无样式闪烁） |
| ui | **CSS containment / content-visibility** — 卡片与文章区域启用 contain，视口外内容跳过布局引擎，长列表滚动流畅 |
| ui | **精确 transition** — 全部动效改为显式属性列表 + 短时长（0.15~0.3s），不再 `transition: all` |
| ui | **排版升级** — 正文 line-height 1.75、blockquote 渐变边框、footer 对比度修正、代码块 macOS 标题栏、表格斑马纹 |
| ui | **微交互补全** — `:focus-visible` 键盘焦点环、`active` 按下反馈、图片 hover 亮度、glow-select 键盘导航（↑↓/Esc/Home/End）、skip-link |
| ui | **视觉特效** — CSS `@property` 硬件加速插值（`--angle` 边框流光）、卡片边框 conic-gradient 流光、`color-mix()` 动态配色 |
| ui | **移动端优化** — 粒子系统硬件降级、`viewport-fit=cover`、iOS 安全区适配、导航阈值 80→60px |

## B站数据时间轴滑块

| 类型 | 说明 |
|------|------|
| feat | **视频详情页时间轴滑块（`19e9571`）** — `/bilibili/video/<id>` 新增双柄范围滑块 + 自定义日历（拖拽选择、跨月），图表按日期区间实时过滤 |
| feat | **全站词云滑块（`19e9571`）** — `bilibili.html` 词云支持按月切换（`data-wc-periods`），拖动时间轴浏览不同时段的视频词云 |
| feat | **UP 主词云按月滑块（`137a593`）** — `precompute_up_wordclouds()` 生成 `up_{up_id}_YYYY-MM` 月度切片，`bilibili_up.html` 复用同一滑块组件 |
| fix | **滑块默认定位最新日期（`1654cae`）** — 初始化 key 改为 `keys[keys.length-1]`（最新月份），滑块默认滑到最右，而非旧的 `'all'` / 首月 |

## 鸿蒙设备系统性适配（commit `6dbf59c`）

| 类型 | 说明 |
|------|------|
| ui | **HarmonyOS Sans 字体优先级** — `font-family` 首选项加入 HarmonyOS Sans SC，华为设备优先使用系统字体 |
| fix | **`@property` 兼容包装** — 用 `@supports (background: paint(x))` 包裹，HarmonyOS 2.x/3.x WebView（Chromium 85-95）不支持时自动跳过 |
| perf | **华为设备粒子静态降级** — UA 正则检测 HarmonyOS/HMS/Huawei/HONOR/nova/Mate/P 系列，低端机型直接显示静态画像替代 WebGL 粒子（防掉帧发热） |
| ui | **`touch-action: manipulation`** — 全部按钮/链接消除移动端 300ms 点击延迟 |
| ui | **抽屉侧滑手势保护** — drawer 设置 `touch-action: pan-y` + `overscroll-behavior: contain` + 24px 边缘逃逸区，避免与鸿蒙侧边返回手势冲突 |

## 交互逻辑性能优化（commit `d8bc74f`）

| 类型 | 说明 |
|------|------|
| perf | **`throttleByRAF()` / `debounce()` 工具函数** — base.js / interactions.js 统一封装 |
| perf | **滚动监听全量 RAF 节流** — 导航显隐、滚动进度条、返回顶部、导航下滑隐藏 4 个 scroll 监听器改为每帧最多执行一次 |
| perf | **resize 防抖** — 150ms 防抖避免高频触发布局重算 |
| perf | **灯箱图片集去重** — `Set` 去重 + `MutationObserver` 自动收集动态添加的图片 |

## 按钮操作逻辑直觉化（commit `201b3e3` / `ad5e951`）

| 类型 | 说明 |
|------|------|
| ui | **按钮完整状态链** — `.btn` / `.btn-primary` / `.btn-ghost` / `.btn-danger` / `.back-btn` / `.btn-pill` 补全 `:focus-visible`（键盘焦点环）、`:active`（按下 `scale(0.97)` 物理反馈）、`:disabled`（0.45 透明度 + not-allowed） |
| ui | **`.is-loading` 加载态** — 提交类按钮加载时显示旋转指示器（CSS 动画），替换文字 |
| ui | **汉堡按钮 X 变形** — 抽屉打开时三线动画变为 ×（`[aria-expanded="true"]` 驱动），明确"点击可关闭"信号 |
| ui | **分页 disabled 语义化** — 禁用页改用 `<span>` 而非带 href 的 `<a>`，不再误导点击 |
| ui | **stat-card 交互感知** — 数据指标卡片添加 `cursor: pointer` + hover 悬浮 + active 选中标记（右上角彩色圆点）+ hover "点击切换" 提示 |
| fix | **24 处 CSS transition 语法错误** — `transition: color, background, background-color, border-color, ..., opacity 0.3s text-decoration: none` 等属性被混进 transition 的畸形语法批量修正 |
| fix | **bilibili 搜索按钮无效 class 修复** — `class-bili-search-btn`（无效属性）改为标准 `.btn` 类 |
| ui | **日历触发器可识别** — 日期选择 input 添加 SVG 日历图标背景，展开时紫色边框 + 外发光，明确可点击 |
| ui | **评论提交结果反馈** — 成功显示绿色 "✓ 已提交" 1.8s，失败显示红色 "✗ 失败" 1.8s，再恢复原文 |

## 词云 BUG 根治（commit `434b443` / `a748778` / `e637f5d`）

| 类型 | 说明 |
|------|------|
| fix | **UP 主页词云错位** — `wordcloud.js` 用 `getBoundingClientRect().width` 取父容器宽度，`border: 1px` 导致 canvas 宽 2px 被 `overflow:hidden` 截断；改用 `parent.clientWidth` 排除 border |
| fix | **UP 主页词云 canvas 无块级样式** — `#wcBili` / `#wcBiliUp` 补全 `display:block;width:100%`（原默认 inline 导致基线偏移） |
| **fix** | **CRITICAL: UP 主按月词云数据泄漏** — `period.like(f'up_{up_id}_%')` 中 `_` 是 SQL LIKE 单字符通配符！`up_id=1` 会匹配 `up_11_2024-01`、`up_100_2024-01` 等其他 UP 主的词云。改用 `escape_like()` 转义 + 显式 `ESCAPE` 参数，精确匹配 `up_{up_id}_` 前缀 |
| fix | **transition 修复副作用** — 批量修复把 `cubic-bezier(0.22,1,0.36,1)` 拆成孤立无效 CSS 行，改为 `transition-timing-function` 独立声明 |
| fix | **`.btn:active` 级联冲突** — 文件末尾重复的 `:active` 规则覆盖前部完整定义（丢失 `translateY(0)` + `box-shadow:none`），移除重复选择器 |
| chore | **删除 .class-bili-search-btn:hover 死代码** — 搜索按钮已改用 `.btn` 类 |

## 导航逻辑直觉化（commit `ed07a3c` / `d1cc1ad`）

| 类型 | 说明 |
|------|------|
| ui | **对比页返回明确化** — `javascript:smartBack(...)`（可被 CSP 阻止的不稳定写法）改为硬链接 `← B站 UP 主` |
| fix | **联系页/关于页 smartBack fallback 指向自身** — 直接访问时点"返回"原地不动；fallback 改为首页 |
| fix | **page-jump 输入框 scroll 保存** — 回车跳页前保存 `scrollY`，新页加载后恢复（与分页链接行为一致） |
| ui | **B站分页显式 `js-scroll-restore` 类** — bilibili.html / bilibili_up.html 分页链接显式标记，换页自动恢复滚动位置 |
| ui | **新增 `.back-link` 样式类** — 子页面面包屑式返回链接统一样式 |
| fix | **视频详情页返回保留页码** — UP 主页视频标题链接携带 `ref_page={{ pagination.page }}`（含搜索词 `q`），视频详情页返回链接读取并还原到对应页码 |

## 全站流畅性优化（commit `be24390`）

| 类型 | 说明 |
|------|------|
| perf | **粒子系统 scroll RAF 节流** — 滚动回调不再每事件写入 `canvas.style`（消减 ~200 次/秒 → 60 次/秒样式重算） |
| perf | **移除 glass-card 无条件 `will-change: transform`** — 每张卡片不再预分配 GPU 合成层（数十张卡片省数十 MB GPU 内存） |
| perf | **字体 preload** — HarmonyOS Sans `rel="preload" as="font"` 提前发现下载，消除 FOIT 字体跳变 |
| chore | **移除冗余 CSS preload** — `glow-design.css` 已有同步 stylesheet link（自带最高优先级），preload hint 多余 |
| ui | **View Transition API** — `<meta name="view-transition" content="same-origin">`，Chrome 111+ 页面导航自动带 0.3s 淡入过渡 |
| fix | **scroll-restore 延迟校正** — 图片加载（lazy）撑开高度后二次校正滚动位置，避免 CLS 漂移 |
| perf | **`.pill-light` transition 属性化** — 从 `transition: 0.3s`（全属性）改为显式 `background/color/border-color` 列表 |

## 新添加 UP 补不全视频修复（commit 未分配）

| 类型 | 说明 |
|------|------|
| fix | **`scrape()` 新 UP 添加改用 `refresh_all` 任务（force=True）** — 原提交 `refresh_up`（force=False）导致 `_run_scrape` 按 `total_in_db > 0` 落入 `_fill_max_pages=3` 分支（默认限翻 3 页 ≈ 30 视频）：一旦 DB 已有该 UP 的少量视频（爬取中断残留 / 先通过"添加视频"建了 UP + 单视频），新添加的 UP 永远只能拿到最近 ~30 个视频，无法补全全部 |
| fix | **全量翻页保障** — `refresh_all` 在 Worker 以 `force=True` 调用 `_run_scrape`，`should_fill=True` 且 `_fill_max_pages` 保持 `None`（不限页），覆盖 API 声明的全部视频 |

## 全站卡死稳定性修复

> 现象：整个项目系统偶发直接卡住，网页全部无响应，需到命令行按 Ctrl+C 才能恢复。
> 根因：Windows 控制台快速编辑模式（QuickEdit）+ Flask 开发服务器单线程 + 子进程共享控制台写日志。

| 类型 | 说明 |
|------|------|
| fix | **禁用 Windows 控制台 QuickEdit Mode（start.bat）** — 默认 QuickEdit 下误点控制台窗口进入"选择/冻结"状态，所有共享该控制台写日志的进程（Web/Worker/看门狗）全部阻塞 → 全站卡死。start.bat 启动前用 `SetConsoleMode` 去掉 `ENABLE_QUICK_EDIT_MODE / ENABLE_EXTENDED_FLAGS`（保留 `processed\|line\|echo\|insert`），误点不再冻结 |
| fix | **Web 服务器单线程 → 多线程（app.py）** — `app.run(..., threaded=True)`。Flask 开发服务器默认单线程：一个慢请求（B站大数据查询 / 词云大页面）会阻塞所有后续请求导致全站无响应；多线程下单请求慢速不再卡死整个 Web |
| fix | **Worker / 看门狗子进程不再共享控制台（app.py）** — `stderr` 从 `_sys.stderr` 改为 `DEVNULL`：子进程日志已完整写入 `blog/logs/*.log` 文件，避免大任务刷屏或控制台写阻塞（缓冲区慢 / QuickEdit）拖慢 Web 进程，零阻塞面 |

## CSRF 校验失效修复（`400 POST ... CSRF token is invalid`）

> 现象：HTTP 内网访问下操作提交（删除 UP 等）偶发 400 CSRF token invalid。
> 根因：`SESSION_COOKIE_SECURE` 默认 `true`，secure cookie 仅在 HTTPS 下浏览器保存/发送；
> 项目经 start.bat 以 HTTP（内网 IP）部署时 cookie 拒发 → session 每次新建 →
> 页面里嵌入的 CSRF token 与提交时 session 中的 token 不匹配 → CSRF invalid。

| 类型 | 说明 |
|------|------|
| fix | **`SESSION_COOKIE_SECURE` 默认改 `false`（config.py）** — 匹配 start.bat HTTP 部署实际；session cookie 在 HTTP 下正常保存，页面 token 与提交 token 一致。生产 HTTPS 需显式设置 `SESSION_COOKIE_SECURE=true` |
| chore | **建议 .env 固定 SECRET_KEY** — 未设置时启用每日自动轮换；固定密钥后 session/CSRF 在服务重启后依然稳定，彻底消除轮换相关失效 |

## 删除 UP 主报错（`IntegrityError 1048 Column 'up_id' cannot be null`）

> 现象：`POST /admin/bilibili/delete/79` 删除 UP 主时 commit 失败：
> `UPDATE bili_subscriptions SET up_id=NULL WHERE id=N` → 数据库列 NOT NULL 拒绝 → 500。
> 根因：`BiliSubscription.up`（many 侧）设置 `passive_deletes=True` 不生效——SQLAlchemy 的
> `passive_deletes` 须配置在 one-to-many **父侧**（`BiliUp.subscriptions`）；父侧 backref 未配置，
> 删除 `BiliUp` 时 SQLAlchemy 默认对已关联订阅做 FK NULLify（而非级联删除），而 `up_id NOT NULL` → 1048。

| 类型 | 说明 |
|------|------|
| fix | **`delete_up` 显式先删订阅（bili_routes.py）** — `BiliSubscription.query.filter_by(up_id=...).delete()`，与现有"按依赖顺序手动删除"（订阅 → 历史快照 → 视频 → UP 主）一致，不依赖关系级联，彻底消除 NULLify 冲突 |
| fix | **`delete_up` 补删 `BiliUpHistory`（bili_routes.py）** — 首轮修复后下一处同类冲突：`bili_up_history.up_id` 同样 NOT NULL 且 `passive_deletes` 又在 many 侧；显式 `BiliUpHistory.query.filter(up_id==...).delete()`，删除顺序修正为：订阅 → UP 粉丝数历史 → 视频历史 → 视频 → UP 主 |

## Worker 弹幕任务失败（`UnboundLocalError: cannot access local variable '_circuit_open_until'`）

> 现象：`danmaku_refresh` 任务在 `_crawl_video_danmakus` 中失败：
> `UnboundLocalError: cannot access local variable '_circuit_open_until' where it is not associated with a value`。
> 根因：Python 作用域规则 —— 函数内一旦给某名字赋值，该名字即视为函数局部变量；
> `_crawl_video_danmakus` 在 1084 行读取全局熔断变量 `_circuit_open_until`、1086 行赋值，
> 但未声明 `global _circuit_open_until` → 赋值的"使用前"读取触发 UnboundLocalError。

| 类型 | 说明 |
|------|------|
| fix | **`_crawl_video_danmakus` 声明 `global _circuit_open_until`（bili_routes.py）** — 与 `_check_new_videos` / `_run_scrape` 保持一致；其余读写 `_circuit_open_until` 的函数均已确认有 global 或仅读不写 |

## 任务重试被"签名校验失败"丢弃（`task_queue.requeue_task`）

> 现象：任务失败重试（第 1 次）后日志出现"任务签名校验失败，丢弃"，重试机制失效。
> 根因：`worker.py` 重试时修改 `data._retries`，但 `requeue_task` 直接入队未重签名；
> `verify_task_signature` 用含 `_retries` 的新 payload 验旧 sig → HMAC 不匹配 → 丢弃。

| 类型 | 说明 |
|------|------|
| fix | **`requeue_task` 入队前重算 HMAC 签名（task_queue.py）** — 用修正后载荷 `_sign(_canonical(不含 sig))` 更新 `task['sig']` 再入队，重试任务可被正确验签执行 |

---

## 技术细节

### SQL LIKE 通配符泄漏原理（`a748778` 核心 bug）

```sql
-- 错误写法：_ 是单字符通配符
WHERE period LIKE 'up_1_%'   -- 匹配 up_1_2024-01 ✅ 也匹配 up_11_2024-01 ❌ 泄漏！

-- 正确写法：\_ 转义为字面下划线
WHERE period LIKE 'up\_1\_%' ESCAPE '\'  -- 仅匹配 up_1_2024-01
```

`SQLAlchemy` 的 `startswith()` 默认 `autoescape=False`，同样不转义 `_`。最终采用：

```python
WordCloudData.period.like(escape_like(f'up_{up_id}_') + '%', escape='\\')
```

`escape_like()` 将 `up_1_` → `up\_1\_`，配合显式 `ESCAPE` 字符精确匹配前缀。

### 视频详情页页码还原链路

```
/bilibili/up/456?page=3&q=keyword
        │ 点击视频标题
        ▼
/bilibili/video/123?ref_page=3&q=keyword#video-123
        │ 点击 "← UP主 返回"
        ▼
/bilibili/up/456?page=3&q=keyword   ← 还原页码 + 搜索词
```

### 词云 canvas 尺寸计算修复

```javascript
// 错误：getBoundingClientRect().width 包含 border，canvas 溢出 2px 被截断
var w = (canvas.parentElement.getBoundingClientRect().width) | 0;

// 正确：clientWidth 排除 border，取实际可用内容宽度
var w = ((parent && parent.clientWidth) || 600) | 0;
```

---

## 新增环境变量

本次会话无新增环境变量；所有行为调整均为硬编码或复用已有配置。

---

## 验证手段

1. UP 主页词云：不同 UP 主页面词云数据互不串扰（含按月滑块切换）
2. 分页跳转：换页 / 页码输入框跳页后滚动位置保持
3. 视频详情返回：`?page=N` 下点击视频 → 详情 → 返回后仍在第 N 页
4. 移动端（含鸿蒙）：抽屉展开、粒子降级、点击无延迟
5. 按钮键盘导航：Tab 焦点环可见，Enter/Space 可激活