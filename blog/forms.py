"""
HOSHINO Blog — WTForms 表单定义

集中管理所有 Flask-WTF 表单类，覆盖：
  - 管理员登录
  - 用户注册
  - 文章新建/编辑
  - 分类新建/编辑
  - 用户管理（管理员编辑用户信息）
  - 个人资料编辑（用户修改自己的信息）
  - 访客评论
  - 联系表单
  - Hero 粒子画像编辑
  - 首页特色卡片编辑

每个表单类使用 WTForms 的验证器确保数据合法性，
并通过 Flask-WTF 的 FlaskForm 基类自动处理 CSRF 保护。

技术要点：
  - Flask-WTF 的 FlaskForm 自动开启 CSRF 保护
  - DataRequired — 必填字段
  - Optional — 可选字段（留空跳过后续验证）
  - Email — 邮箱格式校验
  - URL — URL 格式校验
  - Length — 长度限制
  - EqualTo — 两次输入一致性校验（如密码确认）
  - Regexp — 正则格式校验（如 slug 的字母数字连字符格式）
  - SelectMultipleField — 多选下拉框（配合 coerce=int 自动转为整数）
"""
from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    FileField,
    IntegerField,
    PasswordField,
    SelectField,
    SelectMultipleField,
    StringField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional, Regexp, URL as URLValidator


class LoginForm(FlaskForm):
    """管理员登录表单。

    两个必填字段：用户名和密码。
    使用 DataRequired 确保提交时不为空。
    """
    username = StringField('用户名', validators=[DataRequired()])      # 登录名，必填
    password = PasswordField('密码', validators=[DataRequired()])      # 登录密码，必填


class RegisterForm(FlaskForm):
    """用户注册表单。

    包含用户名、邮箱、密码、确认密码和可选显示名。
    密码需要至少 6 位，确认密码必须与密码一致（EqualTo 验证器）。
    显示名可选，不填则默认使用用户名。
    """
    username = StringField('用户名', validators=[DataRequired(), Length(min=2, max=64)])
    email = StringField('邮箱', validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField('密码', validators=[DataRequired(), Length(min=6)])
    # EqualTo('password') 确保确认密码与密码一致
    password_confirm = PasswordField('确认密码', validators=[DataRequired(), EqualTo('password', message='两次密码输入不一致')])
    display_name = StringField('显示名', validators=[Optional(), Length(max=128)])


class PostForm(FlaskForm):
    """文章编辑表单（新建 / 编辑共用）。

    字段说明：
      title         — 文章标题，最大 256 字符，必填
      slug          — URL 标识，用于 /post/<slug> 路由，只允许小写字母、数字和连字符
      summary       — 文章摘要，选填，列表页卡片展示使用
      content       — Markdown 正文，选填（HTML 页面模式可不填），最大 500000 字符
      categories    — 多选分类，最多 15 个，choices 由视图动态填充
      cover_image   — 封面图片 URL，选填，需符合 URL 格式
      html_file     — 上传自定义 HTML 文件，选填（文件上传字段）
      html_content  — HTML 源码（优先于 html_file），选填
      is_published  — 是否发布，勾选后在前台可见

    注意：
      content 和 html_content/html_file 是互斥或可选的关系：
      - 普通 Markdown 文章：填写 content
      - HTML 页面模式：填写 html_content 或上传 html_file
      两者可以同时存在，渲染时优先使用 HTML 模式。
    """
    title = StringField('标题', validators=[DataRequired(), Length(max=256)])          # 文章标题，必填
    # slug 正则限制：只允许小写字母、数字和连字符，保证 URL 友好
    slug = StringField('链接标识 (URL)', validators=[DataRequired(), Length(max=256), Regexp(r'^[a-z0-9\-]+$', message='只允许小写字母、数字和连字符')])
    summary = TextAreaField('摘要', validators=[Optional()])                           # 文章摘要，选填
    content = TextAreaField('正文 (Markdown)', validators=[Optional(), Length(max=500000)])  # Markdown 格式正文（HTML 页面模式可不填）
    # 多选分类（最多 15 个，choices 在视图函数中动态填充）
    # coerce=int 将提交的字符串值自动转为整数类型
    categories = SelectMultipleField('分类（最多15个）', coerce=int, validators=[Optional()])
    cover_image = StringField('封面图片 URL', validators=[Optional(), URLValidator(), Length(max=512)])  # 封面图链接，选填
    html_file = FileField('上传 HTML 文件', validators=[Optional()])                   # 自定义 HTML 页面文件，选填
    html_content = TextAreaField('HTML 源码', validators=[Optional()])                 # 自定义 HTML 源码（优先于 html_file）
    is_published = BooleanField('发布')                                                # 是否公开可见


class CategoryForm(FlaskForm):
    """分类编辑表单。

    字段说明：
      name        — 分类名称，必填，唯一（同一名称不可重复创建）
      slug        — URL 标识，必填，用于路由 /category/<slug>
      description — 分类描述，选填（列表页提示文字）
    """
    name = StringField('分类名称', validators=[DataRequired(), Length(max=64)])        # 分类名，必填，唯一
    slug = StringField('链接标识 (URL)', validators=[DataRequired(), Length(max=64)])  # URL 标识，必填
    description = TextAreaField('描述', validators=[Optional()])                       # 分类描述，选填


class UserForm(FlaskForm):
    """用户管理表单（管理员编辑用户信息）。

    注意：password 字段允许为空（留空则不修改密码）。
          如果要修改密码，需要至少 6 位。
    与 ProfileForm 的区别：
      - 可以修改 username 和 role
      - 不能修改社交链接和关于页面内容（这些由用户自己在 ProfileForm 中编辑）
    """
    username = StringField('用户名', validators=[DataRequired(), Length(max=64)])      # 登录名，必填
    email = StringField('邮箱', validators=[DataRequired(), Email(), Length(max=120)]) # 邮箱，必填，格式校验
    password = PasswordField('密码', validators=[Optional(), Length(min=6)])           # 密码，选填（留空不修改）
    display_name = StringField('显示名', validators=[Optional(), Length(max=128)])     # 显示昵称，选填
    bio = TextAreaField('个人简介', validators=[Optional()])                            # 个人简介，选填
    website = StringField('个人网站', validators=[Optional(), Length(max=256)])         # 个人网站链接，选填
    # 角色选择：管理员可以在此处更改用户的角色权限
    role = SelectField('角色', choices=[
        ('user', '用户'),
        ('editor', '编辑'),
        ('admin', '管理员'),
    ], default='user')


class ProfileForm(FlaskForm):
    """个人资料编辑表单（用户修改自己的信息）。

    与 UserForm 的区别：
      - username 不可修改（保持唯一性，需管理员才能改）
      - 包含社交链接（GitCode/GitHub/Gitee/Bilibili）和关于页面内容
      - 修改密码时需要输入当前密码验证

    字段说明：
      display_name      — 显示昵称，选填
      bio               — 个人简介，选填
      website           — 个人网站链接，选填
      gitcode_url       — GitCode 主页，选填，URL 格式校验
      github_url        — GitHub 主页，选填，URL 格式校验
      gitee_url         — Gitee 主页，选填，URL 格式校验
      bilibili_url      — Bilibili 主页，选填，URL 格式校验
      email             — 邮箱，选填（非必填，仅当需要修改时填写）
      current_password  — 当前密码，选填（修改密码时需要）
      password          — 新密码，选填，至少 6 位
      password_confirm  — 确认新密码，需与 password 一致
      about_content     — 关于页面富文本内容，选填
    """
    display_name = StringField('显示名', validators=[Optional(), Length(max=128)])     # 显示昵称，选填
    bio = TextAreaField('个人简介', validators=[Optional()])                            # 个人简介，选填
    website = StringField('个人网站', validators=[Optional(), Length(max=256)])         # 个人网站链接，选填
    gitcode_url = StringField('GitCode', validators=[Optional(), URLValidator(), Length(max=256)])  # GitCode 主页
    github_url = StringField('GitHub', validators=[Optional(), URLValidator(), Length(max=256)])    # GitHub 主页
    gitee_url = StringField('Gitee', validators=[Optional(), URLValidator(), Length(max=256)])      # Gitee 主页
    bilibili_url = StringField('Bilibili', validators=[Optional(), URLValidator(), Length(max=256)])  # B站主页
    email = StringField('邮箱', validators=[Optional(), Email(), Length(max=120)])     # 邮箱，选填
    current_password = PasswordField('当前密码', validators=[Optional()])                # 当前密码，改密码时需要验证
    password = PasswordField('新密码', validators=[Optional(), Length(min=6)])          # 新密码，选填
    password_confirm = PasswordField('确认新密码', validators=[Optional(), EqualTo('password', message='两次密码输入不一致')])  # 确认新密码
    about_content = TextAreaField('关于页面内容', validators=[Optional()])               # 关于页富文本，选填


class CommentForm(FlaskForm):
    """访客评论表单。

    评论不需登录即可提交，但需要管理员审核后方可显示。
    仅需昵称和正文，邮箱为选填。

    字段说明：
      author_name  — 评论者昵称，必填，最大 128 字符
      author_email — 评论者邮箱，选填，符合 Email 格式
      content      — 评论正文，必填，最大 50000 字符
    """
    author_name = StringField('昵称', validators=[DataRequired(), Length(max=128)])    # 评论者昵称，必填
    author_email = StringField('邮箱', validators=[Optional(), Email(), Length(max=120)])  # 评论者邮箱，选填
    content = TextAreaField('评论内容', validators=[DataRequired(), Length(max=50000)]) # 评论正文，必填


class ContactForm(FlaskForm):
    """联系表单。

    访客可通过此表单给博主留言。
    当前仅将留言存储到数据库（ContactMessage 模型），
    未接入自动邮件发送系统。

    字段说明：
      name    — 联系人姓名，必填
      email   — 联系人邮箱，必填（用于可能的回复）
      message  — 留言内容，必填
    """
    name = StringField('姓名', validators=[DataRequired(), Length(max=128)])           # 联系人姓名，必填
    email = StringField('邮箱', validators=[DataRequired(), Email(), Length(max=120)]) # 联系人邮箱，必填
    message = TextAreaField('留言', validators=[DataRequired(), Length(max=50000)])     # 留言内容，必填


class HeroImageForm(FlaskForm):
    """Hero 粒子画像编辑表单。

    字段：
      title      — 角色名，可选（仅后台展示用）
      image_url  — 裁剪上传后的图片路径（由前端 bindCropUpload 填充）
      sort_order — 排序权重（越小越靠前），整数
      is_active  — 是否在首页随机展示

    注意：图片通过前端裁剪 → upload_image API → WebP 重编码后存入，
    表单本身不处理文件上传。image_url 字段由前端在裁剪完成后自动填充。
    """
    title = StringField('角色名 (可选)', validators=[Optional(), Length(max=128)])
    image_url = StringField('图片 URL', validators=[Optional(), Length(max=512)])
    sort_order = IntegerField('排序', default=0, validators=[Optional()])
    is_active = BooleanField('启用')


class FeaturedCardForm(FlaskForm):
    """首页特色卡片编辑表单。

    字段说明：
      title       — 卡片标题，必填
      description — 卡片描述，选填
      icon        — 图标符号或 CSS 类名，选填（如 ★、home 等）
      tag         — 卡片标签，选填（用于主题分类）
      link        — 点击跳转链接，选填，需符合 URL 格式
      image_url   — 背景图片 URL，选填，需符合 URL 格式
      sort_order  — 排序权重，整数，越小越靠前
      is_active   — 是否在前台显示
    """
    title = StringField('标题', validators=[DataRequired(), Length(max=128)])          # 卡片标题，必填
    description = StringField('描述', validators=[Optional(), Length(max=256)])        # 卡片描述，选填
    icon = StringField('图标', validators=[Optional(), Length(max=256)])               # 图标符号/类名，选填
    tag = StringField('标签', validators=[Optional(), Length(max=64)])                                  # 卡片标签，下拉选择
    link = StringField('链接 (可选)', validators=[Optional(), URLValidator(), Length(max=256)])  # 点击跳转链接，选填
    image_url = StringField('图片 URL (可选)', validators=[Optional(), URLValidator(), Length(max=256)])  # 背景图片链接，选填
    sort_order = IntegerField('排序', default=0, validators=[Optional()])             # 排序权重（越小越靠前）
    is_active = BooleanField('启用')                                                    # 是否在前台显示


class WordCloudConfigForm(FlaskForm):
    """词云配置表单。

    管理员可在此调整词云渲染参数，包括形状、字号、词数、配色等。
    所有字段均有默认值，首次保存时自动创建配置行。
    """
    shape = SelectField('词云形状', choices=[
        ('circle', '圆形 ○'),
        ('star', '星形 ★'),
        ('heart', '心形 ♥'),
        ('cloud', '云朵 ☁'),
        ('rectangle', '矩形 ▭'),
        ('custom', '自定义图片'),
    ], default='circle')
    max_font = IntegerField('最大字号（px）', default=48, validators=[Optional()])
    min_font = IntegerField('最小字号（px）', default=14, validators=[Optional()])
    canvas_height = IntegerField('画布高度（px）', default=350, validators=[Optional()])
    top_n_article = IntegerField('文章详情词数', default=60, validators=[Optional()])
    top_n_site = IntegerField('首页全站词数', default=50, validators=[Optional()])
    top_n_bili = IntegerField('B站视频词数', default=50, validators=[Optional()])
    color_scheme = SelectField('配色方案', choices=[
        ('glow', '粉紫 Glow'),
        ('ocean', '蓝青 Ocean'),
        ('forest', '绿植 Forest'),
    ], default='glow')
    enabled_article = BooleanField('文章详情页显示词云', default=True)
    enabled_site = BooleanField('首页显示全站词云', default=True)
