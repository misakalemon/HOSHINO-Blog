"""
HOSHINO Blog — 博文词云模块

为博文详情页提供中文分词 + 词频统计功能。
分词结果通过 Redis 缓存，按 post.id + updated_at 失效。

用法:
    from .wordcloud import compute_word_frequencies
    data = compute_word_frequencies(post.content, top_n=60)
"""

import logging
import os
import re
from collections import Counter
from typing import List, Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── jieba 延迟初始化（只在首次调用时加载）──
_jieba_initialized = False


def _init_jieba():
    """初始化 jieba：添加领域词典 + 启用并行分词（4 核）。

    仅在首次调用 compute_word_frequencies 时执行一次。
    """
    global _jieba_initialized
    if _jieba_initialized:
        return
    import jieba
    # 启用并行分词（多核加速）
    try:
        jieba.enable_parallel(4)
    except Exception:
        pass  # 并行不可用时静默降级
    # 添加博客领域词汇，提高分词准确率
    domain_words = [
        'Hoshino', 'Bilibili', 'GitCode', 'GitHub', 'Gitee',
        'Markdown', 'Redis', 'MySQL', 'Flask', 'SQLAlchemy',
        '前端', '后端', '博客', '开源', 'API', 'CSS', 'HTML', 'JavaScript',
        'Python', 'Docker', 'Linux', 'Windows', 'macOS',
    ]
    for w in domain_words:
        jieba.add_word(w)
    _jieba_initialized = True


# ── 预编译正则（模块级，避免重复编译）────────────────
_RE_CODE_BLOCK = re.compile(r'```[\s\S]*?```')
_RE_INLINE_CODE = re.compile(r'`[^`]+`')
_RE_HTML_TAG = re.compile(r'<[^>]+>')
_RE_URL = re.compile(r'https?://\S+|www\.\S+')
_RE_EMAIL = re.compile(r'\S+@\S+\.\S+')
_RE_MD_LINK = re.compile(r'!?\[([^\]]*)\]\([^)]+\)')
_RE_MD_HEADING = re.compile(r'^#{1,6}\s+', re.MULTILINE)
_RE_MD_ULIST = re.compile(r'^[\s]*[-*+]\s+', re.MULTILINE)
_RE_MD_OLIST = re.compile(r'^[\s]*\d+\.\s+', re.MULTILINE)
_RE_MD_HR = re.compile(r'^-{3,}\s*$', re.MULTILINE)
_RE_MD_EM = re.compile(r'[*_]{1,3}')
_RE_PURE_DIGIT = re.compile(r'^\d+(\.\d+)?$')
_RE_PURE_PUNCT = re.compile(r'^[^\w\s]+$')

# ── 中文停用词表（~300 个高频虚词/代词/语气词/连词）────
_STOP_WORDS: set = {
    # ── 代词 ──
    '我', '你', '他', '她', '它', '我们', '你们', '他们', '她们', '它们',
    '自己', '别人', '大家', '各位', '诸位',
    '这', '那', '这个', '那个', '这些', '那些',
    '这里', '那里', '这儿', '那儿', '这样', '那样', '这么', '那么',
    '什么', '谁', '哪', '怎么', '为什么', '如何', '怎样', '怎么样',
    '多少', '几', '何', '孰', '啥', '咋', '干嘛',
    # ── 系词/助词 ──
    '的', '了', '在', '是', '有', '和', '就', '不', '都', '也',
    '到', '说', '要', '去', '会', '着', '没有', '看', '好', '上',
    '很', '能', '下', '用', '让', '被', '把', '对', '还', '但',
    '而', '或', '与', '及', '并', '且', '虽然', '但是', '因为', '所以',
    '如果', '那么', '只是', '不过', '然后', '之后', '以前', '同时',
    '以及', '此外', '例如', '比如', '包括', '关于', '对于', '由于',
    '因此', '从而', '然而', '否则', '不然', '要么', '或者', '还是',
    '之', '以', '为', '于', '其', '中', '个', '所', '从', '将',
    '向', '往', '当', '比', '跟', '同', '被', '给', '由', '让',
    '叫', '把', '将', '被', '让', '给', '对', '对于', '关于', '至于',
    '作为', '当作', '叫做', '称为', '可谓', '便是',
    # ── 副词/语气 ──
    '已经', '曾经', '正在', '刚刚', '马上', '立刻', '突然', '逐渐',
    '终于', '始终', '一直', '从来', '往往', '常常', '经常', '有时',
    '偶尔', '忽然', '仍然', '依然', '依旧', '还是', '当然', '其实',
    '的确', '确实', '根本', '完全', '十分', '非常', '特别', '尤其',
    '比较', '相当', '几乎', '大约', '总共', '一共', '一起', '一同',
    '互相', '分别', '重新', '再次', '还', '再', '又', '也', '都',
    '只', '仅', '就', '便', '才', '刚', '刚', '正', '在', '正在',
    '吗', '呢', '吧', '啊', '呀', '哦', '嗯', '嘛', '哈', '呵',
    '啦', '哇', '哟', '呗', '么', '罢了', '而已', '不成', '与否',
    '的话', '来看', '来说', '起见', '而言', '来说', '所指', '而言',
    '一样', '一般', '似的', '般', '来', '去', '进', '出', '起', '过',
    '可以', '可能', '应该', '必须', '需要', '能够', '愿意', '希望',
    '喜欢', '觉得', '认为', '以为', '知道', '明白', '了解', '发现',
    '开始', '继续', '完成', '结束', '出现', '存在', '发生', '进行',
    '做', '作', '搞', '弄', '干', '办', '处理', '解决', '实现',
    '成为', '作为', '当作', '叫做', '称为', '算', '算作', '看成',
    '可以说', '也就是', '就是说', '这意味着', '换句话说',
    # ── 数量词 ──
    '一', '二', '三', '四', '五', '六', '七', '八', '九', '十',
    '零', '百', '千', '万', '亿', '两', '第', '每', '各', '某', '任何',
    '整个', '全部', '所有', '一切', '部分', '一些', '许多', '大量',
    '很多', '少数', '不少', '任何', '每个', '各自', '别的',
    '之一', '其中', '之一',
    # ── 时间/方位 ──
    '年', '月', '日', '时', '分', '秒', '天', '周', '小时', '分钟',
    '今天', '明天', '昨天', '前天', '后天',
    '早上', '晚上', '上午', '下午', '中午', '深夜',
    '现在', '过去', '未来', '当前', '目前', '之前', '以后', '以来',
    '前后', '左右', '上下', '内外', '中间', '旁边', '附近',
    '这里', '那里', '这边', '那边', '上面', '下面', '里面', '外面',
    '前', '后', '左', '右', '上', '下', '内', '外', '中', '旁',
    '东', '南', '西', '北', '东南', '西南', '东北', '西北',
    # ── 常见英文停用词 ──
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
    'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
    'would', 'could', 'should', 'may', 'might', 'shall', 'can',
    'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it',
    'we', 'they', 'my', 'your', 'his', 'her', 'its', 'our', 'their',
    'me', 'him', 'us', 'them', 'in', 'on', 'at', 'to', 'for', 'of',
    'with', 'by', 'from', 'as', 'about', 'into', 'through', 'during',
    'and', 'or', 'but', 'not', 'no', 'if', 'so', 'than', 'then',
    'just', 'also', 'very', 'too', 'only', 'more', 'some', 'any',
    'up', 'down', 'out', 'off', 'over', 'under', 'again', 'further',
    'once', 'here', 'there', 'when', 'where', 'why', 'how',
    'all', 'each', 'both', 'few', 'most', 'other', 'such',
}


def _clean_text(text: str) -> str:
    """移除 Markdown 标记、HTML 标签、URL、代码块，保留纯文本。

    使用预编译正则，单次遍历完成所有清洗。

    Args:
        text: 原始 Markdown 内容

    Returns:
        清洗后的纯文本
    """
    text = _RE_CODE_BLOCK.sub('', text)
    text = _RE_INLINE_CODE.sub('', text)
    text = _RE_HTML_TAG.sub('', text)
    text = _RE_URL.sub('', text)
    text = _RE_EMAIL.sub('', text)
    text = _RE_MD_LINK.sub(r'\1', text)
    text = _RE_MD_HEADING.sub('', text)
    text = _RE_MD_ULIST.sub('', text)
    text = _RE_MD_OLIST.sub('', text)
    text = _RE_MD_HR.sub('', text)
    text = _RE_MD_EM.sub('', text)
    # 合并连续空白
    text = ' '.join(text.split())
    return text


def _is_valid_word(word: str) -> bool:
    """判断分词结果是否有效（非停用词、非纯数字、非纯标点、长度 ≥ 2）。

    Args:
        word: 单个分词结果

    Returns:
        True 如果该词应保留
    """
    word = word.strip()
    if not word:
        return False
    if len(word) < 2:
        return False  # 过滤单字
    if word.lower() in _STOP_WORDS:
        return False
    if _RE_PURE_DIGIT.match(word):
        return False
    if _RE_PURE_PUNCT.match(word):
        return False
    return True


def tokenize(text: str) -> List[str]:
    """对文本进行中文分词，返回有效词列表。

    首次调用时自动初始化 jieba 并加载领域词典。

    Args:
        text: 原始 Markdown 文本

    Returns:
        过滤后的分词列表（按原文出现顺序）
    """
    _init_jieba()
    import jieba

    cleaned = _clean_text(text)
    if not cleaned.strip():
        return []

    words = jieba.lcut(cleaned, cut_all=False)  # 精确模式
    return [w for w in words if _is_valid_word(w)]


def compute_word_frequencies(text: str, top_n: int = 60) -> Optional[list]:
    """计算词频，返回按权重降序排列的列表。

    使用 Counter 进行高效计数，自动过滤停用词和无效词。

    Args:
        text: 原始 Markdown 文本
        top_n: 返回前 N 个高频词（默认 60）

    Returns:
        [{word: str, weight: int}, ...] 按 weight 降序，无数据时返回 None
    """
    words = tokenize(text)
    if not words:
        return None

    # 使用 Counter 高效计数
    freq = Counter(words)
    # 按词频降序，取 top_n
    most_common = freq.most_common(top_n)

    return [{'word': w, 'weight': c} for w, c in most_common]


def extract_text_for_post(post):
    """从 Post 对象提取可用于分词的纯文本。

    同时处理 content 和 html_content/html_file_url，
    内嵌 HTML 中的标签会被 BeautifulSoup 剥离为纯文本。

    Args:
        post: Post ORM 实例

    Returns:
        str: 清洗后的纯文本，各来源用空格拼接
    """
    texts = []
    if post.content:
        texts.append(post.content)
    if post.html_content:
        soup = BeautifulSoup(post.html_content, 'html.parser')
        texts.append(soup.get_text(separator=' ', strip=True))
    elif post.html_file_url:
        # 尝试读取磁盘上的 HTML 文件（兼容旧数据）
        try:
            from flask import current_app
            filepath = os.path.join(
                current_app.root_path, 'static',
                post.html_file_url.lstrip('/'),
            )
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    soup = BeautifulSoup(f.read(), 'html.parser')
                    texts.append(soup.get_text(separator=' ', strip=True))
        except Exception:
            pass
    return ' '.join(texts)


def precompute_post_wordcloud(post_id):
    """为单篇文章预计算词云并存入数据库。

    从 content + html_content 提取文本，分词后计算词频，
    写入 WordCloudData 表（post_id 索引）。

    Args:
        post_id: 文章 ID
    """
    from . import db
    from .models import Post, WordCloudData, WordCloudConfig

    post = Post.query.get(post_id)
    if not post:
        return

    text = extract_text_for_post(post)
    top_n = WordCloudConfig.get_or_create().top_n_article
    data = compute_word_frequencies(text, top_n=top_n) or []

    record = WordCloudData.query.filter_by(post_id=post_id).first()
    if record is None:
        record = WordCloudData(post_id=post_id, data=data)
        db.session.add(record)
    else:
        record.data = data
    db.session.commit()


def precompute_site_wordcloud():
    """为全站预计算词云并存入数据库。

    汇总所有已发布文章的文本（content + html_content），
    分词后计算词频，同时按月分段计算。

    每条记录以 (post_id, period) 为唯一标识：
      - post_id=NULL, period='all'    → 全站全量
      - post_id=NULL, period='2026-01' → 某月全站
    """
    from . import db
    from .models import Post, WordCloudData, WordCloudConfig
    from sqlalchemy import func

    top_n = WordCloudConfig.get_or_create().top_n_site

    # ── 全量词云 ──
    texts = []
    for post in Post.query.filter_by(is_published=True).all():
        text = extract_text_for_post(post)
        if text.strip():
            texts.append(text)

    full_text = ' '.join(texts)
    data = compute_word_frequencies(full_text, top_n=top_n) or []

    record = WordCloudData.query.filter_by(post_id=None, period='all').first()
    if record is None:
        record = WordCloudData(post_id=None, period='all', data=data)
        db.session.add(record)
    else:
        record.data = data

    # ── 按月分段词云 ──
    # 查询所有已发布文章的不同月份
    months = (
        db.session.query(func.date_format(Post.created_at, '%Y-%m'))
        .filter(Post.is_published == True)
        .distinct()
        .order_by(func.date_format(Post.created_at, '%Y-%m'))
        .all()
    )
    for (month,) in months:
        try:
            month_posts = Post.query.filter(
                Post.is_published == True,
                func.date_format(Post.created_at, '%Y-%m') == month,
            ).all()
            month_texts = []
            for p in month_posts:
                t = extract_text_for_post(p)
                if t.strip():
                    month_texts.append(t)
            month_full = ' '.join(month_texts)
            month_data = compute_word_frequencies(month_full, top_n=top_n) or []

            m_record = WordCloudData.query.filter_by(post_id=None, period=month).first()
            if m_record is None:
                m_record = WordCloudData(post_id=None, period=month, data=month_data)
                db.session.add(m_record)
            else:
                m_record.data = month_data
        except Exception as e:
            logger.warning('预计算 %s 月词云失败: %s', month, e)

    db.session.commit()


def precompute_all_wordclouds():
    """重新计算所有词云（全站 + 每篇已发布文章）。
    
    每篇文章独立 try/except，单篇失败不影响后续。
    """
    precompute_site_wordcloud()
    from .models import Post

    for post in Post.query.filter_by(is_published=True).all():
        try:
            precompute_post_wordcloud(post.id)
        except Exception as e:
            logger.warning('预计算词云失败 post_id=%d: %s', post.id, e)


def precompute_bili_wordclouds():
    """为 B站视频标题+简介预计算词云并存入数据库。

    汇总所有 B站视频的 title + description，分词后计算词频，
    写入 WordCloudData 表（source='bili'），同时按月分段。
    """
    from . import db
    from .models import BiliVideo, WordCloudData, WordCloudConfig
    from sqlalchemy import func

    top_n = WordCloudConfig.get_or_create().top_n_bili

    # ── 全量 B站词云 ──
    videos = BiliVideo.query.all()
    texts = []
    for v in videos:
        parts = []
        if v.title:
            parts.append(v.title)
        if v.description:
            parts.append(v.description)
        texts.append(' '.join(parts))
    full_text = ' '.join(texts)
    data = compute_word_frequencies(full_text, top_n=top_n) or []

    _save_bili_record('all', data)

    # ── 按月分段 ──
    months = (
        db.session.query(func.date_format(BiliVideo.pubdate, '%Y-%m'))
        .filter(BiliVideo.pubdate.isnot(None))
        .distinct()
        .order_by(func.date_format(BiliVideo.pubdate, '%Y-%m'))
        .all()
    )
    for (month_pubdate,) in months:
        month_videos = BiliVideo.query.filter(
            func.date_format(BiliVideo.pubdate, '%Y-%m') == month_pubdate,
        ).all()
        month_texts = []
        for v in month_videos:
            parts = []
            if v.title:
                parts.append(v.title)
            if v.description:
                parts.append(v.description)
            month_texts.append(' '.join(parts))
        month_full = ' '.join(month_texts)
        month_data = compute_word_frequencies(month_full, top_n=top_n) or []
        _save_bili_record(month_pubdate, month_data)

    db.session.commit()


def _save_bili_record(period, data):
    """保存或更新 B站词云记录。"""
    from . import db
    from .models import WordCloudData

    record = WordCloudData.query.filter_by(post_id=None, source='bili', period=period).first()
    if record is None:
        record = WordCloudData(post_id=None, source='bili', period=period, data=data)
        db.session.add(record)
    else:
        record.data = data