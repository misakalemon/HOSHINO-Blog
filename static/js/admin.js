// ── Toast 提示 ─────────────────────────────────
let _toastTimer = null;
function showToast(msg, type) {
  var el = document.getElementById('globalToast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'globalToast';
    el.className = 'color-toast';
    document.body.appendChild(el);
  }
  if (_toastTimer) { clearTimeout(_toastTimer); _toastTimer = null; }
  el.textContent = msg;
  if (type === 'error') {
    el.style.borderColor = 'rgba(255,80,80,0.3)';
    el.style.background = 'rgba(40,12,12,0.95)';
    el.style.color = '#ffb0b0';
  } else if (type === 'success') {
    el.style.borderColor = 'rgba(80,200,120,0.3)';
    el.style.background = 'rgba(12,40,20,0.95)';
    el.style.color = '#b0ffb0';
  } else {
    el.style.borderColor = 'rgba(108,66,209,0.3)';
    el.style.background = 'rgba(18,16,34,0.95)';
    el.style.color = '#e0daff';
  }
  el.classList.add('show');
  _toastTimer = setTimeout(function() { el.classList.remove('show'); }, 2800);
}

// ── 侧边栏切换 ────────────────────────────────
function toggleAdminSidebar() {
  document.getElementById('adminSidebar').classList.toggle('open');
  document.getElementById('adminToggle').classList.toggle('open');
  document.getElementById('adminOverlay').classList.toggle('show');
}
document.getElementById('adminToggle')?.addEventListener('click', toggleAdminSidebar);
document.getElementById('adminOverlay')?.addEventListener('click', toggleAdminSidebar);

// ── 图片裁剪工具（浮动裁剪框模式）─────────────
function openCropModal(file, callback) {
  var RATIOS = [
    { label: '自由', w: 0, h: 0 },
    { label: '1:1', w: 1, h: 1 },
    { label: '4:3', w: 4, h: 3 },
    { label: '16:9', w: 16, h: 9 },
    { label: '3:2', w: 3, h: 2 },
    { label: '21:9', w: 21, h: 9 },
    { label: '2:3', w: 2, h: 3 },
    { label: '3:4', w: 3, h: 4 },
    { label: '9:16', w: 9, h: 16 },
    { label: '1.91:1', w: 1.91, h: 1 },
  ];
  var filename = file.name || 'image.png';

  var ov = document.createElement('div');
  ov.className = 'crop-overlay';
  ov.innerHTML =
    '<div class="crop-modal">' +
      '<div class="crop-modal-header">' +
        '<h3>✂ 裁剪图片</h3>' +
        '<button class="close-btn" id="cropModalClose">&times;</button>' +
      '</div>' +
      '<div class="crop-viewport-area" id="cropViewport">' +
        '<div class="crop-loading hidden" id="cropLoading"><div class="crop-loading-spinner"></div><span>加载中...</span></div>' +
        '<img id="cropImg" src="" draggable="false">' +
        '<div class="crop-mask-layer" id="cropMaskLayer">' +
          '<div class="crop-mask-piece" id="cropMaskTop"></div>' +
          '<div class="crop-mask-piece" id="cropMaskBottom"></div>' +
          '<div class="crop-mask-piece" id="cropMaskLeft"></div>' +
          '<div class="crop-mask-piece" id="cropMaskRight"></div>' +
        '</div>' +
        '<div class="crop-box" id="cropBox">' +
          '<div class="crop-edge crop-edge-top" data-edge="top"></div>' +
          '<div class="crop-edge crop-edge-bottom" data-edge="bottom"></div>' +
          '<div class="crop-edge crop-edge-left" data-edge="left"></div>' +
          '<div class="crop-edge crop-edge-right" data-edge="right"></div>' +
          '<div class="crop-edge crop-edge-tl" data-edge="tl"></div>' +
          '<div class="crop-edge crop-edge-tr" data-edge="tr"></div>' +
          '<div class="crop-edge crop-edge-bl" data-edge="bl"></div>' +
          '<div class="crop-edge crop-edge-br" data-edge="br"></div>' +
        '</div>' +
      '</div>' +
      '<div class="crop-footer">' +
        '<div class="crop-ratios" id="cropRatios"></div>' +
        '<div class="crop-zoom">' +
          '<input type="range" id="cropZoom" min="0.2" max="3" step="0.01" value="1">' +
          '<span class="crop-zoom-val" id="cropZoomVal">100%</span>' +
        '</div>' +
        '<div class="crop-output-size" id="cropOutputSize"></div>' +
        '<div class="crop-actions">' +
          '<button class="action-btn crop-cancel" id="cropReset">重置</button>' +
          '<button class="action-btn crop-cancel" id="cropCancel">取消</button>' +
          '<button class="action-btn crop-apply" id="cropConfirm">确定裁剪</button>' +
        '</div>' +
      '</div>' +
      '<div class="crop-resize-handle" id="cropResizeHandle"></div>' +
    '</div>';
  document.body.appendChild(ov);

  var viewport = ov.querySelector('#cropViewport');
  var img = ov.querySelector('#cropImg');
  var cropBox = ov.querySelector('#cropBox');
  var maskTop = ov.querySelector('#cropMaskTop');
  var maskBottom = ov.querySelector('#cropMaskBottom');
  var maskLeft = ov.querySelector('#cropMaskLeft');
  var maskRight = ov.querySelector('#cropMaskRight');
  var ratiosEl = ov.querySelector('#cropRatios');
  var zoomSlider = ov.querySelector('#cropZoom');
  var zoomVal = ov.querySelector('#cropZoomVal');
  var loadingEl = ov.querySelector('#cropLoading');
  var outputSizeEl = ov.querySelector('#cropOutputSize');

  function updateOutputSize() {
    if (!st.cropMode) { outputSizeEl.textContent = ''; return; }
    var W = st.imgW, H = st.imgH;
    var scale = st.scale, tx = st.tx, ty = st.ty;
    var vp = getVp();
    var imgLeft = vp.w / 2 + tx - W * scale / 2;
    var imgTop = vp.h / 2 + ty - H * scale / 2;
    var left = st.cropLeft, top = st.cropTop;
    var sx = Math.max(0, (left - imgLeft) / scale);
    var sy = Math.max(0, (top - imgTop) / scale);
    var sw = Math.min(st.cropW / scale, W - sx);
    var sh = Math.min(st.cropH / scale, H - sy);
    outputSizeEl.textContent = Math.round(sw) + '×' + Math.round(sh);
  }

  var st = {
    imgW: 0, imgH: 0,
    tx: 0, ty: 0, scale: 1,
    cropMode: false,
    ratio: null,
    cropLeft: 0, cropTop: 0, cropW: 0, cropH: 0,
    dragMode: null,
    resizeEdge: null,
    dragX: 0, dragY: 0,
    dragTx: 0, dragTy: 0,
    dragCropLeft: 0, dragCropTop: 0, dragCropW: 0, dragCropH: 0,
  };

  function clamp(v, mn, mx) { return Math.min(Math.max(v, mn), mx); }

  function getVp() {
    return { w: viewport.clientWidth, h: viewport.clientHeight };
  }

  function getImgRect() {
    var vp = getVp();
    var cx = vp.w / 2 + st.tx, cy = vp.h / 2 + st.ty;
    var sw = st.imgW * st.scale, sh = st.imgH * st.scale;
    return { l: cx - sw/2, t: cy - sh/2, r: cx + sw/2, b: cy + sh/2, w: sw, h: sh };
  }

  function getImgBounds() {
    var vp = getVp();
    var sw = st.imgW * st.scale, sh = st.imgH * st.scale;
    var relax = sw * 0.15, minX, maxX, minY, maxY;
    if (sw <= vp.w) { minX = -(vp.w - sw) / 2; maxX = (vp.w - sw) / 2; }
    else { minX = -(vp.w) / 2; maxX = (vp.w) / 2; }
    if (sh <= vp.h) { minY = -(vp.h - sh) / 2; maxY = (vp.h - sh) / 2; }
    else { minY = -(vp.h) / 2; maxY = (vp.h) / 2; }
    return { minX: minX - relax, maxX: maxX + relax, minY: minY - relax, maxY: maxY + relax };
  }

  function getEdge(px, py) {
    if (!st.cropMode || !st.ratio) return null;
    var l = st.cropLeft, t = st.cropTop, r = l + st.cropW, b = t + st.cropH;
    var S = 10;
    if (px >= l - S && px <= l + S && py >= t - S && py <= t + S) return 'tl';
    if (px >= r - S && px <= r + S && py >= t - S && py <= t + S) return 'tr';
    if (px >= l - S && px <= l + S && py >= b - S && py <= b + S) return 'bl';
    if (px >= r - S && px <= r + S && py >= b - S && py <= b + S) return 'br';
    if (py >= t - S && py <= t + S && px >= l && px <= r) return 'top';
    if (py >= b - S && py <= b + S && px >= l && px <= r) return 'bottom';
    if (px >= l - S && px <= l + S && py >= t && py <= b) return 'left';
    if (px >= r - S && px <= r + S && py >= t && py <= b) return 'right';
    return null;
  }

  function insideCrop(px, py) {
    if (!st.cropMode) return false;
    var pad = 4;
    return px >= st.cropLeft + pad && px <= st.cropLeft + st.cropW - pad &&
           py >= st.cropTop + pad && py <= st.cropTop + st.cropH - pad;
  }

  function vpCoords(e) {
    var r = viewport.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }

  function applyTransform() {
    img.style.transform = 'translate(calc(-50% + ' + st.tx + 'px), calc(-50% + ' + st.ty + 'px)) scale(' + st.scale + ')';
    zoomVal.textContent = Math.round(st.scale * 100) + '%';
  }

  function activateCrop(ratioStr) {
    var ir = getImgRect();
    if (ratioStr === 'free') {
      st.cropLeft = ir.l; st.cropTop = ir.t;
      st.cropW = ir.w; st.cropH = ir.h;
      st.ratio = 'free';
    } else {
      var parts = ratioStr.split(':');
      var rw = parseFloat(parts[0]), rh = parseFloat(parts[1]);
      var vp = getVp();
      var maxW = Math.min(vp.w * 0.9, ir.w);
      var maxH = Math.min(vp.h * 0.9, ir.h);
      var bw, bh;
      if (rw / rh > maxW / maxH) { bw = maxW; bh = bw * rh / rw; }
      else { bh = maxH; bw = bh * rw / rh; }
      bw = Math.min(bw, ir.w); bh = Math.min(bh, ir.h);
      if (bw < 2 || bh < 2) { bw = ir.w; bh = ir.h; }
      st.cropLeft = ir.l + (ir.w - bw) / 2;
      st.cropTop = ir.t + (ir.h - bh) / 2;
      st.cropW = bw; st.cropH = bh;
      st.ratio = ratioStr;
    }
    st.cropMode = true;
    renderCrop();
  }

  function clampCrop() {
    if (!st.cropMode) return;
    var ir = getImgRect();
    st.cropLeft = clamp(st.cropLeft, ir.l, ir.r - st.cropW);
    st.cropTop = clamp(st.cropTop, ir.t, ir.b - st.cropH);
    st.cropW = clamp(st.cropW, 4, ir.w);
    st.cropH = clamp(st.cropH, 4, ir.h);
  }

  function renderCrop() {
    if (!st.cropMode) return;
    clampCrop();
    var vp = getVp();
    var l = st.cropLeft, t = st.cropTop, r = l + st.cropW, b = t + st.cropH;
    cropBox.style.left = l + 'px';
    cropBox.style.top = t + 'px';
    cropBox.style.width = st.cropW + 'px';
    cropBox.style.height = st.cropH + 'px';
    maskTop.style.cssText = 'left:0;top:0;width:' + vp.w + 'px;height:' + t + 'px';
    maskBottom.style.cssText = 'left:0;top:' + b + 'px;width:' + vp.w + 'px;height:' + (vp.h - b) + 'px';
    maskLeft.style.cssText = 'left:0;top:' + t + 'px;width:' + l + 'px;height:' + st.cropH + 'px';
    maskRight.style.cssText = 'left:' + r + 'px;top:' + t + 'px;width:' + (vp.w - r) + 'px;height:' + st.cropH + 'px';
    updateOutputSize();
  }

  loadingEl.classList.remove('hidden');
  var reader = new FileReader();
  reader.onload = function(e) {
    img.onload = function() {
      loadingEl.classList.add('hidden');
      st.imgW = img.naturalWidth;
      st.imgH = img.naturalHeight;
      var vp = getVp();
      var s = Math.min(vp.w / st.imgW, vp.h / st.imgH, 1);
      st.scale = Math.max(s, 0.2);
      zoomSlider.value = st.scale;
      st.tx = 0; st.ty = 0;
      applyTransform();
      activateCrop('free');
    };
    img.onerror = function() {
      loadingEl.classList.add('hidden');
      showToast('图片加载失败，请重试', 'error');
      teardown(); document.body.removeChild(ov); if (callback) callback(null);
    };
    img.src = e.target.result;
  };
  reader.readAsDataURL(file);

  RATIOS.forEach(function(r, idx) {
    var btn = document.createElement('button');
    btn.className = 'crop-ratio-btn' + (idx === 0 ? ' active' : '');
    btn.textContent = r.label;
    btn.onclick = function() {
      ratiosEl.querySelectorAll('.crop-ratio-btn').forEach(function(b) { b.classList.remove('active'); });
      btn.classList.add('active');
      if (r.w === 0) {
        activateCrop('free');
      } else {
        var ratioStr = r.w + ':' + r.h;
        activateCrop(ratioStr);
      }
    };
    ratiosEl.appendChild(btn);
  });

  function onDown(e) {
    if (e.button !== undefined && e.button !== 0) return;
    var p = vpCoords(e);
    if (st.cropMode && st.ratio === 'free') {
      var edge = getEdge(p.x, p.y);
      if (edge) {
        st.dragMode = 'resize'; st.resizeEdge = edge;
        st.dragX = p.x; st.dragY = p.y;
        st.dragCropLeft = st.cropLeft; st.dragCropTop = st.cropTop;
        st.dragCropW = st.cropW; st.dragCropH = st.cropH;
        cropBox.classList.add('dragging');
        e.preventDefault(); return;
      }
    }
    if (st.cropMode && insideCrop(p.x, p.y)) {
      st.dragMode = 'crop';
      st.dragX = p.x; st.dragY = p.y;
      st.dragCropLeft = st.cropLeft; st.dragCropTop = st.cropTop;
      cropBox.classList.add('dragging');
      e.preventDefault(); return;
    }
    st.dragMode = 'image';
    st.dragX = p.x; st.dragY = p.y;
    st.dragTx = st.tx; st.dragTy = st.ty;
    e.preventDefault();
  }

  function onMove(e) {
    if (!st.dragMode) return;
    var p = vpCoords(e);
    var dx = p.x - st.dragX, dy = p.y - st.dragY;
    if (st.dragMode === 'image') {
      var b = getImgBounds();
      st.tx = clamp(st.dragTx + dx, b.minX, b.maxX);
      st.ty = clamp(st.dragTy + dy, b.minY, b.maxY);
      applyTransform();
      if (st.cropMode) renderCrop();
      e.preventDefault();
    } else if (st.dragMode === 'crop') {
      var ir = getImgRect();
      st.cropLeft = clamp(st.dragCropLeft + dx, ir.l, ir.r - st.cropW);
      st.cropTop = clamp(st.dragCropTop + dy, ir.t, ir.b - st.cropH);
      renderCrop();
      e.preventDefault();
    } else if (st.dragMode === 'resize') {
      var edge = st.resizeEdge;
      var nl = st.dragCropLeft, nt = st.dragCropTop;
      var nw = st.dragCropW, nh = st.dragCropH;
      if (edge.includes('r')) nw = Math.max(4, st.dragCropW + dx);
      if (edge.includes('l')) { nw = Math.max(4, st.dragCropW - dx); nl = st.dragCropLeft + st.dragCropW - nw; }
      if (edge.includes('b')) nh = Math.max(4, st.dragCropH + dy);
      if (edge.includes('t')) { nh = Math.max(4, st.dragCropH - dy); nt = st.dragCropTop + st.dragCropH - nh; }
      st.cropLeft = nl; st.cropTop = nt; st.cropW = nw; st.cropH = nh;
      renderCrop();
      e.preventDefault();
    }
  }

  function onUp() {
    if (st.dragMode) {
      cropBox.classList.remove('dragging');
      if (st.cropMode) renderCrop();
      st.dragMode = null; st.resizeEdge = null;
    }
  }

  viewport.addEventListener('mousedown', onDown);
  window.addEventListener('mousemove', onMove);
  window.addEventListener('mouseup', onUp);

  viewport.addEventListener('touchstart', function(e) {
    var t = e.touches[0]; if (!t) return;
    onDown({ button: 0, clientX: t.clientX, clientY: t.clientY, preventDefault: function() {} });
  }, { passive: true });
  var touchMoveH = function(e) {
    var t = e.touches[0]; if (!t || !st.dragMode) return;
    onMove({ clientX: t.clientX, clientY: t.clientY, preventDefault: function() { e.preventDefault(); } });
  };
  window.addEventListener('touchmove', touchMoveH, { passive: false });
  var touchEndH = function() { onUp(); };
  window.addEventListener('touchend', touchEndH, { passive: true });

  viewport.addEventListener('wheel', function(e) {
    e.preventDefault();
    var vp = getVp();
    var p = vpCoords(e);
    var oldScale = st.scale;
    var step = e.deltaY > 0 ? -0.01 : 0.01;
    var newScale = clamp(oldScale + step, 0.2, 3);
    var ratio = newScale / oldScale;
    st.scale = newScale;
    st.tx = (1 - ratio) * (p.x - vp.w / 2) + st.tx * ratio;
    st.ty = (1 - ratio) * (p.y - vp.h / 2) + st.ty * ratio;
    zoomSlider.value = st.scale;
    applyTransform();
    if (st.cropMode) renderCrop();
  }, { passive: false });

  zoomSlider.addEventListener('input', function() {
    st.scale = parseFloat(this.value);
    applyTransform();
    if (st.cropMode) renderCrop();
  });
  var modalEl = ov.querySelector('.crop-modal');
  var resizeHandle = ov.querySelector('#cropResizeHandle');
  var resizeState = null;

  function resizeStart(e) {
    if (e.button !== undefined && e.button !== 0) return;
    resizeState = {
      startX: e.clientX, startY: e.clientY,
      startW: modalEl.offsetWidth, startH: modalEl.offsetHeight,
    };
    resizeHandle.classList.add('dragging');
    if (st.cropMode) cropBox.classList.add('resizing');
    e.preventDefault();
  }

  function resizeMove(e) {
    if (!resizeState) return;
    var dx = e.clientX - resizeState.startX;
    var dy = e.clientY - resizeState.startY;
    var minW = window.innerWidth < 600 ? Math.min(320, window.innerWidth * 0.94) : 480;
    var minH = window.innerHeight < 600 ? 260 : 360;
    var newW = Math.max(minW, Math.min(resizeState.startW + dx, window.innerWidth * 0.96));
    var newH = Math.max(minH, Math.min(resizeState.startH + dy, window.innerHeight * 0.96));
    modalEl.style.width = newW + 'px';
    modalEl.style.height = newH + 'px';
    if (st.cropMode) renderCrop();
    e.preventDefault();
  }

  function resizeEnd() {
    if (resizeState) {
      resizeHandle.classList.remove('dragging');
      if (st.cropMode) { cropBox.classList.remove('resizing'); renderCrop(); }
      resizeState = null;
    }
  }

  resizeHandle.addEventListener('mousedown', resizeStart);
  window.addEventListener('mousemove', resizeMove);
  window.addEventListener('mouseup', resizeEnd);

  resizeHandle.addEventListener('touchstart', function(e) {
    var t = e.touches[0]; if (!t) return;
    resizeStart({ button: 0, clientX: t.clientX, clientY: t.clientY, preventDefault: function() {} });
  }, { passive: true });
  var resizeTouchMove = function(e) {
    var t = e.touches[0]; if (!t || !resizeState) return;
    resizeMove({ clientX: t.clientX, clientY: t.clientY, preventDefault: function() { e.preventDefault(); } });
  };
  window.addEventListener('touchmove', resizeTouchMove, { passive: false });
  var resizeTouchEnd = function() { resizeEnd(); };
  window.addEventListener('touchend', resizeTouchEnd, { passive: true });

  function teardown() {
    document.body.style.overflow = '';
    img.onload = null; img.onerror = null;
    window.removeEventListener('mousemove', onMove);
    window.removeEventListener('mouseup', onUp);
    window.removeEventListener('touchmove', touchMoveH);
    window.removeEventListener('touchend', touchEndH);
    window.removeEventListener('mousemove', resizeMove);
    window.removeEventListener('mouseup', resizeEnd);
    window.removeEventListener('touchmove', resizeTouchMove);
    window.removeEventListener('touchend', resizeTouchEnd);
    window.removeEventListener('keydown', onKeyDown);
  }

  ov.querySelector('#cropReset').onclick = function() {
    st.scale = 1; st.tx = 0; st.ty = 0; zoomSlider.value = 1;
    applyTransform();
    activateCrop('free');
  };

  ov.querySelector('#cropConfirm').onclick = function() {
    var btn = this;
    if (btn.disabled) return;
    btn.disabled = true; btn.classList.add('loading');

    function restoreBtn() {
      btn.disabled = false; btn.classList.remove('loading');
    }

    var vp = getVp();
    var left = st.cropLeft, top = st.cropTop;
    var boxW = st.cropW, boxH = st.cropH;
    if (boxW < 2 || boxH < 2) { restoreBtn(); showToast('裁剪区域过小', 'error'); return; }

    var W = st.imgW, H = st.imgH;
    var scale = st.scale, tx = st.tx, ty = st.ty;
    var imgLeft = vp.w / 2 + tx - W * scale / 2;
    var imgTop = vp.h / 2 + ty - H * scale / 2;

    var sx = Math.max(0, (left - imgLeft) / scale);
    var sy = Math.max(0, (top - imgTop) / scale);
    var sw = Math.min(boxW / scale, W - sx);
    var sh = Math.min(boxH / scale, H - sy);
    if (sw < 1 || sh < 1) { restoreBtn(); showToast('裁剪区域过小', 'error'); return; }

    var outW = Math.round(sw), outH = Math.round(sh);
    var canvas = document.createElement('canvas');
    canvas.width = outW; canvas.height = outH;
    var ctx = canvas.getContext('2d');
    try { ctx.drawImage(img, sx, sy, sw, sh, 0, 0, outW, outH); }
    catch (e) { restoreBtn(); console.error('canvas drawImage 失败', e); showToast('图片处理出错', 'error'); return; }

    var ext = (filename.split('.').pop() || 'png').toLowerCase();
    var mime = {'png':'image/png','webp':'image/webp','gif':'image/gif'}[ext] || 'image/jpeg';

    function onCropDone(blob) {
      if (blob) { teardown(); document.body.removeChild(ov); if (callback) callback(blob); return; }
      if (mime !== 'image/png') {
        canvas.toBlob(function(blob2) {
          if (blob2) { teardown(); document.body.removeChild(ov); if (callback) callback(blob2); return; }
          restoreBtn(); console.error('toBlob 两次均失败'); showToast('图片处理失败，请重试', 'error');
        }, 'image/png');
      } else {
        restoreBtn(); console.error('toBlob 返回 null'); showToast('图片处理失败，请重试', 'error');
      }
    }

    canvas.toBlob(onCropDone, mime);
  };

  ov.querySelector('#cropCancel').onclick = function() {
    teardown();
    document.body.removeChild(ov);
    if (callback) callback(null);
  };
  ov.querySelector('#cropModalClose').onclick = function() {
    teardown();
    document.body.removeChild(ov);
    if (callback) callback(null);
  };
  ov.addEventListener('click', function(e) {
    if (e.target === ov) { teardown(); document.body.removeChild(ov); if (callback) callback(null); }
  });

  function onKeyDown(e) {
    if (e.key === 'Escape') { teardown(); document.body.removeChild(ov); if (callback) callback(null); }
  }
  window.addEventListener('keydown', onKeyDown);

  document.body.style.overflow = 'hidden';
  ov.style.display = 'flex';
}

function bindCropUpload(inputId, uploadUrl, fieldSelector, previewSelector, onSuccess) {
  var input = document.getElementById(inputId);
  if (!input) return;
  input.addEventListener('change', function() {
    var file = this.files[0];
    if (!file) return;
    this.value = '';
    openCropModal(file, function(cropped) {
      if (!cropped) return;
      var formData = new FormData();
      formData.append('file', cropped, file.name);
      showToast('上传中…');
      fetch(uploadUrl, {
        method:'POST',
        headers: { 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').getAttribute('content') },
        body: formData
      })
      .then(function(r) {
        if (!r.ok) return r.json().then(function(d) { throw new Error(d.error || '上传失败'); });
        return r.json();
      })
      .then(function(data) {
        if (fieldSelector) {
          document.querySelector(fieldSelector).value = data.url.replace('/static/', '');
        }
        if (previewSelector) {
          var el = document.querySelector(previewSelector);
          if (el) { el.innerHTML = '<img src="' + data.url + '" alt="crop">'; el.style.display = 'block'; }
          var upload = input.closest('[class*="-upload"]');
          if (upload) upload.classList.add('has-image');
          var placeholder = input.closest('[class*="-upload"]') ? input.closest('[class*="-upload"]').querySelector('[class*="placeholder"]') : null;
          if (placeholder) placeholder.style.display = 'none';
        }
        if (onSuccess) onSuccess(data, input);
        showToast('上传成功', 'success');
      })
      .catch(function(err) { showToast(err.message || '上传失败', 'error'); });
    });
  });
}

// ── 自定义下拉框 (glow-select) 驱动 ────────────
function toggleGlowSelect(t){
  var r=t.parentNode,u=r.classList.contains('is-open');
  if(u){r.classList.remove('is-open');return;}
  if(!r.getAttribute('data-multiple')){
    document.querySelectorAll('.glow-select-wrap.is-open').forEach(function(w){w.classList.remove('is-open')});
  }
  if(r.getAttribute('data-multiple')!==null){
    var c=r.querySelectorAll('.glow-select-option.is-selected').length;
    r.querySelector('.glow-select-value').textContent='已选 '+c+' 项';
  }
  r.classList.add('is-open');
}
document.addEventListener('click',function(e){
  var o=e.target.closest('.glow-select-option');
  if(o){
    var w=o.closest('.glow-select-wrap');if(!w)return;
    var v=o.getAttribute('data-value');
    if(w.getAttribute('data-multiple')!==null){
      o.classList.toggle('is-selected');
      var sel=w.querySelector('select');
      if(sel){
        for(var i=0;i<sel.options.length;i++){
          sel.options[i].selected=(sel.options[i].value===v)?!sel.options[i].selected:sel.options[i].selected;
        }
        sel.dispatchEvent(new Event('change',{bubbles:true}));
      }
      var c=w.querySelectorAll('.glow-select-option.is-selected').length;
      w.querySelector('.glow-select-value').textContent='已选 '+c+' 项';
    }else{
      var t=w.querySelector('.glow-select-trigger');
      if(t)t.querySelector('.glow-select-value').textContent=o.textContent;
      w.querySelectorAll('.glow-select-option').forEach(function(x){x.classList.toggle('is-selected',x===o)});
      w.classList.remove('is-open');
      var n=w.querySelector('select');
      if(n){n.value=v;n.dispatchEvent(new Event('change',{bubbles:true}))}
    }
    return;
  }
  if(!e.target.closest('.glow-select-wrap')){
    document.querySelectorAll('.glow-select-wrap.is-open').forEach(function(w){w.classList.remove('is-open')});
  }
});

// ── 全局弹窗 ──────────────────────────────────
(function() {
  if (document.querySelector('.glow-modal-overlay')) return;
  var overlay = document.createElement('div');
  overlay.className = 'glow-modal-overlay';
  overlay.innerHTML =
    '<div class="glow-modal">' +
      '<h4 id="gmd-title"></h4>' +
      '<p id="gmd-msg"></p>' +
      '<input class="glow-modal-input" id="gmd-input" style="display:none">' +
      '<div class="glow-modal-actions" id="gmd-actions"></div>' +
    '</div>';
  overlay.addEventListener('click', function(e) {
    if (e.target === overlay) overlay.style.display = 'none';
  });
  document.body.appendChild(overlay);

  var titleEl = document.getElementById('gmd-title');
  var msgEl = document.getElementById('gmd-msg');
  var inputEl = document.getElementById('gmd-input');
  var actionsEl = document.getElementById('gmd-actions');

  function hideOverlay() {
    overlay.style.display = 'none';
  }

  window.alert = function(msg) {
    titleEl.textContent = '提示';
    msgEl.innerHTML = msg;
    actionsEl.innerHTML = '<button class="btn btn-primary" style="flex:1;justify-content:center">确定</button>';
    actionsEl.querySelector('button').onclick = hideOverlay;
    overlay.style.display = 'flex';
  };

  window.confirm = function(msg, cb) {
    if (typeof cb !== 'function') return true;
    titleEl.textContent = '确认操作';
    msgEl.innerHTML = msg;
    actionsEl.innerHTML =
      '<button class="btn btn-ghost" style="flex:1;justify-content:center">取消</button>' +
      '<button class="btn btn-primary" style="flex:1;justify-content:center">确定</button>';
    var btns = actionsEl.querySelectorAll('button');
    btns[0].onclick = function() { hideOverlay(); cb(false); };
    btns[1].onclick = function() { hideOverlay(); cb(true); };
    overlay.style.display = 'flex';
  };

  window.prompt = function(msg, def) {
    titleEl.textContent = '输入';
    msgEl.innerHTML = msg;
    inputEl.style.display = 'block';
    inputEl.value = def || '';
    actionsEl.innerHTML =
      '<button class="btn btn-ghost" style="flex:1;justify-content:center">取消</button>' +
      '<button class="btn btn-primary" style="flex:1;justify-content:center">确定</button>';
    var btns = actionsEl.querySelectorAll('button');
    btns[0].onclick = function() { hideOverlay(); inputEl.style.display = 'none'; };
    btns[1].onclick = function() { hideOverlay(); inputEl.style.display = 'none'; };
    overlay.style.display = 'flex';
    return def || '';
  };
})();

function showConfirm(msg, cb) {
  var overlay = document.querySelector('.glow-modal-overlay');
  if (!overlay) { if (cb) cb(true); return; }
  document.getElementById('gmd-input').style.display = 'none';
  document.getElementById('gmd-title').textContent = '确认操作';
  document.getElementById('gmd-msg').innerHTML = msg;
  var actionsEl = document.getElementById('gmd-actions');
  actionsEl.innerHTML =
    '<button class="btn btn-ghost" style="flex:1;justify-content:center">取消</button>' +
    '<button class="btn btn-primary" style="flex:1;justify-content:center">确定</button>';
  var btns = actionsEl.querySelectorAll('button');
  btns[0].onclick = function() { overlay.style.display = 'none'; if (cb) cb(false); };
  btns[1].onclick = function() { overlay.style.display = 'none'; if (cb) cb(true); };
  overlay.style.display = 'flex';
}
