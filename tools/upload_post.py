#!/usr/bin/env python3
"""
HOSHINO Blog — 文章上传工具

将 Markdown 文件通过 API 发布到博客，一气呵成：md → JSON → POST/PUT → 验证。

用法：
  python tools/upload_post.py posts/my-post.md --token TOKEN --site https://blog.example.com
  python tools/upload_post.py posts/my-post.md --token TOKEN --update          # 更新已有文章
  python tools/upload_post.py posts/my-post.md --token TOKEN --dry-run          # 仅生成 JSON 不发送
  python tools/upload_post.py posts/my-post.md --token TOKEN --publish          # 直接发布（默认草稿）

Markdown 文件可含 YAML front matter：
  ---
  title: "我的文章"
  slug: "my-post"
  categories: [Agent, 技术]
  summary: "摘要"
  cover_image: "https://..."
  ---
  正文内容...

命令行参数会覆盖 front matter 中的同名字段。

配置：
  也可用环境变量 HOSHINO_API_TOKEN 和 HOSHINO_API_SITE 避免每次传 --token/--site。
"""

import argparse
import json
import os
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_SLUG_RE = re.compile(r'^[a-z0-9\-]+$')
_MAX_TITLE = 256
_MAX_SLUG = 256
_MAX_CONTENT = 500000
_MAX_CATEGORIES = 15


def die(msg, code=1):
    print(f'✗ {msg}', file=sys.stderr)
    sys.exit(code)


def parse_front_matter(text):
    """解析 Markdown YAML front matter，返回 (meta_dict, content)。"""
    meta = {}
    if not text.startswith('---'):
        return meta, text
    rest = text[3:]
    end = rest.find('\n---')
    if end < 0:
        return meta, text
    front = rest[:end]
    content = rest[end + 4:].lstrip('\n')
    for line in front.strip().split('\n'):
        if ':' in line:
            key, _, val = line.partition(':')
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if val.startswith('[') and val.endswith(']'):
                items = [c.strip().strip('"').strip("'") for c in val[1:-1].split(',') if c.strip()]
                meta[key] = items
            elif val.lower() in ('true', 'false'):
                meta[key] = val.lower() == 'true'
            else:
                meta[key] = val
    return meta, content


def validate_payload(payload, editing=False):
    """客户端 schema 校验，返回错误列表。"""
    errors = []
    if not editing:
        if not payload.get('title'):
            errors.append('title 必填')
        if not payload.get('slug'):
            errors.append('slug 必填')
    title = payload.get('title')
    if title and len(title) > _MAX_TITLE:
        errors.append(f'title 最长 {_MAX_TITLE} 字符（当前 {len(title)}）')
    slug = payload.get('slug')
    if slug:
        if not _SLUG_RE.match(slug):
            errors.append(f'slug 只允许小写字母、数字和连字符（当前: {slug}）')
        if len(slug) > _MAX_SLUG:
            errors.append(f'slug 最长 {_MAX_SLUG} 字符')
    content = payload.get('content', '')
    if len(content) > _MAX_CONTENT:
        errors.append(f'content 最长 {_MAX_CONTENT} 字符（当前 {len(content)}）')
    cats = payload.get('categories', [])
    if cats and len(cats) > _MAX_CATEGORIES:
        errors.append(f'categories 最多 {_MAX_CATEGORIES} 个（当前 {len(cats)}）')
    return errors


def api_call(site, token, method, path, body=None):
    """调用 API，返回 (status_code, json_response)。"""
    url = site.rstrip('/') + path
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }
    data = json.dumps(body, ensure_ascii=False).encode('utf-8') if body else None
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=30) as resp:
            raw = resp.read().decode('utf-8')
            return resp.status, json.loads(raw) if raw else {}
    except HTTPError as e:
        raw = e.read().decode('utf-8') if e.fp else ''
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {'error': raw}
    except URLError as e:
        return 0, {'error': str(e.reason)}


def retry(fn, retries=3, backoff=1.0):
    """指数退避重试，仅对 5xx 和网络错误重试。"""
    for attempt in range(retries):
        status, resp = fn()
        if status and status < 500:
            return status, resp
        if attempt < retries - 1:
            wait = backoff * (2 ** attempt)
            print(f'  重试 {attempt + 1}/{retries}（{wait:.0f}s 后）…', file=sys.stderr)
            time.sleep(wait)
    return status, resp


def main():
    parser = argparse.ArgumentParser(description='上传 Markdown 文章到 HOSHINO Blog')
    parser.add_argument('file', help='Markdown 文件路径')
    parser.add_argument('--token', default=os.environ.get('HOSHINO_API_TOKEN', ''), help='API 令牌（或 env HOSHINO_API_TOKEN）')
    parser.add_argument('--site', default=os.environ.get('HOSHINO_API_SITE', 'http://127.0.0.1:5000'), help='站点地址（或 env HOSHINO_API_SITE）')
    parser.add_argument('--title', help='文章标题（覆盖 front matter）')
    parser.add_argument('--slug', help='文章 slug（覆盖 front matter）')
    parser.add_argument('--categories', nargs='*', help='分类列表（覆盖 front matter）')
    parser.add_argument('--summary', help='摘要')
    parser.add_argument('--cover-image', dest='cover_image', help='封面图 URL')
    parser.add_argument('--publish', action='store_true', help='直接发布（默认草稿）')
    parser.add_argument('--update', action='store_true', help='更新模式（PUT）')
    parser.add_argument('--dry-run', dest='dry_run', action='store_true', help='仅生成 JSON 不发送')
    parser.add_argument('--html', action='store_true', help='正文作为 html_content 而非 Markdown')
    args = parser.parse_args()

    if not args.token:
        die('缺少 API 令牌，请用 --token 或设置 HOSHINO_API_TOKEN 环境变量')
    if not os.path.isfile(args.file):
        die(f'文件不存在: {args.file}')

    with open(args.file, 'r', encoding='utf-8') as f:
        text = f.read()
    meta, content = parse_front_matter(text)

    title = args.title or meta.get('title', '')
    slug = args.slug or meta.get('slug', os.path.splitext(os.path.basename(args.file))[0])
    categories = args.categories or meta.get('categories', [])
    summary = args.summary if args.summary is not None else meta.get('summary', '')
    cover = args.cover_image or meta.get('cover_image', '')
    is_published = args.publish or meta.get('published', False)

    payload = {
        'title': title,
        'slug': slug,
        'summary': summary,
        'cover_image': cover,
        'categories': categories,
        'is_published': is_published,
    }
    if args.html:
        payload['html_content'] = content
    else:
        payload['content'] = content

    if args.update:
        payload.pop('title', None)
        payload.pop('slug', None)

    errors = validate_payload(payload, editing=args.update)
    if errors:
        die('Schema 校验失败:\n  ' + '\n  '.join(errors))

    print(f'✓ Schema 校验通过')
    print(f'  标题: {title}')
    print(f'  Slug: {slug}')
    print(f'  分类: {categories}')
    print(f'  字数: {len(content)}')
    print(f'  状态: {"发布" if is_published else "草稿"}')

    if args.dry_run:
        out_path = slug + '.payload.json'
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f'✓ Dry-run 完成，JSON 已写入 {out_path}')
        return

    if not args.update:
        status, resp = api_call(args.site, args.token, 'GET', f'/api/v1/posts/{slug}')
        if status == 200:
            die(f'slug "{slug}" 已存在（id={resp.get("post", {}).get("id")}），用 --update 更新或修改 slug')
        print(f'✓ Slug 唯一性预检通过')

    method = 'PUT' if args.update else 'POST'
    path = f'/api/v1/posts/{slug}' if args.update else '/api/v1/posts'

    status, resp = retry(lambda: api_call(args.site, args.token, method, path, payload))

    if status in (200, 201) and resp.get('ok'):
        post = resp.get('post', {})
        print(f'✓ {"更新" if args.update else "创建"}成功')
        print(f'  ID:  {post.get("id")}')
        print(f'  URL: {post.get("url", "(未返回)")}')
        print(f'  Slug: {post.get("slug")}')
        print(f'  创建时间: {post.get("created_at")}')
        resp_path = f'{slug}.response.json'
        with open(resp_path, 'w', encoding='utf-8') as f:
            json.dump(resp, f, ensure_ascii=False, indent=2)
        print(f'  响应已保存: {resp_path}')
    else:
        die(f'API 失败 (HTTP {status}): {resp.get("error", resp)}')


if __name__ == '__main__':
    main()