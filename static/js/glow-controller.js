/* ═══════════════════════════════════════════════
   Glow Controller v2.0
   光感设计系统 — 鼠标追踪光效 & 交互控制
   ═══════════════════════════════════════════════ */

/* ── 1. 卡片鼠标追踪光效 (CSS custom property) ── */
(function() {
  var CONFIG = { maxDist: 200, opacityMin: 0, opacityMax: 1 };
  var cards = document.querySelectorAll('.glass-card[data-glow], .admin-card[data-glow], .featured-card[data-glow]');
  if (!cards.length) return;

  var cardData = [];
  cards.forEach(function(card) { cardData.push({ card: card, rect: null }); });

  function updateRects() {
    cardData.forEach(function(data) { data.rect = data.card.getBoundingClientRect(); });
  }

  var mouseX = -9999, mouseY = -9999, rafId = null;

  function onMouseMove(e) {
    mouseX = e.clientX; mouseY = e.clientY;
    if (rafId) return;
    rafId = requestAnimationFrame(function() { updateGlow(); rafId = null; });
  }

  function updateGlow() {
    updateRects();
    var mx = mouseX, my = mouseY, maxDist = CONFIG.maxDist;
    cardData.forEach(function(data) {
      var rect = data.rect;
      if (!rect) return;
      var dx = 0;
      if (mx < rect.left) dx = rect.left - mx;
      else if (mx > rect.right) dx = mx - rect.right;
      var dy = 0;
      if (my < rect.top) dy = rect.top - my;
      else if (my > rect.bottom) dy = my - rect.bottom;
      var dist = Math.sqrt(dx * dx + dy * dy);
      var opacity = 0;
      if (dist < maxDist) {
        var t = 1 - (dist / maxDist);
        t = t * t;
        opacity = CONFIG.opacityMin + (CONFIG.opacityMax - CONFIG.opacityMin) * t;
      }
      var px = 50, py = 50;
      if (mx < rect.left) px = 0;
      else if (mx > rect.right) px = 100;
      else px = ((mx - rect.left) / rect.width) * 100;
      if (my < rect.top) py = 0;
      else if (my > rect.bottom) py = 100;
      else py = ((my - rect.top) / rect.height) * 100;
      px = Math.min(100, Math.max(0, px));
      py = Math.min(100, Math.max(0, py));
      data.card.style.setProperty('--gx', px + '%');
      data.card.style.setProperty('--gy', py + '%');
      data.card.style.setProperty('--glow-opacity', opacity);
      data.card.style.setProperty('--glow-intensity', opacity);
    });
  }

  document.addEventListener('mousemove', onMouseMove);
  document.addEventListener('mouseleave', function() {
    cardData.forEach(function(data) {
      data.card.style.setProperty('--glow-opacity', 0);
      data.card.style.setProperty('--glow-intensity', 0);
    });
  });
  window.addEventListener('resize', updateRects);
  window.addEventListener('scroll', updateRects);

  updateRects();
  cardData.forEach(function(data) {
    data.card.style.setProperty('--glow-opacity', 0);
    data.card.style.setProperty('--glow-intensity', 0);
  });

  /* observe new cards added to DOM */
  var observer = new MutationObserver(function() {
    document.querySelectorAll('.glass-card[data-glow], .admin-card[data-glow], .featured-card[data-glow]').forEach(function(card) {
      if (!card._glowInit) {
        card._glowInit = true;
        cardData.push({ card: card, rect: null });
      }
    });
  });
  observer.observe(document.body, { childList: true, subtree: true });
})();

/* ── 2. 导航控制 ────────────────────────────── */
function toggleNav() {
  document.getElementById('navToggle').classList.toggle('open');
  document.getElementById('navLinks').classList.toggle('open');
  document.getElementById('navOverlay').classList.toggle('show');
}

function toggleAdminSidebar() {
  document.getElementById('adminToggle').classList.toggle('open');
  document.getElementById('adminSidebar').classList.toggle('open');
  document.getElementById('adminOverlay').classList.toggle('show');
}

/* ── 3. 工具函数 ────────────────────────────── */
function switchTool(name) {
  document.querySelectorAll('.tool-pane').forEach(function(p) { p.classList.remove('active'); });
  document.querySelectorAll('.tools-nav-btn').forEach(function(t) { t.classList.remove('active'); });
  document.getElementById('tool-' + name).classList.add('active');
  var btn = document.querySelector('.tools-nav-btn[data-tool="' + name + '"]');
  if (btn) btn.classList.add('active');
}

function b64Encode() {
  document.getElementById('b64-output').value = btoa(unescape(encodeURIComponent(document.getElementById('b64-input').value)));
}
function b64Decode() {
  try {
    document.getElementById('b64-output').value = decodeURIComponent(escape(atob(document.getElementById('b64-input').value)));
  } catch(e) {
    document.getElementById('b64-output').value = '解码失败: 无效的 Base64';
  }
}

function wordCount() {
  var t = document.getElementById('wc-input').value;
  document.getElementById('wc-chars').textContent = t.replace(/\s/g,'').length;
  document.getElementById('wc-chars-sp').textContent = t.length;
  document.getElementById('wc-lines').textContent = t ? t.split('\n').length : 0;
}

function colorFromPicker() {
  var c = document.getElementById('color-picker').value;
  var r = parseInt(c.slice(1,3),16), g = parseInt(c.slice(3,5),16), b = parseInt(c.slice(5,7),16);
  document.getElementById('color-hex').value = c;
  document.getElementById('color-rgb').value = 'rgb('+r+','+g+','+b+')';
  document.getElementById('color-hsl').value = rgbToHsl(r,g,b);
}
function colorFromHex(h) {
  if (!/^#[0-9a-f]{6}$/i.test(h)) return;
  var r = parseInt(h.slice(1,3),16), g = parseInt(h.slice(3,5),16), b = parseInt(h.slice(5,7),16);
  document.getElementById('color-picker').value = h;
  document.getElementById('color-rgb').value = 'rgb('+r+','+g+','+b+')';
  document.getElementById('color-hsl').value = rgbToHsl(r,g,b);
}
function colorFromRGB(rgb) {
  var m = rgb.match(/\d+/g); if (!m || m.length<3) return;
  var r=+m[0],g=+m[1],b=+m[2];
  var h = '#' + [r,g,b].map(function(x){return ('0'+x.toString(16)).slice(-2)}).join('');
  document.getElementById('color-picker').value = h;
  document.getElementById('color-hex').value = h;
  document.getElementById('color-rgb').value = 'rgb('+r+','+g+','+b+')';
  document.getElementById('color-hsl').value = rgbToHsl(r,g,b);
}
function rgbToHsl(r,g,b) {
  r/=255; g/=255; b/=255;
  var max=Math.max(r,g,b), min=Math.min(r,g,b), h, s, l=(max+min)/2;
  if (max===min) { h=0; s=0; } else {
    var d=max-min;
    s=l>0.5 ? d/(2-max-min) : d/(max+min);
    if (max===r) h=((g-b)/d+(g<b?6:0))/6;
    else if (max===g) h=((b-r)/d+2)/6;
    else h=((r-g)/d+4)/6;
    h*=60;
  }
  return 'hsl('+Math.round(h)+','+Math.round(s*100)+'%,'+Math.round(l*100)+'%)';
}

function jsonFormat() {
  try { var o = JSON.parse(document.getElementById('json-input').value); document.getElementById('json-output').value = JSON.stringify(o,null,2); }
  catch(e) { document.getElementById('json-output').value = 'JSON 格式错误: ' + e.message; }
}
function jsonCompact() {
  try { var o = JSON.parse(document.getElementById('json-input').value); document.getElementById('json-output').value = JSON.stringify(o); }
  catch(e) { document.getElementById('json-output').value = 'JSON 格式错误: ' + e.message; }
}

function initTimestamp() {
  document.getElementById('ts-unix').value = Math.floor(Date.now()/1000);
  document.getElementById('ts-datetime').value = new Date().toISOString().slice(0,19).replace('T',' ');
  tsFromUnix(document.getElementById('ts-unix').value);
}
function tsFromUnix(ts) {
  var n = parseInt(ts); if (!isNaN(n)) { var d=new Date(n*1000); document.getElementById('ts-datetime').value=d.toISOString().slice(0,19).replace('T',' '); showTsResult(n); }
}
function tsFromDatetime(dt) {
  var d = new Date(dt); if (!isNaN(d.getTime())) { var u=Math.floor(d.getTime()/1000); document.getElementById('ts-unix').value=u; showTsResult(u); }
}
function tsNow() { initTimestamp(); }
function showTsResult(ts) {
  var d = new Date(ts*1000);
  document.getElementById('ts-result').innerHTML = 'Unix 秒: <strong>'+ts+'</strong><br>Unix 毫秒: <strong>'+(ts*1000)+'</strong><br>UTC: <strong>'+d.toUTCString()+'</strong><br>本地: <strong>'+d.toLocaleString()+'</strong>';
}

function calcHash() {
  var t = document.getElementById('hash-input').value;
  if (!t) { document.getElementById('hash-md5').value=''; document.getElementById('hash-sha1').value=''; document.getElementById('hash-sha256').value=''; return; }
  var enc = new TextEncoder().encode(t);
  crypto.subtle.digest('MD5', enc).then(function(b){ document.getElementById('hash-md5').value = buf2hex(b); });
  crypto.subtle.digest('SHA-1', enc).then(function(b){ document.getElementById('hash-sha1').value = buf2hex(b); });
  crypto.subtle.digest('SHA-256', enc).then(function(b){ document.getElementById('hash-sha256').value = buf2hex(b); });
}
function buf2hex(b) { return Array.from(new Uint8Array(b)).map(function(x){return ('0'+x.toString(16)).slice(-2)}).join(''); }

function clearTool(name) {
  document.querySelectorAll('#tool-' + name + ' textarea').forEach(function(t){ t.value=''; });
}

var izSrcImg = null, izBlobUrl = null;
function izSelect() { document.getElementById('iz-input').click(); }
function izLoad() {
  var f = document.getElementById('iz-input').files[0];
  if (!f) return;
  var reader = new FileReader();
  reader.onload = function(e) {
    var img = new Image();
    img.onload = function() {
      izSrcImg = img;
      document.getElementById('iz-original').innerHTML = '<img src="'+e.target.result+'" style="max-width:100%;max-height:140px;border-radius:6px">';
      var kb = (f.size / 1024).toFixed(1);
      document.getElementById('iz-originfo').textContent = img.width+'\u00D7'+img.height+' \u00B7 '+kb+'KB \u00B7 '+f.type;
      izUpdate();
    };
    img.src = e.target.result;
  };
  reader.readAsDataURL(f);
}
function izUpdate() {
  if (!izSrcImg) return;
  var q = parseInt(document.getElementById('iz-quality').value);
  document.getElementById('iz-q-val').textContent = q + '%';
  var maxw = parseInt(document.getElementById('iz-maxw').value);
  var fmt = document.getElementById('iz-fmt').value;
  var w = izSrcImg.width, h = izSrcImg.height;
  if (maxw > 0 && w > maxw) { h = Math.round(h * maxw / w); w = maxw; }
  var c = document.createElement('canvas');
  c.width = w; c.height = h;
  var ctx = c.getContext('2d');
  ctx.drawImage(izSrcImg, 0, 0, w, h);
  c.toBlob(function(blob) {
    if (izBlobUrl) URL.revokeObjectURL(izBlobUrl);
    izBlobUrl = URL.createObjectURL(blob);
    document.getElementById('iz-result').innerHTML = '<img src="'+izBlobUrl+'" style="max-width:100%;max-height:140px;border-radius:6px">';
    var kb = (blob.size / 1024).toFixed(1);
    document.getElementById('iz-resinfo').textContent = w+'\u00D7'+h+' \u00B7 '+kb+'KB';
    document.getElementById('iz-dlbtn').disabled = false;
  }, fmt, q/100);
}
function izDownload() {
  if (!izBlobUrl) return;
  var a = document.createElement('a');
  a.href = izBlobUrl;
  var ext = { 'image/jpeg':'.jpg','image/webp':'.webp','image/png':'.png' };
  a.download = 'compressed' + (ext[document.getElementById('iz-fmt').value] || '.jpg');
  a.click();
}

/* ── 4. 自定义下拉框 ────────────────────────── */
function initGlowSelects() {
  /* 自动包装原生 <select> → glow-select-wrap（排除已包装的和 RTE 工具栏） */
  document.querySelectorAll('select:not([multiple])').forEach(function(select) {
    if (select.closest('#rte-toolbar')) return;
    if (select.closest('.glow-select-wrap')) return;
    if (!select.options.length) return;
    var selected = select.options[select.selectedIndex];
    var wrap = document.createElement('div');
    wrap.className = 'glow-select-wrap';
    var trigger = document.createElement('div');
    trigger.className = 'glow-select-trigger';
    var label = document.createElement('span');
    label.textContent = selected ? selected.text : '选择';
    var arrow = document.createElement('span');
    arrow.className = 'glow-select-arrow';
    arrow.textContent = '▼';
    trigger.appendChild(label); trigger.appendChild(arrow);
    var menu = document.createElement('div');
    menu.className = 'glow-select-menu';
    Array.from(select.options).forEach(function(opt) {
      var item = document.createElement('div');
      item.className = 'glow-select-option' + (opt.selected ? ' is-selected' : '');
      item.dataset.value = opt.value; item.textContent = opt.text;
      menu.appendChild(item);
    });
    select.style.display = 'none';
    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(trigger); wrap.appendChild(select); wrap.appendChild(menu);
  });

  /* 初始化所有 wrap */
  document.querySelectorAll('.glow-select-wrap').forEach(function(wrap) {
    if (wrap._glowSelectInit) return;
    wrap._glowSelectInit = true;
    var native = wrap.querySelector('.glow-select-native') || wrap.querySelector('select');
    var trigger = wrap.querySelector('.glow-select-trigger');
    var menu = wrap.querySelector('.glow-select-menu');
    if (!native || !trigger || !menu) return;

    function update(val, fireChange) {
      var label = val;
      menu.querySelectorAll('.glow-select-option').forEach(function(o) {
        var isSel = o.dataset.value === val;
        o.classList.toggle('is-selected', isSel);
        if (isSel) label = o.textContent;
      });
      trigger.childNodes[0].textContent = label;
      native.value = val;
      if (fireChange) {
        native.dispatchEvent(new Event('change', { bubbles: true }));
      }
    }

    trigger.addEventListener('click', function(e) {
      e.stopPropagation();
      var wasOpen = wrap.classList.contains('is-open');
      document.querySelectorAll('.glow-select-wrap.is-open').forEach(function(w) {
        w.classList.remove('is-open');
      });
      if (!wasOpen) wrap.classList.add('is-open');
    });

    menu.querySelectorAll('.glow-select-option').forEach(function(opt) {
      opt.addEventListener('click', function() {
        update(opt.dataset.value, true);
        wrap.classList.remove('is-open');
      });
    });

    native.style.display = 'none';
    update(native.value, false);
  });

  document.addEventListener('click', function() {
    document.querySelectorAll('.glow-select-wrap.is-open').forEach(function(w) {
      w.classList.remove('is-open');
    });
  });
}

initGlowSelects();
