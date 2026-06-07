# -*- coding: utf-8 -*-
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, BooleanField, PasswordField, SelectField, SelectMultipleField, FileField
from wtforms.validators import DataRequired, Email, Length, Optional


class LoginForm(FlaskForm):
    username = StringField('用户名', validators=[DataRequired()])
    password = PasswordField('密码', validators=[DataRequired()])


class PostForm(FlaskForm):
    title = StringField('标题', validators=[DataRequired(), Length(max=256)])
    slug = StringField('链接标识 (URL)', validators=[DataRequired(), Length(max=256)])
    summary = TextAreaField('摘要', validators=[Optional()])
    content = TextAreaField('正文 (Markdown)', validators=[DataRequired()])
    categories = SelectMultipleField('分类（最多15个）', coerce=int, validators=[Optional()])
    cover_image = StringField('封面图片 URL', validators=[Optional()])
    is_published = BooleanField('发布')


class CategoryForm(FlaskForm):
    name = StringField('\u5206\u7c7b\u540d\u79f0', validators=[DataRequired(), Length(max=64)])
    slug = StringField('\u94fe\u63a5\u63a5 (URL)', validators=[DataRequired(), Length(max=64)])
    description = TextAreaField('\u63cf\u8ff0', validators=[Optional()])


class UserForm(FlaskForm):
    username = StringField('\u7528\u6237\u540d', validators=[DataRequired(), Length(max=64)])
    email = StringField('\u90ae\u7bb1', validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField('\u5bc6\u7801', validators=[Optional(), Length(min=6)])
    display_name = StringField('\u663e\u793a\u540d', validators=[Optional(), Length(max=128)])
    bio = TextAreaField('\u4e2a\u4eba\u7b80\u4ecb', validators=[Optional()])
    is_admin = BooleanField('\u7ba1\u7406\u5458')


class ProfileForm(FlaskForm):
    display_name = StringField('\u663e\u793a\u540d', validators=[Optional(), Length(max=128)])
    bio = TextAreaField('\u4e2a\u4eba\u7b80\u4ecb', validators=[Optional()])
    email = StringField('\u90ae\u7bb1', validators=[Optional(), Email(), Length(max=120)])
    password = PasswordField('\u65b0\u5bc6\u7801 (\u7559\u7a7a\u5219\u4e0d\u4fee\u6539)', validators=[Optional(), Length(min=6)])


class CommentForm(FlaskForm):
    author_name = StringField('\u6635\u79f0', validators=[DataRequired(), Length(max=128)])
    author_email = StringField('\u90ae\u7bb1', validators=[Optional(), Email(), Length(max=120)])
    content = TextAreaField('\u8bc4\u8bba\u5185\u5bb9', validators=[DataRequired()])
