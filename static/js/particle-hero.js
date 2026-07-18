/**
 * particle-hero.js — 首页 Hero 粒子画像引擎
 *
 * 工作流程：
 *   1. 加载后台配置的 PNG 透明背景画像
 *   2. 采样 RGBA 像素 → 生成 ~2 万粒子（移动端 ~1.6 万）
 *   3. 粒子从画面外飞入 → 汇聚成画像轮廓（intro 动画）
 *   4. 鼠标交互：拨开（斥力）+ 点击涟漪（burst）
 *   5. 滚动页面 → 粒子从中心向外渐进散开
 *   6. 按钮切换「散开/汇聚」模式，散开 8s 后自动汇聚
 *   7. prefers-reduced-motion 降级：直接静态显示画像
 *
 * 性能优化：
 *   - 超屏粒子跳过绘制
 *   - 移动端粒子数减半
 *   - 无 spark 高光层（移除冗余渲染）
 *   - DPR 上限 1.6
 */
(function () {
  var canvas = document.getElementById('particleCanvas');
  if (!canvas) return;
  var imgUrl = canvas.getAttribute('data-src');
  if (!imgUrl) return;

  var ctx = canvas.getContext('2d');
  var reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

  var W = 0, H = 0, DPR = 1;
  var particles = [];
  var motes = [];
  var bursts = [];
  var mode = 'gather';
  var assemble = 0;
  var scatterTimer = null;
  var t = 0;
  var mouse = { x: -9999, y: -9999, active: false };
  var sampleData = null;
  var dispRect = null;

  var MOUSE_R = 110, MOUSE_F = 2.4;
  var K_GATHER = 0.030, K_SCATTER = 0.0009;
  var DAMP_GATHER = 0.88, DAMP_SCATTER = 0.965;
  var scrollRatio = 0;

  // ── 窗口缩放：重设 Canvas 尺寸、重映射粒子目标位置 ──
  function resize() {
    DPR = Math.min(window.devicePixelRatio || 1, 1.6);
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = W * DPR; canvas.height = H * DPR;
    canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    if (sampleData) remapHomes();
    buildMotes();
  }

  // ── PNG 像素采样：以自适应步长提取非透明像素 ──
  function sampleImage(img) {
    var iw = img.naturalWidth, ih = img.naturalHeight;
    var off = document.createElement('canvas');
    off.width = iw; off.height = ih;
    var octx = off.getContext('2d', { willReadFrequently: true });
    octx.drawImage(img, 0, 0);
    var data = octx.getImageData(0, 0, iw, ih).data;

    var fg = 0;
    for (var i = 3; i < data.length; i += 64) if (data[i] > 140) fg++;
    var totalFg = fg * 16;
    var targetParticles = window.innerWidth < 900 ? 16000 : 20000;
    var step = Math.max(2, Math.min(8, Math.round(Math.sqrt(totalFg / targetParticles))));

    var pts = [];
    for (var y = 0; y < ih; y += step) {
      var row = y * iw;
      for (var x = 0; x < iw; x += step) {
        var idx = (row + x) * 4;
        if (data[idx + 3] > 140) pts.push([x, y, data[idx], data[idx + 1], data[idx + 2]]);
      }
    }
    sampleData = { pts: pts, iw: iw, ih: ih, step: step };
  }

  // ── 计算画像在画面中的显示区域（居左/居中） ──
  function computeRect() {
    var iw = sampleData.iw, ih = sampleData.ih;
    var portrait = W >= 900;
    var maxH = H * (portrait ? 0.95 : 0.70);
    var maxW = W * (portrait ? 0.55 : 0.95);
    var s = Math.min(maxH / ih, maxW / iw);
    var dw = iw * s, dh = ih * s;
    var ox = portrait ? W * 0.55 - dw / 2 : (W - dw) / 2;
    var oy = portrait ? (H - dh) * 0.40 : H * 0.10;
    var psize = Math.max(1.6, sampleData.step * s * 0.62);
    dispRect = { s: s, ox: ox, oy: oy, psize: psize };
  }

  // ── 从采样点生成粒子数组（intro=true 时从画面外飞入） ──
  function buildParticles(intro) {
    var pts = sampleData.pts;
    var s = dispRect.s, ox = dispRect.ox, oy = dispRect.oy, psize = dispRect.psize;
    var cx = W / 2, cy = H / 2;
    particles = pts.map(function (pt) {
      var ix = pt[0], iy = pt[1], r = pt[2], g = pt[3], b = pt[4];
      var hx = ox + ix * s, hy = oy + iy * s;
      var x, y;
      if (intro) {
        var a = Math.random() * Math.PI * 2;
        var d = Math.max(W, H) * (0.55 + Math.random() * 0.6);
        x = cx + Math.cos(a) * d; y = cy + Math.sin(a) * d;
      } else {
        x = hx; y = hy;
      }
      var spark = (r > 168 && g < 125 && b < 125);
      return {
        x: x, y: y, hx: hx, hy: hy, vx: 0, vy: 0,
        s: psize * (0.8 + Math.random() * 0.45),
        c: 'rgb(' + r + ',' + g + ',' + b + ')',
        tw: Math.random() < 0.05 ? 1 : 0,
        ph: Math.random() * Math.PI * 2,
        spark: spark
      };
    });
    assemble = intro ? 0 : 1;
  }

  // ── 窗口缩放后重新映射粒子的目标位置 ──
  function remapHomes() {
    computeRect();
    if (!particles.length) { buildParticles(true); return; }
    var s = dispRect.s, ox = dispRect.ox, oy = dispRect.oy, psize = dispRect.psize;
    var pts = sampleData.pts;
    for (var i = 0; i < particles.length; i++) {
      var p = particles[i];
      p.hx = ox + pts[i][0] * s;
      p.hy = oy + pts[i][1] * s;
      p.s = psize * (0.8 + Math.random() * 0.45);
      p.x = Math.min(Math.max(p.x, -50), W + 50);
      p.y = Math.min(Math.max(p.y, -50), H + 50);
    }
  }

  // ── 背景浮游光点（环境粒子） ──
  var moteSprites = {};
  function makeSprite(color) {
    var c = document.createElement('canvas'); c.width = c.height = 64;
    var g = c.getContext('2d');
    var grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    grad.addColorStop(0, color + '1)');
    grad.addColorStop(0.35, color + '.45)');
    grad.addColorStop(1, color + '0)');
    g.fillStyle = grad; g.fillRect(0, 0, 64, 64);
    return c;
  }

  // ── 生成背景浮游光点 ──
  function buildMotes() {
    var palette = ['rgba(196,132,252,', 'rgba(255,138,174,', 'rgba(192,168,255,'];
    palette.forEach(function (c, i) { moteSprites[i] = makeSprite(c); });
    var n = Math.round(Math.min(90, W * H / 16000));
    motes = [];
    for (var i = 0; i < n; i++) {
      motes.push({
        x: Math.random() * W, y: Math.random() * H,
        r: 1.5 + Math.random() * 4.5,
        vy: -(0.06 + Math.random() * 0.22),
        sway: Math.random() * Math.PI * 2,
        sp: 0.3 + Math.random() * 0.9,
        spr: Math.floor(Math.random() * 3),
        a: 0.25 + Math.random() * 0.55
      });
    }
  }

  window.addEventListener('pointermove', function (e) {
    mouse.x = e.clientX; mouse.y = e.clientY; mouse.active = true;
  }, { passive: true });
  window.addEventListener('pointerleave', function () { mouse.active = false; });

  window.addEventListener('scroll', function () {
    var h = window.innerHeight;
    scrollRatio = Math.min(window.scrollY / h, 1.0);
    if (window.scrollY > h * 0.85) {
      canvas.style.pointerEvents = 'none';
      canvas.style.opacity = Math.max(0, 1 - (window.scrollY - h * 0.85) / (h * 0.15));
    } else {
      canvas.style.pointerEvents = 'auto';
      canvas.style.opacity = 1;
    }
  }, { passive: true });

  canvas.addEventListener('pointerdown', function (e) {
    bursts.push({ x: e.clientX, y: e.clientY, t: 0 });
  });

  // ── 切换散开/汇聚模式 ──
  function setMode(m) {
    mode = m;
    var btn = document.getElementById('btnScatter');
    if (btn) btn.textContent = m === 'gather' ? '粒子散开' : '粒子汇聚';
    clearTimeout(scatterTimer);
    if (m === 'scatter') {
      var cx = dispRect.ox + sampleData.iw * dispRect.s / 2;
      var cy = dispRect.oy + sampleData.ih * dispRect.s / 2;
      for (var i = 0; i < particles.length; i++) {
        var p = particles[i];
        var a = Math.atan2(p.y - cy, p.x - cx) + (Math.random() - 0.5) * 1.2;
        var f = 3 + Math.random() * 9;
        p.vx += Math.cos(a) * f; p.vy += Math.sin(a) * f;
      }
      scatterTimer = setTimeout(function () { setMode('gather'); }, 8000);
    }
  }

  // ── 全局暴露的切换按钮回调 ──
  function toggleScatter() {
    setMode(mode === 'gather' ? 'scatter' : 'gather');
  }

  // ── 物理模拟步进：引力/斥力/阻尼/鼠标交互/涟漪/滚动 ──
  function step() {
    t++;
    assemble = Math.min(1, assemble + 0.006);
    var ease = 1 - Math.pow(1 - assemble, 3);
    var K = mode === 'gather' ? (0.004 + (K_GATHER - 0.004) * ease) : K_SCATTER;
    var DAMP = mode === 'gather' ? DAMP_GATHER : DAMP_SCATTER;

    for (var i = bursts.length - 1; i >= 0; i--) {
      var b = bursts[i];
      b.t++;
      if (b.t > 26) { bursts.splice(i, 1); continue; }
      var R = 90 + b.t * 14, F = (26 - b.t) * 0.9;
      for (var j = 0; j < particles.length; j++) {
        var p = particles[j];
        var dx = p.x - b.x, dy = p.y - b.y;
        var d2 = dx * dx + dy * dy;
        if (d2 < R * R && d2 > 0.01) {
          var d = Math.sqrt(d2);
          var f = (1 - d / R) * F;
          p.vx += dx / d * f; p.vy += dy / d * f;
        }
      }
    }

    var mR2 = MOUSE_R * MOUSE_R;
    for (var j = 0; j < particles.length; j++) {
      var p = particles[j];
      var fx = Math.sin(t * 0.012 + p.ph) * 1.4;
      var fy = Math.cos(t * 0.010 + p.ph * 1.7) * 1.4;
      p.vx += (p.hx + fx - p.x) * K;
      p.vy += (p.hy + fy - p.y) * K;

      if (mode === 'scatter') {
        p.vx += (Math.random() - 0.5) * 0.5;
        p.vy += (Math.random() - 0.5) * 0.5;
      }
      if (scrollRatio > 0.01) {
        var cx = dispRect.ox + sampleData.iw * dispRect.s / 2;
        var cy = dispRect.oy + sampleData.ih * dispRect.s / 2;
        var sdx = p.hx - cx, sdy = p.hy - cy;
        var sd = Math.sqrt(sdx * sdx + sdy * sdy);
        if (sd > 1) {
          var f = scrollRatio * 2.0;
          p.vx += sdx / sd * f; p.vy += sdy / sd * f;
        }
      }
      if (mouse.active) {
        var dx = p.x - mouse.x, dy = p.y - mouse.y;
        var d2 = dx * dx + dy * dy;
        if (d2 < mR2 && d2 > 0.01) {
          var d = Math.sqrt(d2);
          var f = (1 - d / MOUSE_R) * MOUSE_F;
          p.vx += dx / d * f; p.vy += dy / d * f;
        }
      }
      p.vx *= DAMP; p.vy *= DAMP;
      p.x += p.vx; p.y += p.vy;
    }
  }

  // ── 渲染帧：背景浮游光点（lighter 混合）+ 粒子画像 ──
  function draw() {
    ctx.clearRect(0, 0, W, H);

    ctx.globalCompositeOperation = 'lighter';
    for (var i = 0; i < motes.length; i++) {
      var m = motes[i];
      m.y += m.vy; m.sway += 0.004 * m.sp;
      m.x += Math.sin(m.sway) * 0.25;
      if (m.y < -12) { m.y = H + 12; m.x = Math.random() * W; }
      var twk = 0.5 + 0.5 * Math.sin(t * 0.02 * m.sp + m.sway * 7);
      ctx.globalAlpha = m.a * twk * 0.8;
      var sz = m.r * 5;
      ctx.drawImage(moteSprites[m.spr], m.x - sz / 2, m.y - sz / 2, sz, sz);
    }
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = 'source-over';

    for (var i = 0; i < particles.length; i++) {
      var p = particles[i];
      if (p.x < -10 || p.x > W + 10 || p.y < -10 || p.y > H + 10) continue;
      if (p.tw) ctx.globalAlpha = 0.55 + 0.45 * Math.sin(t * 0.09 + p.ph * 3);
      ctx.fillStyle = p.c;
      ctx.fillRect(p.x, p.y, p.s, p.s);
      if (p.tw) ctx.globalAlpha = 1;
    }


  }

  // ── 主循环 ──
  function loop() {
    step();
    draw();
    requestAnimationFrame(loop);
  }

  var resizeTimer;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(resize, 250);
  });

  var img = new Image();
  img.onload = function () {
    sampleImage(img);
    resize();
    computeRect();
    buildParticles(true);
    var loader = document.getElementById('particleLoader');
    if (loader) { loader.classList.add('done'); }
    if (reduced) {
      assemble = 1;
      for (var i = 0; i < particles.length; i++) {
        particles[i].x = particles[i].hx;
        particles[i].y = particles[i].hy;
      }
      draw();
    } else {
      requestAnimationFrame(loop);
    }
  };
  img.onerror = function () {
    var el = document.getElementById('particleLoader');
    if (el) el.textContent = '画像加载失败';
  };
  img.src = imgUrl;

  window._particleToggle = toggleScatter;
})();
