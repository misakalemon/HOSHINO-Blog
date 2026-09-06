# HOSHINO Blog 开发日志 —— 2026-07-14

> 邮件订阅系统 / 视频对比 / 统计增长指标 / 全站确认保护

---

## 新增功能

| 时间 | 类型 | 说明 |
|------|------|------|
| 07/14 | feat | **B站 UP 主新视频邮件订阅** — 用户通过邮箱订阅 UP 主，新视频发布时自动发送邮件通知 |
| 07/14 | feat | **批量订阅** — 支持一次勾选多个 UP 主，同一批次共用验证 token，一封邮件批量确认 |
| 07/14 | feat | **视频对比** — 跨 UP 主选择多个视频（localStorage 持久化），对比表 + ECharts 柱状图 |
| 07/14 | feat | **视频统计卡片增长指标** — 每项指标下方显示"总增长"和"上次爬取增长"，绿色 ▲ / 红色 ▼ |
| 07/14 | feat | **浮动对比栏** — `/bilibili/up/<id>` 和 `/bilibili/` 底部同步显示已选视频数量 |
| 07/14 | feat | **自定义复选框** — 视频对比复选框重构为粉色边框 + ✓ 符号，匹配暗色主题 |
| 07/14 | feat | 对比页支持逐个移除视频（✕ 按钮） |

### 邮件订阅流程

```
/bilibili/ 页面底部
    ↓ 输入邮箱 + 勾选 UP 主
    ↓ 点击订阅
    ↓ 创建 BiliSubscription（未验证）+ 后台线程发信
    ↓ 用户点击验证链接 → verified = true
    ↓ 每 30 分钟增量检查发现新视频
    ↓ 查询该 UP 主的所有已验证订阅
    ↓ 后台线程非阻塞发送通知邮件
```

- **双 opt-in**：必须点击验证链接后才激活，防止滥用
- **批量 token**：同一批次订阅共享 token，一条链接验证/退订整批
- **SMTP 适配**：支持 SSL (465) / TLS (587) 两种模式

### 视频对比交互

```
UP 主视频列表页 → 勾选多个视频（复选框，localStorage 持久化）
    ↓ 浮动对比栏显示已选数量
    ↓ 点击「开始对比」
    ↓ /bilibili/compare?ids=1,2,3
    ↓ 视频卡片（UP 主+时长+日期）
    ↓ 7 指标对比表（最大值高亮）
    ↓ ECharts 分组柱状图
```

- 上限 10 个，最少 2 个
- 翻页/跨页面不丢失（localStorage）
- ✕ 按钮可逐个移除，剩余 ≥ 2 更新页面

---

## Bug 修复

| 时间 | 类型 | 严重度 | 说明 |
|------|------|--------|------|
| 07/14 | fix | **严重** | BiliSubscription.token 迁移逻辑错误 — 用名称含"unique"判断而非 `unique` 属性，导致 UNIQUE 索引未删除，批量订阅报 IntegrityError |
| 07/14 | fix | **中** | Jinja2 不支持 `{... for x in ...}` 字典推导式，对比页模板编译 500 错误 |
| 07/14 | fix | **中** | 折线图 x 轴标签与图例重叠 — grid.bottom 30→50 |
| 07/14 | fix | **低** | 对比模板 `|tojson` 过滤器优先级错误导致 UP 主名称截断 |
| 07/14 | fix | **低** | 补全全站 8 处删除操作的自定义 `showConfirm` 二次确认弹窗 |
| 07/14 | fix | **低** | 邮件发送静默吞异常 — 区分 SMTPAuthenticationError 日志，支持 SSL |
| 07/14 | fix | **低** | `.arts/` IDE 目录被误提交，加入 `.gitignore` 并删除跟踪 |

---

## 代码变更量

| 文件 | + | - | 说明 |
|------|---|---|------|
| `blog/mail.py` | **新建** | 0 | SMTP 邮件发送模块（非阻塞后台线程，SSL/TLS 双模） |
| `blog/models.py` | +21 | -0 | BiliSubscription 模型 |
| `blog/bili_public_routes.py` | +99 | -22 | 订阅三接口 + 对比路由 + 增长计算 |
| `blog/bili_routes.py` | +23 | -0 | 新视频通知集成到增量检查 |
| `blog/admin.py` | +56 | -1 | 订阅管理后台（列表/搜索/删除/清理） |
| `blog/__init__.py` | +67 | -13 | token 索引迁移 |
| `config.py` | +18 | -0 | SMTP 配置 + MAIL_USE_SSL/MAIL_TIMEOUT |
| `templates/bilibili_compare.html` | **新建** | 0 | 对比页面（表格 + ECharts 柱状图） |
| `templates/bilibili.html` | +54 | -0 | 浮动对比栏 + localStorage JS |
| `templates/bilibili_up.html` | +91 | -61 | 复选框 + 浮动栏（移入独立 JS） |
| `templates/bilibili_video.html` | +41 | -1 | 增长指标显示 + 图例 padding 修复 |
| `templates/mail/verify_subscription.html` | **新建** | 0 | 验证邮件 HTML |
| `templates/mail/new_video_notify.html` | **新建** | 0 | 通知邮件 HTML |
| `templates/message.html` | **新建** | 0 | 通用消息结果页 |
| `templates/admin/bili_subscriptions.html` | **新建** | 0 | 订阅管理页 |
| `templates/admin/base_admin.html` | +5 | -1 | 侧边栏「邮件订阅」入口 |
| 其他 8 个模板 | +30 | -6 | 删除确认弹窗统一/修复 |
| `.gitignore` | +1 | -0 | .arts/ |
| `.env.example` | +9 | -0 | SMTP 配置示例 |
| **合计** | **~515** | **~105** | **19 文件，~410 净增** |

---

## 新增文件

```
blog/mail.py                          # 邮件发送模块
templates/mail/verify_subscription.html  # 验证邮件模板
templates/mail/new_video_notify.html     # 通知邮件模板
templates/message.html                   # 通用消息页（验证/退订结果）
templates/bilibili_compare.html          # 视频对比页
templates/admin/bili_subscriptions.html  # 订阅管理后台
```

---

## 新增路由

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/bilibili/compare?ids=1,2,3` | 视频对比页面 |
| POST | `/bilibili/subscribe` | 订阅邮件通知（支持 up_ids[] 批量） |
| GET | `/bilibili/verify/<token>` | 验证订阅链接 |
| GET | `/bilibili/unsubscribe/<token>` | 取消订阅链接 |
| GET | `/admin/bili-subscriptions` | 订阅管理列表（admin） |
| POST | `/admin/bili-subscriptions/<id>/delete` | 删除订阅 |
| POST | `/admin/bili-subscriptions/cleanup-unverified` | 清理 24h 未验证订阅 |

---

## 配置变更

### `.env` 新增

```ini
# SMTP 邮件（B站 UP 主新视频邮件订阅）
MAIL_SERVER=smtp.163.com
MAIL_PORT=465
MAIL_USE_SSL=true
MAIL_USE_TLS=false
MAIL_USERNAME=your_email@163.com
MAIL_PASSWORD=your_smtp_password    # SMTP 授权码，非登录密码
MAIL_DEFAULT_SENDER=your_email@163.com
MAIL_TIMEOUT=10
```

---

## 待办

- [ ] 对比页表格增加"数据差值"行（每个视频与平均值的偏差）
- [ ] 邮件模板支持更多品牌自定义（站点名称/Logo/主题色）
- [ ] 考虑退订链接加入一键退订全部（token 需标记 batch）
- [ ] 添加邮件发送频率限制（同一邮箱每小时最多 n 封）
- [ ] 考虑 Redis 队列替代线程池（防止大量订阅阻塞）
