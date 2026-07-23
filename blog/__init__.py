"""
HOSHINO Blog — 蓝图注册与数据库初始化

职责：
  1. 定义前台（blog_bp）和后台（admin_bp）两个 Flask Blueprint。
  2. 提供 init_db() 函数，在应用启动时执行：
     - 建表（db.create_all）
     - 自动迁移 v1（单分类）→ v2（多对多分类）
     - 创建默认管理员（首次启动）
  3. 后导入（lazy import）routes 和 admin 模块，避免循环依赖。

Blueprint 路由前缀：
  blog_bp  → / （前台，无前缀）
  admin_bp → /admin （后台，自动追加前缀）

导入顺序约定：
  创建蓝图 → 导入模型 → 导入路由
  这个顺序是打破 Flask 循环导入的关键模式。
"""

from flask import Blueprint
from flask_migrate import Migrate

# ── 蓝图 ──────────────────────────────────────────
# 前台 blueprint（URL 前缀为空，所有前台路由直接挂在 / 下）
blog_bp = Blueprint('blog', __name__)
# 后台 blueprint（所有后台路由自动添加 /admin 前缀）
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


# 先导入模型，确保 admin 和 routes 中的 from .models import ... 可用
# 这种 "先声明蓝图、再导入模型、最后导入路由" 的顺序是关键，
# 可以避免 Flask 常见的循环导入问题。
from .models import (
    BiliSubscription,
    BiliUp,
    BiliUpHistory,
    BiliVideo,
    BiliVideoHistory,
    BiliWatchedVideo,
    Category,
    Comment,
    FeaturedCard,
    HeroImage,
    Post,
    User,
    db,
)

# ── 蓝图集合 ──────────────────────────────────────
# 将所有 blueprint 放入字典，供 create_app() 批量注册
blueprints = {
    'blog_bp': blog_bp,
    'admin_bp': admin_bp,
}

import re


@blog_bp.app_template_filter('inline_html')
def inline_html(html):
    """剥离外壳 + CSS 作用域化 + 包裹 #html-scope，实现内联渲染无样式冲突。

    处理流程（三步）：
      1. 剥离：移除 DOCTYPE / html / head / body 外壳标签，保留内部全部内容
      2. 作用域化：将 <style> 内的每条 CSS 选择器前加上 #html-scope 前缀
      3. 包裹：在最外层套上 <div id="html-scope">，使作用域选择器生效

    作用域化处理了以下场景：
      - 普通 CSS 规则：添加前缀（.foo → #html-scope .foo）
      - body/html 选择器：替换为 #html-scope
      - * 选择器：替换为 #html-scope *
      - @media / @supports 规则：内部子规则递归作用域化
      - @keyframes/font-face：完整保留，不做作用域化
      - 已包含 #html-scope 的选择器：保持原样

    Args:
        html: 原始 HTML 字符串（可选含 DOCTYPE 的完整文档）

    Returns:
        作用域化的内联 HTML，或原始输入（输入为空时）
    """
    if not html:
        return html
    # 1. 剥离 DOCTYPE/html/head/body 外壳标签（保留内部全部内容）
    # 使用 re.IGNORECASE 兼容大小写混用的情况
    html = re.sub(r'<!DOCTYPE[^>]*>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'</?html[^>]*>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'</?head[^>]*>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'</?body[^>]*>', '', html, flags=re.IGNORECASE)

    # 2. 作用域化 <style> 内的 CSS
    def _scope_css(match):
        """对单个 <style> 标签内的 CSS 文本做作用域化处理。

        内部实现说明：
          - 按顶级花括号深度将 CSS 拆解为块（chunks）
          - 每个块独立判断 → 作用域化 or 跳过
          - 支持嵌套的 @ 规则（如 @media 中的 @keyframes）

        Args:
            match: re.sub 传入的匹配对象，match.group(1) 为 CSS 文本

        Returns:
            作用域化后的 CSS 文本
        """
        css = match.group(1)  # <style>...</style> 之间的原始 CSS
        SEL = '#html-scope'

        def _scope_one(sel):
            """为单个选择器添加作用域前缀。

            规则：
              - 空字符串或已含 #html-scope → 不变
              - body/html → #html-scope（视为根元素）
              - * → #html-scope *（全局选择器限定在作用域内）
              - 其他选择器 → #html-scope <原始选择器>

            Args:
                sel: 单个 CSS 选择器字符串

            Returns:
                作用域化后的选择器字符串
            """
            s = sel.strip()
            if not s or SEL in s:
                return s
            if s in ('body', 'html'):
                return SEL
            if s == '*':
                return f'{SEL} *'
            return f'{SEL} {s}'

        # 按顶级花括号深度拆块
        # 一个"块"是一条完整的 CSS 规则（选择器 + { 声明 }）
        # 或一个完整的 @ 规则
        chunks = []
        depth = 0
        buf = []
        for ch in css:
            buf.append(ch)
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    # depth 回到 0 表示一个完整的顶级块结束
                    chunks.append(''.join(buf).strip())
                    buf = []
        # 处理末尾未闭合的文本（如尾部注释或多余空格）
        if buf and ''.join(buf).strip():
            chunks.append(''.join(buf).strip())

        out = []
        for chunk in chunks:
            if not chunk:
                continue
            if chunk.startswith('@'):
                # 处理 @ 规则（@media, @keyframes, @font-face, @supports 等）
                if chunk.startswith(('@keyframes', '@font-face')):
                    # @keyframes 和 @font-face 中的选择器是非标准的，
                    # 作用域化会导致动画/字体失效，完整保留
                    out.append(chunk)
                    continue
                # 其他 @ 规则（如 @media, @supports）：对外层不处理，
                # 对内层子规则递归作用域化
                m = re.match(r'(@[^{]+)\{(.*)\}$', chunk, re.DOTALL)
                if m:
                    head = m.group(1)  # @media (max-width: 768px)
                    inner = m.group(2)  # 内部规则集
                    scoped = re.sub(
                        r'([^{}]+)(\s*\{)',
                        lambda m: ', '.join(
                            _scope_one(s) for s in m.group(1).split(',')
                        )
                        + m.group(2),
                        inner,
                    )
                    out.append(f'{head}{{{scoped}}}')
                else:
                    out.append(chunk)
            elif '{' in chunk:
                # 普通 CSS 规则：选择器 { 声明 }
                idx = chunk.index('{')
                sel_part = chunk[:idx]  # 选择器部分（逗号分隔）
                rest = chunk[idx:]       # { 声明 }
                scoped_sel = ', '.join(
                    _scope_one(s) for s in sel_part.split(',')
                )
                out.append(f'{scoped_sel} {rest}')
            else:
                # 无花括号的片段（如注释、空白），原样保留
                out.append(chunk)
        return '\n'.join(out)

    html = re.sub(
        r'<style[^>]*>(.*?)</style>',
        lambda m: '<style>' + _scope_css(m) + '</style>',
        html,
        flags=re.DOTALL,
    )

    # 3. 包裹作用域容器
    # 使用 <div id="html-scope"> 作为作用域根元素，
    # 配合第二步中添加的 #html-scope 前缀选择器实现样式隔离
    return f'<div id="html-scope">{html}</div>'


def init_db(app):
    """初始化数据库：建表 + 自动迁移 + 创建默认管理员。

    执行流程：
    1. db.init_app(app)         — 将 SQLAlchemy 绑定到 Flask 应用
    2. db.create_all()          — 创建所有未存在的表
    3. _migrate_category_to_many2many() — 兼容旧版单分类数据
    4. 检查 admin 用户是否已存在 → 不存在则创建默认管理员

    注意：
      - 所有 _migrate_* 函数在每次启动时都会执行，
        它们内部会通过 inspector 检查列是否存在，确保幂等性。
      - 迁移仅对 MySQL 数据库执行，SQLite 不会执行 ALTER TABLE。
    """
    # 防止重复初始化
    # app.extensions 记录了已注册的 Flask 扩展，避免重复注册
    if 'sqlalchemy' not in app.extensions:
        db.init_app(app)
    if 'migrate' not in app.extensions:
        Migrate(app, db)
    with app.app_context():
        # ── 建表 ──────────────────────────────────
        # SQLAlchemy 根据 Model 定义自动 CREATE TABLE IF NOT EXISTS
        db.create_all()

        # ── 自动迁移 v1→v2 ───────────────────────
        # 检查 posts 表是否还有旧的 category_id 列，
        # 如果有则将其数据复制到新版的 post_categories 关联表
        _migrate_category_to_many2many(app)

        # ── 迁移 is_admin 布尔值 → role 字符串 ──
        # 必须在任何 User 查询之前执行，因为新字段还不存在于 MySQL 表中
        _migrate_is_admin_to_role(app)

        # ── 迁移 User 新增列（gitcode_url, github_url, about_content）──
        # 也必须在任何 User 查询之前执行
        _migrate_user_profile_fields(app)

        # ── 创建默认管理员 ────────────────────────
        # 仅当 users 表中没有任何用户名为 "admin" 的记录时执行
        if not User.query.filter_by(username='admin').first():
            import secrets

            admin_password = app.config.get('ADMIN_PASSWORD', 'CHANGE_ME')
            if admin_password == 'CHANGE_ME':
                admin_password = secrets.token_urlsafe(24)
                app.logger.warning('=' * 60)
                app.logger.warning('默认管理员密码未设置，已自动生成: %s', admin_password)
                app.logger.warning('请在 .env 中设置 ADMIN_PASSWORD，或登录后立即修改！')
                app.logger.warning('=' * 60)
            admin = User(
                username=app.config.get('ADMIN_USERNAME', 'admin'),
                email=app.config.get('ADMIN_EMAIL', 'admin@localhost'),
                display_name=app.config.get('ADMIN_DISPLAY_NAME', 'Admin'),
                is_admin=True,
                is_active=True,
            )
            # set_password() 内部使用 werkzeug 的加密哈希，
            # 不会明文存储密码
            admin.set_password(admin_password)
            db.session.add(admin)
            db.session.commit()

        # ── 迁移 author 角色 → user 角色 ────────
        _migrate_author_to_user(app)

        # ── 迁移 FeaturedCard.icon 字段长度 ────
        _migrate_featured_icon(app)

        # ── 迁移 Post.content 从 TEXT 到 MEDIUMTEXT ────
        _migrate_post_content(app)

        # ── 迁移 BiliUp 表新增字段 ────────────────
        _migrate_bili_up_fields(app)

        # ── 迁移 BiliVideo 表新增字段 ──────────────
        _migrate_bili_video_fields(app)

        # ── 迁移 BiliVideo/BiliVideoHistory 复合索引 ─
        _migrate_bili_indexes(app)

        # ── 迁移 BiliSubscription.token 唯一约束 → 普通索引 ─
        _migrate_bili_sub_token_index(app)

        _migrate_post_html_file_url(app)

        _migrate_post_html_content(app)

        # ── 迁移 wordcloud_data 表新增字段 ───────
        _migrate_wordcloud_data_fields(app)

        # ── 迁移 wordcloud_config 表新增字段 ────
        _migrate_wordcloud_config_fields(app)
        _migrate_wordcloud_canvas_height(app)

        # ── 迁移 posts 表 FULLTEXT 索引 ───────
        _migrate_post_fulltext_index(app)

        # ── 迁移 bili_videos.tags 列 ──────────
        _migrate_bili_video_tags(app)

        # ── 迁移 bili_videos.subtitle_text 列 ──
        _migrate_bili_video_subtitle_text(app)

        # ── 迁移 subtitle_text TEXT→MEDIUMTEXT ─
        _migrate_bili_video_subtitle_mediumtext(app)

        # ── 迁移 bili_video_comments 表 ───────
        _migrate_bili_video_comments_table(app)

        # ── 迁移 wordcloud_data.source 长度 ───
        _migrate_wordcloud_source_length(app)

        # ── 迁移 wordcloud_data.period 长度 ───
        _migrate_wordcloud_period_length(app)

        # ── 迁移 bili_videos.comments_crawled_at 列 ──
        _migrate_bili_video_comments_crawled_at(app)

        # ── 迁移 wordcloud_data.data JSON→ZLIB BLOB ──
        _migrate_wordcloud_data_compress(app)


def _migrate_post_html_file_url(app):
    """迁移：为 Post 表添加 html_file_url 字段。

    该字段用于存储自定义 HTML 页面的文件路径（相对于 static 目录），
    使得文章可以展示独立设计的 HTML 页面而非 Markdown 渲染。
    """
    engine = db.get_engine()
    dialect = engine.dialect.name
    # SQLite 不支持动态 ADD COLUMN 带 DEFAULT，跳过
    if dialect != 'mysql':
        return
    inspector = db.inspect(engine)
    cols = {c['name'] for c in inspector.get_columns('posts')}
    if 'html_file_url' not in cols:
        try:
            db.session.execute(db.text("ALTER TABLE posts ADD COLUMN html_file_url VARCHAR(512) DEFAULT ''"))
            db.session.commit()
            app.logger.info('迁移: 已添加 posts.html_file_url 列')
        except Exception as e:
            db.session.rollback()
            app.logger.warning('迁移: 添加 posts.html_file_url 列失败: %s', e)


def _migrate_post_html_content(app):
    """迁移：为 Post 表添加 html_content 列。

    该字段存储直接编写的 HTML 源码（优先于 html_file_url），
    用于内联 HTML 页面模式，不需要额外的文件托管。
    """
    engine = db.get_engine()
    dialect = engine.dialect.name
    if dialect != 'mysql':
        return
    inspector = db.inspect(engine)
    cols = {c['name'] for c in inspector.get_columns('posts')}
    if 'html_content' not in cols:
        try:
            db.session.execute(db.text("ALTER TABLE posts ADD COLUMN html_content MEDIUMTEXT"))
            db.session.commit()
            app.logger.info('迁移: 已添加 posts.html_content 列')
        except Exception as e:
            db.session.rollback()
            app.logger.warning('迁移: 添加 posts.html_content 列失败: %s', e)


def _migrate_category_to_many2many(app):
    """自动迁移：v1 (category_id 单分类) → v2 (post_categories 多对多)。

    迁移逻辑：
      - 如果 posts 表还有 category_id 列 → 复制数据到 post_categories
      - 如果没有该列 → 跳过（已经是 v2 或新库）
      - 兼容 MySQL（INSERT IGNORE）和 SQLite（INSERT OR IGNORE）

    为什么需要：
      项目早期版本中 Post 模型只有单个分类字段 category_id，
      v2 改为多对多关联后，旧数据需要迁移到新的关联表。

    INSERT IGNORE / INSERT OR IGNORE 确保幂等性：
      即使已存在相同的 (post_id, category_id) 对也不会报错。
    """
    engine = db.get_engine()
    inspector = db.inspect(engine)

    # 检查 posts 表是否还有旧版 category_id 列
    cols = [c['name'] for c in inspector.get_columns('posts')]
    if 'category_id' not in cols:
        return  # 已迁移或新库，无需操作

    # 根据数据库类型选择兼容的 INSERT 语法
    #   SQLite → INSERT OR IGNORE
    #   MySQL  → INSERT IGNORE
    # 两种语法语义相同：遇到唯一键冲突时静默跳过
    driver = ''
    try:
        driver = engine.url.get_driver_name()
    except AttributeError:
        pass
    ignore_keyword = 'OR IGNORE' if 'sqlite' in driver else 'IGNORE'

    # 执行迁移 SQL：将所有有分类的文章关联写入 post_categories 表
    try:
        sql = f"""
            INSERT {ignore_keyword} INTO post_categories (post_id, category_id)
            SELECT id, category_id FROM posts WHERE category_id IS NOT NULL
        """
        result = db.session.execute(db.text(sql))
        rowcount = result.rowcount
        if rowcount > 0:
            app.logger.info('迁移: 已迁移 %d 条分类关联记录 (category_id → post_categories)', rowcount)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.warning('迁移: category_id 迁移失败: %s', e)


def _migrate_is_admin_to_role(app):
    """迁移：添加 role 字段 + 将 is_admin 布尔值转换为 role 字符串。

    背景：
      早期版本使用 is_admin (Boolean) 来标记管理员，
      新版本改用 role (String) 来支持更多角色层次。
    执行步骤：
      1. 检查并添加 role / last_login_at / last_login_ip / login_count / website 列
      2. 将 is_admin=True 的用户设为 role='admin'
      3. 删除旧的 is_admin 列

    注意：
      - 仅 MySQL 执行 ALTER TABLE（SQLite 不运行）
      - 列名使用正则校验，防止 SQL 注入（避免 col 参数直接被拼接）
    """
    engine = db.get_engine()
    inspector = db.inspect(engine)
    cols = {c['name'] for c in inspector.get_columns('users')}
    dialect = engine.dialect.name
    from sqlalchemy import text

    # ── 添加缺失的列（仅 MySQL） ─────────────
    if dialect == 'mysql':
        new_columns = {
            'role': "VARCHAR(16) DEFAULT 'user'",
            'last_login_at': 'DATETIME NULL',
            'last_login_ip': "VARCHAR(45) DEFAULT ''",
            'login_count': 'INT DEFAULT 0',
            'website': "VARCHAR(256) DEFAULT ''",
        }
        for col, col_type in new_columns.items():
            if col not in cols:
                try:
                    # 安全性检查：只允许合法的 MySQL 标识符
                    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', col):
                        app.logger.warning('迁移: 跳过非法列名 %s', col)
                        continue
                    db.session.execute(text(f'ALTER TABLE users ADD COLUMN {col} {col_type}'))
                    db.session.commit()
                    app.logger.info('迁移: 已添加 users.%s 列', col)
                except Exception as e:
                    db.session.rollback()
                    app.logger.warning('迁移: 添加 users.%s 列失败: %s', col, e)

    # ── 数据迁移：is_admin → role ────────────
    if 'is_admin' in cols and 'role' in cols:
        # 将 is_admin 为 TRUE/1 的用户角色设为 admin
        result = db.session.execute(
            text("UPDATE users SET role = 'admin' WHERE is_admin = 1 OR is_admin = TRUE")
        )
        if result.rowcount > 0:
            app.logger.info('迁移: 已将 %d 个用户从 is_admin 迁移到 role', result.rowcount)
        db.session.commit()

        # 迁移完成后删除旧列 is_admin
        if dialect == 'mysql':
            try:
                db.session.execute(text('ALTER TABLE users DROP COLUMN is_admin'))
                db.session.commit()
                app.logger.info('迁移: 已删除 is_admin 列')
            except Exception:
                db.session.rollback()


def _migrate_featured_icon(app):
    """迁移 FeaturedCard.icon 从 VARCHAR(16) 到 VARCHAR(256)。

    早期版本限制图标为 16 字符，更新后支持更长的 CSS Class 或图标符号。
    """
    engine = db.get_engine()
    dialect = engine.dialect.name
    if dialect == 'mysql':
        try:
            db.session.execute(
                db.text("ALTER TABLE featured_cards MODIFY icon VARCHAR(256) DEFAULT '✦'")
            )
            db.session.commit()
        except Exception:
            db.session.rollback()


def _migrate_post_content(app):
    """迁移 Post.content 从 TEXT 到 MEDIUMTEXT（支持长文）。

    TEXT 类型最大 65535 字节，对于长篇文章不够，
    MEDIUMTEXT 最大 16MB，满足绝大多数场景。
    """
    engine = db.get_engine()
    dialect = engine.dialect.name
    if dialect == 'mysql':
        try:
            db.session.execute(db.text('ALTER TABLE posts MODIFY content MEDIUMTEXT NOT NULL'))
            db.session.commit()
            app.logger.info('迁移: posts.content 已扩展为 MEDIUMTEXT')
        except Exception:
            db.session.rollback()


def _migrate_author_to_user(app):
    """迁移：将已废弃的 author 角色合并到 user 角色。

    author 角色已被移除，所有权限已转移给 user。
    将数据库中 role='author' 的用户改为 role='user'。
    """
    from sqlalchemy import text

    try:
        result = db.session.execute(text("UPDATE users SET role = 'user' WHERE role = 'author'"))
        if result.rowcount > 0:
            app.logger.info('迁移: 已将 %d 个用户从 author 角色合并到 user 角色', result.rowcount)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.warning('迁移: author→user 合并失败: %s', e)


def _migrate_user_profile_fields(app):
    """迁移：为 User 表添加社交链接和关于页面字段（仅 MySQL 需 ALTER）。

    新增字段：
      gitcode_url     — GitCode 个人主页
      github_url      — GitHub 个人主页
      gitee_url       — Gitee 个人主页
      bilibili_url    — Bilibili 个人主页
      about_content   — 关于页面富文本内容（MEDIUMTEXT 支持长文）

    每个字段通过 inspector 检查是否已存在，确保幂等性。
    """
    engine = db.get_engine()
    inspector = db.inspect(engine)
    cols = {c['name'] for c in inspector.get_columns('users')}
    dialect = engine.dialect.name
    if dialect != 'mysql':
        return
    from sqlalchemy import text

    new_columns = {
        'gitcode_url': "VARCHAR(256) DEFAULT ''",
        'github_url': "VARCHAR(256) DEFAULT ''",
        'gitee_url': "VARCHAR(256) DEFAULT ''",
        'bilibili_url': "VARCHAR(256) DEFAULT ''",
        'about_content': 'MEDIUMTEXT',
    }
    for col, col_type in new_columns.items():
        if col not in cols:
            try:
                if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', col):
                    app.logger.warning('迁移: 跳过非法列名 %s', col)
                    continue
                db.session.execute(text(f'ALTER TABLE users ADD COLUMN {col} {col_type}'))
                db.session.commit()
                app.logger.info('迁移: 已添加 users.%s 列', col)
            except Exception as e:
                db.session.rollback()
                app.logger.warning('迁移: 添加 users.%s 列失败: %s', col, e)


def _migrate_bili_up_fields(app):
    """迁移：为 BiliUp 表添加 follower_count 字段。

    在后续开发中增加了 UP 主粉丝数记录功能，
    需要对已有数据库结构进行扩展。
    """
    engine = db.get_engine()
    inspector = db.inspect(engine)
    cols = {c['name'] for c in inspector.get_columns('bili_ups')}
    dialect = engine.dialect.name
    if dialect != 'mysql':
        return
    from sqlalchemy import text

    if 'follower_count' not in cols:
        try:
            db.session.execute(
                text('ALTER TABLE bili_ups ADD COLUMN follower_count INTEGER DEFAULT 0')
            )
            db.session.commit()
            app.logger.info('迁移: 已添加 bili_ups.follower_count 列')
        except Exception as e:
            db.session.rollback()
            app.logger.warning('迁移: 添加 bili_ups.follower_count 列失败: %s', e)


def _migrate_bili_video_fields(app):
    """迁移：为 BiliVideo 表添加 pub_datetime 字段。

    原有 pubdate 字段为 Unix 时间戳（INT），
    新字段 pub_datetime 为 DATETIME 类型，便于 SQL 查询和 ORM 使用。
    迁移时会用已有 pubdate 回填新字段。
    """
    engine = db.get_engine()
    inspector = db.inspect(engine)
    cols = {c['name'] for c in inspector.get_columns('bili_videos')}
    dialect = engine.dialect.name
    if dialect != 'mysql':
        return
    from sqlalchemy import text

    if 'pub_datetime' not in cols:
        try:
            db.session.execute(text('ALTER TABLE bili_videos ADD COLUMN pub_datetime DATETIME'))
            # 用已有 pubdate 时间戳回填 pub_datetime
            # FROM_UNIXTIME() 是 MySQL 内置函数，将秒级时间戳转为 DATETIME
            db.session.execute(
                text(
                    'UPDATE bili_videos SET pub_datetime = FROM_UNIXTIME(pubdate) WHERE pubdate IS NOT NULL AND pub_datetime IS NULL'
                )
            )
            db.session.commit()
            app.logger.info('迁移: 已添加 bili_videos.pub_datetime 列')
        except Exception as e:
            db.session.rollback()
            app.logger.warning('迁移: 添加 bili_videos.pub_datetime 列失败: %s', e)


def _migrate_bili_indexes(app):
    """迁移：为 BiliVideo/BiliVideoHistory 表添加复合索引。

    添加的索引：
      ix_bili_video_up_pubdatetime    — bili_videos (up_id, pub_datetime)
        加速按 UP 主和时间排序的视频查询
      ix_bili_video_up_updated        — bili_videos (up_id, updated_at)
        加速按 UP 主和更新时间排序的视频查询
      ix_bili_video_history_video_recorded — bili_video_history (video_id, recorded_at)
        加速按视频 ID 和时间范围的历史快照查询

    先检查索引是否已存在（inspector.get_indexes），
    避免重复创建导致错误。
    """
    engine = db.get_engine()
    inspector = db.inspect(engine)
    dialect = engine.dialect.name
    if dialect != 'mysql':
        return
    from sqlalchemy import text

    existing = {ix['name'] for ix in inspector.get_indexes('bili_videos')}
    existing.update(ix['name'] for ix in inspector.get_indexes('bili_video_history'))

    index_defs = {
        'ix_bili_video_up_pubdatetime': 'CREATE INDEX ix_bili_video_up_pubdatetime ON bili_videos (up_id, pub_datetime)',
        'ix_bili_video_up_updated': 'CREATE INDEX ix_bili_video_up_updated ON bili_videos (up_id, updated_at)',
        'ix_bili_video_history_video_recorded': 'CREATE INDEX ix_bili_video_history_video_recorded ON bili_video_history (video_id, recorded_at)',
    }

    for name, ddl in index_defs.items():
        if name in existing:
            continue
        try:
            db.session.execute(text(ddl))
            db.session.commit()
            app.logger.info('迁移: 已添加 %s 索引', name)
        except Exception as e:
            db.session.rollback()
            app.logger.warning('迁移: 添加 %s 索引失败: %s', name, e)


def _migrate_bili_sub_token_index(app):
    """迁移：BiliSubscription.token 从 UNIQUE 改为普通 INDEX（支持批量共用 token）。

    背景：
      早期设计为每封订阅邮件生成唯一 token，
      改为批量订阅后，同一批次的多条订阅共用同一个 token，
      因此 UNIQUE 约束不再适用。
    操作：
      1. 查找 token 列上的 UNIQUE 索引并删除
      2. 添加同名的普通索引（如果不存在）
      3. 尝试回退方案：直接 DROP INDEX token
    """
    engine = db.get_engine()
    dialect = engine.dialect.name
    if dialect != 'mysql':
        return
    from sqlalchemy import text

    inspector = db.inspect(engine)
    indexes = inspector.get_indexes('bili_subscriptions')
    existing_names = {ix['name'] for ix in indexes}

    # 删除 token 列的 UNIQUE 索引
    dropped = False
    for ix in indexes:
        if 'token' in ix.get('column_names', []) and ix.get('unique', False):
            try:
                db.session.execute(text(f'ALTER TABLE bili_subscriptions DROP INDEX {ix["name"]}'))
                db.session.commit()
                app.logger.info('迁移: 已删除 bili_subscriptions 的 UNIQUE 索引 %s', ix['name'])
                dropped = True
            except Exception:
                db.session.rollback()

    # 添加普通索引（如果还没有的话）
    if 'ix_bili_sub_token' not in existing_names:
        try:
            db.session.execute(text('CREATE INDEX ix_bili_sub_token ON bili_subscriptions (token)'))
            db.session.commit()
            app.logger.info('迁移: 已添加 bili_subscriptions.token 普通索引')
        except Exception as e:
            db.session.rollback()
            app.logger.warning('迁移: 添加 bili_subscriptions.token 索引失败: %s', e)

    # 如果 token 列仍存在 UNIQUE 约束（非索引方式），删除它
    # 这是一个回退方案，处理某些 MySQL 版本中 UNIQUE 约束的表现形式差异
    if not dropped and 'token' in inspector.get_columns('bili_subscriptions'):
        try:
            db.session.execute(text('ALTER TABLE bili_subscriptions DROP INDEX token'))
            db.session.commit()
            app.logger.info('迁移: 已删除 bili_subscriptions 的 token 索引（回退方案）')
        except Exception:
            db.session.rollback()


def _migrate_wordcloud_data_fields(app):
    """迁移：为 wordcloud_data 表添加 period 和 source 字段。

    这两个字段在后续开发中新增，用于按月分段词云和区分 B站来源。
    """
    from sqlalchemy import text

    engine = db.get_engine()
    dialect = engine.dialect.name
    if dialect != 'mysql':
        return
    inspector = db.inspect(engine)
    cols = {c['name'] for c in inspector.get_columns('wordcloud_data')}
    for col_name, col_type in [
        ('period', "VARCHAR(16) DEFAULT 'all'"),
        ('source', "VARCHAR(8) DEFAULT 'blog'"),
    ]:
        if col_name not in cols:
            try:
                db.session.execute(
                    text(f'ALTER TABLE wordcloud_data ADD COLUMN {col_name} {col_type}')
                )
                db.session.commit()
                app.logger.info('迁移: 已添加 wordcloud_data.%s 列', col_name)
            except Exception as e:
                db.session.rollback()
                app.logger.warning('迁移: 添加 wordcloud_data.%s 列失败: %s', col_name, e)


def _migrate_wordcloud_config_fields(app):
    """迁移：确保 wordcloud_config 表包含模型定义的所有列。

    逐列检查并补加缺失的列（兼容旧表升级），使用 ALTER TABLE
    配合 DEFAULT 值避免已有行出现 NULL。
    """
    from sqlalchemy import text

    engine = db.get_engine()
    dialect = engine.dialect.name
    if dialect != 'mysql':
        return
    inspector = db.inspect(engine)
    cols = {c['name'] for c in inspector.get_columns('wordcloud_config')}

    missing = {
        'shape': "VARCHAR(20) NOT NULL DEFAULT 'circle'",
        'max_font': 'INTEGER NOT NULL DEFAULT 48',
        'min_font': 'INTEGER NOT NULL DEFAULT 14',
        'top_n_article': 'INTEGER NOT NULL DEFAULT 60',
        'top_n_site': 'INTEGER NOT NULL DEFAULT 50',
        'canvas_height': 'INTEGER NOT NULL DEFAULT 350',
        'top_n_bili': 'INTEGER NOT NULL DEFAULT 100',
        'color_scheme': "VARCHAR(20) NOT NULL DEFAULT 'glow'",
        'enabled_article': 'TINYINT(1) NOT NULL DEFAULT 1',
        'enabled_site': 'TINYINT(1) NOT NULL DEFAULT 1',
        'shape_image': "VARCHAR(256) NOT NULL DEFAULT ''",
        'stop_words': 'TEXT NOT NULL',
    }
    for col_name, col_def in missing.items():
        if col_name not in cols:
            try:
                db.session.execute(
                    text(f'ALTER TABLE wordcloud_config ADD COLUMN {col_name} {col_def}')
                )
                db.session.commit()
                app.logger.info('迁移: 已添加 wordcloud_config.%s 列', col_name)
            except Exception as e:
                db.session.rollback()
                app.logger.warning('迁移: 添加 wordcloud_config.%s 列失败: %s', col_name, e)


def _migrate_wordcloud_canvas_height(app):
    """迁移：为 wordcloud_config 表添加 canvas_height 字段。

    该字段用于自定义词云画布高度。
    """
    from sqlalchemy import text

    engine = db.get_engine()
    dialect = engine.dialect.name
    if dialect != 'mysql':
        return
    inspector = db.inspect(engine)
    cols = {c['name'] for c in inspector.get_columns('wordcloud_config')}
    if 'canvas_height' not in cols:
        try:
            db.session.execute(
                text('ALTER TABLE wordcloud_config ADD COLUMN canvas_height INTEGER DEFAULT 350')
            )
            db.session.commit()
            app.logger.info('迁移: 已添加 wordcloud_config.canvas_height 列')
        except Exception as e:
            db.session.rollback()
            app.logger.warning('迁移: 添加 wordcloud_config.canvas_height 列失败: %s', e)


def _migrate_post_fulltext_index(app):
    """迁移：为 posts 表添加 FULLTEXT 索引（仅 MySQL）。

    用于中文全文搜索 MATCH (title, content) AGAINST (...)。
    已有数据库可能缺少此索引，需手动创建。
    """
    engine = db.get_engine()
    dialect = engine.dialect.name
    if dialect != 'mysql':
        return
    inspector = db.inspect(engine)
    indexes = [ix['name'] for ix in inspector.get_indexes('posts')]
    if 'ix_post_fulltext' not in indexes:
        try:
            db.session.execute(
                text('ALTER TABLE posts ADD FULLTEXT INDEX ix_post_fulltext (title, content)')
            )
            db.session.commit()
            app.logger.info('迁移: 已添加 posts 的 FULLTEXT 索引 ix_post_fulltext')
        except Exception as e:
            db.session.rollback()
            app.logger.warning('迁移: 添加 FULLTEXT 索引失败: %s', e)


def _migrate_bili_video_tags(app):
    """迁移：为 bili_videos 表添加 tags JSON 列。"""
    from sqlalchemy import text

    engine = db.get_engine()
    dialect = engine.dialect.name
    if dialect != 'mysql':
        return
    inspector = db.inspect(engine)
    cols = {c['name'] for c in inspector.get_columns('bili_videos')}
    if 'tags' not in cols:
        try:
            db.session.execute(text('ALTER TABLE bili_videos ADD COLUMN tags JSON NULL COMMENT "视频标签名数组" AFTER created_at'))
            db.session.commit()
            app.logger.info('迁移: 已添加 bili_videos.tags 列')
        except Exception as e:
            db.session.rollback()
            app.logger.warning('迁移: 添加 bili_videos.tags 列失败: %s', e)


def _migrate_bili_video_comments_table(app):
    """迁移：创建 bili_video_comments 表（如不存在）。"""
    from sqlalchemy import text

    engine = db.get_engine()
    dialect = engine.dialect.name
    if dialect != 'mysql':
        return
    inspector = db.inspect(engine)
    tables = inspector.get_table_names()
    if 'bili_video_comments' not in tables:
        try:
            db.session.execute(text('''
                CREATE TABLE bili_video_comments (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    video_id INT NOT NULL,
                    content TEXT NOT NULL,
                    author VARCHAR(64) DEFAULT '',
                    ctime INT DEFAULT 0,
                    like_count INT DEFAULT 0,
                    INDEX idx_video_id (video_id),
                    FOREIGN KEY (video_id) REFERENCES bili_videos(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            '''))
            db.session.commit()
            app.logger.info('迁移: 已创建 bili_video_comments 表')
        except Exception as e:
            db.session.rollback()
            app.logger.warning('迁移: 创建 bili_video_comments 表失败: %s', e)


def _migrate_wordcloud_source_length(app):
    """迁移：扩展 wordcloud_data.source 从 VARCHAR(8) 到 VARCHAR(16)。"""
    from sqlalchemy import text

    engine = db.get_engine()
    dialect = engine.dialect.name
    if dialect != 'mysql':
        return
    inspector = db.inspect(engine)
    cols = {c['name'] for c in inspector.get_columns('wordcloud_data')}
    if 'source' in cols:
        try:
            db.session.execute(text('ALTER TABLE wordcloud_data MODIFY source VARCHAR(16) DEFAULT "blog"'))
            db.session.commit()
            app.logger.info('迁移: 已扩展 wordcloud_data.source 到 VARCHAR(16)')
        except Exception as e:
            db.session.rollback()
            app.logger.warning('迁移: 扩展 wordcloud_data.source 失败: %s', e)


def _migrate_bili_video_subtitle_text(app):
    """迁移：为 bili_videos 表添加 subtitle_text 列。"""
    from sqlalchemy import text

    engine = db.get_engine()
    dialect = engine.dialect.name
    if dialect != 'mysql':
        return
    inspector = db.inspect(engine)
    cols = {c['name'] for c in inspector.get_columns('bili_videos')}
    if 'subtitle_text' not in cols:
        try:
            db.session.execute(
                text('ALTER TABLE bili_videos ADD COLUMN subtitle_text TEXT NULL COMMENT "AI字幕文本"')
            )
            db.session.commit()
            app.logger.info('迁移: 已添加 bili_videos.subtitle_text 列')
        except Exception as e:
            db.session.rollback()
            app.logger.warning('迁移: 添加 bili_videos.subtitle_text 列失败: %s', e)


def _migrate_wordcloud_period_length(app):
    """迁移：扩展 wordcloud_data.period 从 VARCHAR(16) 到 VARCHAR(32)。"""
    from sqlalchemy import text

    engine = db.get_engine()
    dialect = engine.dialect.name
    if dialect != 'mysql':
        return
    inspector = db.inspect(engine)
    cols = {c['name'] for c in inspector.get_columns('wordcloud_data')}
    if 'period' in cols:
        try:
            db.session.execute(text('ALTER TABLE wordcloud_data MODIFY period VARCHAR(32) DEFAULT "all"'))
            db.session.commit()
            app.logger.info('迁移: 已扩展 wordcloud_data.period 到 VARCHAR(32)')
        except Exception as e:
            db.session.rollback()
            app.logger.warning('迁移: 扩展 wordcloud_data.period 失败: %s', e)


def _migrate_bili_video_comments_crawled_at(app):
    """迁移：为 BiliVideo 表添加 comments_crawled_at 字段。"""
    from sqlalchemy import text

    engine = db.get_engine()
    inspector = db.inspect(engine)
    cols = {c['name'] for c in inspector.get_columns('bili_videos')}
    dialect = engine.dialect.name
    if dialect != 'mysql':
        return
    if 'comments_crawled_at' not in cols:
        try:
            db.session.execute(text('ALTER TABLE bili_videos ADD COLUMN comments_crawled_at DATETIME NULL COMMENT "评论最后爬取时间"'))
            db.session.commit()
            app.logger.info('迁移: 已添加 bili_videos.comments_crawled_at 列')
        except Exception as e:
            db.session.rollback()
            app.logger.warning('迁移: 添加 bili_videos.comments_crawled_at 列失败: %s', e)


def _migrate_bili_video_subtitle_mediumtext(app):
    """迁移：bili_videos.subtitle_text 从 TEXT 改为 MEDIUMTEXT（解决长字幕截断）。"""
    from sqlalchemy import text

    engine = db.get_engine()
    inspector = db.inspect(engine)
    cols = {c['name'] for c in inspector.get_columns('bili_videos')}
    dialect = engine.dialect.name
    if dialect != 'mysql':
        return
    if 'subtitle_text' in cols:
        try:
            # 获取当前列类型
            current_type = None
            for c in inspector.get_columns('bili_videos'):
                if c['name'] == 'subtitle_text':
                    current_type = str(c.get('type', ''))
                    break
            # 仅在当前是 TEXT 时修改（避免重复执行）
            if current_type and 'MEDIUMTEXT' not in current_type.upper():
                db.session.execute(text('ALTER TABLE bili_videos MODIFY subtitle_text MEDIUMTEXT COMMENT "AI字幕文本"'))
                db.session.commit()
                app.logger.info('迁移: bili_videos.subtitle_text 已扩展为 MEDIUMTEXT')
        except Exception as e:
            db.session.rollback()
            app.logger.warning('迁移: 扩展 subtitle_text 为 MEDIUMTEXT 失败: %s', e)


def _migrate_wordcloud_data_compress(app):
    """迁移：将 wordcloud_data.data 从 MySQL JSON 压缩为 ZLIB BLOB。

    执行步骤：
      1. 检查当前 data 列是否已是 BLOB（已迁移过则跳过）
      2. ADD data_gz LONGBLOB — 新增临时列
      3. UPDATE ... SET data_gz = COMPRESS(data) — 用 MySQL 原生 COMPRESS() 压缩
         MySQL COMPRESS() 使用 RFC 1950 zlib 格式，与 Python zlib 兼容
      4. DROP data — 删除旧 JSON 列
      5. CHANGE data_gz → data — 重命名为原列名
      6. 模型中的 CompressedJSON TypeDecorator 对读写透明压缩/解压

    此迁移仅在 MySQL 方言上执行，SQLite 跳过。
    """
    from sqlalchemy import text

    engine = db.get_engine()
    inspector = db.inspect(engine)
    cols = {c['name'] for c in inspector.get_columns('wordcloud_data')}
    dialect = engine.dialect.name
    if dialect != 'mysql':
        return
    # data_gz 已存在且 data 已不存在 → 迁移已完成
    if 'data_gz' in cols and 'data' not in cols:
        return
    # data_gz 和 data 同时存在 → 上次迁移部分失败（ADD 成功但后续步骤失败）
    if 'data_gz' in cols and 'data' in cols:
        try:
            db.session.execute(text('ALTER TABLE wordcloud_data DROP COLUMN data_gz'))
            db.session.commit()
        except Exception:
            db.session.rollback()

    data_type = ''
    for c in inspector.get_columns('wordcloud_data'):
        if c['name'] == 'data':
            data_type = str(c.get('type', '')).upper()
            break
    if 'BLOB' in data_type:
        # data 列已是 BLOB → 用 MySQL UNCOMPRESS() 恢复为明文 JSON
        # 后续第一次读走 process_result_value 格式 2（明文 JSON），
        # 第一次写走 process_bind_param 自动转为纯 zlib
        try:
            # COALESCE: UNCOMPRESS 对非 MySQL COMPRESS 数据返回 NULL，此时保留原值
            db.session.execute(text(
                "UPDATE wordcloud_data SET data = COALESCE(UNCOMPRESS(data), data) "
                "WHERE data IS NOT NULL"
            ))
            db.session.commit()
            app.logger.info('迁移修复: wordcloud_data.data 已通过 UNCOMPRESS 恢复为明文 JSON')
        except Exception as e:
            db.session.rollback()
            app.logger.warning('迁移修复: UNCOMPRESS 失败: %s', e)
        return

    try:
        db.session.execute(text('ALTER TABLE wordcloud_data ADD COLUMN data_gz LONGBLOB AFTER data'))
        db.session.commit()
        db.session.execute(text('UPDATE wordcloud_data SET data_gz = COMPRESS(data) WHERE data IS NOT NULL'))
        db.session.commit()
        db.session.execute(text('ALTER TABLE wordcloud_data DROP COLUMN data'))
        db.session.commit()
        db.session.execute(text('ALTER TABLE wordcloud_data CHANGE data_gz data LONGBLOB NOT NULL'))
        db.session.commit()
        app.logger.info('迁移: wordcloud_data.data 已压缩为 ZLIB BLOB')
    except Exception as e:
        db.session.rollback()
        app.logger.warning('迁移: 压缩 wordcloud_data.data 失败: %s', e)


# ── 后导入路由（延迟导入） ─────────────────────
# 此处的 import 必须放在模型和 init_db 之后，否则会导致循环引用：
#   __init__.py → routes.py → __init__.py
# 延迟导入打破了这个循环。
from . import admin, routes
