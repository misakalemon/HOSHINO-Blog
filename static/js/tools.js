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
  var input = document.getElementById('b64-input').value;
  try { document.getElementById('b64-output').value = btoa(input); }
  catch(e) { alert('编码失败: ' + e.message); }
}
function b64Decode() {
  var input = document.getElementById('b64-input').value;
  try { document.getElementById('b64-output').value = atob(input); }
  catch(e) { alert('解码失败: 无效的 Base64'); }
}

// ── 2. 字数统计 ──────────────────────────────
function wordCount() {
  var t = document.getElementById('wc-input').value;
  document.getElementById('wc-chars').textContent = t.replace(/\s/g, '').length;
  document.getElementById('wc-chars-sp').textContent = t.length;
  document.getElementById('wc-lines').textContent = t === '' ? 0 : t.split('\n').length;
}

// ── 3. 颜色转换 ──────────────────────────────
function hexToRgb(hex) {
  var v = parseInt(hex.replace('#', ''), 16);
  return { r: (v >> 16) & 255, g: (v >> 8) & 255, b: v & 255 };
}
function rgbToHsl(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  var max = Math.max(r, g, b), min = Math.min(r, g, b);
  var h = 0, s = 0, l = (max + min) / 2;
  if (max !== min) {
    var d = max - min;
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
  var rgb = hexToRgb(hex);
  var hsl = rgbToHsl(rgb.r, rgb.g, rgb.b);
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
  var v = document.getElementById('colorHex').value.replace(/[^0-9a-fA-F]/g, '');
  if (v.length === 6) updateColor(v);
}
function onRgbInput() {
  var r = clamp(parseInt(document.getElementById('colorR').value) || 0, 0, 255);
  var g = clamp(parseInt(document.getElementById('colorG').value) || 0, 0, 255);
  var b = clamp(parseInt(document.getElementById('colorB').value) || 0, 0, 255);
  updateColor(((r << 16) | (g << 8) | b).toString(16).padStart(6, '0'));
}
function onHslInput() {
  // Simplified: HSL to RGB conversion
  var h = clamp(parseInt(document.getElementById('colorH').value) || 0, 0, 360);
  var s = clamp(parseInt(document.getElementById('colorS').value) || 0, 0, 100);
  var l = clamp(parseInt(document.getElementById('colorL').value) || 0, 0, 100);
  s /= 100; l /= 100;
  var c = (1 - Math.abs(2 * l - 1)) * s;
  var x = c * (1 - Math.abs((h / 60) % 2 - 1));
  var m = l - c / 2;
  var r, g, b;
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

function copyColor(type) {
  var val = '';
  if (type === 'hex') val = '#' + document.getElementById('previewHex').textContent;
  else if (type === 'rgb') val = document.getElementById('previewRgb').textContent;
  else if (type === 'hsl') val = document.getElementById('previewHsl').textContent;
  if (val) {
    navigator.clipboard.writeText(val).catch(function() {});
    var btn = event.target;
    var orig = btn.textContent;
    btn.textContent = '✓ 已复制';
    setTimeout(function() { btn.textContent = orig; }, 1500);
  }
}

// 取色面板
var colorPickerOpen = false;
function toggleColorPicker() {
  colorPickerOpen = !colorPickerOpen;
  document.getElementById('colorPickerPanel').classList.toggle('open', colorPickerOpen);
  document.getElementById('triggerArrow').textContent = colorPickerOpen ? '▲' : '▼';
}

// ── 4. JSON ──────────────────────────────────
function jsonFormat() {
  var input = document.getElementById('json-input').value;
  try { document.getElementById('json-output').value = JSON.stringify(JSON.parse(input), null, 2); }
  catch(e) { alert('无效的 JSON: ' + e.message); }
}
function jsonCompact() {
  var input = document.getElementById('json-input').value;
  try { document.getElementById('json-output').value = JSON.stringify(JSON.parse(input)); }
  catch(e) { alert('无效的 JSON: ' + e.message); }
}

// ── 5. 时间戳 ────────────────────────────────
function initTimestamp() {
  var now = new Date();
  document.getElementById('ts-now-sec').textContent = Math.floor(now.getTime() / 1000);
  document.getElementById('ts-now-ms').textContent = now.getTime();
  document.getElementById('ts-now-local').textContent = now.toLocaleString();
}
function tsNow() { initTimestamp(); }
function tsFromUnix(val) {
  if (!val) return;
  var d = new Date(parseInt(val) * 1000);
  document.getElementById('ts-datetime').value = isNaN(d.getTime()) ? '' : d.toLocaleString();
}
function tsFromDatetime(val) {
  if (!val) return;
  var ms = Date.parse(val);
  document.getElementById('ts-unix').value = ms ? Math.floor(ms / 1000) : '';
}

// ── 6. 哈希 ──────────────────────────────────
async function calcHash() {
  var input = document.getElementById('hash-input').value;
  if (!input) return;
  var enc = new TextEncoder().encode(input);
  var hex = function(b) { return Array.from(b).map(function(x) { return x.toString(16).padStart(2, '0'); }).join(''); };
  document.getElementById('hash-md5').value = '（浏览器不支持 MD5）';
  document.getElementById('hash-sha1').value = hex(new Uint8Array(await crypto.subtle.digest('SHA-1', enc)));
  document.getElementById('hash-sha256').value = hex(new Uint8Array(await crypto.subtle.digest('SHA-256', enc)));
}

// ── 7. 密码生成 ──────────────────────────────
function pwGenerate() {
  var bits = parseInt(document.getElementById('keyBits').value) || 256;
  var length = bits / 4;
  var chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*()_+-=[]{}|;:,.<>?';
  var result = '';
  var arr = new Uint8Array(length);
  crypto.getRandomValues(arr);
  for (var i = 0; i < length; i++) result += chars[arr[i] % chars.length];
  var fmt = document.querySelector('input[name="keyFmt"]:checked');
  if (fmt && fmt.value === 'hex') {
    result = '';
    for (var i = 0; i < length; i++) result += arr[i].toString(16).padStart(2, '0');
  }
  document.getElementById('pwOutput').textContent = result;
  document.getElementById('pwOutput').style.display = 'block';
}
function pwCopy() {
  var el = document.getElementById('pwOutput');
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
var izFile = null;
function izSelect() {
  document.getElementById('iz-input').click();
}
function izLoad(e) {
  var file = e.target.files[0];
  if (!file) return;
  izFile = file;
  document.getElementById('iz-info').textContent = file.name + ' (' + (file.size / 1024).toFixed(1) + ' KB)';
  izUpdate();
}
function izUpdate() {
  if (!izFile) return;
  var quality = parseInt(document.getElementById('iz-quality').value) / 100;
  var maxW = parseInt(document.getElementById('iz-maxw').value) || 0;
  var fmt = document.getElementById('iz-fmt').value;
  var img = new Image();
  img.onload = function() {
    var w = maxW > 0 ? Math.min(img.width, maxW) : img.width;
    var h = w * img.height / img.width;
    var c = document.createElement('canvas');
    c.width = w; c.height = h;
    var ctx = c.getContext('2d');
    ctx.drawImage(img, 0, 0, w, h);
    c.toBlob(function(blob) {
    var url = URL.createObjectURL(blob);
    document.getElementById('iz-preview').innerHTML = '<img src="' + url + '">';
    document.getElementById('iz-size').textContent = (blob.size / 1024).toFixed(1) + ' KB (' + Math.round(blob.size / izFile.size * 100) + '%)';
    document.getElementById('iz-dl').innerHTML = '<a href="' + url + '" download="compressed.' + fmt.split('/')[1] + '" class="btn btn-primary btn-sm">⬇ 下载</a>';
    document.getElementById('iz-dlbtn').disabled = false;
  }, fmt, quality);
};
img.src = URL.createObjectURL(izFile);
}
function izDownload() {
var dl = document.querySelector('#iz-dl a');
if (dl) dl.click();
}
