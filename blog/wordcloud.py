"""
HOSHINO Blog — 博文词云模块

为博文详情页提供中文分词 + 词频统计功能。
分词结果通过 Redis 缓存，按 post.id + updated_at 失效。

用法:
    from .wordcloud import compute_word_frequencies
    data = compute_word_frequencies(post.content, top_n=60)
"""

import logging
import re
from typing import List

logger = logging.getLogger(__name__)

# ── 中文停用词表（~200 个高频虚词/代词/语气词/连词）────────
_STOP_WORDS: set = {
    # 代词
    '我', '你', '他', '她', '它', '我们', '你们', '他们', '她们', '它们',
    '自己', '别人', '大家', '这', '那', '这个', '那个', '这些', '那些',
    '这里', '那里', '这儿', '那儿', '这样', '那样', '这么', '那么',
    '什么', '谁', '哪', '怎么', '为什么', '如何', '怎样',
    # 系词/助词
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
    # 副词/语气
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
    # 长度/数字相关
    '一', '二', '三', '四', '五', '六', '七', '八', '九', '十',
    '零', '百', '千', '万', '亿', '第', '每', '各', '某', '任何',
    '整个', '全部', '所有', '一切', '部分', '一些', '许多', '大量',
    '很多', '少数', '不少', '任何', '每个', '各自', '别的',
    # 时间/方位
    '年', '月', '日', '时', '分', '秒', '天', '周', '小时',
    '今天', '明天', '昨天', '早上', '晚上', '上午', '下午',
    '现在', '过去', '未来', '当前', '目前', '之前', '以后',
    '前后', '左右', '上下', '内外', '中间', '旁边', '附近',
    '这里', '那里', '这边', '那边', '上面', '下面', '里面', '外面',
    '前', '后', '左', '右', '上', '下', '内', '外', '中', '旁',
    '东', '南', '西', '北',
    # 常见英文停用词（少量）
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
    'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
    'would', 'could', 'should', 'may', 'might', 'shall', 'can',
    'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it',
    'we', 'they', 'my', 'your', 'his', 'her', 'its', 'our', 'their',
    'me', 'him', 'us', 'them', 'in', 'on', 'at', 'to', 'for', 'of',
    'with', 'by', 'from', 'as', 'about', 'into', 'through', 'during',
    'and', 'or', 'but', 'not', 'no', 'if', 'so', 'than', 'then',
    'just', 'also', 'very', 'too', 'only', 'more', 'some', 'any',
}

# ── 过滤模式 ──────────────────────────────────
# 匹配纯数字、纯标点、URL、邮箱
_PURE_DIGIT = re.compile(r'^\d+(\.\d+)?$')
_PURE_PUNCT = re.compile(r'^[^\w\s]+$')
_URL = re.compile(r'https?://\S+|www\.\S+')
_EMAIL = re.compile(r'\S+@\S+\.\S+')


def _clean_text(text: str) -> str:
    """移除 Markdown 标记、HTML 标签、URL、代码块，保留纯文本。

    Args:
        text: 原始 Markdown 内容

    Returns:
        清洗后的纯文本
    """
    # 移除代码块（```...``` 和 `inline code`）
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`[^`]+`', '', text)
    # 移除 HTML 标签
    text = re.sub(r'<[^>]+>', '', text)
    # 移除 URL
    text = _URL.sub('', text)
    text = _EMAIL.sub('', text)
    # 移除 Markdown 图片/链接语法 ![alt](url) 和 [text](url)
    text = re.sub(r'!?\[([^\]]*)\]\([^)]+\)', r'\1', text)
    # 移除 Markdown 标题标记 (#)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # 移除 Markdown 列表标记
    text = re.sub(r'^[\s]*[-*+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[\s]*\d+\.\s+', '', text, flags=re.MULTILINE)
    # 移除分割线
    text = re.sub(r'^-{3,}\s*$', '', text, flags=re.MULTILINE)
    # 移除加粗/斜体标记
    text = re.sub(r'[*_]{1,3}', '', text)
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
    if _PURE_DIGIT.match(word):
        return False
    if _PURE_PUNCT.match(word):
        return False
    return True


def tokenize(text: str) -> List[str]:
    """对文本进行中文分词，返回有效词列表。

    Args:
        text: 原始 Markdown 文本

    Returns:
        过滤后的分词列表（按原文出现顺序）
    """
    import jieba

    cleaned = _clean_text(text)
    if not cleaned.strip():
        return []

    words = jieba.lcut(cleaned)
    return [w for w in words if _is_valid_word(w)]


def compute_word_frequencies(text: str, top_n: int = 60) -> list:
    """计算词频，返回按权重降序排列的列表。

    Args:
        text: 原始 Markdown 文本
        top_n: 返回前 N 个高频词（默认 60）

    Returns:
        [{word: str, weight: int}, ...]  按 weight 降序
    """
    words = tokenize(text)
    if not words:
        return []

    freq: dict = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1

    # 按词频降序，取 top_n
    sorted_items = sorted(freq.items(), key=lambda x: -x[1])[:top_n]

    return [{'word': w, 'weight': c} for w, c in sorted_items]