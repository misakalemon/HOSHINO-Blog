# -*- coding: utf-8 -*-
"""
HOSHINO Blog — WTForms 表单定义

提供登录、文章编辑、分类管理、用户管理、个人资料、评论等表单。
"""
from flask_wtf import FlaskForm
from wtforms import (
    StringField, TextAreaField, BooleanField,
    PasswordField, SelectField, SelectMultipleField
)
from wtforms.validators import DataRequired, Email, Length, Optional


class LoginForm(FlaskForm):
    """管理员登录表单。"""
    username = StringField('用户名', validators=[DataRequired()])
    password = PasswordField('密码', validators=[DataRequired()])


class PostForm(FlaskForm):
    """文章编辑表单（新建 / 编辑共用）。"""
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
    """用户管理表单（管理员编辑用户信息）。"""
    username = StringField('用户名', validators=[DataRequired(), Length(max=64)])
    email = StringField('邮箱', validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField('密码', validators=[Optional(), Length(min=6)])
    display_name = StringField('显示名', validators=[Optional(), Length(max=128)])
    bio = TextAreaField('个人简介', validators=[Optional()])
    is_admin = BooleanField('管理员')


class ProfileForm(FlaskForm):
    """个人资料编辑表单（用户修改自己的信息）。"""
    display_name = StringField('显示名', validators=[Optional(), Length(max=128)])
    bio = TextAreaField('个人简介', validators=[Optional()])
    email = StringField('邮箱', validators=[Optional(), Email(), Length(max=120)])
    password = PasswordField('新密码（留空则不修改）', validators=[Optional(), Length(min=6)])


class CommentForm(FlaskForm):
    """访客评论表单。"""
    author_name = StringField('昵称', validators=[DataRequired(), Length(max=128)])
    author_email = StringField('邮箱', validators=[Optional(), Email(), Length(max=120)])
    content = TextAreaField('评论内容', validators=[DataRequired()])
