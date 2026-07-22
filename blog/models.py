"""
HOSHINO Blog — 数据模型

本模块定义所有 SQLAlchemy ORM 模型，按用途分为如下几组：

--- 核心内容 ---
  User     — 用户（支持多角色权限系统：admin/editor/author/user）
  Category — 文章分类（支持多对多关联）
  Post     — 文章（支持多对多分类、长文 MEDIUMTEXT、全文索引、HTML 页面模式）
  Comment  — 评论（需管理员审核）
  ContactMessage — 联系页访客留言

--- 首页展示 ---
  HeroImage     — 首页粒子画像（透明 PNG 立绘，由 particle-hero.js 采样展示）
  FeaturedCard  — 首页特色卡片（可后台管理）

--- Bilibili 数据 ---
  BiliUp             — B 站 UP 主
  BiliVideo          — B 站视频数据（含播放/点赞/投币等统计数据）
  BiliUpHistory      — UP 主粉丝数历史快照
  BiliVideoHistory   — 视频统计数据历史快照
  BiliWatchedVideo   — 用户标记的重点追踪视频
  BiliSubscription   — B 站 UP 主邮件订阅（支持批量订阅/验证/取消）
  BiliCleanupConfig  — B 站历史快照自动清理配置

--- 其他 ---
  ExchangeRate       — 汇率记录（外币对人民币，Exa 爬取）

关联关系摘要：
  User ──1:N──→ Post             一个用户有多篇文章
  Post ──M:N──→ Category         一篇文章可属于多个分类
  Post ──1:N──→ Comment          一篇文章有多条评论
  BiliUp ──1:N──→ BiliVideo      一个 UP 主有多个视频
  BiliUp ──1:N──→ BiliUpHistory  一个 UP 主有多个粉丝数快照
  BiliVideo ──1:N──→ BiliVideoHistory  一个视频有多个统计快照

技术栈：
  Flask-SQLAlchemy — ORM 映射
  Flask-Login 的 UserMixin — 提供 is_authenticated / is_active 等属性
  Werkzeug 的 security 模块 — 密码哈希（PBKDF2-SHA256）
  SQLAlchemy MEDIUMTEXT — MySQL 长文本类型（最大 16MB）
"""

import datetime
import json
import logging
import zlib
from datetime import timezone, timedelta

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from werkzeug.security import check_password_hash, generate_password_hash

# 东八区（CST，中国标准时间）— 全站 B站 数据统一使用时区
CST = timezone(timedelta(hours=8))

# SQLAlchemy 实例，所有模型共享
# 采用延迟初始化模式：先创建 db 实例，然后在 create_app() 中 db.init_app(app)
# 这种模式是 Flask 扩展的常见用法，避免了循环导入和应用上下文问题
db = SQLAlchemy()


# ── 多对多关联表 ────────────────────────────────
# 文章 ↔ 分类 的多对多关系表
# 允许一篇文章属于多个分类，一个分类包含多篇文章
# 使用 SQLAlchemy 的 Table 定义，不是 Model 类
# 使用 Table 而非 Model 表示这是一个纯关联表，不需要独立的主键或额外字段
post_categories = db.Table(
    'post_categories',
    # post_id 和 category_id 组成联合主键，确保同一对关系不重复
    # ondelete='CASCADE'：删除文章或分类时自动清除关联记录
    db.Column('post_id', db.Integer, db.ForeignKey('posts.id', ondelete='CASCADE'), primary_key=True),
    db.Column('category_id', db.Integer, db.ForeignKey('categories.id', ondelete='CASCADE'), primary_key=True),
)


class User(UserMixin, db.Model):
    """用户模型。

    继承 UserMixin 以获得 Flask-Login 所需的：
      is_authenticated, is_active, is_anonymous, get_id()
    不需要显式实现这些方法。

    __tablename__ = 'users'

    角色系统（分层权限）：
      admin  — 超级管理员，所有权限（管理用户/文章/分类/评论/系统设置）
      editor — 编辑，可管理文章/分类/评论（但不能管理用户和系统设置）
      author — 已废弃，保留历史兼容，所有权限已合并到 user
      user   — 普通订阅用户，仅前台浏览，可撰写/管理自己的文章

    密码安全：
      使用 Werkzeug 的 PBKDF2-SHA256 哈希存储，
      不保存明文密码。set_password() / check_password() 封装了哈希操作。
    """

    __tablename__ = 'users'

    # ── 角色常量 ────────────────────────────────
    ROLE_ADMIN = 'admin'
    ROLE_EDITOR = 'editor'
    ROLE_AUTHOR = 'author'  # 已废弃，仅用于迁移兼容
    ROLE_USER = 'user'

    # ── 基本信息 ────────────────────────────────
    id = db.Column(db.Integer, primary_key=True)  # 主键，自增
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)  # 登录名，唯一
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)  # 邮箱，唯一，用于登录和通知
    password_hash = db.Column(db.String(256), nullable=False)  # 加密后的密码哈希值（Werkzeug 生成，含 salt）

    # ── 个人信息（可选） ─────────────────────────
    display_name = db.Column(db.String(128), default='')  # 显示昵称（页面展示用，可为空则回退到 username）
    bio = db.Column(db.Text, default='')  # 个人简介（支持文本内容）
    avatar = db.Column(  # 头像路径（相对于 static/）
        db.String(256), default='images/avatar/main-avatar.jpg'
    )
    website = db.Column(db.String(256), default='')  # 个人网站/社交媒体链接
    gitcode_url = db.Column(db.String(256), default='')  # GitCode 主页链接
    github_url = db.Column(db.String(256), default='')  # GitHub 主页链接
    gitee_url = db.Column(db.String(256), default='')  # Gitee 主页链接
    bilibili_url = db.Column(db.String(256), default='')  # Bilibili 主页链接
    about_content = db.Column(MEDIUMTEXT, default='')  # 关于页面内容（富文本 HTML，独立页面展示）

    # ── 权限状态 ────────────────────────────────
    role = db.Column(db.String(16), default='user')  # 角色：admin/editor/author/user
    is_active = db.Column(db.Boolean, default=True)  # 是否激活（可登录），False 时账号被禁用

    # ── 登录追踪 ────────────────────────────────
    # 用于安全审计和用户活动分析
    last_login_at = db.Column(db.DateTime, nullable=True)  # 最后登录时间
    last_login_ip = db.Column(db.String(45), default='')  # 最后登录 IP（IPv4 最长 15，IPv6 最长 45）
    login_count = db.Column(db.Integer, default=0)  # 累计登录次数

    # ── 时间戳 ──────────────────────────────────
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))))

    # ── 关联关系 ────────────────────────────────
    # 一对多：一个用户可撰写多篇文章
    # lazy='dynamic' 返回 Query 对象而非列表，支持链式过滤（.filter_by().order_by()）
    # cascade='all, delete-orphan'：删除用户时一并删除其所有文章
    posts = db.relationship('Post', backref='author', lazy='dynamic', cascade='all, delete-orphan')

    # ── 属性 ────────────────────────────────────
    @property
    def is_admin(self):
        """是否为管理员角色。"""
        return self.role == self.ROLE_ADMIN

    @is_admin.setter
    def is_admin(self, value):
        """设置管理员角色（兼容旧版 is_admin 赋值代码）。

        Args:
            value: True 设为 admin，False 设为 user
        """
        self.role = self.ROLE_ADMIN if value else self.ROLE_USER

    @property
    def is_editor(self):
        """是否为编辑角色（admin 拥有全部权限，包含编辑权限）。"""
        return self.role in (self.ROLE_ADMIN, self.ROLE_EDITOR)

    @property
    def is_author(self):
        """可撰写/管理自己的文章：admin、editor、user 均有此权限。"""
        return self.role in (self.ROLE_ADMIN, self.ROLE_EDITOR, self.ROLE_USER, self.ROLE_AUTHOR)

    @property
    def role_label(self):
        """返回角色的中文显示标签。"""
        return {
            self.ROLE_ADMIN: '管理员',
            self.ROLE_EDITOR: '编辑',
            self.ROLE_USER: '用户',
        }.get(self.role, '用户')

    @property
    def role_badge_class(self):
        """返回角色对应的 CSS 徽章类名（用于前台样式展示）。"""
        return {
            self.ROLE_ADMIN: 'badge-admin',
            self.ROLE_EDITOR: 'badge-editor',
            self.ROLE_USER: 'badge-user',
        }.get(self.role, 'badge-user')

    # ── 密码方法 ────────────────────────────────
    def set_password(self, password):
        """设置密码哈希值。

        使用 generate_password_hash() 生成 PBKDF2-SHA256 哈希，
        自动加入随机 salt，不同用户即使密码相同哈希也不同。

        Args:
            password: 明文密码字符串
        """
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """验证密码是否正确。

        Args:
            password: 待验证的明文密码

        Returns:
            bool：密码匹配返回 True，否则 False
        """
        return check_password_hash(self.password_hash, password)

    # ── 序列化 ──────────────────────────────────
    def to_dict(self):
        """将用户对象转换为字典（用于 API 响应或模板渲染）。"""
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'display_name': self.display_name,
            'role': self.role,
            'is_admin': self.is_admin,
        }


class Category(db.Model):
    """文章分类模型。

    __tablename__ = 'categories'

    每个分类有唯一的 name（显示名）和 slug（URL 友好标识）。
    通过 post_categories 关联表与 Post 建立多对多关系。
    一个分类下可以有多篇文章（通过关联表查询）。

    字段说明：
      name        — 分类显示名称（如"技术"），唯一
      slug        — URL 标识（如"tech"），唯一，用于路由 /category/<slug>
      description — 分类描述（选填，列表页展示）
    """

    __tablename__ = 'categories'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)  # 分类名，唯一
    slug = db.Column(db.String(64), unique=True, nullable=False, index=True)  # URL 标识，唯一
    description = db.Column(db.Text, default='')  # 分类描述
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))))

    # 多对多关联：一个分类包含多篇文章
    # secondary 指向关联表 post_categories
    # back_populates='categories' 与 Post 中的 categories 双向对应
    # lazy='dynamic' 返回 Query 而非列表，支持链式过滤
    posts = db.relationship(
        'Post', secondary=post_categories, back_populates='categories', lazy='dynamic'
    )

    def post_count(self):
        """返回该分类下已发布的文章数。

        过滤 is_published=True，不统计草稿。

        Returns:
            int：已发布文章数量
        """
        return self.posts.filter_by(is_published=True).count()


class Post(db.Model):
    """文章模型。

    __tablename__ = 'posts'

    文章支持 Markdown 格式的内容，支持多分类标签（最多 15 个），
    关联的评论需要管理员审核后才能公开显示。
    slug 用于 URL 友好访问（/post/<slug>），必须唯一。

    内容模式：
      1. Markdown 模式：content 字段写 Markdown，前端渲染为 HTML
      2. HTML 页面模式：html_content 或 html_file_url 提供自定义 HTML
         html_content 优先于 html_file_url

    索引：
      ix_post_fulltext — 标题 + 正文的 MySQL FULLTEXT 索引，用于中文全文搜索
      created_at 索引 — 加速按时间排序的文章列表查询
    """

    __tablename__ = 'posts'
    # FULLTEXT 索引用于中文全文搜索（MySQL 支持），加速 title/content 的 LIKE 查询
    __table_args__ = (db.Index('ix_post_fulltext', 'title', 'content', mysql_prefix='FULLTEXT'),)

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(256), nullable=False)  # 文章标题
    slug = db.Column(db.String(256), unique=True, nullable=False, index=True)  # URL 标识，用于 /post/<slug>
    summary = db.Column(db.Text, default='')  # 文章摘要（列表页/卡片展示使用）
    content = db.Column(MEDIUMTEXT, nullable=False)  # 正文 Markdown（支持长文，MEDIUMTEXT 最大 16MB）
    cover_image = db.Column(db.String(256), default='')  # 封面图片路径/URL
    html_file_url = db.Column(db.String(512), default='')  # 自定义 HTML 页面文件路径（可选，兼容旧数据）
    html_content = db.Column(MEDIUMTEXT, default='')  # 自定义 HTML 页面源码（可选，优先于 html_file_url）
    author_id = db.Column(  # 作者 ID（外键 → users.id）
        db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False
    )
    is_published = db.Column(db.Boolean, default=False, index=True)  # 是否已发布（前台可见）

    # ── 时间戳 ──────────────────────────────────
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))), index=True
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))),
        onupdate=lambda: datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))),  # 更新时自动修改
    )

    # ── 关联关系 ────────────────────────────────
    # 多对多：一篇文章可以有多个分类（最多 15 个，前端/视图层限制）
    # lazy='select' 在访问时才加载（默认行为），避免每次查询都 JOIN
    categories = db.relationship(
        'Category', secondary=post_categories, back_populates='posts', lazy='select'
    )
    # 一对多：一篇文章有多条评论
    # lazy='dynamic' 返回 Query，可链式过滤 is_approved=True
    # order_by='Comment.created_at' 按评论时间正序排列
    comments = db.relationship(
        'Comment', backref='post', lazy='dynamic', order_by='Comment.created_at'
    )

    # ── 辅助方法 ────────────────────────────────
    def published_comments(self):
        """返回已审核通过的评论数。

        前台仅显示 is_approved=True 的评论，
        未审核或已拒绝的评论不对普通访客展示。

        Returns:
            int：通过审核的评论数量
        """
        return self.comments.filter_by(is_approved=True).count()

    def category_names(self):
        """返回所有分类名称列表。"""
        return [c.name for c in self.categories]

    def category_slugs(self):
        """返回所有分类 slug 列表。"""
        return [c.slug for c in self.categories]


class Comment(db.Model):
    """评论模型。

    __tablename__ = 'comments'

    访客评论需管理员审核（is_approved=False 时不显示在前台）。
    支持邮箱字段（选填），不强制登录即可评论。
    评论按时间正序排列。

    字段说明：
      post_id      — 所属文章（外键，级联删除）
      author_name  — 评论者昵称，必填
      author_email — 评论者邮箱，选填（用于回复通知）
      content      — 评论正文，支持纯文本
      is_approved  — 审核状态，后台管理员可批准/拒绝
    """

    __tablename__ = 'comments'

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(  # 所属文章（外键 → posts.id）
        db.Integer, db.ForeignKey('posts.id', ondelete='CASCADE'), nullable=False
    )
    author_name = db.Column(db.String(128), nullable=False)  # 评论者昵称
    author_email = db.Column(db.String(120), nullable=True)  # 评论者邮箱（选填，用于回复通知）
    content = db.Column(db.Text, nullable=False)  # 评论正文
    is_approved = db.Column(db.Boolean, default=False, index=True)  # 管理员审核标记（默认未审核）
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))))


class ContactMessage(db.Model):
    """联系页留言

    访客通过前台联系表单提交的留言。
    当前仅存储在数据库中，未集成邮件通知功能。

    __tablename__ = 'contact_messages'
    """

    __tablename__ = 'contact_messages'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)  # 联系人姓名
    email = db.Column(db.String(120), nullable=False)  # 联系人邮箱
    subject = db.Column(db.String(256), default='')  # 主题
    content = db.Column(db.Text, nullable=False)  # 留言内容
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))))


class FeaturedCard(db.Model):
    """首页特色卡片（可后台管理）。

    首页展示多个特色卡片，每个卡片包含图标、标题、描述和链接。
    卡片支持拖拽排序（sort_order），可单独启用/禁用。

    __tablename__ = 'featured_cards'
    """

    __tablename__ = 'featured_cards'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(128), nullable=False)  # 卡片标题
    description = db.Column(db.String(256), default='')  # 卡片描述
    icon = db.Column(db.String(256), default='✦')  # 图标符号或 CSS Class
    tag = db.Column(db.String(16), default='anime')  # 卡片标签（用于分类/主题筛选）
    link = db.Column(db.String(256), default='')  # 点击跳转链接
    image_url = db.Column(db.String(256), default='')  # 背景图片 URL
    sort_order = db.Column(db.Integer, default=0)  # 排序权重（越小越靠前）
    is_active = db.Column(db.Boolean, default=True, index=True)  # 是否在前台显示
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))),
        onupdate=lambda: datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))),
    )


class ExchangeRate(db.Model):
    """汇率记录（外币对人民币）。

    每次 Exa 爬取时自动记录各币种实时汇率，
    用于汇率走势分析和历史回溯。
    __tablename__ = 'exchange_rates'
    """

    __tablename__ = 'exchange_rates'

    id = db.Column(db.Integer, primary_key=True)
    currency = db.Column(db.String(10), nullable=False, index=True)  # 币种代码（USD / EUR / GBP / JPY 等）
    rate = db.Column(db.Float, nullable=False)  # 兑换人民币汇率（1 外币 = rate CNY）
    recorded_at = db.Column(
        db.DateTime, default=lambda: datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))), index=True
    )


# ── Bilibili 数据 ────────────────────────────────


class BiliUp(db.Model):
    """B站 UP 主

    存储 UP 主的基本信息，包括粉丝数等统计数据。
    与 BiliVideo 为一对多关系，一个 UP 主有多个视频。
    与 BiliUpHistory 为一对多关系，记录粉丝数变化轨迹。

    __tablename__ = 'bili_ups'
    """

    __tablename__ = 'bili_ups'

    id = db.Column(db.Integer, primary_key=True)
    mid = db.Column(db.BigInteger, unique=True, nullable=False, index=True, comment='B站 mid')
    name = db.Column(db.String(128), default='', comment='UP主名称')
    avatar = db.Column(db.String(256), default='', comment='头像 URL')
    space_url = db.Column(db.String(256), default='', comment='空间链接')
    video_count = db.Column(db.Integer, default=0, comment='视频数')
    follower_count = db.Column(db.Integer, default=0, comment='粉丝数')
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(CST))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.datetime.now(CST),
        onupdate=lambda: datetime.datetime.now(CST),
    )

    # 一对多：一个 UP 主有多个视频
    # lazy='dynamic' 支持链式过滤，cascade='all, delete-orphan' 级联删除
    videos = db.relationship(
        'BiliVideo', backref='up', lazy='dynamic', cascade='all, delete-orphan'
    )

    def __repr__(self):
        return f'<BiliUp {self.name or self.mid}>'

    @property
    def safe_avatar(self):
        """返回 HTTPS 协议的头像 URL（强制替换 http:// → https://）。"""
        return (self.avatar or '').replace('http://', 'https://')


class BiliVideo(db.Model):
    """B站视频数据

    存储视频的基本信息及实时统计数据（播放/点赞/投币/收藏/转发/评论/弹幕）。
    通过 up_id 外键关联到 UP 主。
    统计数据通过 BiliVideoHistory 记录历史变化。

    __tablename__ = 'bili_videos'

    索引：
      ix_bili_video_up_pubdatetime — (up_id, pub_datetime) 加速按 UP 主+时间的查询
      ix_bili_video_up_updated     — (up_id, updated_at)   加速按 UP 主+更新的查询
      bvid                         — 唯一索引，通过 BV 号快速查找
    """

    __tablename__ = 'bili_videos'
    __table_args__ = (
        db.Index('ix_bili_video_up_pubdatetime', 'up_id', 'pub_datetime'),
        db.Index('ix_bili_video_up_updated', 'up_id', 'updated_at'),
    )

    id = db.Column(db.Integer, primary_key=True)
    up_id = db.Column(db.Integer, db.ForeignKey('bili_ups.id', ondelete='CASCADE'), nullable=False, index=True)
    bvid = db.Column(db.String(64), unique=True, nullable=False, index=True, comment='BV 号')
    aid = db.Column(db.BigInteger, unique=True, nullable=False, comment='稿件 ID')
    title = db.Column(db.Text, nullable=True, comment='视频标题')
    description = db.Column(db.Text, nullable=True, comment='视频简介')
    duration = db.Column(db.Integer, default=0, comment='时长（秒）')
    pubdate = db.Column(db.Integer, nullable=True, comment='发布时间戳（Unix 秒级时间戳）')
    pub_date = db.Column(db.Date, nullable=True, comment='发布日期（仅日期部分）')
    pub_datetime = db.Column(db.DateTime, nullable=True, comment='发布日期时间（完整 DATETIME）')
    view_count = db.Column(db.Integer, default=0, comment='播放数')
    like_count = db.Column(db.Integer, default=0, comment='点赞数')
    coin_count = db.Column(db.Integer, default=0, comment='投币数')
    favorite_count = db.Column(db.Integer, default=0, comment='收藏数')
    share_count = db.Column(db.Integer, default=0, comment='转发数')
    comment_count = db.Column(db.Integer, default=0, comment='评论数')
    danmaku_count = db.Column(db.Integer, default=0, comment='弹幕数')
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(CST))
    tags = db.Column(db.JSON, nullable=True, comment='视频标签名数组')
    subtitle_text = db.Column(MEDIUMTEXT, nullable=True, comment='AI 字幕文本（自动语音识别生成）')
    comments_crawled_at = db.Column(db.DateTime, nullable=True, comment='评论最后爬取时间')

    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.datetime.now(CST),
        onupdate=lambda: datetime.datetime.now(CST),
    )

    def __repr__(self):
        return f'<BiliVideo {self.bvid} {self.title[:20]!r}>'

    def to_dict(self):
        """序列化为字典（用于 API 响应或缓存）。"""
        return {
            'bvid': self.bvid,
            'aid': self.aid,
            'title': self.title,
            'duration': self.duration,
            'pub_date': self.pub_date.isoformat() if self.pub_date else None,
            'view_count': self.view_count,
            'like_count': self.like_count,
            'coin_count': self.coin_count,
            'favorite_count': self.favorite_count,
            'share_count': self.share_count,
            'comment_count': self.comment_count,
            'danmaku_count': self.danmaku_count,
        }


class BiliVideoComment(db.Model):
    """B站视频评论（热门评论，最多前10页）

    从 B站 API 爬取的视频评论，用于词云文本源和页面展示。
    """
    __tablename__ = 'bili_video_comments'

    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(
        db.Integer, db.ForeignKey('bili_videos.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    content = db.Column(db.Text, nullable=False, comment='评论内容')
    author = db.Column(db.String(64), default='', comment='评论者昵称')
    ctime = db.Column(db.Integer, default=0, comment='评论时间戳')
    like_count = db.Column(db.Integer, default=0, comment='点赞数')

    video = db.relationship('BiliVideo', backref=db.backref('comments', lazy='dynamic', cascade='all, delete-orphan'))


class BiliUpHistory(db.Model):
    """UP 主粉丝数历史快照

    定期（如每天）采样 UP 主的粉丝数，存入此表。
    用于绘制粉丝数变化趋势图。
    __tablename__ = 'bili_up_history'
    """

    __tablename__ = 'bili_up_history'

    id = db.Column(db.Integer, primary_key=True)
    up_id = db.Column(db.Integer, db.ForeignKey('bili_ups.id', ondelete='CASCADE'), nullable=False, index=True)
    follower_count = db.Column(db.Integer, default=0, comment='采样时的粉丝数')
    recorded_at = db.Column(
        db.DateTime, default=lambda: datetime.datetime.now(CST), index=True
    )

    # lazy='joined'：查询时使用 JOIN 一次性加载关联的 BiliUp，减少 N+1 查询
    up = db.relationship('BiliUp', backref='history_records', lazy='joined', passive_deletes=True)


class BiliVideoHistory(db.Model):
    """视频统计数据历史快照

    定期（如每 30 分钟）采样视频的播放/点赞等统计数据，存入此表。
    用于绘制视频数据变化趋势图。

    __tablename__ = 'bili_video_history'

    索引：
      ix_bili_video_history_video_recorded — (video_id, recorded_at) 加速按视频+时间的查询
    """

    __tablename__ = 'bili_video_history'
    __table_args__ = (db.Index('ix_bili_video_history_video_recorded', 'video_id', 'recorded_at'),)

    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.Integer, db.ForeignKey('bili_videos.id', ondelete='CASCADE'), nullable=False, index=True)
    view_count = db.Column(db.Integer, default=0, comment='播放数')
    like_count = db.Column(db.Integer, default=0, comment='点赞数')
    coin_count = db.Column(db.Integer, default=0, comment='投币数')
    favorite_count = db.Column(db.Integer, default=0, comment='收藏数')
    share_count = db.Column(db.Integer, default=0, comment='转发数')
    comment_count = db.Column(db.Integer, default=0, comment='评论数')
    danmaku_count = db.Column(db.Integer, default=0, comment='弹幕数')
    recorded_at = db.Column(
        db.DateTime, default=lambda: datetime.datetime.now(CST), index=True
    )

    # lazy='joined'：查询时 JOIN BiliVideo，避免 N+1
    # 因为历史快照总是需要关联视频信息，所以使用 joined 加载
    video = db.relationship('BiliVideo', backref='history_records', lazy='joined')


class BiliWatchedVideo(db.Model):
    """用户标记的重点追踪视频（每 30 分钟增量检查时更新统计）

    通过将某个视频加入此表，系统会在定时任务中高频刷新其统计数据，
    实现实时追踪特定视频的播放/点赞变化。

    __tablename__ = 'bili_watched_videos'
    """

    __tablename__ = 'bili_watched_videos'

    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(
        db.Integer, db.ForeignKey('bili_videos.id', ondelete='CASCADE'), unique=True, nullable=False
    )
    added_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(CST))

    # lazy='joined'：查询时 JOIN BiliVideo
    video = db.relationship('BiliVideo', backref='watched_entry', lazy='joined')


class BiliSubscription(db.Model):
    """B站 UP 主邮件订阅

    用户通过邮箱订阅某个 UP 主，新视频发布时接收邮件通知。
    需通过邮件验证链接确认后才激活。

    批量订阅：一次订阅多个 UP 主时，所有记录共用同一个 token，
    验证/取消订阅时批量操作。

    约束：
      (email, up_id) 联合唯一，防止同一用户重复订阅同一 UP 主。
      token 有普通索引（非 UNIQUE），支持批量共用。

    __tablename__ = 'bili_subscriptions'
    """

    __tablename__ = 'bili_subscriptions'
    # 联合唯一约束：同一用户不能重复订阅同一 UP 主
    __table_args__ = (db.UniqueConstraint('email', 'up_id', name='uq_sub_email_up'),)

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False, index=True)  # 订阅者邮箱
    up_id = db.Column(db.Integer, db.ForeignKey('bili_ups.id', ondelete='CASCADE'), nullable=False, index=True)
    token = db.Column(
        db.String(64), nullable=False, index=True, comment='验证/取消订阅 token（同批次相同）'
    )
    verified = db.Column(db.Boolean, default=False, comment='是否已通过邮件验证')
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(CST))

    # passive_deletes=True：不主动加载关联对象，让数据库级联删除
    up = db.relationship('BiliUp', backref=db.backref('subscriptions', lazy='dynamic'), passive_deletes=True)


class BiliCleanupConfig(db.Model):
    """B站历史快照自动清理配置

    配置自动清理几天前的历史数据，避免数据表无限膨胀。
    __tablename__ = 'bili_cleanup_config'
    """

    __tablename__ = 'bili_cleanup_config'

    id = db.Column(db.Integer, primary_key=True)
    days = db.Column(db.Integer, default=90, nullable=False, comment='清理几天前的数据')
    enabled = db.Column(db.Boolean, default=False, comment='是否启用自动清理')
    updated_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(CST))


class HeroImage(db.Model):
    """首页粒子画像模型。

    __tablename__ = 'hero_images'

    管理员通过后台上传透明背景 PNG 立绘，
    首页每次刷新随机选择一张激活的画像，
    由 particle-hero.js 引擎采样为粒子系统展示。

    字段说明：
      title      — 角色名（如"小鸟游星野"），仅后台展示用
      image_url  — 图片文件的静态 URL（如 /static/uploads/hero/xxx.png）
      is_active  — 是否在首页随机池中
      sort_order — 排序权重（越小越优先）
    """

    __tablename__ = 'hero_images'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(128), default='')  # 角色名/标题，仅后台展示
    image_url = db.Column(db.String(512), nullable=False)  # 图片静态 URL
    is_active = db.Column(db.Boolean, default=True, index=True)  # 是否启用（首页随机展示）
    sort_order = db.Column(db.Integer, default=0)  # 排序权重
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))))


class WordCloudConfig(db.Model):
    """词云配置模型。

    单行配置表，存储词云渲染参数（形状、字号、配色等）。
    通过 get_or_create() 惰性初始化，确保始终只有一行数据。
    """
    __tablename__ = 'wordcloud_config'

    id = db.Column(db.Integer, primary_key=True)
    # 词云形状：circle / star / heart / cloud / rectangle
    shape = db.Column(db.String(20), default='circle', nullable=False)
    max_font = db.Column(db.Integer, default=48, nullable=False)
    min_font = db.Column(db.Integer, default=14, nullable=False)
    # 文章详情页显示的词数
    top_n_article = db.Column(db.Integer, default=60, nullable=False)
    # 首页全站词云显示的词数
    top_n_site = db.Column(db.Integer, default=50, nullable=False)
    # 词云画布高度（px）
    canvas_height = db.Column(db.Integer, default=350, nullable=False)
    # B站视频标题词云显示的词数
    top_n_bili = db.Column(db.Integer, default=100, nullable=False)
    # 配色方案：glow / ocean / forest
    color_scheme = db.Column(db.String(20), default='glow', nullable=False)
    # 是否在文章详情页显示词云
    enabled_article = db.Column(db.Boolean, default=True, nullable=False)
    # 是否在首页显示全站词云
    enabled_site = db.Column(db.Boolean, default=True, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))),
        onupdate=lambda: datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))),
    )

    @classmethod
    def get_or_create(cls):
        """获取配置（单行），不存在时自动创建默认配置。

        Returns:
            WordCloudConfig: 配置实例
        """
        config = cls.query.first()
        if config is None:
            config = cls()
            from . import db
            db.session.add(config)
            db.session.commit()
        return config

    def to_dict(self):
        """将配置转为字典，供模板和前端使用。

        Returns:
            dict: 配置字典
        """
        return {
            'shape': self.shape,
            'maxFont': self.max_font,
            'minFont': self.min_font,
            'top_n_article': self.top_n_article,
            'top_n_site': self.top_n_site,
            'canvasHeight': self.canvas_height,
            'top_n_bili': self.top_n_bili,
            'color_scheme': self.color_scheme,
            'enabled_article': self.enabled_article,
            'enabled_site': self.enabled_site,
        }


class CompressedJSON(db.TypeDecorator):
    """透明 ZLIB 压缩 JSON 列。

    写入时自动压缩（dict/list → zlib BLOB），读取时自动解压。
    对上层代码完全透明，使用方式与普通 JSON 列无异。

    MySQL COMPRESS()/UNCOMPRESS() 与 Python zlib 使用相同的 RFC 1950 格式，
    因此迁移阶段用 MySQL COMPRESS() 压缩的历史数据可直接用 Python 解压。
    """

    impl = db.LargeBinary

    def process_bind_param(self, value, dialect):
        """写入时：Python list/dict → JSON 字符串 → zlib 压缩 → BLOB。"""
        if value is None:
            return None
        return zlib.compress(json.dumps(value, ensure_ascii=False).encode('utf-8'))

    def process_result_value(self, value, dialect):
        """读取时：BLOB → zlib 解压 → JSON 解码 → Python list/dict。

        兼容 3 种存储格式：
          1. 纯 zlib（Python zlib.compress 写入，首字节 0x78）
          2. MySQL COMPRESS() 格式（4 字节长度前缀 + zlib，第 5 字节 0x78）
          3. 未压缩的明文 JSON（迁移前的旧数据）
        """
        if value is None:
            return None
        logger = logging.getLogger(__name__ + '.CompressedJSON')
        # 格式 1：纯 zlib
        try:
            return json.loads(zlib.decompress(value).decode('utf-8'))
        except (zlib.error, UnicodeDecodeError):
            pass
        # 格式 2：MySQL COMPRESS（跳过 4 字节长度前缀）
        try:
            return json.loads(zlib.decompress(value[4:]).decode('utf-8'))
        except (zlib.error, UnicodeDecodeError, IndexError):
            pass
        # 格式 3：未压缩的明文 JSON
        try:
            return json.loads(value.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.warning('wordcloud data corrupt: first 8 bytes=%s len=%d',
                           value[:8].hex(), len(value))
            return []


class WordCloudData(db.Model):
    """预计算词云数据。

    每篇文章一行（post_id 有值），全站词云一行（post_id 为 NULL）。
    数据在发布/更新文章时触发重新计算，或由定时任务每日刷新。
    """
    __tablename__ = 'wordcloud_data'

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(
        db.Integer, db.ForeignKey('posts.id', ondelete='CASCADE'),
        nullable=True, index=True,
        comment='文章 ID，NULL 表示全站词云',
    )
    period = db.Column(
        db.String(32), default='all', index=True,
        comment='时间周期: all=全部, 2026-01=某月, bvid_xxx=单视频, up_id=单UP',
    )
    source = db.Column(
        db.String(16), default='blog', index=True,
        comment='来源: blog=博客文章, bili=B站视频, bili_video=单视频',
    )
    data = db.Column(CompressedJSON, nullable=False, comment='词频数据 [{word, weight}, ...]')
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))),
        onupdate=lambda: datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))),
    )

    post = db.relationship('Post', backref=db.backref('wordcloud_data', uselist=False, cascade='all, delete-orphan'))
