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
    PasswordField,
    SelectMultipleField,
    StringField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Email, Length, Optional


class LoginForm(FlaskForm):
    """管理员登录表单。"""
    username = StringField('用户名', validators=[DataRequired()])
    password = PasswordField('密码', validators=[DataRequired()])


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
    title = StringField('标题', validators=[DataRequired(), Length(max=256)])
    slug = StringField('链接标识 (URL)', validators=[DataRequired(), Length(max=256)])
    summary = TextAreaField('摘要', validators=[Optional()])
    content = TextAreaField('正文 (Markdown)', validators=[DataRequired()])
    # 多选分类（最多 15 个，choices 在视图函数中动态填充）
    categories = SelectMultipleField('分类（最多15个）', coerce=int, validators=[Optional()])
    cover_image = StringField('封面图片 URL', validators=[Optional()])
    is_published = BooleanField('发布')


class CategoryForm(FlaskForm):
    """分类编辑表单。"""
    name = StringField('分类名称', validators=[DataRequired(), Length(max=64)])
    slug = StringField('链接标识 (URL)', validators=[DataRequired(), Length(max=64)])
    description = TextAreaField('描述', validators=[Optional()])


class UserForm(FlaskForm):
    """用户管理表单（管理员编辑用户信息）。

    注意：password 字段允许为空（留空则不修改密码）。
    """
    username = StringField('用户名', validators=[DataRequired(), Length(max=64)])
    email = StringField('邮箱', validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField('密码', validators=[Optional(), Length(min=6)])
    display_name = StringField('显示名', validators=[Optional(), Length(max=128)])
    bio = TextAreaField('个人简介', validators=[Optional()])
    is_admin = BooleanField('管理员')


class ProfileForm(FlaskForm):
    """个人资料编辑表单（用户修改自己的信息）。

    与 UserForm 的区别：
      - username 不可修改（保持唯一性）
      - 字段更少，仅显示名/简介/邮箱/密码
    """
    display_name = StringField('显示名', validators=[Optional(), Length(max=128)])
    bio = TextAreaField('个人简介', validators=[Optional()])
    email = StringField('邮箱', validators=[Optional(), Email(), Length(max=120)])
    password = PasswordField('新密码（留空则不修改）', validators=[Optional(), Length(min=6)])


class CommentForm(FlaskForm):
    """访客评论表单。

    评论不需登录即可提交，但需要管理员审核后方可显示。
    """
    author_name = StringField('昵称', validators=[DataRequired(), Length(max=128)])
    author_email = StringField('邮箱', validators=[Optional(), Email(), Length(max=120)])
    content = TextAreaField('评论内容', validators=[DataRequired()])


class ContactForm(FlaskForm):
    """联系表单。

    访客可通过此表单给博主留言。
    （当前仅做展示与 CSRF 保护，未接入邮件发送）
    """
    name = StringField('姓名', validators=[DataRequired(), Length(max=128)])
    email = StringField('邮箱', validators=[DataRequired(), Email(), Length(max=120)])
    message = TextAreaField('留言', validators=[DataRequired()])
