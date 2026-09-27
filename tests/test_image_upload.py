"""图片处理与上传模块测试（blog/core/images.py）

覆盖此前三个上传入口各自实现时的缺陷修复：
  - EXIF 方向转正（手机竖拍照片不再横躺）
  - 色彩模式归一（P/PA/LA/CMYK/L → RGB/RGBA，避免转 WebP/JPEG 报错或丢透明）
  - 动画 GIF 保留全部帧（此前 img.save 只写当前帧）
  - 扩展名 + 魔数 + 体积三重校验
  - 最长边限制（只缩不放）
"""

import io

import pytest
from PIL import Image

from blog.core.images import (
    ImageUploadError,
    detect_format,
    encode_animated_gif,
    normalize_image,
    process_upload,
    validate_upload,
)

pytestmark = pytest.mark.pure


# ── 测试辅助 ─────────────────────────────────────
class FakeUpload:
    """模拟 werkzeug FileStorage（模块只依赖 filename 与 stream）。"""

    def __init__(self, data: bytes, filename: str):
        self.filename = filename
        self.stream = io.BytesIO(data)


def make_image_bytes(fmt='PNG', size=(10, 10), mode='RGB', **save_kwargs) -> bytes:
    color = 0 if mode in ('P', 'L', '1') else ('red' if mode != 'CMYK' else None)
    img = Image.new(mode, size, color) if color is not None else Image.new(mode, size)
    buf = io.BytesIO()
    img.save(buf, fmt, **save_kwargs)
    return buf.getvalue()


def make_animated_gif(n_frames=3, size=(20, 20)) -> bytes:
    palette = Image.new('P', (1, 1))
    palette.putpalette([255, 0, 0, 0, 255, 0, 0, 0, 255] + [0, 0, 0] * 253)
    frames = []
    for i in range(n_frames):
        f = Image.new('P', size, i % 3)
        f.putpalette(palette.getpalette())
        frames.append(f)
    buf = io.BytesIO()
    frames[0].save(buf, 'GIF', save_all=True, append_images=frames[1:], duration=100, loop=0)
    return buf.getvalue()


def make_exif_jpeg(size=(100, 50), orientation=6) -> bytes:
    """构造带 EXIF Orientation 的 JPEG（orientation=6 表示需顺时针旋转 90°）。"""
    img = Image.new('RGB', size, 'red')
    exif = img.getexif()
    exif[274] = orientation
    buf = io.BytesIO()
    img.save(buf, 'JPEG', exif=exif.tobytes())
    return buf.getvalue()


# ── 1. 魔数识别 ──────────────────────────────────
@pytest.mark.parametrize(
    'fmt, expected',
    [('PNG', 'png'), ('JPEG', 'jpg'), ('GIF', 'gif'), ('WEBP', 'webp'), ('BMP', 'bmp')],
)
def test_detect_format_recognizes_real_formats(fmt, expected):
    data = make_image_bytes(fmt)
    assert detect_format(data[:12]) == expected


def test_detect_format_rejects_non_image():
    assert detect_format(b'<html><body') is None
    assert detect_format(b'%PDF-1.7') is None
    assert detect_format(b'') is None


# ── 2. 上传校验 ──────────────────────────────────
def test_validate_upload_accepts_valid_png():
    assert validate_upload(FakeUpload(make_image_bytes('PNG'), 'a.png')) == 'png'


def test_validate_upload_normalizes_jpeg_extension():
    assert validate_upload(FakeUpload(make_image_bytes('JPEG'), 'a.jpeg')) == 'jpg'


def test_validate_upload_rejects_unknown_extension():
    with pytest.raises(ImageUploadError):
        validate_upload(FakeUpload(b'hello', 'a.txt'))


def test_validate_upload_rejects_magic_mismatch():
    """扩展名是 .png 但内容是文本 → 拒绝（防改名绕过）。"""
    with pytest.raises(ImageUploadError):
        validate_upload(FakeUpload(b'not an image at all', 'fake.png'))


def test_validate_upload_rejects_disallowed_content_format():
    """真实格式不在允许列表内 → 拒绝（形状图片不允许 GIF）。"""
    data = make_animated_gif(2)
    with pytest.raises(ImageUploadError):
        validate_upload(FakeUpload(data, 'a.gif'), allowed_exts=('png', 'webp', 'jpg', 'jpeg'))


def test_validate_upload_enforces_size_limit(monkeypatch):
    monkeypatch.setenv('UPLOAD_MAX_BYTES', '10')
    data = make_image_bytes('PNG', (64, 64))
    assert len(data) > 10
    with pytest.raises(ImageUploadError, match='过大'):
        validate_upload(FakeUpload(data, 'a.png'))


def test_validate_upload_missing_file():
    with pytest.raises(ImageUploadError):
        validate_upload(FakeUpload(b'', ''))


# ── 3. 模式归一 ──────────────────────────────────
@pytest.mark.parametrize(
    'mode, expected',
    [('RGB', 'RGB'), ('RGBA', 'RGBA'), ('L', 'RGB'), ('CMYK', 'RGB'), ('LA', 'RGBA')],
)
def test_normalize_image_converts_modes(mode, expected):
    img = Image.new(mode, (8, 8))
    assert normalize_image(img).mode == expected


def test_normalize_image_palette_without_transparency_to_rgb():
    img = Image.new('P', (8, 8), 0)
    img.putpalette([255, 0, 0] + [0, 0, 0] * 255)
    assert normalize_image(img).mode == 'RGB'


def test_normalize_image_palette_with_transparency_to_rgba():
    img = Image.new('P', (8, 8), 0)
    img.putpalette([255, 0, 0, 0, 255, 0] + [0, 0, 0] * 254)
    img.info['transparency'] = 0
    assert normalize_image(img).mode == 'RGBA'


# ── 4. EXIF 方向转正（关键修复）──────────────────
def test_normalize_image_applies_exif_orientation():
    """Orientation=6 的 100x50 图应被转正为 50x100。"""
    data = make_exif_jpeg(size=(100, 50), orientation=6)
    img = Image.open(io.BytesIO(data))
    assert img.size == (100, 50), '读取时 PIL 不做自动旋转'

    normalized = normalize_image(img)
    assert normalized.size == (50, 100), 'EXIF 转正后应交换宽高'


def test_process_upload_applies_exif_orientation():
    """端到端：带 EXIF 方向的 JPEG 经 process_upload 后尺寸已转正。"""
    data = make_exif_jpeg(size=(120, 60), orientation=6)
    result = process_upload(FakeUpload(data, 'photo.jpg'), max_side=4096)
    assert (result['width'], result['height']) == (60, 120)


# ── 5. 编码与格式选择 ────────────────────────────
def test_process_upload_converts_png_to_webp():
    result = process_upload(FakeUpload(make_image_bytes('PNG'), 'a.png'), )
    assert result['ext'] == 'webp'
    assert Image.open(io.BytesIO(result['data'])).format == 'WEBP'


def test_process_upload_converts_cmyk_jpeg_without_error():
    """CMYK 图片转 WebP 不再报错（此前模式未归一）。"""
    data = make_image_bytes('JPEG', mode='CMYK')
    result = process_upload(FakeUpload(data, 'print.jpg'), )
    assert result['ext'] == 'webp'
    assert Image.open(io.BytesIO(result['data'])).mode in ('RGB', 'RGBA')


def test_process_upload_keeps_gif_format():
    data = make_image_bytes('GIF', size=(16, 16), mode='P')
    result = process_upload(FakeUpload(data, 'a.gif'), )
    assert result['ext'] == 'gif'
    assert Image.open(io.BytesIO(result['data'])).format == 'GIF'


def test_process_upload_preserves_animation_frames():
    """动画 GIF 必须保留全部帧（此前 img.save 只写当前帧）。"""
    data = make_animated_gif(n_frames=3)
    result = process_upload(FakeUpload(data, 'anim.gif'), )
    assert result['animated'] is True
    assert result['ext'] == 'gif'
    reopened = Image.open(io.BytesIO(result['data']))
    assert getattr(reopened, 'n_frames', 1) == 3


def test_encode_animated_gif_falls_back_when_too_many_frames():
    """帧数超过上限时原样返回，保证不丢动画。"""
    data = make_animated_gif(n_frames=4)
    img = Image.open(io.BytesIO(data))
    out = encode_animated_gif(img, max_side=100, max_frames=2, raw_bytes=data)
    assert out == data


# ── 6. 尺寸限制 ──────────────────────────────────
def test_process_upload_resizes_only_when_larger():
    big = process_upload(
        FakeUpload(make_image_bytes('PNG', (400, 200)), 'big.png'),
        max_side=100,
    )
    assert (big['width'], big['height']) == (100, 50)

    small = process_upload(
        FakeUpload(make_image_bytes('PNG', (40, 20)), 'small.png'),
        max_side=100,
    )
    assert (small['width'], small['height']) == (40, 20), '小图不应被放大'


def test_process_upload_result_shape():
    result = process_upload(FakeUpload(make_image_bytes('PNG'), 'a.png'), )
    for key in ('data', 'ext', 'width', 'height', 'animated', 'source_ext', 'bytes'):
        assert key in result, f'结果缺少字段 {key}'
    assert result['bytes'] == len(result['data'])
    assert result['source_ext'] == 'png'


# ── 7. 失败路径 ──────────────────────────────────
def test_process_upload_rejects_corrupt_image():
    """魔数正确但内容损坏 → 抛出可展示的错误而非崩溃。"""
    broken = b'\x89PNG\r\n\x1a\n' + b'\x00' * 40
    with pytest.raises(ImageUploadError):
        process_upload(FakeUpload(broken, 'broken.png'), )
