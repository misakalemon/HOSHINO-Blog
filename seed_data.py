# -*- coding: utf-8 -*-
"""
HOSHINO Blog — 测试数据生成脚本
生成 100 篇文章及分类、评论等完整测试数据。
"""
import os
import sys
import random
import datetime

# 确保能找到项目模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 必须先设置环境变量再导入 app
os.environ.setdefault('DATABASE_URL', 'mysql+pymysql://hoshino:hoshino_pass@127.0.0.1:3306/hoshino_blog?charset=utf8mb4')

from app import create_app
from blog import db
from blog.models import User, Category, Post, Comment

# ─── 测试数据 ─────────────────────────────────

CATEGORIES = [
    ('技术', 'tech', '编程、框架、工具等技术相关'),
    ('生活', 'life', '日常生活记录与感悟'),
    ('前端', 'frontend', 'HTML/CSS/JavaScript/Vue/React'),
    ('后端', 'backend', 'Python/Go/Node.js 服务端开发'),
    ('数据库', 'database', 'MySQL/PostgreSQL/Redis/MongoDB'),
    ('DevOps', 'devops', 'Docker/K8s/CI-CD/运维'),
    ('算法', 'algorithm', '数据结构与算法、刷题'),
    ('AI', 'ai', '机器学习、深度学习、AI 工具'),
    ('阅读', 'reading', '读书笔记、书评'),
    ('随笔', 'essay', '随便写写'),
]

AUTHOR_NAMES = ['admin', 'Hoshino']

POST_TITLES = [
    # 技术类
    'Python 装饰器从入门到精通',
    '深入理解 Docker 容器网络',
    'Flask 应用性能优化实战',
    'MySQL 索引原理与优化技巧',
    'Redis 缓存策略最佳实践',
    'RESTful API 设计指南',
    'Git 高级用法与工作流',
    'Linux 系统调优实战笔记',
    'Nginx 反向代理配置详解',
    '微服务架构设计模式',
    '如何写出优雅的 Python 代码',
    '异步编程：从回调到协程',
    'WebSocket 实时通信原理',
    'JWT 认证机制详解',
    'API 限流策略与实现',
    '消息队列选型与对比',
    '单元测试最佳实践',
    '日志系统设计与实现',
    '配置中心原理与实践',
    '分布式事务解决方案',

    # 前端类
    'CSS Grid 布局完全指南',
    'Flexbox 布局实战技巧',
    'JavaScript 异步编程进阶',
    'Vue 3 组合式 API 详解',
    'React Hooks 深入理解',
    '前端性能优化 checklist',
    'TypeScript 类型体操',
    'Webpack 配置优化指南',
    '响应式设计最佳实践',
    '前端工程化之路',
    '浏览器渲染原理',
    '跨域解决方案汇总',
    '前端安全防护指南',
    'Web 动画性能优化',
    '移动端适配最佳实践',
    'ES2024 新特性一览',
    '前端状态管理方案对比',
    '微前端架构实践',
    'SSR 与 SSG 对比分析',
    'PWA 渐进式 Web 应用',

    # 数据库类
    'SQL 优化实战案例',
    '数据库分库分表方案',
    'MySQ L 主从复制配置',
    'ORM 框架原理与选型',
    '数据库连接池详解',
    'NoSQL 与 SQL 对比',
    'Elasticsearch 入门指南',
    '数据迁移最佳实践',
    '慢查询分析与优化',
    '数据库备份恢复策略',

    # DevOps 类
    'Docker Compose 编排实战',
    'Kubernetes 入门教程',
    'CI/CD 流水线搭建',
    'Prometheus 监控系统',
    '自动化部署方案对比',
    '容器化最佳实践',
    'GitLab CI 配置详解',
    '云原生技术栈概览',
    'Helm Charts 使用指南',
    '服务网格 Istio 入门',

    # AI 类
    '机器学习入门路线图',
    '深度学习框架对比',
    '大语言模型应用开发',
    'Prompt Engineering 指南',
    'AI 绘画工具推荐',
    '自然语言处理基础',
    '推荐系统算法简介',
    '计算机视觉入门',
    'AI 辅助编程体验',
    'RAG 应用开发实践',

    # 算法类
    '排序算法可视化讲解',
    '动态规划入门',
    '二叉树遍历全解',
    '图算法基础',
    '字符串匹配算法',
    '贪心算法应用场景',
    '回溯算法经典题',
    '并查集原理与应用',
    '线段树与树状数组',
    '位运算技巧汇总',

    # 生活类
    '程序员健康指南',
    '居家办公效率提升',
    '我的 2026 上半年总结',
    '技术博客写作心得',
    '开源项目维护经验',
    '远程办公工具推荐',
    '程序员副业探索',
    '如何保持学习动力',
    '技术社区参与指南',
    '个人知识管理体系',

    # 阅读类
    '《重构》读书笔记',
    '《设计模式》学习总结',
    '《代码整洁之道》读后感',
    '《深入理解计算机系统》笔记',
    '《程序员修炼之道》心得',
    '《软技能》读书笔记',
    '《系统设计面试》学习',
    '《数据密集型应用系统设计》',
    '《算法导论》阅读心得',
    '《黑客与画家》读后感',

    # 随笔类
    '写博客的初心',
    '关于技术选型的思考',
    '编程语言的偏见',
    '从菜鸟到大牛的路',
    '技术分享的意义',
    '第一次参加黑客松',
    '我的开发环境配置',
    '开源精神与实践',
    '技术债务的反思',
    '写给未来的自己',
]

COMMENT_TEMPLATES = [
    '写得很棒，学到了！',
    '感谢分享，非常实用',
    '这篇文章解决了我的大问题',
    '有一个地方不太明白，能详细解释一下吗？',
    '大佬，请问这个有坑吗？',
    '收藏了，慢慢看',
    '很详细，赞一个',
    '能不能出一期视频教程？',
    '实践中遇到了类似问题，参考了你的思路解决了',
    '好文，已转发给同事',
    '请问使用的版本是什么？',
    '补充一点，还可以用 xxx 方案实现',
    '太强了，向你学习',
    '写得不错，期待后续',
    '干货满满，推荐！',
    '这个思路很新颖，以前没想到',
    '代码可以优化一下，用 xxx 更简洁',
    '已 star，支持开源！',
    '排版很舒服，读起来轻松',
    '这是我看过最好的教程',
]

COMMENTERS = [
    ('小明', 'xiaoming@example.com'),
    ('张三', 'zhangsan@example.com'),
    ('李四', 'lisi@example.com'),
    ('匿名用户', ''),
    ('程序员小张', 'zhang@example.com'),
    ('CoderLi', 'coderli@example.com'),
    ('老王', 'laowang@example.com'),
    ('小白', ''),
    ('技术控', 'techfan@example.com'),
    ('路人甲', ''),
    ('Hacker', 'hacker@example.com'),
    ('测试用户', 'test@example.com'),
    ('Pythonista', 'py@example.com'),
    ('前端小菜', ''),
    ('全栈工程师', 'fullstack@example.com'),
]


def seed():
    confirm = input('此操作将清空现有测试数据并重新生成，是否继续？(y/N): ').strip().lower()
    if confirm != 'y':
        print('已取消')
        return

    app = create_app()
    with app.app_context():
        print('开始写入测试数据...')

        # 清空旧数据（按外键顺序）
        Comment.query.delete()
        db.session.execute(db.text('DELETE FROM post_categories'))
        Post.query.delete()
        Category.query.delete()
        # 保留 admin 用户，不清除
        User.query.filter(User.username != 'admin').delete()
        db.session.commit()

        # ── 1. 创建分类 ──
        cats = {}
        for name, slug, desc in CATEGORIES:
            cat = Category(name=name, slug=slug, description=desc)
            db.session.add(cat)
            db.session.flush()
            cats[slug] = cat
        db.session.commit()
        print(f'  ✓ 创建了 {len(cats)} 个分类')

        # ── 2. 获取作者 ──
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(
                username='admin', email='admin@localhost',
                display_name='Admin', is_admin=True, is_active=True
            )
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()

        # ── 3. 创建 100 篇文章 ──
        all_cat_slugs = list(cats.keys())
        posts = []
        for i in range(100):
            title = POST_TITLES[i] if i < len(POST_TITLES) else f'测试文章第 {i+1} 篇'
            slug = f'test-post-{i+1:03d}'
            # 生成摘要
            summary = f'这是「{title}」的摘要。本文讨论了相关技术要点和实践经验，适合开发者阅读参考。'
            # Markdown 正文
            content = f"""# {title}

## 引言

这是本文的引言部分。在软件开发实践中，我们经常会遇到各种各样的问题，本文将结合实际案例进行详细分析。

## 核心概念

### 什么是关键点？

首先，我们需要理解这个概念的核心含义。在现代软件开发中，这个概念扮演着重要的角色。

```python
# 示例代码
def hello_world():
    \"\"\"一个简单的示例函数\"\"\"
    print("你好，世界！")
    return True
```

### 为什么重要？

理解这个原理对于日常开发有着重要意义。下面我们来详细分析：

1. **可维护性** - 好的代码结构让项目更容易维护
2. **可扩展性** - 合理的设计模式便于功能扩展
3. **性能优化** - 掌握原理才能写出高效的代码

## 实践案例

### 场景描述

假设我们正在开发一个 Web 应用，需要处理大量并发请求。下面是一个实际的优化方案。

| 方案 | 优点 | 缺点 | 适用场景 |
|------|------|------|----------|
| 方案A | 实现简单 | 性能一般 | 中小型项目 |
| 方案B | 性能优秀 | 配置复杂 | 大型项目 |
| 方案C | 平衡方案 | 需要权衡 | 大多数场景 |

### 具体实现

```javascript
// 前端实现示例
async function fetchData() {{
    const response = await fetch('/api/data');
    const data = await response.json();
    return data;
}}
```

## 总结

本文详细介绍了 {title} 的相关知识和实践经验。希望对大家有所帮助。如果有任何问题，欢迎在评论区讨论。

---

*本文发布于 HOSHINO Blog，转载请注明出处*
"""
            # 发布时间：分散在最近 90 天内
            days_ago = random.randint(0, 90)
            hours_ago = random.randint(0, 23)
            created_at = datetime.datetime.utcnow() - datetime.timedelta(days=days_ago, hours=hours_ago)
            is_published = True

            post = Post(
                title=title,
                slug=slug,
                summary=summary,
                content=content,
                author_id=admin.id,
                is_published=is_published,
                created_at=created_at,
            )
            # 30% 文章带封面
            if random.random() < 0.3:
                cover_number = random.randint(1, 2)
                post.cover_image = f'images/categories/category-item-{cover_number}.jpg'

            # 每篇文章 1~3 个分类
            num_cats = random.randint(1, 3)
            chosen_slugs = random.sample(all_cat_slugs, min(num_cats, len(all_cat_slugs)))
            post.categories = [cats[s] for s in chosen_slugs]

            db.session.add(post)
            posts.append(post)

        db.session.commit()
        print(f'  ✓ 创建了 {len(posts)} 篇文章')

        # ── 4. 创建评论 ──
        comments_count = 0
        for post in posts:
            # 70% 的文章有评论，每篇 0~5 条
            if random.random() < 0.7:
                num_comments = random.randint(0, 5)
                for _ in range(num_comments):
                    commenter = random.choice(COMMENTERS)
                    comment = Comment(
                        post_id=post.id,
                        author_name=commenter[0],
                        author_email=commenter[1],
                        content=random.choice(COMMENT_TEMPLATES),
                        is_approved=random.random() < 0.8,  # 80% 审核通过
                        created_at=post.created_at + datetime.timedelta(
                            hours=random.randint(1, 72)
                        )
                    )
                    db.session.add(comment)
                    comments_count += 1

        db.session.commit()
        print(f'  ✓ 创建了 {comments_count} 条评论')

        # ── 统计 ──
        total_posts = Post.query.count()
        total_comments = Comment.query.count()
        total_categories = Category.query.count()
        total_users = User.query.count()
        print(f'\n{"="*40}')
        print(f'  测试数据写入完成!')
        print(f'{"="*40}')
        print(f'  用户:     {total_users}')
        print(f'  分类:     {total_categories}')
        print(f'  文章:     {total_posts}')
        print(f'  评论:     {total_comments}')
        print(f'{"="*40}')


if __name__ == '__main__':
    seed()
