/* ═══════════════════════════════════════════════
   Glow Controller v2.0
   光感设计系统 — 鼠标追踪光效 & 交互控制
   ═══════════════════════════════════════════════ */

/* ── 1. 卡片鼠标追踪光效 (CSS custom property) ── */
/**
 * 通过 mousemove 事件实时计算鼠标与卡片的位置关系，
 * 将光晕中心 (--gx/--gy) 和强度 (--glow-opacity/--glow-intensity)
 * 写入 CSS 自定义属性，驱动 ::before 伪元素的 radial-gradient 光效。
 */
(function() {
  /* 配置参数：最大感应距离、光晕透明度范围 */
  var CONFIG = { maxDist: 200, opacityMin: 0, opacityMax: 1 };
  /* 选取需要光效的卡片：玻璃卡片、管理卡片、特色卡片 */
  var cards = document.querySelectorAll('.glass-card[data-glow], .admin-card[data-glow], .featured-card[data-glow]');
  if (!cards.length) return;

  /* 缓存每张卡片的 DOM 引用和布局矩形，避免重复查询 */
  var cardData = [];
  cards.forEach(function(card) { cardData.push({ card: card, rect: null }); });

  /**
   * 刷新所有卡片的 getBoundingClientRect，
   * 在滚动 / 缩放后保证坐标准确。
   */
  function updateRects() {
    cardData.forEach(function(data) { data.rect = data.card.getBoundingClientRect(); });
  }

  var mouseX = -9999, mouseY = -9999, rafId = null;

  /**
   * 鼠标移动处理器：仅记录最新坐标，
   * 通过 requestAnimationFrame 节流，避免每帧重复计算。
   */
  function onMouseMove(e) {
    mouseX = e.clientX; mouseY = e.clientY;
    if (rafId) return;
    rafId = requestAnimationFrame(function() { updateGlow(); rafId = null; });
  }

  /**
   * 核心计算：对每张卡片求出鼠标到卡片边缘的最短距离，
   * 距离越近光晕越亮、范围越大；同时计算光晕中心相对卡片的位置百分比。
   */
  function updateGlow() {
    updateRects();
    var mx = mouseX, my = mouseY, maxDist = CONFIG.maxDist;
    cardData.forEach(function(data) {
      var rect = data.rect;
      if (!rect) return;
      /* 计算鼠标到卡片矩形的最短水平距离 */
      var dx = 0;
      if (mx < rect.left) dx = rect.left - mx;
      else if (mx > rect.right) dx = mx - rect.right;
      /* 计算鼠标到卡片矩形的最短垂直距离 */
      var dy = 0;
      if (my < rect.top) dy = rect.top - my;
      else if (my > rect.bottom) dy = my - rect.bottom;
      /* 欧几里得距离 */
      var dist = Math.sqrt(dx * dx + dy * dy);
      /* 在感应范围内，距离越近透明度越高（平方衰减，过渡更自然） */
      var opacity = 0;
      if (dist < maxDist) {
        var t = 1 - (dist / maxDist);
        t = t * t;
        opacity = CONFIG.opacityMin + (CONFIG.opacityMax - CONFIG.opacityMin) * t;
      }
      /* 将鼠标坐标映射为卡片宽高的百分比（超出边界则 clamp 到 0/100） */
      var px = 50, py = 50;
      if (mx < rect.left) px = 0;
      else if (mx > rect.right) px = 100;
      else px = ((mx - rect.left) / rect.width) * 100;
      if (my < rect.top) py = 0;
      else if (my > rect.bottom) py = 100;
      else py = ((my - rect.top) / rect.height) * 100;
      px = Math.min(100, Math.max(0, px));
      py = Math.min(100, Math.max(0, py));
      /* 写入 CSS 自定义属性，驱动伪元素的光晕位置和强度 */
      data.card.style.setProperty('--gx', px + '%');
      data.card.style.setProperty('--gy', py + '%');
      data.card.style.setProperty('--glow-opacity', opacity);
      data.card.style.setProperty('--glow-intensity', opacity);
    });
  }

  document.addEventListener('mousemove', onMouseMove);
  /* 鼠标离开页面时熄灭全部光晕 */
  document.addEventListener('mouseleave', function() {
    cardData.forEach(function(data) {
      data.card.style.setProperty('--glow-opacity', 0);
      data.card.style.setProperty('--glow-intensity', 0);
    });
  });
  window.addEventListener('resize', updateRects);
  window.addEventListener('scroll', function() { updateRects(); updateGlow(); });

  updateRects();
  /* 初始状态光晕不可见 */
  cardData.forEach(function(data) {
    data.card.style.setProperty('--glow-opacity', 0);
    data.card.style.setProperty('--glow-intensity', 0);
  });

  /* 通过 MutationObserver 监视 DOM 变化，自动为新加入的卡片绑定光效 */
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
/** 切换移动端抽屉菜单的打开/关闭状态 */
function toggleDrawer() {
  document.getElementById('mobileDrawer').classList.toggle('open');
  document.getElementById('drawerOverlay').classList.toggle('show');
}

/** 切换后台管理侧边栏的打开/关闭状态 */
function toggleAdminSidebar() {
  document.getElementById('adminToggle').classList.toggle('open');
  document.getElementById('adminSidebar').classList.toggle('open');
  document.getElementById('adminOverlay').classList.toggle('show');
}

/* ── 3. 工具函数 ────────────────────────────── */
/**
 * 在工具页中切换到指定工具面板。
 * @param {string} name - 工具名称，对应 tool-pane 的 id 后缀
 */
function switchTool(name) {
  document.querySelectorAll('.tool-pane').forEach(function(p) { p.classList.remove('active'); });
  document.querySelectorAll('.tools-nav-btn').forEach(function(t) { t.classList.remove('active'); });
  document.getElementById('tool-' + name).classList.add('active');
  var btn = document.querySelector('.tools-nav-btn[data-tool="' + name + '"]');
  if (btn) btn.classList.add('active');
}

/* ---- Base64 编解码 ---- */
/** 将输入文本编码为 Base64（先 UTF-8 编码再 btoa） */
function b64Encode() {
  document.getElementById('b64-output').value = btoa(unescape(encodeURIComponent(document.getElementById('b64-input').value)));
}
/** 将 Base64 解码为原文，解码失败时显示中文错误提示 */
function b64Decode() {
  try {
    document.getElementById('b64-output').value = decodeURIComponent(escape(atob(document.getElementById('b64-input').value)));
  } catch(e) {
    document.getElementById('b64-output').value = '解码失败: 无效的 Base64';
  }
}

/* ---- 字数统计 ---- */
/** 统计输入文本的字符数（去空格/含空格）、行数，实时更新到 DOM */
function wordCount() {
  var t = document.getElementById('wc-input').value;
  document.getElementById('wc-chars').textContent = t.replace(/\s/g,'').length;
  document.getElementById('wc-chars-sp').textContent = t.length;
  document.getElementById('wc-lines').textContent = t ? t.split('\n').length : 0;
}

/* ---- 颜色转换 ---- */
/** 从颜色选择器取色，同时转换为 RGB 和 HSL 显示 */
function colorFromPicker() {
  var c = document.getElementById('color-picker').value;
  var r = parseInt(c.slice(1,3),16), g = parseInt(c.slice(3,5),16), b = parseInt(c.slice(5,7),16);
  document.getElementById('color-hex').value = c;
  document.getElementById('color-rgb').value = 'rgb('+r+','+g+','+b+')';
  document.getElementById('color-hsl').value = rgbToHsl(r,g,b);
}
/** 从 HEX 文本框中取色，更新各字段 */
function colorFromHex(h) {
  if (!/^#[0-9a-f]{6}$/i.test(h)) return;
  var r = parseInt(h.slice(1,3),16), g = parseInt(h.slice(3,5),16), b = parseInt(h.slice(5,7),16);
  document.getElementById('color-picker').value = h;
  document.getElementById('color-rgb').value = 'rgb('+r+','+g+','+b+')';
  document.getElementById('color-hsl').value = rgbToHsl(r,g,b);
}
/** 从 RGB 文本框中取色，正则提取三个数值后更新各字段 */
function colorFromRGB(rgb) {
  var m = rgb.match(/\d+/g); if (!m || m.length<3) return;
  var r=+m[0],g=+m[1],b=+m[2];
  var h = '#' + [r,g,b].map(function(x){return ('0'+x.toString(16)).slice(-2)}).join('');
  document.getElementById('color-picker').value = h;
  document.getElementById('color-hex').value = h;
  document.getElementById('color-rgb').value = 'rgb('+r+','+g+','+b+')';
  document.getElementById('color-hsl').value = rgbToHsl(r,g,b);
}
/** RGB → HSL 转换算法，返回 "hsl(deg, pct, pct)" 格式字符串 */
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

/* ---- JSON 格式化 ---- */
/** 美化 JSON（带缩进 2 空格），解析失败则显示错误信息 */
function jsonFormat() {
  try { var o = JSON.parse(document.getElementById('json-input').value); document.getElementById('json-output').value = JSON.stringify(o,null,2); }
  catch(e) { document.getElementById('json-output').value = 'JSON 格式错误: ' + e.message; }
}
/** 压缩 JSON（无多余空格） */
function jsonCompact() {
  try { var o = JSON.parse(document.getElementById('json-input').value); document.getElementById('json-output').value = JSON.stringify(o); }
  catch(e) { document.getElementById('json-output').value = 'JSON 格式错误: ' + e.message; }
}

/* ---- 时间戳 ---- */
/** 初始化时间戳工具：填充当前 Unix 秒数和可读时间 */
function initTimestamp() {
  document.getElementById('ts-unix').value = Math.floor(Date.now()/1000);
  document.getElementById('ts-datetime').value = new Date().toISOString().slice(0,19).replace('T',' ');
  tsFromUnix(document.getElementById('ts-unix').value);
}
/** 从 Unix 秒数转换为可读时间 */
function tsFromUnix(ts) {
  var n = parseInt(ts); if (!isNaN(n)) { var d=new Date(n*1000); document.getElementById('ts-datetime').value=d.toISOString().slice(0,19).replace('T',' '); showTsResult(n); }
}
/** 从可读时间字符串转换为 Unix 秒数 */
function tsFromDatetime(dt) {
  var d = new Date(dt); if (!isNaN(d.getTime())) { var u=Math.floor(d.getTime()/1000); document.getElementById('ts-unix').value=u; showTsResult(u); }
}
/** 获取当前时间戳（快捷按钮） */
function tsNow() { initTimestamp(); }
/** 显示时间戳详信息：Unix 秒/毫秒、UTC 时间、本地时间 */
function showTsResult(ts) {
  var d = new Date(ts*1000);
  document.getElementById('ts-result').innerHTML = 'Unix 秒: <strong>'+ts+'</strong><br>Unix 毫秒: <strong>'+(ts*1000)+'</strong><br>UTC: <strong>'+d.toUTCString()+'</strong><br>本地: <strong>'+d.toLocaleString()+'</strong>';
}

/* ---- 哈希计算 ---- */
/** 利用 Web Crypto API 异步计算输入文本的 MD5、SHA-1、SHA-256 */
function calcHash() {
  var t = document.getElementById('hash-input').value;
  if (!t) { document.getElementById('hash-md5').value=''; document.getElementById('hash-sha1').value=''; document.getElementById('hash-sha256').value=''; return; }
  var enc = new TextEncoder().encode(t);
  crypto.subtle.digest('MD5', enc).then(function(b){ document.getElementById('hash-md5').value = buf2hex(b); });
  crypto.subtle.digest('SHA-1', enc).then(function(b){ document.getElementById('hash-sha1').value = buf2hex(b); });
  crypto.subtle.digest('SHA-256', enc).then(function(b){ document.getElementById('hash-sha256').value = buf2hex(b); });
}
/** 将 ArrayBuffer 转为十六进制小写字符串 */
function buf2hex(b) { return Array.from(new Uint8Array(b)).map(function(x){return ('0'+x.toString(16)).slice(-2)}).join(''); }

/** 清空指定工具面板下所有 textarea 的内容 */
function clearTool(name) {
  document.querySelectorAll('#tool-' + name + ' textarea').forEach(function(t){ t.value=''; });
}

/* ---- 图片压缩 ---- */
var izSrcImg = null, izBlobUrl = null;
/** 触发文件选择器（隐藏 input） */
function izSelect() { document.getElementById('iz-input').click(); }
/** 加载用户选择的图片，读取到 Image 对象并显示原始预览和基本信息 */
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
/**
 * 根据用户调节的质量、最大宽度、输出格式参数，
 * 在 Canvas 上重绘并导出为 Blob，实时显示压缩预览和文件大小。
 */
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
    /* 释放上一次生成的 Blob URL，避免内存泄漏 */
    if (izBlobUrl) URL.revokeObjectURL(izBlobUrl);
    izBlobUrl = URL.createObjectURL(blob);
    document.getElementById('iz-result').innerHTML = '<img src="'+izBlobUrl+'" style="max-width:100%;max-height:140px;border-radius:6px">';
    var kb = (blob.size / 1024).toFixed(1);
    document.getElementById('iz-resinfo').textContent = w+'\u00D7'+h+' \u00B7 '+kb+'KB';
    document.getElementById('iz-dlbtn').disabled = false;
  }, fmt, q/100);
}
/** 将压缩后的图片作为文件下载到本地 */
function izDownload() {
  if (!izBlobUrl) return;
  var a = document.createElement('a');
  a.href = izBlobUrl;
  var ext = { 'image/jpeg':'.jpg','image/webp':'.webp','image/png':'.png' };
  a.download = 'compressed' + (ext[document.getElementById('iz-fmt').value] || '.jpg');
  a.click();
}

/* ── 4. 自定义下拉框 ────────────────────────── */
/**
 * 初始化所有自定义下拉框：
 * 1. 自动将原生 <select> 包装为 glow-select-wrap
 * 2. 绑定点击展开/收起、选项选择、全局点击关闭等交互
 */
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
    /* 遍历原生 option 生成自定义菜单项 */
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

  /* 初始化所有 wrap：绑定事件、设置默认值 */
  document.querySelectorAll('.glow-select-wrap').forEach(function(wrap) {
    if (wrap._glowSelectInit) return;
    wrap._glowSelectInit = true;
    var native = wrap.querySelector('.glow-select-native') || wrap.querySelector('select');
    var trigger = wrap.querySelector('.glow-select-trigger');
    var menu = wrap.querySelector('.glow-select-menu');
    if (!native || !trigger || !menu) return;

    /**
     * 更新下拉框的选中状态：
     * 修改 trigger 文本、标记菜单项、更新原生 select 的值。
     * @param {string} val - 新选中的 value
     * @param {boolean} fireChange - 是否触发原生 change 事件
     */
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

    /* 点击 trigger 切换展开状态，同时关闭其他已展开的下拉框 */
    trigger.addEventListener('click', function(e) {
      e.stopPropagation();
      var wasOpen = wrap.classList.contains('is-open');
      document.querySelectorAll('.glow-select-wrap.is-open').forEach(function(w) {
        w.classList.remove('is-open');
      });
      if (!wasOpen) wrap.classList.add('is-open');
    });

    /* 点击选项后选中该项并收起菜单 */
    menu.querySelectorAll('.glow-select-option').forEach(function(opt) {
      opt.addEventListener('click', function() {
        update(opt.dataset.value, true);
        wrap.classList.remove('is-open');
      });
    });

    native.style.display = 'none';
    update(native.value, false);
  });

  /* 点击页面任意空白处关闭所有已展开的下拉框 */
  document.addEventListener('click', function() {
    document.querySelectorAll('.glow-select-wrap.is-open').forEach(function(w) {
      w.classList.remove('is-open');
    });
  });
}

initGlowSelects();

/* ── 5. 图片灯箱 ────────────────────────────── */
/** 以全屏灯箱方式展示大图，滚动条锁定防止背景滚动 */
function openLightbox(src) {
  var lb = document.getElementById('lightbox');
  var img = document.getElementById('lightboxImg');
  img.src = src;
  lb.style.display = 'flex';
  document.body.style.overflow = 'hidden';
}
/** 关闭灯箱，恢复页面滚动 */
function closeLightbox() {
  document.getElementById('lightbox').style.display = 'none';
  document.body.style.overflow = '';
}

/* ── 6. 移动端：点击标题打开侧栏 ──────────── */
/* 在移动端（<640px）点击导航 Logo 触发抽屉菜单，而非跳转首页 */
document.getElementById('navLogo') && document.getElementById('navLogo').addEventListener('click', function(e) {
  if (window.innerWidth < 640) { e.preventDefault(); toggleDrawer(); }
});
