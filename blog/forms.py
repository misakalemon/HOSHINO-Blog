"""
HOSHINO Blog — WTForms 表单定义

集中管理所有 Flask-WTF 表单类，覆盖：
  - 管理员登录
  - 文章新建/编辑
  - 分类新建/编辑
  - 用户新建/编辑
  - 个人资料编辑
  - 访客评论
  - 联系表单

每个表单类使用 WTForms 的验证器确保数据合法性，
并通过 Flask-WTF 的 FlaskForm 基类自动处理 CSRF 保护。
"""
from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    IntegerField,
    PasswordField,
    SelectField,
    SelectMultipleField,
    StringField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Email, Length, Optional


class LoginForm(FlaskForm):
    """管理员登录表单。"""
    username = StringField('用户名', validators=[DataRequired()])      # 登录名，必填
    password = PasswordField('密码', validators=[DataRequired()])      # 登录密码，必填


class RegisterForm(FlaskForm):
    """用户注册表单。"""
    username = StringField('用户名', validators=[DataRequired(), Length(min=2, max=64)])
    email = StringField('邮箱', validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField('密码', validators=[DataRequired(), Length(min=6)])
    display_name = StringField('显示名', validators=[Optional(), Length(max=128)])


class PostForm(FlaskForm):
    """文章编辑表单（新建 / 编辑共用）。

    字段说明：
      title         — 文章标题，最大 256 字符，必填
      slug          — URL 标识，用于 /post/<slug> 路由，必填且唯一
      summary       — 文章摘要，选填
      content       — Markdown 正文，必填
      categories    — 多选分类，最多 15 个，choices 由视图动态填充
      cover_image   — 封面图片 URL，选填
      is_published  — 是否发布，勾选后在前台可见
    """
    title = StringField('标题', validators=[DataRequired(), Length(max=256)])          # 文章标题，必填
    slug = StringField('链接标识 (URL)', validators=[DataRequired(), Length(max=256)]) # URL 友好标识，必填
    summary = TextAreaField('摘要', validators=[Optional()])                           # 文章摘要，选填
    content = TextAreaField('正文 (Markdown)', validators=[DataRequired()])            # Markdown 格式正文，必填
    # 多选分类（最多 15 个，choices 在视图函数中动态填充）
    categories = SelectMultipleField('分类（最多15个）', coerce=int, validators=[Optional()])
    cover_image = StringField('封面图片 URL', validators=[Optional()])                 # 封面图链接，选填
    is_published = BooleanField('发布')                                                # 是否公开可见


class CategoryForm(FlaskForm):
    """分类编辑表单。"""
    name = StringField('分类名称', validators=[DataRequired(), Length(max=64)])        # 分类名，必填，唯一
    slug = StringField('链接标识 (URL)', validators=[DataRequired(), Length(max=64)])  # URL 标识，必填
    description = TextAreaField('描述', validators=[Optional()])                       # 分类描述，选填


class UserForm(FlaskForm):
    """用户管理表单（管理员编辑用户信息）。

    注意：password 字段允许为空（留空则不修改密码）。
    """
    username = StringField('用户名', validators=[DataRequired(), Length(max=64)])      # 登录名，必填
    email = StringField('邮箱', validators=[DataRequired(), Email(), Length(max=120)]) # 邮箱，必填，格式校验
    password = PasswordField('密码', validators=[Optional(), Length(min=6)])           # 密码，选填（留空不修改）
    display_name = StringField('显示名', validators=[Optional(), Length(max=128)])     # 显示昵称，选填
    bio = TextAreaField('个人简介', validators=[Optional()])                            # 个人简介，选填
    website = StringField('个人网站', validators=[Optional(), Length(max=256)])         # 个人网站链接，选填
    role = SelectField('角色', choices=[
        ('user', '用户'),
        ('editor', '编辑'),
        ('admin', '管理员'),
    ], default='user')


class ProfileForm(FlaskForm):
    """个人资料编辑表单（用户修改自己的信息）。

    与 UserForm 的区别：
      - username 不可修改（保持唯一性）
      - 字段更少，仅显示名/简介/网站/邮箱/密码
    """
    display_name = StringField('显示名', validators=[Optional(), Length(max=128)])     # 显示昵称，选填
    bio = TextAreaField('个人简介', validators=[Optional()])                            # 个人简介，选填
    website = StringField('个人网站', validators=[Optional(), Length(max=256)])         # 个人网站链接，选填
    gitcode_url = StringField('GitCode', validators=[Optional(), Length(max=256)])     # GitCode 主页
    github_url = StringField('GitHub', validators=[Optional(), Length(max=256)])       # GitHub 主页
    email = StringField('邮箱', validators=[Optional(), Email(), Length(max=120)])     # 邮箱，选填
    password = PasswordField('新密码（留空则不修改）', validators=[Optional(), Length(min=6)])  # 新密码，选填
    about_content = TextAreaField('关于页面内容', validators=[Optional()])               # 关于页富文本，选填


class CommentForm(FlaskForm):
    """访客评论表单。

    评论不需登录即可提交，但需要管理员审核后方可显示。
    """
    author_name = StringField('昵称', validators=[DataRequired(), Length(max=128)])    # 评论者昵称，必填
    author_email = StringField('邮箱', validators=[Optional(), Email(), Length(max=120)])  # 评论者邮箱，选填
    content = TextAreaField('评论内容', validators=[DataRequired()])                    # 评论正文，必填


class ContactForm(FlaskForm):
    """联系表单。

    访客可通过此表单给博主留言。
    （当前仅做展示与 CSRF 保护，未接入邮件发送）
    """
    name = StringField('姓名', validators=[DataRequired(), Length(max=128)])           # 联系人姓名，必填
    email = StringField('邮箱', validators=[DataRequired(), Email(), Length(max=120)]) # 联系人邮箱，必填
    message = TextAreaField('留言', validators=[DataRequired()])                       # 留言内容，必填


class FeaturedCardForm(FlaskForm):
    """首页特色卡片编辑表单。"""
    title = StringField('标题', validators=[DataRequired(), Length(max=128)])          # 卡片标题，必填
    description = StringField('描述', validators=[Optional(), Length(max=256)])        # 卡片描述，选填
    icon = StringField('图标', validators=[Optional(), Length(max=256)])               # 图标符号/类名，选填
    tag = SelectField('标签', coerce=str, default='')                                  # 卡片标签，下拉选择
    link = StringField('链接 (可选)', validators=[Optional(), Length(max=256)])        # 点击跳转链接，选填
    image_url = StringField('图片 URL (可选)', validators=[Optional(), Length(max=256)])  # 背景图片链接，选填
    sort_order = IntegerField('排序', default=0)                                       # 排序权重（越小越靠前）
    is_active = BooleanField('启用')                                                    # 是否在前台显示
