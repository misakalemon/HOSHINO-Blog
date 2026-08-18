"""
HOSHINO Blog — 博文词云模块

为博文详情页提供中文分词 + 词频统计功能。
分词结果通过 Redis 缓存，按 post.id + updated_at 失效。

用法:
    from .wordcloud import compute_word_frequencies
    data = compute_word_frequencies(post.content, top_n=60)
"""

import gc
import logging
import os
import queue
import re
import sys
import threading
from collections import Counter
from typing import Generator, List, Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── 内存监控 ──────────────────────────────────────────
try:
    import psutil as _psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


def _log_memory(logger, label: str = ''):
    """记录当前进程内存使用量（psutil 可用时）或 gc 对象计数。"""
    if _HAS_PSUTIL:
        proc = _psutil.Process()
        mem = proc.memory_info()
        logger.info(
            '内存 [%s] RSS=%.1fMB VMS=%.1fMB gc=%d',
            label,
            mem.rss / 1024 / 1024,
            mem.vms / 1024 / 1024,
            len(gc.get_objects()),
        )
    else:
        logger.info('内存 [%s] gc_objects=%d gc_count=%s', label,
                     len(gc.get_objects()), gc.get_count())


def _maybe_collect(force: bool = False):
    """按阈值触发 GC + 内存水位回收。

    - 每 5 次调用执行一次常规 gc.collect()；
    - 当进程 RSS 超过阈值（默认 1.5GB，可用 BILI_WC_MEM_LIMIT 覆盖）时，
      强制触发 gc.collect() 并把已分代对象全部回收，缓解长期运行内存堆积。
    - 注意：gc.collect() 只是把对象从引用图摘除、内存回到 Python 的
      pymalloc arena，并非立即归还操作系统；但能阻止跨任务的内存累积。
    """
    _maybe_collect.counter += 1
    need = force or _maybe_collect.counter % 5 == 0
    if _HAS_PSUTIL and not force:
        try:
            _rss_mb = _psutil.Process().memory_info().rss / 1024 / 1024
            _limit_mb = float(os.environ.get('BILI_WC_MEM_LIMIT', '1500'))
            if _rss_mb > _limit_mb:
                need = True
                logger.warning('内存水位 %.0fMB 超过阈值 %.0fMB，强制 GC 回收',
                               _rss_mb, _limit_mb)
        except Exception:
            pass
    if need:
        collected = gc.collect()
        if collected:
            logger.debug('GC 回收 %d 个对象', collected)


_maybe_collect.counter = 0

# ── jieba 延迟初始化（只在首次调用时调用）──
_jieba_initialized = False

# ── 词云后台任务队列 ──────────────────────────────────
# 所有用户触发的词云重算（发布文章、刷新UP主等）投递到此队列，
# 由单线程消费者异步执行，避免 jieba 分词阻塞 HTTP 请求。
# 定时任务（02:10 / 02:15）仍直接调用函数，不经过此队列。
# ──────────────────────────────────────────────────────
# 有界队列：maxsize=200，防止发布/删除频繁触发任务时无限增长直至 OOM。
# 满时丢弃最旧任务（投递端见 submit_task 的容量控制）。
_task_queue: queue.Queue = queue.Queue(maxsize=200)
_worker_started = False
_worker_lock = threading.Lock()
_wc_app = None
# 重型任务（bili_up / all）并发上限，避免过多线程挤占资源
_heavy_task_semaphore = threading.Semaphore(2)
# 重型任务去重：记录已提交（含排队/运行中）的重型任务键，防止连点重复提交
# 键: 'all' 或 f'up_{up_id}'
_heavy_queued: set[str] = set()
_heavy_queued_lock = threading.Lock()
# 词云数据写入锁：串行化 post_id=NULL 记录（全站/B站词云）的本进程写入，
# 因为 MySQL 唯一索引对 NULL 行不生效，无法靠 DB 约束防重复
_wc_write_lock = threading.Lock()


def _upsert_wordcloud(post_id, source, period, data):
    """原子写入/更新词云记录。

    - post_id 非 NULL（文章词云）：MySQL ON DUPLICATE KEY UPDATE，并发安全；
    - post_id 为 NULL（全站/B站/UP/视频词云）：MySQL 唯一索引不覆盖 NULL 行，
      由 _wc_write_lock 串行化本进程写入（跨进程残留窗口极小，由启动迁移清理兜底）。
    """
    from . import db
    from .models import WordCloudData, now_cst

    if post_id is None:
        with _wc_write_lock:
            record = WordCloudData.query.filter_by(
                post_id=None, source=source, period=period
            ).first()
            if record is None:
                record = WordCloudData(post_id=None, source=source, period=period, data=data)
                db.session.add(record)
            else:
                record.data = data
            db.session.flush()
        return

    from sqlalchemy.dialects.mysql import insert as _mysql_insert

    stmt = _mysql_insert(WordCloudData).values(
        post_id=post_id, source=source, period=period, data=data,
    )
    stmt = stmt.on_duplicate_key_update(
        data=stmt.inserted.data,
        updated_at=now_cst(),
    )
    db.session.execute(stmt)


def _ensure_worker():
    """惰性启动后台工作线程（首次 submit_task 时在请求上下文中调用）。

    Flask 的 current_app 只能在有请求上下文时使用，因此首次初始化
    必须在 submit_task 被某个请求处理器调用时完成（而非模块加载时）。
    后续调用直接跳过，不依赖上下文。
    """
    global _worker_started, _wc_app
    with _worker_lock:
        if _worker_started:
            return
        from flask import current_app
        _wc_app = current_app._get_current_object()
        t = threading.Thread(target=_worker_loop, daemon=True)
        t.start()
        _worker_started = True


def _run_heavy_task(task_type: str, kwargs: dict):
    """在独立线程中执行重型词云任务，不阻塞 _worker_loop。

    信号量由 submit_task 在提交时非阻塞获取并在此线程结束后释放
    （见 _run_and_release），此处只负责执行。
    """
    try:
        with _wc_app.app_context():
            try:
                if task_type == 'bili_up':
                    precompute_up_wordclouds(kwargs['up_id'])
                elif task_type == 'all':
                    precompute_all_wordclouds()
                    precompute_bili_wordclouds()
            finally:
                from . import db
                db.session.remove()
    except Exception as e:
        logger.error('词云重型任务失败 type=%s: %s', task_type, e)


def _worker_loop():
    """单线程工作循环：处理轻量词云任务，不阻塞 HTTP 请求。

    重型任务（bili_up, all）在调用 submit_task 时直接开独立线程，
    不经过此队列，避免 ThreadPoolExecutor + f.result() 阻塞队列消费。
    """
    while True:
        task = _task_queue.get()
        with _wc_app.app_context():
            try:
                task_type = task.pop('type')
                if task_type == 'post':
                    precompute_post_wordcloud(task['post_id'])
                elif task_type == 'site':
                    precompute_site_wordcloud()
            except Exception as e:
                logger.error('词云任务失败 type=%s: %s', task.get('type', '?'), e)
            finally:
                from . import db
                db.session.remove()
                _task_queue.task_done()


def submit_task(task_type: str, **kwargs):
    """将词云任务投递到后台执行，立即返回（不阻塞请求线程）。

    这是用户触发词云重算的唯一入口。所有调用点（admin.py 发表/编辑/删除文章、
    手动重算、bili_routes.py 刷新UP评论/字幕）都通过此函数投递，
    而不是直接调用预计算函数。

    重型任务（bili_up, all）直接在独立线程中执行，避免阻塞队列消费者；
    轻量任务（post, site）投递到 _task_queue 由单线程串行处理。

    支持的 task_type:
      - 'post'      → precompute_post_wordcloud(post_id)
      - 'site'      → precompute_site_wordcloud()
      - 'all'       → precompute_all_wordclouds() + precompute_bili_wordclouds()（重型，独立线程）
      - 'bili_up'   → precompute_up_wordclouds(up_id)（重型，独立线程）

    Args:
        task_type: 任务类型标识
        **kwargs: 透传给预计算函数的参数
    """
    _ensure_worker()
    if task_type in ('bili_up', 'all'):
        # 重型任务：按业务键去重（all / up_{id}），已在排队或运行中则跳过。
        # 不再为每次提交创建线程（原先会无限堆积阻塞在信号量上的线程）。
        heavy_key = 'all' if task_type == 'all' else f'up_{kwargs.get("up_id")}'
        with _heavy_queued_lock:
            if heavy_key in _heavy_queued:
                logger.info('重型词云任务已在排队/运行，跳过: %s', heavy_key)
                return
            _heavy_queued.add(heavy_key)
        # 非阻塞获取并发槽位：槽位已满说明同类任务在跑，直接跳过
        if not _heavy_task_semaphore.acquire(blocking=False):
            with _heavy_queued_lock:
                _heavy_queued.discard(heavy_key)
            logger.info('重型词云任务并发槽位已满，跳过: %s', heavy_key)
            return
        _heavy_queued.discard(heavy_key)  # 进入执行即释放去重标记（由信号量控并发）

        def _run_and_release():
            try:
                _run_heavy_task(task_type, kwargs)
            finally:
                _heavy_task_semaphore.release()

        t = threading.Thread(target=_run_and_release, daemon=True)
        t.start()
    else:
        task = dict(type=task_type, **kwargs)
        # 轻量任务去重：按 (type, 业务标识) 合并——仅同参数任务合并，
        # 避免"连续发布两篇文章时第二篇词云被误跳过"（原先按 type 去重）
        dedup_key = (task_type, task.get('post_id'))
        with _worker_lock:
            existing = list(_task_queue.queue)
            if any(
                (t.get('type'), t.get('post_id')) == dedup_key for t in existing
            ):
                return
            try:
                _task_queue.put_nowait(task)
            except queue.Full:
                # 队列满：丢弃最旧任务（词云可重新计算，丢旧不影响正确性）
                try:
                    _task_queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    _task_queue.put_nowait(task)
                except queue.Full:
                    logger.warning('词云任务队列满，丢弃任务 %s', task_type)


def _init_jieba():
    """初始化 jieba：添加领域词典。

    不启用 jieba.enable_parallel（它会创建 4 个 multiprocessing 进程，
    每个进程独立加载词典，增加 ~40MB 额外内存开销，与 ThreadPoolExecutor
    并行方案冲突）。
    """
    global _jieba_initialized
    if _jieba_initialized:
        return
    import jieba
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
    '之一', '其中',
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
    if len(word) < 2 and not (len(word) == 1 and '\u4e00' <= word <= '\u9fff'):
        return False  # 过滤非中文单字
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
    同时加载 WordCloudConfig 中的自定义屏蔽词，分词后一并过滤。

    Args:
        text: 原始 Markdown 文本
        top_n: 返回前 N 个高频词（默认 60）

    Returns:
        [{word: str, weight: int}, ...] 按 weight 降序，无数据时返回 None
    """
    words = tokenize(text)
    if not words:
        return None

    # 加载用户自定义屏蔽词（每行一个）
    try:
        from .models import WordCloudConfig
        cfg = WordCloudConfig.get_or_create()
        if cfg.stop_words and cfg.stop_words.strip():
            extra_stops = {
                w.strip().lower() for w in cfg.stop_words.split('\n')
                if w.strip()
            }
            if extra_stops:
                logger.info('词云屏蔽词生效: %d 个', len(extra_stops))
                words = [w for w in words if w.lower() not in extra_stops]
    except Exception as e:
        logger.warning('词云屏蔽词加载失败: %s', e)

    freq = Counter(words)
    most_common = freq.most_common(top_n)

    return [{'word': w, 'weight': c} for w, c in most_common]


def compute_word_frequencies_stream(texts, top_n: int = 60, chunk_size: int = 200) -> Optional[list]:
    """流式计算词频，避免一次性把全部文本载入内存。

    与 compute_word_frequencies 等价，但逐个（或分批）处理 texts 迭代器中的
    文本块，用共享 Counter 累计词频。峰值内存只与单块文本大小相关，而非
    全部文本总和——适用于 51K+ 视频/全站词云这种大文本聚合场景。

    Args:
        texts:      文本块迭代器（str 或 str 列表均可）。
        top_n:      返回前 N 个高频词（默认 60）。
        chunk_size: 每批合并多少文本块再分词（越大越省 CPU，但峰值内存越高）。
    Returns:
        [{word: str, weight: int}, ...] 按 weight 降序，无数据时返回 None。
    """
    freq: Counter = Counter()
    buf: list[str] = []
    processed = 0
    for t in texts:
        if not t or not t.strip():
            continue
        buf.append(t)
        processed += 1
        if len(buf) >= chunk_size:
            freq.update(tokenize(' '.join(buf)))
            buf.clear()
            if processed % 5000 == 0:
                _maybe_collect()
    if buf:
        freq.update(tokenize(' '.join(buf)))

    if not freq:
        return None

    # 加载用户自定义屏蔽词（每行一个）
    try:
        from .models import WordCloudConfig
        cfg = WordCloudConfig.get_or_create()
        if cfg.stop_words and cfg.stop_words.strip():
            extra_stops = {
                w.strip().lower() for w in cfg.stop_words.split('\n')
                if w.strip()
            }
            if extra_stops:
                for w in list(freq.keys()):
                    if w.lower() in extra_stops:
                        del freq[w]
    except Exception as e:
        logger.warning('词云屏蔽词加载失败: %s', e)

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

    post = db.session.get(Post, post_id)
    if not post:
        return

    text = extract_text_for_post(post)
    top_n = WordCloudConfig.get_or_create().top_n_article
    data = compute_word_frequencies(text, top_n=top_n) or []

    # 原子 upsert（唯一约束 (post_id, source, period) 防并发重复行）
    _upsert_wordcloud(post_id, 'blog', 'all', data)
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

    _upsert_wordcloud(None, 'blog', 'all', data)

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

            _upsert_wordcloud(None, 'blog', month, month_data)
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


# 每批处理的 B站 视频数（控制内存峰值，避免 51K+ 视频 + 评论/弹幕一次性加载）
_BILI_BATCH = int(os.environ.get('BILI_WC_BATCH', '200'))


def _bili_texts_from_videos(videos):
    """从 B站视频列表提取各文本源，权重：字幕×5 > 标题×3 > 弹幕×2 > 评论×2 > 标签×2 > 简介×1。

    每次处理一批视频（_BILI_BATCH），加载其评论/弹幕后立即丢弃，避免
    全部评论/弹幕驻留内存。返回 Generator 逐条产出拼接文本。
    弹幕按视频取前 BILI_DANMAKU_WC_LIMIT 条（词云只需代表性样本，
    避免单视频上万条弹幕拖垮内存）。
    """
    from .models import BiliDanmaku, BiliVideoComment

    # 词云用：每视频最多取多少条弹幕/评论（超过则截取，词频已足够代表）
    _dm_limit = int(os.environ.get('BILI_DANMAKU_WC_LIMIT', '300'))
    _cm_limit = int(os.environ.get('BILI_COMMENT_WC_LIMIT', '300'))

    for i in range(0, len(videos), _BILI_BATCH):
        batch = videos[i:i + _BILI_BATCH]
        video_ids = [v.id for v in batch]
        comment_map = {}
        danmaku_map = {}
        if video_ids:
            batch_comments = BiliVideoComment.query.filter(
                BiliVideoComment.video_id.in_(video_ids)
            ).all()
            for c in batch_comments:
                lst = comment_map.setdefault(c.video_id, [])
                if len(lst) < _cm_limit:
                    lst.append(c.content)
            batch_danmakus = BiliDanmaku.query.filter(
                BiliDanmaku.video_id.in_(video_ids)
            ).all()
            for d in batch_danmakus:
                lst = danmaku_map.setdefault(d.video_id, [])
                if len(lst) < _dm_limit:
                    lst.append(d.content)
        for v in batch:
            parts = []
            if v.subtitle_text:
                parts.extend([v.subtitle_text] * 5)
            if v.title:
                parts.extend([v.title] * 3)
            for content in danmaku_map.get(v.id, []):
                if content:
                    parts.extend([content] * 2)
            for content in comment_map.get(v.id, []):
                if content:
                    parts.extend([content] * 2)
            if v.tags:
                for t in v.tags:
                    parts.extend([t] * 2)
            if v.description:
                parts.append(v.description)
            yield ' '.join(parts)
        del batch, video_ids, comment_map, danmaku_map
        if 'batch_comments' in locals():
            del batch_comments
        if 'batch_danmakus' in locals():
            del batch_danmakus
        _maybe_collect()


def precompute_bili_wordclouds():
    """为 B站视频预计算词云并存入数据库。

    分批加载视频 + 评论，每批 _BILI_BATCH 个，避免 51K+ 视频
    全部加载导致 OOM。每批处理后释放引用 + 触发 GC。
    文本采用流式分词（compute_word_frequencies_stream），
    峰值内存只与单批文本相关，不随视频总量线性增长。
    """
    from . import db
    from .models import BiliUp, BiliVideo, WordCloudData, WordCloudConfig
    from sqlalchemy import func

    top_n = WordCloudConfig.get_or_create().top_n_bili
    _log_memory(logger, 'precompute_bili_wordclouds start')

    def _iter_all_texts():
        """按 keyset 分页流式产出全部视频的文本（不驻留内存）。"""
        _last_id = 0
        while True:
            batch = (
                BiliVideo.query.filter(
                    BiliVideo.id > _last_id,
                    BiliVideo.is_deleted == False,
                )
                .order_by(BiliVideo.id)
                .limit(_BILI_BATCH)
                .all()
            )
            if not batch:
                break
            _last_id = batch[-1].id
            for text in _bili_texts_from_videos(batch):
                yield text
            del batch
            _maybe_collect()

    def _iter_month_texts(m_start, m_end):
        _last_id = 0
        while True:
            batch = (
                BiliVideo.query.filter(
                    BiliVideo.pub_datetime >= m_start,
                    BiliVideo.pub_datetime < m_end,
                    BiliVideo.id > _last_id,
                    BiliVideo.is_deleted == False,
                )
                .order_by(BiliVideo.id)
                .limit(_BILI_BATCH)
                .all()
            )
            if not batch:
                break
            _last_id = batch[-1].id
            for text in _bili_texts_from_videos(batch):
                yield text
            del batch
            _maybe_collect()

    def _iter_up_texts(up_id):
        _last_id = 0
        while True:
            batch = (
                BiliVideo.query.filter(
                    BiliVideo.up_id == up_id,
                    BiliVideo.id > _last_id,
                    BiliVideo.is_deleted == False,
                )
                .order_by(BiliVideo.id)
                .limit(_BILI_BATCH)
                .all()
            )
            if not batch:
                break
            _last_id = batch[-1].id
            for text in _bili_texts_from_videos(batch):
                yield text
            del batch
            _maybe_collect()

    # ── 全量 B站词云 ──
    data = compute_word_frequencies_stream(_iter_all_texts(), top_n=top_n) or []
    _save_bili_record('all', data)
    _log_memory(logger, 'full done')

    # ── 按月分段 ──
    # 单月过滤用 pub_datetime 范围查询（可走索引），替代 DATE_FORMAT 函数全表扫描
    from datetime import datetime as _dt
    months = (
        db.session.query(func.date_format(BiliVideo.pub_datetime, '%Y-%m'))
        .filter(BiliVideo.pub_datetime.isnot(None))
        .distinct()
        .order_by(func.date_format(BiliVideo.pub_datetime, '%Y-%m'))
        .all()
    )
    for (month_pubdate,) in months:
        try:
            _year, _mon = map(int, month_pubdate.split('-'))
            _m_start = _dt(_year, _mon, 1)
            _m_end = _dt(_year + 1, 1, 1) if _mon == 12 else _dt(_year, _mon + 1, 1)
            month_data = compute_word_frequencies_stream(
                _iter_month_texts(_m_start, _m_end), top_n=top_n
            ) or []
            _save_bili_record(month_pubdate, month_data)
        except Exception as e:
            logger.warning('📊 %s 月词云失败: %s', month_pubdate, e)
        _maybe_collect()

    # ── 按 UP 主分段 ──
    for up in BiliUp.query.all():
        try:
            up_data = compute_word_frequencies_stream(
                _iter_up_texts(up.id), top_n=top_n
            ) or []
            if not up_data:
                continue
            period = f'up_{up.id}'
            _save_bili_record(period, up_data)
            db.session.flush()
        except Exception as e:
            logger.warning('📊 UP %s 词云失败: %s', up.id, e)
        _maybe_collect()

    db.session.commit()
    _log_memory(logger, 'bili done, starting per-video')

    # 生成每期视频词云
    precompute_video_wordclouds()



def _save_bili_record(period, data):
    """保存或更新 B站词云记录（原子 upsert）。"""
    _upsert_wordcloud(None, 'bili', period, data)


def _compute_video_wc_wrapper(video_id, app):
    """线程安全的单视频词云计算包装。"""
    with app.app_context():
        from . import db
        from .models import BiliVideo
        try:
            video = db.session.get(BiliVideo, video_id)
            if video:
                _compute_single_video_wordcloud(video)
        except Exception as e:
            logger.warning('📊 词云计算失败 id=%d: %s', video_id, e)
        finally:
            db.session.remove()


def precompute_video_wordclouds():
    """为每个 B站视频生成词云（标题 + 简介 + 标签 + 评论 = 全量，与主词云同源）。

    从 BiliVideo 读取 title/description/tags，从 BiliVideoComment 读取评论，
    拼合后分词计算词频，存入 WordCloudData(source='bili_video', period='bvid_{bvid}')。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from flask import current_app
    from .models import BiliVideo

    total = BiliVideo.query.filter_by(is_deleted=False).count()
    video_ids = [
        r[0] for r in BiliVideo.query.with_entities(BiliVideo.id)
        .filter_by(is_deleted=False).all()
    ]
    app = current_app._get_current_object()
    logger.info('📊 批量词云计算开始: 共 %d 个视频', total)
    _log_memory(logger, 'precompute_video_wordclouds start')

    # 分批提交（每批 500），避免一次性 5 万+ Future 占用内存峰值
    batch_size = 500
    done = 0
    with ThreadPoolExecutor(max_workers=2) as pool:
        for start in range(0, len(video_ids), batch_size):
            batch = video_ids[start : start + batch_size]
            futures = [pool.submit(_compute_video_wc_wrapper, vid, app) for vid in batch]
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception as e:
                    logger.warning('📊 词云线程异常: %s', e)
                done += 1
                if done % 500 == 0:
                    _maybe_collect(force=True)
                if done % 5000 == 0:
                    _log_memory(logger, f'video wordcloud {done}/{total}')
                if done % 50 == 0:
                    logger.info('📊 词云进度: %d/%d', done, total)

    logger.info('📊 批量词云计算完成: %d 个视频', total)


def _compute_single_video_wordcloud(video):
    """为单个视频生成词云并存入数据库。

    文本来源权重：字幕×5 > 标题×3 > 弹幕×2 > 评论×2 > 标签×2 > 简介×1
    弹幕/评论按前 N 条截取（词云只需代表性样本，避免单视频上万条驻留内存）。
    """
    from . import db
    from .models import BiliDanmaku, WordCloudConfig, WordCloudData

    # 已删除/不可见的稿件不再生成词云
    if getattr(video, 'is_deleted', False):
        return

    top_n = WordCloudConfig.get_or_create().top_n_bili
    parts = []
    if video.subtitle_text:
        parts.extend([video.subtitle_text] * 5)
    if video.title:
        parts.extend([video.title] * 3)
    _dm_limit = int(os.environ.get('BILI_DANMAKU_WC_LIMIT', '300'))
    _cm_limit = int(os.environ.get('BILI_COMMENT_WC_LIMIT', '300'))
    danmaku_texts = [
        d.content for d in video.danmakus.limit(_dm_limit).all()
        if d.content
    ]
    if danmaku_texts:
        parts.extend(danmaku_texts * 2)
    comment_texts = [
        c.content for c in video.comments.limit(_cm_limit).all()
        if c.content
    ]
    if comment_texts:
        parts.extend(comment_texts * 2)
    if video.tags:
        for t in video.tags:
            parts.extend([t] * 2)
    if video.description:
        parts.append(video.description)

    text = ' '.join(parts)
    if not text.strip():
        return

    data = compute_word_frequencies(text, top_n=top_n) or []
    if not data:
        return

    period = f'bvid_{video.bvid}'
    _upsert_wordcloud(None, 'bili_video', period, data)
    db.session.commit()


def precompute_up_wordclouds(up_id: int):
    """为指定 UP 主的所有视频生成词云并刷新 UP 主页聚合词云。

    1. 并行计算各视频词云（单视频 source='bili_video'）
    2. 汇总该 UP 主全部文本，刷新 UP 主页聚合词云 (source='bili', period='up_{up_id}')

    Args:
        up_id (int): UP 主数据库 ID
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from flask import current_app
    from . import db
    from .models import BiliVideo, WordCloudConfig, WordCloudData

    videos = BiliVideo.query.filter_by(up_id=up_id, is_deleted=False).with_entities(BiliVideo.id).all()
    video_ids = [v.id for v in videos]
    app = current_app._get_current_object()
    total = len(video_ids)
    logger.info('📊 UP %s 词云计算: 共 %d 个视频', up_id, total)
    _log_memory(logger, f'precompute_up_wordclouds up_id={up_id} start')

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_compute_video_wc_wrapper, vid, app) for vid in video_ids]
        done = 0
        for f in as_completed(futures):
            try:
                f.result()
            except Exception as e:
                logger.warning('📊 UP %s 词云线程异常: %s', up_id, e)
            done += 1
            if done % 100 == 0:
                logger.info('📊 UP %s 词云进度: %d/%d', up_id, done, total)
            if done % 500 == 0:
                _maybe_collect(force=True)

    # ── 聚合 UP 主词云 ──
    all_videos = BiliVideo.query.filter_by(up_id=up_id, is_deleted=False).all()
    up_texts = _bili_texts_from_videos(all_videos)
    up_full = ' '.join(up_texts)
    if up_full.strip():
        top_n = WordCloudConfig.get_or_create().top_n_bili
        up_data = compute_word_frequencies(up_full, top_n=top_n) or []
        period = f'up_{up_id}'
        _upsert_wordcloud(None, 'bili', period, up_data)
        db.session.commit()
        logger.info('📊 UP %s 聚合词云已更新', up_id)

    logger.info('📊 UP %s 词云计算完成', up_id)