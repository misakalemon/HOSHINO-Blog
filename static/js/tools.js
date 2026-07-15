// ═══════════════════════════════════════════════
// 工具页面 — 所有工具函数
// ═══════════════════════════════════════════════

// ── 工具切换 ──────────────────────────────────
function switchTool(tool) {
  document.querySelectorAll('.tools-nav-btn').forEach(function(b) {
    b.classList.toggle('active', b.getAttribute('data-tool') === tool);
  });
  document.querySelectorAll('.tool-pane').forEach(function(p) {
    p.classList.toggle('active', p.id === 'tool-' + tool);
  });
}

function clearTool(id) {
  document.getElementById(id + '-input').value = '';
  document.getElementById(id + '-output').value = '';
}

// ── 1. Base64 ────────────────────────────────
function b64Encode() {
  const input = document.getElementById('b64-input').value;
  try { document.getElementById('b64-output').value = btoa(input); }
  catch(e) { alert('编码失败: ' + e.message); }
}
function b64Decode() {
  const input = document.getElementById('b64-input').value;
  try { document.getElementById('b64-output').value = atob(input); }
  catch(e) { alert('解码失败: 无效的 Base64'); }
}

// ── 2. 字数统计 ──────────────────────────────
function wordCount() {
  const t = document.getElementById('wc-input').value;
  document.getElementById('wc-chars').textContent = t.replace(/\s/g, '').length;
  document.getElementById('wc-chars-sp').textContent = t.length;
  document.getElementById('wc-lines').textContent = t === '' ? 0 : t.split('\n').length;
}

// ── 3. 颜色转换 ──────────────────────────────
function hexToRgb(hex) {
  const v = parseInt(hex.replace('#', ''), 16);
  return { r: (v >> 16) & 255, g: (v >> 8) & 255, b: v & 255 };
}
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
function updateColor(hex) {
  hex = hex.replace('#', '');
  if (hex.length !== 6) return;
  const rgb = hexToRgb(hex);
  const hsl = rgbToHsl(rgb.r, rgb.g, rgb.b);
  document.getElementById('previewHex').textContent = hex.toUpperCase();
  document.getElementById('previewRgb').textContent = 'rgb(' + rgb.r + ', ' + rgb.g + ', ' + rgb.b + ')';
  document.getElementById('previewHsl').textContent = 'hsl(' + hsl.h + ', ' + hsl.s + '%, ' + hsl.l + '%)';
  document.getElementById('previewSwatch').style.background = '#' + hex;
  document.getElementById('triggerSwatch').style.background = '#' + hex;
  document.getElementById('colorHex').value = hex.toUpperCase();
  document.getElementById('colorR').value = rgb.r;
  document.getElementById('colorG').value = rgb.g;
  document.getElementById('colorB').value = rgb.b;
  document.getElementById('colorH').value = hsl.h;
  document.getElementById('colorS').value = hsl.s;
  document.getElementById('colorL').value = hsl.l;
}
function onHexInput() {
  const v = document.getElementById('colorHex').value.replace(/[^0-9a-fA-F]/g, '');
  if (v.length === 6) updateColor(v);
}
function onRgbInput() {
  const r = clamp(parseInt(document.getElementById('colorR').value) || 0, 0, 255);
  const g = clamp(parseInt(document.getElementById('colorG').value) || 0, 0, 255);
  const b = clamp(parseInt(document.getElementById('colorB').value) || 0, 0, 255);
  updateColor(((r << 16) | (g << 8) | b).toString(16).padStart(6, '0'));
}
function onHslInput() {
  // Simplified: HSL to RGB conversion
  const h = clamp(parseInt(document.getElementById('colorH').value) || 0, 0, 360);
  let s = clamp(parseInt(document.getElementById('colorS').value) || 0, 0, 100);
  let l = clamp(parseInt(document.getElementById('colorL').value) || 0, 0, 100);
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
  r = Math.round((r + m) * 255);
  g = Math.round((g + m) * 255);
  b = Math.round((b + m) * 255);
  updateColor(((r << 16) | (g << 8) | b).toString(16).padStart(6, '0'));
}
function clamp(v, mn, mx) { return Math.min(Math.max(v, mn), mx); }

function copyColor(type, e) {
  var ev = e || window.event;
  if (!ev) return;
  let val = '';
  if (type === 'hex') val = '#' + document.getElementById('previewHex').textContent;
  else if (type === 'rgb') val = document.getElementById('previewRgb').textContent;
  else if (type === 'hsl') val = document.getElementById('previewHsl').textContent;
  if (val) {
    navigator.clipboard.writeText(val).catch(function() {});
    const btn = ev.currentTarget || ev.target;
    const orig = btn.textContent;
    btn.textContent = '✓ 已复制';
    setTimeout(function() { btn.textContent = orig; }, 1500);
  }
}

// ── 取色面板（浮层）───────────────────────
const cpState = { h: 258, s: 62, v: 82 };
function openColorPanel() {
  const ov = document.getElementById('colorPanelOverlay');
  if (!ov) return;
  ov.classList.add('open');
  document.body.style.overflow = 'hidden';
  setTimeout(function() { initColorCanvases(); }, 50);
}
function closeColorPanel() {
  const ov = document.getElementById('colorPanelOverlay');
  if (!ov) return;
  ov.classList.remove('open');
  document.body.style.overflow = '';
}
// 初始化画布取色器
function initColorCanvases() {
  const sv = document.getElementById('svCanvas');
  const hue = document.getElementById('hueCanvas');
  if (!sv || !hue) return;
  // 实际尺寸
  sv.width = sv.clientWidth * 2 || 400;
  sv.height = sv.clientHeight * 2 || 400;
  hue.width = hue.clientWidth * 2 || 52;
  hue.height = hue.clientHeight * 2 || 400;
  drawHue(hue);
  drawSV(sv, cpState.h);
}
function drawHue(canvas) {
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  for (let y = 0; y < h; y++) {
    const hue = (y / h) * 360;
    ctx.fillStyle = 'hsl(' + hue + ', 100%, 50%)';
    ctx.fillRect(0, y, w, 1);
  }
}
function drawSV(canvas, hue) {
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  // 水平: 饱和度, 垂直: 明度
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
function svToHsl(hue, sat, val) {
  const l = val * (1 - sat / 2);
  const s = (l === 0 || l === 1) ? 0 : (val - l) / Math.min(l, 1 - l);
  return { h: hue, s: Math.round(s * 100), l: Math.round(l * 100) };
}
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
function cpPickHue(e) {
  const hue = document.getElementById('hueCanvas');
  if (!hue) return;
  const r = hue.getBoundingClientRect();
  const y = Math.max(0, Math.min(1, (e.clientY - r.top) / r.height));
  cpState.h = Math.round(y * 360);
  const handle = document.getElementById('hueHandle');
  if (handle) handle.style.top = (y * 100) + '%';
  drawSV(document.getElementById('svCanvas'), cpState.h);
  updateColorFromCp();
}
function updateColorFromCp() {
  const rgb = hslToRgb(cpState.h, cpState.s, cpState.v);
  const hex = ((rgb.r << 16) | (rgb.g << 8) | rgb.b).toString(16).padStart(6, '0');
  updateColor(hex);
}
// 面板关闭按钮
document.addEventListener('DOMContentLoaded', function() {
  const ov = document.getElementById('colorPanelOverlay');
  const closeBtn = document.getElementById('panelCloseBtn');
  const confirmBtn = document.getElementById('confirmColorBtn');
  if (closeBtn) closeBtn.onclick = closeColorPanel;
  if (confirmBtn) confirmBtn.onclick = function() { closeColorPanel(); };
  if (ov) ov.onclick = function(e) { if (e.target === ov) closeColorPanel(); };
  // SV picker
  const svCanvas = document.getElementById('svCanvas');
  if (svCanvas) {
    svCanvas.addEventListener('mousedown', function(e) { cpPickSV(e); });
    svCanvas.addEventListener('mousemove', function(e) { if (e.buttons !== 1) return; cpPickSV(e); });
    svCanvas.addEventListener('touchmove', function(e) { e.preventDefault(); const t = e.touches[0]; if (t) cpPickSV(t); }, { passive: false });
    svCanvas.addEventListener('touchstart', function(e) { const t = e.touches[0]; if (t) cpPickSV(t); }, { passive: true });
  }
  // Hue picker
  const hueCanvas = document.getElementById('hueCanvas');
  if (hueCanvas) {
    hueCanvas.addEventListener('mousedown', function(e) { cpPickHue(e); });
    hueCanvas.addEventListener('mousemove', function(e) { if (e.buttons !== 1) return; cpPickHue(e); });
    hueCanvas.addEventListener('touchmove', function(e) { e.preventDefault(); const t = e.touches[0]; if (t) cpPickHue(t); }, { passive: false });
    hueCanvas.addEventListener('touchstart', function(e) { const t = e.touches[0]; if (t) cpPickHue(t); }, { passive: true });
  }
});

// ── 4. JSON ──────────────────────────────────
function jsonFormat() {
  const input = document.getElementById('json-input').value;
  try { document.getElementById('json-output').value = JSON.stringify(JSON.parse(input), null, 2); }
  catch(e) { alert('无效的 JSON: ' + e.message); }
}
function jsonCompact() {
  const input = document.getElementById('json-input').value;
  try { document.getElementById('json-output').value = JSON.stringify(JSON.parse(input)); }
  catch(e) { alert('无效的 JSON: ' + e.message); }
}

// ── 5. 时间戳 ────────────────────────────────
function initTimestamp() {
  const now = new Date();
  document.getElementById('ts-now-sec').textContent = Math.floor(now.getTime() / 1000);
  document.getElementById('ts-now-ms').textContent = now.getTime();
  document.getElementById('ts-now-local').textContent = now.toLocaleString();
}
function tsNow() { initTimestamp(); }
function tsFromUnix(val) {
  if (!val) return;
  const d = new Date(parseInt(val) * 1000);
  document.getElementById('ts-datetime').value = isNaN(d.getTime()) ? '' : d.toLocaleString();
}
function tsFromDatetime(val) {
  if (!val) return;
  const ms = Date.parse(val);
  document.getElementById('ts-unix').value = ms ? Math.floor(ms / 1000) : '';
}

// ── 6. 哈希 ──────────────────────────────────
async function calcHash() {
  const input = document.getElementById('hash-input').value;
  if (!input) return;
  const enc = new TextEncoder().encode(input);
  const hex = function(b) { return Array.from(b).map(function(x) { return x.toString(16).padStart(2, '0'); }).join(''); };
  document.getElementById('hash-md5').value = '（浏览器不支持 MD5）';
  document.getElementById('hash-sha1').value = hex(new Uint8Array(await crypto.subtle.digest('SHA-1', enc)));
  document.getElementById('hash-sha256').value = hex(new Uint8Array(await crypto.subtle.digest('SHA-256', enc)));
}

// ── 7. 密码生成 ──────────────────────────────
function pwGenerate() {
  const bits = parseInt(document.getElementById('keyBits').value) || 256;
  const length = bits / 4;
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*()_+-=[]{}|;:,.<>?';
  let result = '';
  const arr = new Uint8Array(length);
  crypto.getRandomValues(arr);
  for (let i = 0; i < length; i++) result += chars[arr[i] % chars.length];
  const fmt = document.querySelector('input[name="keyFmt"]:checked');
  if (fmt && fmt.value === 'hex') {
    result = '';
    for (let i = 0; i < length; i++) result += arr[i].toString(16).padStart(2, '0');
  }
  document.getElementById('pwOutput').textContent = result;
  document.getElementById('pwOutput').style.display = 'block';
}
function pwCopy() {
  const el = document.getElementById('pwOutput');
  if (el && el.textContent) {
    navigator.clipboard.writeText(el.textContent).catch(function() {});
    alert('已复制');
  }
}
function keyGenerate() {
  pwGenerate();
}
function keyCopy() {
  pwCopy();
}

// ── 8. 图片压缩 ──────────────────────────────
let izFile = null;
function izSelect() {
  document.getElementById('iz-input').click();
}
function izLoad(e) {
  const file = e.target.files[0];
  if (!file) return;
  izFile = file;
  document.getElementById('iz-info').textContent = file.name + ' (' + (file.size / 1024).toFixed(1) + ' KB)';
  izUpdate();
}
function izUpdate() {
  if (!izFile) return;
  const quality = parseInt(document.getElementById('iz-quality').value) / 100;
  const maxW = parseInt(document.getElementById('iz-maxw').value) || 0;
  const fmt = document.getElementById('iz-fmt').value;
  const img = new Image();
  img.onload = function() {
    const w = maxW > 0 ? Math.min(img.width, maxW) : img.width;
    const h = w * img.height / img.width;
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const ctx = c.getContext('2d');
    ctx.drawImage(img, 0, 0, w, h);
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
function izDownload() {
const dl = document.querySelector('#iz-dl a');
if (dl) dl.click();
}
