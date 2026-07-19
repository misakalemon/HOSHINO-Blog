"""
HOSHINO Blog — 数据模型

四个核心模型：
  User     — 用户（管理员 + 普通用户）
  Category — 文章分类（支持多对多）
  Post     — 文章（支持多对多分类，最多 15 个）
  Comment  — 评论（需管理员审核）

关联关系：
  User ──1:N──→ Post                  一个用户有多篇文章
  Post ──M:N──→ Category             一篇文章可属于多个分类
  Post ──1:N──→ Comment               一篇文章有多条评论

技术栈：
  Flask-SQLAlchemy — ORM 映射
  Flask-Login 的 UserMixin — 提供 is_authenticated / is_active 等属性
  Werkzeug 的 security 模块 — 密码哈希（PBKDF2-SHA256）
"""

import datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from werkzeug.security import check_password_hash, generate_password_hash

# SQLAlchemy 实例，所有模型共享
# 采用延迟初始化模式：先创建 db 实例，然后在 create_app() 中 db.init_app(app)
db = SQLAlchemy()


# ── 多对多关联表 ────────────────────────────────
# 文章 ↔ 分类 的多对多关系表
# 允许一篇文章属于多个分类，一个分类包含多篇文章
# 使用 SQLAlchemy 的 Table 定义，不是 Model 类
post_categories = db.Table(
    'post_categories',
    # post_id 和 category_id 组成联合主键，确保同一对关系不重复
    db.Column('post_id', db.Integer, db.ForeignKey('posts.id'), primary_key=True),
    db.Column('category_id', db.Integer, db.ForeignKey('categories.id'), primary_key=True),
)


class User(UserMixin, db.Model):
    """用户模型。

    继承 UserMixin 以获得 Flask-Login 所需的：
      is_authenticated, is_active, is_anonymous, get_id()
    不需要显式实现这些方法。

    __tablename__ = 'users'

    角色系统：
      admin  — 超级管理员，所有权限
      editor — 编辑，可管理文章/分类/评论
      author — 作者，可撰写/编辑自己的文章
      user   — 普通订阅用户，仅前台浏览
    """

    __tablename__ = 'users'

    ROLE_ADMIN = 'admin'
    ROLE_EDITOR = 'editor'
    ROLE_AUTHOR = 'author'
    ROLE_USER = 'user'

    # ── 基本信息 ────────────────────────────────
    id = db.Column(db.Integer, primary_key=True)  # 主键，自增
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)  # 登录名，唯一
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)  # 邮箱，唯一
    password_hash = db.Column(db.String(256), nullable=False)  # 加密后的密码哈希值

    # ── 个人信息（可选） ─────────────────────────
    display_name = db.Column(db.String(128), default='')  # 显示昵称（页面展示用）
    bio = db.Column(db.Text, default='')  # 个人简介
    avatar = db.Column(  # 头像路径（相对于 static/）
        db.String(256), default='images/avatar/main-avatar.jpg'
    )
    website = db.Column(db.String(256), default='')  # 个人网站/社交媒体链接
    gitcode_url = db.Column(db.String(256), default='')  # GitCode 主页
    github_url = db.Column(db.String(256), default='')  # GitHub 主页
    gitee_url = db.Column(db.String(256), default='')  # Gitee 主页
    bilibili_url = db.Column(db.String(256), default='')  # Bilibili 主页
    about_content = db.Column(MEDIUMTEXT, default='')  # 关于页面内容（富文本 HTML）

    # ── 权限状态 ────────────────────────────────
    role = db.Column(db.String(16), default='user')  # 角色：admin/editor/author/user
    is_active = db.Column(db.Boolean, default=True)  # 是否激活（可登录）

    # ── 登录追踪 ────────────────────────────────
    last_login_at = db.Column(db.DateTime, nullable=True)  # 最后登录时间
    last_login_ip = db.Column(db.String(45), default='')  # 最后登录 IP
    login_count = db.Column(db.Integer, default=0)  # 登录次数

    # ── 时间戳 ──────────────────────────────────
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    # ── 关联关系 ────────────────────────────────
    posts = db.relationship('Post', backref='author', lazy='dynamic')

    # ── 属性 ────────────────────────────────────
    @property
    def is_admin(self):
        return self.role == self.ROLE_ADMIN

    @is_admin.setter
    def is_admin(self, value):
        self.role = self.ROLE_ADMIN if value else self.ROLE_USER

    @property
    def is_editor(self):
        return self.role in (self.ROLE_ADMIN, self.ROLE_EDITOR)

    @property
    def is_author(self):
        """可撰写/管理自己的文章：admin、editor、user 均有此权限。"""
        return self.role in (self.ROLE_ADMIN, self.ROLE_EDITOR, self.ROLE_USER)

    @property
    def role_label(self):
        return {
            self.ROLE_ADMIN: '管理员',
            self.ROLE_EDITOR: '编辑',
            self.ROLE_USER: '用户',
        }.get(self.role, '用户')

    @property
    def role_badge_class(self):
        return {
            self.ROLE_ADMIN: 'badge-admin',
            self.ROLE_EDITOR: 'badge-editor',
            self.ROLE_USER: 'badge-user',
        }.get(self.role, 'badge-user')

    # ── 密码方法 ────────────────────────────────
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # ── 序列化 ──────────────────────────────────
    def to_dict(self):
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

    每个分类有唯一的 name 和 slug（slug 用于 URL）。
    通过 post_categories 关联表与 Post 建立多对多关系。
    """

    __tablename__ = 'categories'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)  # 分类名，唯一
    slug = db.Column(db.String(64), unique=True, nullable=False, index=True)  # URL 标识
    description = db.Column(db.Text, default='')  # 分类描述
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    # 多对多关联：一个分类包含多篇文章
    # secondary 指向关联表 post_categories
    # back_populates='categories' 与 Post 中的 categories 对应
    # lazy='dynamic' 返回 Query 而非列表
    posts = db.relationship(
        'Post', secondary=post_categories, back_populates='categories', lazy='dynamic'
    )

    def post_count(self):
        """返回该分类下已发布的文章数。

        过滤 is_published=True，不统计草稿。
        """
        return self.posts.filter_by(is_published=True).count()


class Post(db.Model):
    """文章模型。

    __tablename__ = 'posts'

    文章支持 Markdown 格式的内容，支持多分类标签，
    关联的评论需要管理员审核后才能公开显示。
    slug 用于 URL 友好访问，必须唯一。
    """

    __tablename__ = 'posts'
    __table_args__ = (db.Index('ix_post_fulltext', 'title', 'content', mysql_prefix='FULLTEXT'),)

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(256), nullable=False)  # 文章标题
    slug = db.Column(db.String(256), unique=True, nullable=False, index=True)  # URL 标识
    summary = db.Column(db.Text, default='')  # 文章摘要（列表页使用）
    content = db.Column(MEDIUMTEXT, nullable=False)  # 正文（支持长文）
    cover_image = db.Column(db.String(256), default='')  # 封面图片路径
    html_file_url = db.Column(db.String(512), default='')  # 自定义 HTML 页面文件路径（可选）
    author_id = db.Column(  # 作者（外键 → users.id）
        db.Integer, db.ForeignKey('users.id'), nullable=False
    )
    is_published = db.Column(db.Boolean, default=False, index=True)  # 是否已发布

    # ── 时间戳 ──────────────────────────────────
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), index=True
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc),  # 更新时自动修改
    )

    # ── 关联关系 ────────────────────────────────
    # 多对多：一篇文章可以有多个分类（最多 15 个）
    # lazy='select' 在访问时才加载（默认行为）
    categories = db.relationship(
        'Category', secondary=post_categories, back_populates='posts', lazy='select'
    )
    # 一对多：一篇文章有多条评论
    # lazy='dynamic' 返回 Query，可链式过滤 is_approved=True
    comments = db.relationship(
        'Comment', backref='post', lazy='dynamic', order_by='Comment.created_at'
    )

    # ── 辅助方法 ────────────────────────────────
    def published_comments(self):
        """返回已审核通过的评论数。"""
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
    """

    __tablename__ = 'comments'

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(  # 所属文章（外键 → posts.id）
        db.Integer, db.ForeignKey('posts.id', ondelete='CASCADE'), nullable=False
    )
    author_name = db.Column(db.String(128), nullable=False)  # 评论者昵称
    author_email = db.Column(db.String(120), nullable=True)  # 评论者邮箱（选填）
    content = db.Column(db.Text, nullable=False)  # 评论正文
    is_approved = db.Column(db.Boolean, default=False)  # 管理员审核标记
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))


class ContactMessage(db.Model):
    """联系页留言"""

    __tablename__ = 'contact_messages'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    subject = db.Column(db.String(256), default='')
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))


class FeaturedCard(db.Model):
    """首页特色卡片（可后台管理）。

    __tablename__ = 'featured_cards'
    """

    __tablename__ = 'featured_cards'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(128), nullable=False)
    description = db.Column(db.String(256), default='')
    icon = db.Column(db.String(256), default='✦')
    tag = db.Column(db.String(16), default='anime')
    link = db.Column(db.String(256), default='')
    image_url = db.Column(db.String(256), default='')
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc),
    )


class ExchangeRate(db.Model):
    """汇率记录（外币对人民币）。

    每次 Exa 爬取时自动记录各币种实时汇率，
    用于汇率走势分析和历史回溯。
    __tablename__ = 'exchange_rates'
    """

    __tablename__ = 'exchange_rates'

    id = db.Column(db.Integer, primary_key=True)
    currency = db.Column(db.String(10), nullable=False, index=True)  # USD / EUR / GBP
    rate = db.Column(db.Float, nullable=False)  # → CNY
    recorded_at = db.Column(
        db.DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), index=True
    )


# ── Bilibili 数据 ────────────────────────────────


class BiliUp(db.Model):
    """B站 UP 主"""

    __tablename__ = 'bili_ups'

    id = db.Column(db.Integer, primary_key=True)
    mid = db.Column(db.BigInteger, unique=True, nullable=False, index=True, comment='B站 mid')
    name = db.Column(db.String(128), default='', comment='UP主名称')
    avatar = db.Column(db.String(256), default='', comment='头像 URL')
    space_url = db.Column(db.String(256), default='', comment='空间链接')
    video_count = db.Column(db.Integer, default=0, comment='视频数')
    follower_count = db.Column(db.Integer, default=0, comment='粉丝数')
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc),
    )

    videos = db.relationship(
        'BiliVideo', backref='up', lazy='dynamic', cascade='all, delete-orphan'
    )

    def __repr__(self):
        return f'<BiliUp {self.name or self.mid}>'

    @property
    def safe_avatar(self):
        return (self.avatar or '').replace('http://', 'https://')


class BiliVideo(db.Model):
    """B站视频数据"""

    __tablename__ = 'bili_videos'
    __table_args__ = (
        db.Index('ix_bili_video_up_pubdatetime', 'up_id', 'pub_datetime'),
        db.Index('ix_bili_video_up_updated', 'up_id', 'updated_at'),
    )

    id = db.Column(db.Integer, primary_key=True)
    up_id = db.Column(db.Integer, db.ForeignKey('bili_ups.id'), nullable=False, index=True)
    bvid = db.Column(db.String(64), unique=True, nullable=False, index=True, comment='BV 号')
    aid = db.Column(db.BigInteger, unique=True, nullable=False, comment='稿件 ID')
    title = db.Column(db.Text, nullable=True, comment='视频标题')
    description = db.Column(db.Text, nullable=True, comment='视频简介')
    duration = db.Column(db.Integer, default=0, comment='时长（秒）')
    pubdate = db.Column(db.Integer, nullable=True, comment='发布时间戳')
    pub_date = db.Column(db.Date, nullable=True, comment='发布日期')
    pub_datetime = db.Column(db.DateTime, nullable=True, comment='发布日期时间')
    view_count = db.Column(db.Integer, default=0, comment='播放数')
    like_count = db.Column(db.Integer, default=0, comment='点赞数')
    coin_count = db.Column(db.Integer, default=0, comment='投币数')
    favorite_count = db.Column(db.Integer, default=0, comment='收藏数')
    share_count = db.Column(db.Integer, default=0, comment='转发数')
    comment_count = db.Column(db.Integer, default=0, comment='评论数')
    danmaku_count = db.Column(db.Integer, default=0, comment='弹幕数')
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc),
    )

    def __repr__(self):
        return f'<BiliVideo {self.bvid} {self.title[:20]!r}>'

    def to_dict(self):
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


class BiliUpHistory(db.Model):
    """UP 主粉丝数历史快照"""

    __tablename__ = 'bili_up_history'

    id = db.Column(db.Integer, primary_key=True)
    up_id = db.Column(db.Integer, db.ForeignKey('bili_ups.id'), nullable=False, index=True)
    follower_count = db.Column(db.Integer, default=0, comment='粉丝数')
    recorded_at = db.Column(
        db.DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), index=True
    )

    up = db.relationship('BiliUp', backref='history_records', lazy='joined')


class BiliVideoHistory(db.Model):
    """视频统计数据历史快照"""

    __tablename__ = 'bili_video_history'
    __table_args__ = (db.Index('ix_bili_video_history_video_recorded', 'video_id', 'recorded_at'),)

    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.Integer, db.ForeignKey('bili_videos.id'), nullable=False, index=True)
    view_count = db.Column(db.Integer, default=0, comment='播放数')
    like_count = db.Column(db.Integer, default=0, comment='点赞数')
    coin_count = db.Column(db.Integer, default=0, comment='投币数')
    favorite_count = db.Column(db.Integer, default=0, comment='收藏数')
    share_count = db.Column(db.Integer, default=0, comment='转发数')
    comment_count = db.Column(db.Integer, default=0, comment='评论数')
    danmaku_count = db.Column(db.Integer, default=0, comment='弹幕数')
    recorded_at = db.Column(
        db.DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), index=True
    )

    video = db.relationship('BiliVideo', backref='history_records', lazy='joined')


class BiliWatchedVideo(db.Model):
    """用户标记的重点追踪视频（每 30 分钟增量检查时更新统计）"""

    __tablename__ = 'bili_watched_videos'

    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(
        db.Integer, db.ForeignKey('bili_videos.id', ondelete='CASCADE'), unique=True, nullable=False
    )
    added_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    video = db.relationship('BiliVideo', backref='watched_entry', lazy='joined')


class BiliSubscription(db.Model):
    """B站 UP 主邮件订阅

    用户通过邮箱订阅某个 UP 主，新视频发布时接收邮件通知。
    需通过邮件验证链接确认后才激活。

    批量订阅：一次订阅多个 UP 主时，所有记录共用同一个 token，
    验证/取消订阅时批量操作。
    """

    __tablename__ = 'bili_subscriptions'
    __table_args__ = (db.UniqueConstraint('email', 'up_id', name='uq_sub_email_up'),)

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False, index=True)
    up_id = db.Column(db.Integer, db.ForeignKey('bili_ups.id'), nullable=False, index=True)
    token = db.Column(
        db.String(64), nullable=False, index=True, comment='验证/取消订阅 token（同批次相同）'
    )
    verified = db.Column(db.Boolean, default=False, comment='是否已通过邮件验证')
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    up = db.relationship('BiliUp', backref=db.backref('subscriptions', lazy='dynamic'))


class BiliCleanupConfig(db.Model):
    """B站历史快照自动清理配置"""

    __tablename__ = 'bili_cleanup_config'

    id = db.Column(db.Integer, primary_key=True)
    days = db.Column(db.Integer, default=90, nullable=False, comment='清理几天前的数据')
    enabled = db.Column(db.Boolean, default=False, comment='是否启用自动清理')
    updated_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))


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
      sort_order — 排序权重
    """

    __tablename__ = 'hero_images'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(128), default='')
    image_url = db.Column(db.String(512), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
