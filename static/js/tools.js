/**
 * tools.js — HOSHINO Blog 工具箱
 *
 * 提供多种在线小工具，所有计算在浏览器本地完成，不依赖服务端。
 *
 * 工具列表：
 *   1. Base64 编码/解码
 *   2. 字数统计（字符/行数）
 *   3. 颜色转换（HEX ↔ RGB ↔ HSL）+ 可视化取色面板
 *   4. JSON 格式化/压缩
 *   5. 时间戳转换（Unix ↔ 日期时间）
 *   6. 哈希计算（SHA-1 / SHA-256）
 *   7. 密码/密钥生成（随机/十六进制）
 *   8. 图片压缩（质量/尺寸/格式）
 */

// ═══════════════════════════════════════════════
// 工具切换
// ═══════════════════════════════════════════════

/**
 * 切换当前显示的工具面板
 * @param {string} tool - 工具标识（对应 data-tool 属性值）
 */
function switchTool(tool) {
  // 高亮当前选中的导航按钮
  document.querySelectorAll('.tools-nav-btn').forEach(function(b) {
    b.classList.toggle('active', b.getAttribute('data-tool') === tool);
  });
  // 显示对应工具面板，隐藏其他
  document.querySelectorAll('.tool-pane').forEach(function(p) {
    p.classList.toggle('active', p.id === 'tool-' + tool);
  });
}

/**
 * 清空工具的输入和输出
 * @param {string} id - 工具标识前缀（如 'b64'、'json'）
 */
function clearTool(id) {
  document.getElementById(id + '-input').value = '';
  document.getElementById(id + '-output').value = '';
}

// ── 1. Base64 编码/解码 ───────────────────────
/** 将输入文本编码为 Base64 */
function b64Encode() {
  const input = document.getElementById('b64-input').value;
  try { document.getElementById('b64-output').value = btoa(input); }
  catch(e) { alert('编码失败: ' + e.message); }
}
/** 将 Base64 字符串解码为原始文本 */
function b64Decode() {
  const input = document.getElementById('b64-input').value;
  try { document.getElementById('b64-output').value = atob(input); }
  catch(e) { alert('解码失败: 无效的 Base64'); }
}

// ── 2. 字数统计 ──────────────────────────────
/** 统计输入文本的字符数（含/不含空格）和行数 */
function wordCount() {
  const t = document.getElementById('wc-input').value;
  document.getElementById('wc-chars').textContent = t.replace(/\s/g, '').length;     // 不含空格的字符数
  document.getElementById('wc-chars-sp').textContent = t.length;                      // 含空格的字符数
  document.getElementById('wc-lines').textContent = t === '' ? 0 : t.split('\n').length; // 行数
}

// ── 3. 颜色转换 ──────────────────────────────
/**
 * HEX 颜色转 RGB
 * @param {string} hex - 十六进制颜色值（如 'ff6b9d'）
 * @returns {{r: number, g: number, b: number}}
 */
function hexToRgb(hex) {
  const v = parseInt(hex.replace('#', ''), 16);
  return { r: (v >> 16) & 255, g: (v >> 8) & 255, b: v & 255 };
}

/**
 * RGB 转 HSL
 * @param {number} r - 红色通道 (0-255)
 * @param {number} g - 绿色通道 (0-255)
 * @param {number} b - 蓝色通道 (0-255)
 * @returns {{h: number, s: number, l: number}} HSL 值 (h:0-360, s:0-100, l:0-100)
 */
function rgbToHsl(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  let h = 0, s = 0, l = (max + min) / 2;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) / 6;
    else if (max === g) h = ((b - r) / d + 2) / 6;
    else h = ((r - g) / d + 4) / 6;
  }
  return { h: Math.round(h * 360), s: Math.round(s * 100), l: Math.round(l * 100) };
}

/**
 * 根据 HEX 值更新所有颜色显示（预览色块、RGB/HSL 输入框）
 * @param {string} hex - 6 位十六进制颜色值（不含 #）
 */
function updateColor(hex) {
  hex = hex.replace('#', '');
  if (hex.length !== 6) return;
  const rgb = hexToRgb(hex);
  const hsl = rgbToHsl(rgb.r, rgb.g, rgb.b);
  // 更新预览区域
  document.getElementById('previewHex').textContent = hex.toUpperCase();
  document.getElementById('previewRgb').textContent = 'rgb(' + rgb.r + ', ' + rgb.g + ', ' + rgb.b + ')';
  document.getElementById('previewHsl').textContent = 'hsl(' + hsl.h + ', ' + hsl.s + '%, ' + hsl.l + '%)';
  document.getElementById('previewSwatch').style.background = '#' + hex;
  document.getElementById('triggerSwatch').style.background = '#' + hex;
  // 同步更新输入框
  document.getElementById('colorHex').value = hex.toUpperCase();
  document.getElementById('colorR').value = rgb.r;
  document.getElementById('colorG').value = rgb.g;
  document.getElementById('colorB').value = rgb.b;
  document.getElementById('colorH').value = hsl.h;
  document.getElementById('colorS').value = hsl.s;
  document.getElementById('colorL').value = hsl.l;
}

/** HEX 输入框变化时更新颜色 */
function onHexInput() {
  const v = document.getElementById('colorHex').value.replace(/[^0-9a-fA-F]/g, '');
  if (v.length === 6) updateColor(v);
}

/** RGB 输入框变化时更新颜色 */
function onRgbInput() {
  const r = clamp(parseInt(document.getElementById('colorR').value) || 0, 0, 255);
  const g = clamp(parseInt(document.getElementById('colorG').value) || 0, 0, 255);
  const b = clamp(parseInt(document.getElementById('colorB').value) || 0, 0, 255);
  updateColor(((r << 16) | (g << 8) | b).toString(16).padStart(6, '0'));
}

/** HSL 输入框变化时更新颜色（HSL → RGB → HEX） */
function onHslInput() {
  const h = clamp(parseInt(document.getElementById('colorH').value) || 0, 0, 360);
  let s = clamp(parseInt(document.getElementById('colorS').value) || 0, 0, 100);
  let l = clamp(parseInt(document.getElementById('colorL').value) || 0, 0, 100);
  s /= 100; l /= 100;
  // HSL → RGB 转换算法
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs((h / 60) % 2 - 1));
  const m = l - c / 2;
  let r, g, b;
  if (h < 60) { r = c; g = x; b = 0; }
  else if (h < 120) { r = x; g = c; b = 0; }
  else if (h < 180) { r = 0; g = c; b = x; }
  else if (h < 240) { r = 0; g = x; b = c; }
  else if (h < 300) { r = x; g = 0; b = c; }
  else { r = c; g = 0; b = x; }
  r = Math.round((r + m) * 255);
  g = Math.round((g + m) * 255);
  b = Math.round((b + m) * 255);
  updateColor(((r << 16) | (g << 8) | b).toString(16).padStart(6, '0'));
}

/**
 * 数值限幅
 * @param {number} v - 输入值
 * @param {number} mn - 最小值
 * @param {number} mx - 最大值
 * @returns {number} 限幅后的值
 */
function clamp(v, mn, mx) { return Math.min(Math.max(v, mn), mx); }

/**
 * 复制颜色值到剪贴板
 * @param {string} type - 'hex' | 'rgb' | 'hsl'
 * @param {Event} e - 点击事件
 */
function copyColor(type, e) {
  var ev = e || window.event;
  if (!ev) return;
  let val = '';
  if (type === 'hex') val = '#' + document.getElementById('previewHex').textContent;
  else if (type === 'rgb') val = document.getElementById('previewRgb').textContent;
  else if (type === 'hsl') val = document.getElementById('previewHsl').textContent;
  if (val) {
    navigator.clipboard.writeText(val).catch(function() {});
    // 按钮短暂显示"已复制"反馈
    const btn = ev.currentTarget || ev.target;
    const orig = btn.textContent;
    btn.textContent = '✓ 已复制';
    setTimeout(function() { btn.textContent = orig; }, 1500);
  }
}

// ── 取色面板（HSV 色彩空间浮层）───────────────
// 状态：当前选中的 HSV 值（H: 色相, S: 饱和度, V: 明度）
const cpState = { h: 258, s: 62, v: 82 };

/** 打开取色面板浮层 */
function openColorPanel() {
  const ov = document.getElementById('colorPanelOverlay');
  if (!ov) return;
  ov.classList.add('open');
  document.body.style.overflow = 'hidden'; // 禁止背景滚动
  setTimeout(function() { initColorCanvases(); }, 50); // 延迟初始化画布（等待 DOM 渲染）
}

/** 关闭取色面板浮层 */
function closeColorPanel() {
  const ov = document.getElementById('colorPanelOverlay');
  if (!ov) return;
  ov.classList.remove('open');
  document.body.style.overflow = '';
}

/** 初始化取色器画布（SV 面板 + Hue 条） */
function initColorCanvases() {
  const sv = document.getElementById('svCanvas');
  const hue = document.getElementById('hueCanvas');
  if (!sv || !hue) return;
  // 2x 分辨率渲染，确保 Retina 屏幕清晰
  sv.width = sv.clientWidth * 2 || 400;
  sv.height = sv.clientHeight * 2 || 400;
  hue.width = hue.clientWidth * 2 || 52;
  hue.height = hue.clientHeight * 2 || 400;
  drawHue(hue);           // 绘制色相条
  drawSV(sv, cpState.h);  // 绘制饱和度-明度面板
}

/** 绘制色相条（垂直渐变，0°-360°） */
function drawHue(canvas) {
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  for (let y = 0; y < h; y++) {
    const hue = (y / h) * 360;
    ctx.fillStyle = 'hsl(' + hue + ', 100%, 50%)';
    ctx.fillRect(0, y, w, 1);
  }
}

/**
 * 绘制饱和度-明度面板
 * 水平方向：饱和度（0→100%），垂直方向：明度（100%→0%）
 * @param {HTMLCanvasElement} canvas - SV 面板画布
 * @param {number} hue - 当前色相值
 */
function drawSV(canvas, hue) {
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  const img = ctx.createImageData(w, h);
  for (let x = 0; x < w; x++) {
    for (let y = 0; y < h; y++) {
      const sat = x / w;
      const val = 1 - y / h;
      const hsl = svToHsl(hue, sat, val);
      const rgb = hslToRgb(hsl.h, hsl.s, hsl.l);
      const idx = (y * w + x) * 4;
      img.data[idx] = rgb.r;
      img.data[idx + 1] = rgb.g;
      img.data[idx + 2] = rgb.b;
      img.data[idx + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
}

/**
 * HSV → HSL 转换
 * @param {number} hue - 色相 (0-360)
 * @param {number} sat - 饱和度 (0-1)
 * @param {number} val - 明度 (0-1)
 * @returns {{h: number, s: number, l: number}}
 */
function svToHsl(hue, sat, val) {
  const l = val * (1 - sat / 2);
  const s = (l === 0 || l === 1) ? 0 : (val - l) / Math.min(l, 1 - l);
  return { h: hue, s: Math.round(s * 100), l: Math.round(l * 100) };
}

/**
 * HSL → RGB 转换
 * @param {number} h - 色相 (0-360)
 * @param {number} s - 饱和度 (0-100)
 * @param {number} l - 亮度 (0-100)
 * @returns {{r: number, g: number, b: number}}
 */
function hslToRgb(h, s, l) {
  s /= 100; l /= 100;
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs((h / 60) % 2 - 1));
  const m = l - c / 2;
  let r, g, b;
  if (h < 60) { r = c; g = x; b = 0; }
  else if (h < 120) { r = x; g = c; b = 0; }
  else if (h < 180) { r = 0; g = c; b = x; }
  else if (h < 240) { r = 0; g = x; b = c; }
  else if (h < 300) { r = x; g = 0; b = c; }
  else { r = c; g = 0; b = x; }
  return { r: Math.round((r + m) * 255), g: Math.round((g + m) * 255), b: Math.round((b + m) * 255) };
}

/** SV 面板鼠标/触摸取色 */
function cpPickSV(e) {
  const sv = document.getElementById('svCanvas');
  const dot = document.getElementById('svCursor');
  if (!sv || !dot) return;
  const r = sv.getBoundingClientRect();
  const x = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
  const y = Math.max(0, Math.min(1, (e.clientY - r.top) / r.height));
  dot.style.left = (x * 100) + '%';
  dot.style.top = (y * 100) + '%';
  cpState.s = Math.round(x * 100);
  cpState.v = Math.round((1 - y) * 100);
  updateColorFromCp();
}

/** Hue 条鼠标/触摸取色 */
function cpPickHue(e) {
  const hue = document.getElementById('hueCanvas');
  if (!hue) return;
  const r = hue.getBoundingClientRect();
  const y = Math.max(0, Math.min(1, (e.clientY - r.top) / r.height));
  cpState.h = Math.round(y * 360);
  const handle = document.getElementById('hueHandle');
  if (handle) handle.style.top = (y * 100) + '%';
  // 色相变化时重绘 SV 面板
  drawSV(document.getElementById('svCanvas'), cpState.h);
  updateColorFromCp();
}

/** 从取色面板状态更新颜色显示 */
function updateColorFromCp() {
  const rgb = hslToRgb(cpState.h, cpState.s, cpState.v);
  const hex = ((rgb.r << 16) | (rgb.g << 8) | rgb.b).toString(16).padStart(6, '0');
  updateColor(hex);
}

// 取色面板事件绑定（DOM 加载完成后执行）
document.addEventListener('DOMContentLoaded', function() {
  const ov = document.getElementById('colorPanelOverlay');
  const closeBtn = document.getElementById('panelCloseBtn');
  const confirmBtn = document.getElementById('confirmColorBtn');
  if (closeBtn) closeBtn.onclick = closeColorPanel;
  if (confirmBtn) confirmBtn.onclick = function() { closeColorPanel(); };
  if (ov) ov.onclick = function(e) { if (e.target === ov) closeColorPanel(); };
  // SV 面板：鼠标按下拖动取色 + 触摸滑动取色
  const svCanvas = document.getElementById('svCanvas');
  if (svCanvas) {
    svCanvas.addEventListener('mousedown', function(e) { cpPickSV(e); });
    svCanvas.addEventListener('mousemove', function(e) { if (e.buttons !== 1) return; cpPickSV(e); });
    svCanvas.addEventListener('touchmove', function(e) { e.preventDefault(); const t = e.touches[0]; if (t) cpPickSV(t); }, { passive: false });
    svCanvas.addEventListener('touchstart', function(e) { const t = e.touches[0]; if (t) cpPickSV(t); }, { passive: true });
  }
  // Hue 条：鼠标按下拖动取色 + 触摸滑动取色
  const hueCanvas = document.getElementById('hueCanvas');
  if (hueCanvas) {
    hueCanvas.addEventListener('mousedown', function(e) { cpPickHue(e); });
    hueCanvas.addEventListener('mousemove', function(e) { if (e.buttons !== 1) return; cpPickHue(e); });
    hueCanvas.addEventListener('touchmove', function(e) { e.preventDefault(); const t = e.touches[0]; if (t) cpPickHue(t); }, { passive: false });
    hueCanvas.addEventListener('touchstart', function(e) { const t = e.touches[0]; if (t) cpPickHue(t); }, { passive: true });
  }
});

// ── 4. JSON 格式化/压缩 ──────────────────────
/** 将 JSON 字符串格式化为缩进 2 空格的美化输出 */
function jsonFormat() {
  const input = document.getElementById('json-input').value;
  try { document.getElementById('json-output').value = JSON.stringify(JSON.parse(input), null, 2); }
  catch(e) { alert('无效的 JSON: ' + e.message); }
}
/** 将 JSON 字符串压缩为单行 */
function jsonCompact() {
  const input = document.getElementById('json-input').value;
  try { document.getElementById('json-output').value = JSON.stringify(JSON.parse(input)); }
  catch(e) { alert('无效的 JSON: ' + e.message); }
}

// ── 5. 时间戳转换 ────────────────────────────
/** 初始化时间戳工具：显示当前时间的 Unix 秒/毫秒和本地时间 */
function initTimestamp() {
  const now = new Date();
  document.getElementById('ts-now-sec').textContent = Math.floor(now.getTime() / 1000);
  document.getElementById('ts-now-ms').textContent = now.getTime();
  document.getElementById('ts-now-local').textContent = now.toLocaleString();
}
/** 刷新当前时间显示 */
function tsNow() { initTimestamp(); }
/**
 * Unix 时间戳 → 本地日期时间
 * @param {string} val - Unix 秒级时间戳
 */
function tsFromUnix(val) {
  if (!val) return;
  const d = new Date(parseInt(val) * 1000);
  document.getElementById('ts-datetime').value = isNaN(d.getTime()) ? '' : d.toLocaleString();
}
/**
 * 本地日期时间 → Unix 时间戳
 * @param {string} val - 日期时间字符串
 */
function tsFromDatetime(val) {
  if (!val) return;
  const ms = Date.parse(val);
  document.getElementById('ts-unix').value = ms ? Math.floor(ms / 1000) : '';
}

// ── 6. 哈希计算 ──────────────────────────────
/**
 * 使用 Web Crypto API 计算输入文本的 SHA-1 和 SHA-256 哈希值
 * 注意：浏览器原生不支持 MD5，显示提示文字
 */
async function calcHash() {
  const input = document.getElementById('hash-input').value;
  if (!input) return;
  const enc = new TextEncoder().encode(input);
  const hex = function(b) { return Array.from(b).map(function(x) { return x.toString(16).padStart(2, '0'); }).join(''); };
  document.getElementById('hash-md5').value = '（浏览器不支持 MD5）';
  document.getElementById('hash-sha1').value = hex(new Uint8Array(await crypto.subtle.digest('SHA-1', enc)));
  document.getElementById('hash-sha256').value = hex(new Uint8Array(await crypto.subtle.digest('SHA-256', enc)));
}

// ── 7. 密码/密钥生成 ─────────────────────────
/**
 * 使用 crypto.getRandomValues() 生成密码学安全的随机密码或密钥
 * 支持两种格式：字符模式（含特殊字符）和十六进制模式
 */
function pwGenerate() {
  const bits = parseInt(document.getElementById('keyBits').value) || 256;
  const length = bits / 4; // 每个十六进制字符 = 4 bit
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*()_+-=[]{}|;:,.<>?';
  let result = '';
  const arr = new Uint8Array(length);
  crypto.getRandomValues(arr); // 密码学安全随机数
  for (let i = 0; i < length; i++) result += chars[arr[i] % chars.length];
  // 十六进制格式：直接将随机字节转为十六进制字符串
  const fmt = document.querySelector('input[name="keyFmt"]:checked');
  if (fmt && fmt.value === 'hex') {
    result = '';
    for (let i = 0; i < length; i++) result += arr[i].toString(16).padStart(2, '0');
  }
  document.getElementById('pwOutput').textContent = result;
  document.getElementById('pwOutput').style.display = 'block';
}

/** 复制生成的密码到剪贴板 */
function pwCopy() {
  const el = document.getElementById('pwOutput');
  if (el && el.textContent) {
    navigator.clipboard.writeText(el.textContent).catch(function() {});
    alert('已复制');
  }
}

/** 密钥生成（别名，复用密码生成逻辑） */
function keyGenerate() { pwGenerate(); }
/** 密钥复制（别名） */
function keyCopy() { pwCopy(); }

// ── 8. 图片压缩 ──────────────────────────────
let izFile = null; // 当前选中的图片文件

/** 触发图片文件选择 */
function izSelect() {
  document.getElementById('iz-input').click();
}

/**
 * 加载选中的图片文件并预览
 * @param {Event} e - 文件选择事件
 */
function izLoad(e) {
  const file = e.target.files[0];
  if (!file) return;
  izFile = file;
  document.getElementById('iz-info').textContent = file.name + ' (' + (file.size / 1024).toFixed(1) + ' KB)';
  izUpdate();
}

/**
 * 根据当前参数（质量/最大宽度/格式）重新压缩图片
 * 使用 Canvas API 进行客户端图片压缩，无需上传到服务器
 */
function izUpdate() {
  if (!izFile) return;
  const quality = parseInt(document.getElementById('iz-quality').value) / 100;
  const maxW = parseInt(document.getElementById('iz-maxw').value) || 0;
  const fmt = document.getElementById('iz-fmt').value;
  const img = new Image();
  img.onload = function() {
    // 按最大宽度等比缩放
    const w = maxW > 0 ? Math.min(img.width, maxW) : img.width;
    const h = w * img.height / img.width;
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const ctx = c.getContext('2d');
    ctx.drawImage(img, 0, 0, w, h);
    // toBlob 异步回调，生成压缩后的图片
    c.toBlob(function(blob) {
      const url = URL.createObjectURL(blob);
      document.getElementById('iz-preview').innerHTML = '<img src="' + url + '">';
      document.getElementById('iz-size').textContent = (blob.size / 1024).toFixed(1) + ' KB (' + Math.round(blob.size / izFile.size * 100) + '%)';
      document.getElementById('iz-dl').innerHTML = '<a href="' + url + '" download="compressed.' + fmt.split('/')[1] + '" class="btn btn-primary btn-sm">⬇ 下载</a>';
      document.getElementById('iz-dlbtn').disabled = false;
    }, fmt, quality);
  };
  img.src = URL.createObjectURL(izFile);
}

/** 触发下载压缩后的图片 */
function izDownload() {
  const dl = document.querySelector('#iz-dl a');
  if (dl) dl.click();
}
