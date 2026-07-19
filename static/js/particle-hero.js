/**
 * particle-hero.js — WebGL 1.0 粒子画像引擎
 *
 * 使用 GPU (gl.POINTS) 渲染 2 万粒子，CPU 运行物理模拟。
 * 背景浮游光点（motes）在独立的 2D Canvas 叠加层上绘制。
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
 *   - WebGL 硬件加速渲染（vs Canvas 2D CPU 渲染）
 *   - 单次 drawcall 提交所有粒子（gl.POINTS）
 *   - 移动端粒子数减半
 *   - DPR 上限 1.6
 */
(function () {
  var canvas = document.getElementById('particleCanvas');
  if (!canvas) return;
  var imgUrl = canvas.getAttribute('data-src');
  if (!imgUrl) return;

  // ── WebGL 初始化 ──────────────────────────────
  var gl = canvas.getContext('webgl', { alpha: true, antialias: false, premultipliedAlpha: true })
        || canvas.getContext('experimental-webgl', { alpha: true, antialias: false, premultipliedAlpha: true });
  if (!gl) {
    var el = document.getElementById('particleLoader');
    if (el) el.textContent = 'WebGL 不可用';
    return;
  }

  // 顶点着色器
  var VS = [
    'attribute vec2 aPos;',
    'attribute vec3 aColor;',
    'attribute float aSize;',
    'attribute float aTw;',
    'attribute float aPh;',
    'uniform vec2 uRes;',
    'uniform float uDPR;',
    'uniform float uTime;',
    'varying vec3 vColor;',
    'varying float vAlpha;',
    'void main(){',
    '  vec2 c=aPos/uRes*2.0-1.0;',
    '  gl_Position=vec4(c.x,-c.y,0.0,1.0);',
    '  gl_PointSize=aSize*uDPR;',
    '  vColor=aColor;',
    '  vAlpha=mix(1.0,0.55+0.45*sin(uTime*0.09+aPh*3.0),aTw);',
    '}'
  ].join('\n');

  // 片元着色器
  var FS = [
    'precision mediump float;',
    'varying vec3 vColor;',
    'varying float vAlpha;',
    'void main(){',
    '  vec2 d=gl_PointCoord-vec2(0.5);',
    '  float r=length(d);',
    '  if(r>0.5)discard;',
    '  float a=vAlpha*(1.0-smoothstep(0.25,0.5,r));',
    '  gl_FragColor=vec4(vColor*a,a);',
    '}'
  ].join('\n');

  function compileShader(src, type) {
    var s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      console.error('Shader compile error:', gl.getShaderInfoLog(s));
      gl.deleteShader(s);
      return null;
    }
    return s;
  }

  var vs = compileShader(VS, gl.VERTEX_SHADER);
  var fs = compileShader(FS, gl.FRAGMENT_SHADER);
  if (!vs || !fs) return;

  var prog = gl.createProgram();
  gl.attachShader(prog, vs);
  gl.attachShader(prog, fs);
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
    console.error('Program link error:', gl.getProgramInfoLog(prog));
    return;
  }
  gl.useProgram(prog);

  var loc = {
    aPos: gl.getAttribLocation(prog, 'aPos'),
    aColor: gl.getAttribLocation(prog, 'aColor'),
    aSize: gl.getAttribLocation(prog, 'aSize'),
    aTw: gl.getAttribLocation(prog, 'aTw'),
    aPh: gl.getAttribLocation(prog, 'aPh'),
    uRes: gl.getUniformLocation(prog, 'uRes'),
    uDPR: gl.getUniformLocation(prog, 'uDPR'),
    uTime: gl.getUniformLocation(prog, 'uTime'),
  };

  // 启用属性（指针绑定推迟到 buffer 创建后）
  gl.enableVertexAttribArray(loc.aPos);
  gl.enableVertexAttribArray(loc.aColor);
  gl.enableVertexAttribArray(loc.aSize);
  gl.enableVertexAttribArray(loc.aTw);
  gl.enableVertexAttribArray(loc.aPh);

  // 插槽布局常量
  var F = 8, STRIDE = F * 4;

  gl.enable(gl.BLEND);
  gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);

  // ── 2D 叠加 Canvas（背景浮游光点） ──────────────
  var moteCanvas = document.createElement('canvas');
  moteCanvas.id = 'moteCanvas';
  moteCanvas.style.cssText = 'position:fixed;inset:0;width:100%;height:100%;pointer-events:none;z-index:1;';
  canvas.parentNode.insertBefore(moteCanvas, canvas.nextSibling);
  var mctx = moteCanvas.getContext('2d');

  // ── 状态变量 ─────────────────────────────────
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
  var vertData = null;
  var vertexCount = 0;
  var vertexBuffer = null;
  var reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

  var MOUSE_R = 110, MOUSE_F = 1.2;
  var K_GATHER = 0.015, K_SCATTER = 0.0009;
  var DAMP_GATHER = 0.82, DAMP_SCATTER = 0.965;
  var scrollRatio = 0;

  // ── 窗口缩放 ─────────────────────────────────
  function resize() {
    DPR = Math.min(window.devicePixelRatio || 1, 1.6);
    W = window.innerWidth; H = window.innerHeight;

    canvas.width = W * DPR;
    canvas.height = H * DPR;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    gl.viewport(0, 0, canvas.width, canvas.height);

    moteCanvas.width = W * DPR;
    moteCanvas.height = H * DPR;
    moteCanvas.style.width = W + 'px';
    moteCanvas.style.height = H + 'px';
    mctx.setTransform(DPR, 0, 0, DPR, 0, 0);

    gl.uniform2f(loc.uRes, W, H);
    gl.uniform1f(loc.uDPR, DPR);

    if (sampleData) remapHomes();
    buildMotes();
  }

  // ── PNG 像素采样 ─────────────────────────────
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

  // ── 显示区域计算 ─────────────────────────────
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

  // ── 生成粒子（JS 物理对象 + GPU 顶点缓冲） ─────
  function buildParticles(intro) {
    var pts = sampleData.pts;
    var s = dispRect.s, ox = dispRect.ox, oy = dispRect.oy, psize = dispRect.psize;
    var cx = W / 2, cy = H / 2;
    var n = pts.length;

    vertData = new Float32Array(n * F);
    particles = [];

    for (var i = 0; i < n; i++) {
      var pt = pts[i];
      var ix = pt[0], iy = pt[1], ri = pt[2], gi = pt[3], bi = pt[4];
      var hx = ox + ix * s, hy = oy + iy * s;
      var x, y;
      if (intro) {
        var a = Math.random() * Math.PI * 2;
        var d = Math.max(W, H) * (0.55 + Math.random() * 0.6);
        x = cx + Math.cos(a) * d; y = cy + Math.sin(a) * d;
      } else {
        x = hx; y = hy;
      }

      var sz = psize * (0.8 + Math.random() * 0.45);
      var tw = Math.random() < 0.05 ? 1 : 0;
      var ph = Math.random() * Math.PI * 2;

      particles.push({
        x: x, y: y, hx: hx, hy: hy, vx: 0, vy: 0,
        tw: tw, ph: ph
      });

      var base = i * F;
      vertData[base]     = x;
      vertData[base + 1] = y;
      vertData[base + 2] = ri / 255;
      vertData[base + 3] = gi / 255;
      vertData[base + 4] = bi / 255;
      vertData[base + 5] = sz;
      vertData[base + 6] = tw;
      vertData[base + 7] = ph;
    }

    vertexCount = n;

    vertexBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, vertexBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, vertData, gl.DYNAMIC_DRAW);

    // 绑定属性指针到当前 buffer
    gl.vertexAttribPointer(loc.aPos,   2, gl.FLOAT, false, STRIDE, 0);
    gl.vertexAttribPointer(loc.aColor, 3, gl.FLOAT, false, STRIDE, 8);
    gl.vertexAttribPointer(loc.aSize,  1, gl.FLOAT, false, STRIDE, 20);
    gl.vertexAttribPointer(loc.aTw,    1, gl.FLOAT, false, STRIDE, 24);
    gl.vertexAttribPointer(loc.aPh,    1, gl.FLOAT, false, STRIDE, 28);

    assemble = intro ? 0 : 1;
  }

  // ── 重映射目标位置（窗口缩放后） ────────────────
  function remapHomes() {
    computeRect();
    if (!particles.length) { buildParticles(true); return; }
    var s = dispRect.s, ox = dispRect.ox, oy = dispRect.oy, psize = dispRect.psize;
    var pts = sampleData.pts;
    for (var i = 0; i < particles.length; i++) {
      var p = particles[i];
      p.hx = ox + pts[i][0] * s;
      p.hy = oy + pts[i][1] * s;
      p.x = Math.min(Math.max(p.x, -50), W + 50);
      p.y = Math.min(Math.max(p.y, -50), H + 50);
    }
  }

  // ── 背景浮游光点 ─────────────────────────────
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

  // ── 渲染帧（WebGL 粒子 + 2D 光点） ─────────────
  function draw() {
    gl.bindBuffer(gl.ARRAY_BUFFER, vertexBuffer);
    for (var i = 0; i < particles.length; i++) {
      var p = particles[i];
      var base = i * F;
      vertData[base]     = p.x;
      vertData[base + 1] = p.y;
    }
    gl.bufferSubData(gl.ARRAY_BUFFER, 0, vertData);

    // WebGL 粒子渲染（GPU）
    gl.clearColor(0, 0, 0, 0);
    gl.uniform1f(loc.uTime, t);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.drawArrays(gl.POINTS, 0, vertexCount);

    // 2D 光点渲染（叠加 Canvas）
    mctx.clearRect(0, 0, W, H);
    mctx.globalCompositeOperation = 'lighter';
    for (var i = 0; i < motes.length; i++) {
      var m = motes[i];
      m.y += m.vy; m.sway += 0.004 * m.sp;
      m.x += Math.sin(m.sway) * 0.25;
      if (m.y < -12) { m.y = H + 12; m.x = Math.random() * W; }
      var twk = 0.5 + 0.5 * Math.sin(t * 0.02 * m.sp + m.sway * 7);
      mctx.globalAlpha = m.a * twk * 0.8;
      var sz = m.r * 5;
      mctx.drawImage(moteSprites[m.spr], m.x - sz / 2, m.y - sz / 2, sz, sz);
    }
    mctx.globalAlpha = 1;
    mctx.globalCompositeOperation = 'source-over';
  }

  // ── 物理模拟步进 ─────────────────────────────
  function step() {
    t++;
    assemble = Math.min(1, assemble + 0.003);
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

  // ── 主循环 ───────────────────────────────────
  function loop() {
    step();
    draw();
    requestAnimationFrame(loop);
  }

  // ── 事件 ─────────────────────────────────────
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

  // ── 切换散开/汇聚 ────────────────────────────
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

  function toggleScatter() {
    setMode(mode === 'gather' ? 'scatter' : 'gather');
  }

  var resizeTimer;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(resize, 250);
  });

  // ── 启动 ─────────────────────────────────────
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
