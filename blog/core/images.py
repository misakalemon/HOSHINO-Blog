"""HOSHINO Blog — 图片处理与上传工具（统一入口）

背景：图片上传此前有三个独立入口（富文本编辑器 / 用户头像 / 词云形状），
加上缩略图服务，各自实现魔数校验、PIL 解码、缩放、编码与落盘，存在四份
重复逻辑，并带来同类缺陷：

  1. **EXIF 方向未处理** —— 手机竖拍照片（EXIF Orientation=6/8）经
     Image.open 读到的仍是未旋转的原始像素，缩放/重编码后方向信息丢失，
     结果在页面上横躺。
  2. **色彩模式未归一** —— CMYK（印刷图）、P 模式带透明、LA、16 位灰度等
     模式在转 WebP/JPEG 时可能报错或丢失透明通道（Pillow 各版本支持度不同）。
  3. **动画 GIF 丢帧** —— ``img.save(buf, 'GIF')`` 只写当前帧，与"保留动画"
     的注释矛盾；多帧图片被静默压成静态图。
  4. **忽略 UPLOAD_FOLDER 配置** —— 三处均硬编码 ``root_path/static/uploads``，
     配置里的 ``UPLOAD_FOLDER`` 形同虚设。
  5. **删除旧文件缺少路径校验** —— 头像有 realpath 校验，词云形状没有。

本模块统一提供：校验（扩展名 + 魔数 + 体积）、解码（含解压炸弹防护）、
归一（EXIF 转正 + 模式转换）、缩放、编码（含动画 GIF 分支）、落盘与安全删除。

用法::

    from .images import ImageUploadError, process_upload, save_upload

    try:
        result = process_upload(file, prefix='img', max_side=4096)
    except ImageUploadError as e:
        return jsonify({'error': str(e)}), 400
    filename, rel_path = save_upload(result['data'], result['ext'], 'img')
"""

import io
import logging
import os
import uuid

from flask import current_app
from PIL import Image, ImageOps, ImageSequence

logger = logging.getLogger(__name__)

# ── 默认限制（均可用环境变量覆盖）─────────────────────
DEFAULT_MAX_BYTES = 20 * 1024 * 1024     # 单张图片上限 20MB（UPLOAD_MAX_BYTES）
DEFAULT_MAX_PIXELS = 50_000_000          # 解压炸弹防护（UPLOAD_MAX_PIXELS）
DEFAULT_MAX_SIDE = 4096                  # 最长边上限（UPLOAD_MAX_SIDE）
DEFAULT_QUALITY = 85
GIF_MAX_FRAMES = 200                     # 动画帧数上限，超过则原样保存

# 允许的扩展名（jpeg 归一到 jpg）
ALLOWED_EXTS = ('png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp')


class ImageUploadError(ValueError):
    """图片上传失败（消息面向用户，可直接展示）。"""


# ═══════════════════════════════════════════════
# 配置读取
# ═══════════════════════════════════════════════
def _env_int(name: str, default: int) -> int:
    """读取整型环境变量，非法值回退默认（不抛异常）。"""
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == '':
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        logger.warning('环境变量 %s=%r 不是整数，使用默认值 %d', name, raw, default)
        return default


def max_bytes() -> int:
    """单张图片体积上限（字节）。"""
    return _env_int('UPLOAD_MAX_BYTES', DEFAULT_MAX_BYTES)


def max_pixels() -> int:
    """解码像素上限（解压炸弹防护）。"""
    return _env_int('UPLOAD_MAX_PIXELS', DEFAULT_MAX_PIXELS)


def upload_dir_path() -> str:
    """返回上传目录（优先 UPLOAD_FOLDER 配置，缺失时回退 static/uploads）。"""
    directory = current_app.config.get('UPLOAD_FOLDER') or os.path.join(
        current_app.root_path, 'static', 'uploads'
    )
    os.makedirs(directory, exist_ok=True)
    return directory


# ═══════════════════════════════════════════════
# 校验
# ═══════════════════════════════════════════════
def detect_format(head: bytes):
    """按文件头（魔数）识别真实格式，无法识别返回 None。

    仅检查前 12 字节：PNG / JPEG / GIF87a|89a / RIFF....WEBP / BMP。
    """
    if head.startswith(b'\x89PNG'):
        return 'png'
    if head.startswith(b'\xff\xd8'):
        return 'jpg'
    if head.startswith((b'GIF87a', b'GIF89a')):
        return 'gif'
    if len(head) >= 12 and head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'webp'
    if head.startswith(b'BM'):
        return 'bmp'
    return None


def _stream_size(stream) -> int:
    """测量流大小（不消耗数据；不可 seek 时返回 -1）。"""
    try:
        pos = stream.tell()
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(pos)
        return size
    except (OSError, AttributeError, ValueError):
        return -1


def validate_upload(file_storage, allowed_exts=ALLOWED_EXTS) -> str:
    """校验上传文件：体积 → 扩展名 → 魔数，返回规范化的真实扩展名。

    Raises:
        ImageUploadError: 校验失败（消息可直接展示给用户）。
    """
    if file_storage is None or not getattr(file_storage, 'filename', ''):
        raise ImageUploadError('没有选择文件')
    stream = file_storage.stream

    limit = max_bytes()
    size = _stream_size(stream)
    if size > limit:
        raise ImageUploadError(f'图片过大（{size // 1024 // 1024}MB），上限 {limit // 1024 // 1024}MB')

    filename = file_storage.filename
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    if ext not in allowed_exts:
        raise ImageUploadError('不支持的图片格式：' + (ext or '未知'))

    head = stream.read(12)
    stream.seek(0)
    real_ext = detect_format(head)
    if real_ext is None:
        raise ImageUploadError('文件内容不是有效的图片')
    # 以文件内容为准：要求真实格式在允许列表内（jpg/jpeg 视为同族）
    allowed_real = {'jpg' if e in ('jpg', 'jpeg') else e for e in allowed_exts}
    if real_ext not in allowed_real:
        raise ImageUploadError('文件内容与扩展名不匹配')
    return real_ext


# ═══════════════════════════════════════════════
# 解码与归一
# ═══════════════════════════════════════════════
def decode_image(file_storage) -> Image.Image:
    """解码上传图片（含解压炸弹防护与完整性校验）。

    先 verify() 校验结构完整，再重新打开并 load() 完成实际解码——
    仅 verify 不 load 时，部分损坏文件会在后续访问属性时才暴露。
    """
    Image.MAX_IMAGE_PIXELS = max_pixels()
    stream = file_storage.stream
    stream.seek(0)
    try:
        probe = Image.open(stream)
        probe.verify()
    except Exception as e:
        raise ImageUploadError('无法解析图片文件（文件可能已损坏）') from e
    stream.seek(0)
    try:
        img = Image.open(stream)
        img.load()
    except Exception as e:
        raise ImageUploadError('图片解码失败（文件可能已损坏）') from e
    return img


def normalize_image(img: Image.Image) -> Image.Image:
    """EXIF 方向转正 + 色彩模式归一，返回可直接编码的图片。

    - EXIF Orientation：按拍摄方向旋转像素（手机竖拍照片的关键修复）
    - P/PA：按是否含透明通道转 RGBA/RGB
    - LA → RGBA；L/1/I/F/I;16/CMYK → RGB
    """
    try:
        transposed = ImageOps.exif_transpose(img)
        if transposed is not None:
            img = transposed
    except Exception as e:  # 损坏的 EXIF 不应导致上传失败
        logger.debug('EXIF 转正失败（忽略）: %s', e)

    mode = img.mode
    if mode in ('RGB', 'RGBA'):
        return img
    if mode in ('P', 'PA'):
        has_alpha = mode == 'PA' or 'transparency' in img.info
        return img.convert('RGBA' if has_alpha else 'RGB')
    if mode == 'LA':
        return img.convert('RGBA')
    return img.convert('RGB')


def _resize_to_max_side(img: Image.Image, max_side: int) -> Image.Image:
    """仅缩小不放大，保持宽高比。"""
    if max_side <= 0:
        return img
    longest = max(img.size)
    if longest <= max_side:
        return img
    ratio = max_side / longest
    return img.resize(
        (max(1, int(img.width * ratio)), max(1, int(img.height * ratio))),
        Image.LANCZOS,
    )


# ═══════════════════════════════════════════════
# 编码
# ═══════════════════════════════════════════════
def _choose_format(source_ext: str, prefer_webp: bool) -> tuple:
    """选择编码格式，返回 (PIL 格式名, 输出扩展名)。

    - GIF 始终保留 GIF（动画语义，转 WebP 会丢失部分客户端的动图支持）
    - prefer_webp=True 时，非 GIF 统一转 WebP（体积更小、支持透明）
    """
    if source_ext == 'gif':
        return 'GIF', 'gif'
    if prefer_webp:
        return 'WEBP', 'webp'
    if source_ext in ('jpg', 'jpeg'):
        return 'JPEG', 'jpg'
    if source_ext == 'png':
        return 'PNG', 'png'
    return 'WEBP', 'webp'


def encode_image(img: Image.Image, fmt: str, quality: int = DEFAULT_QUALITY) -> bytes:
    """把图片编码为字节。fmt 取 WEBP / JPEG / PNG / GIF。"""
    buf = io.BytesIO()
    if fmt == 'WEBP':
        img.save(buf, 'WEBP', quality=quality, method=6)
    elif fmt == 'JPEG':
        img.save(buf, 'JPEG', quality=quality, optimize=True, progressive=True)
    elif fmt == 'PNG':
        img.save(buf, 'PNG', optimize=True)
    elif fmt == 'GIF':
        img.save(buf, 'GIF', optimize=True)
    else:  # pragma: no cover - 调用方只传上述四种
        raise ImageUploadError(f'不支持的输出格式: {fmt}')
    return buf.getvalue()


def encode_animated_gif(img: Image.Image, max_side: int,
                        max_frames: int = GIF_MAX_FRAMES,
                        raw_bytes: bytes = None) -> bytes:
    """逐帧缩放并重新编码动画 GIF，保留全部帧、时长与循环次数。

    帧数超过 max_frames 时直接返回原始字节（避免逐帧处理开销）；
    逐帧处理失败时同样回退原始字节，保证动图不丢。
    raw_bytes 为原始文件字节（由调用方在流未消费时读取），回退时使用。
    """
    frame_count = getattr(img, 'n_frames', 1)
    if frame_count > max_frames and raw_bytes:
        logger.info('动画 GIF 帧数 %d 超过上限 %d，原样保存', frame_count, max_frames)
        return raw_bytes

    try:
        frames = []
        for frame in ImageSequence.Iterator(img):
            f = frame.convert('RGBA') if frame.mode in ('P', 'PA', 'LA') else frame.convert('RGB')
            f = _resize_to_max_side(f, max_side)
            frames.append(f.convert('P', palette=Image.ADAPTIVE))
            if len(frames) >= max_frames:
                break
        if not frames:
            raise ImageUploadError('动画 GIF 没有可用帧')
        buf = io.BytesIO()
        frames[0].save(
            buf,
            'GIF',
            save_all=True,
            append_images=frames[1:],
            duration=img.info.get('duration', 100),
            loop=img.info.get('loop', 0),
            optimize=True,
            disposal=img.info.get('disposal', 2),
        )
        return buf.getvalue()
    except Exception as e:
        if raw_bytes:
            logger.warning('动画 GIF 逐帧处理失败，回退原样保存: %s', e)
            return raw_bytes
        raise ImageUploadError('动画图片处理失败') from e


# ═══════════════════════════════════════════════
# 一站式处理
# ═══════════════════════════════════════════════
def process_upload(file_storage, *, max_side=None, quality: int = DEFAULT_QUALITY,
                   allowed_exts=ALLOWED_EXTS, prefer_webp: bool = True,
                   keep_animation: bool = True) -> dict:
    """校验 → 解码 → 归一 → 缩放 → 编码，返回处理结果。

    Returns:
        dict: {data, ext, width, height, animated, source_ext, bytes}
              data 为待落盘的字节；width/height 为最终尺寸。

    Raises:
        ImageUploadError: 任一环节失败（消息可展示）。
    """
    source_ext = validate_upload(file_storage, allowed_exts)
    img = decode_image(file_storage)
    if max_side is None:
        max_side = _env_int('UPLOAD_MAX_SIDE', DEFAULT_MAX_SIDE)

    animated = bool(keep_animation and getattr(img, 'is_animated', False))

    if source_ext == 'gif' and animated:
        stream = file_storage.stream
        stream.seek(0)
        raw_bytes = stream.read()   # 供帧数超限/处理失败时回退
        data = encode_animated_gif(img, max_side, raw_bytes=raw_bytes)
        return {
            'data': data,
            'ext': 'gif',
            'width': img.width,
            'height': img.height,
            'animated': True,
            'source_ext': source_ext,
            'bytes': len(data),
        }

    img = normalize_image(img)
    img = _resize_to_max_side(img, max_side)
    fmt, out_ext = _choose_format(source_ext, prefer_webp)
    try:
        data = encode_image(img, fmt, quality)
    except Exception as e:
        raise ImageUploadError('图片处理失败（格式不受支持）') from e
    return {
        'data': data,
        'ext': out_ext,
        'width': img.width,
        'height': img.height,
        'animated': False,
        'source_ext': source_ext,
        'bytes': len(data),
    }


# ═══════════════════════════════════════════════
# 落盘与删除
# ═══════════════════════════════════════════════
def save_upload(data: bytes, ext: str, prefix: str) -> tuple:
    """把处理后的字节写入上传目录，返回 (filename, 相对 static 的路径)。

    文件名为 ``<prefix>_<uuid16>.<ext>``：前缀便于区分来源（img/avatar/shape），
    UUID 避免冲突与文件名猜测。
    """
    directory = upload_dir_path()
    filename = f'{prefix}_{uuid.uuid4().hex[:16]}.{ext}'
    with open(os.path.join(directory, filename), 'wb') as f:
        f.write(data)
    return filename, f'uploads/{filename}'


def safe_remove_upload(rel_path: str) -> bool:
    """删除站内上传文件（realpath 校验，防路径穿越）。

    接受 ``uploads/xxx.webp`` 或 ``/static/uploads/xxx.webp`` 形式；
    仅当解析后的真实路径位于 ``static/`` 之内且为普通文件时才删除。

    Returns:
        bool: 是否实际删除了文件。
    """
    if not rel_path or not isinstance(rel_path, str):
        return False
    rel = rel_path.strip()
    if rel.startswith('/static/'):
        rel = rel[len('/static/'):]
    elif rel.startswith('static/'):
        rel = rel[len('static/'):]
    if not rel.startswith('uploads/'):
        return False
    static_root = os.path.realpath(os.path.join(current_app.root_path, 'static'))
    target = os.path.realpath(os.path.join(static_root, rel))
    if not target.startswith(static_root + os.sep) or not os.path.isfile(target):
        return False
    try:
        os.remove(target)
        return True
    except OSError as e:
        logger.warning('删除上传文件失败 %s: %s', rel_path, e)
        return False
