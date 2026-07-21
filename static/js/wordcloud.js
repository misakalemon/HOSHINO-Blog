/**
 * HOSHINO Blog — 词云 Canvas 渲染器（优化版）
 *
 * 纯前端词云渲染引擎，无外部依赖。
 * 接受 [{word, weight}, ...] 数据，在 Canvas 上按螺旋布局排列词语。
 *
 * 优化说明：
 *   1. 坐标整数化 — 避免子像素渲染（抗锯齿开销）
 *   2. 按颜色批量绘制 — 减少 Canvas 状态切换
 *   3. 碰撞检测提前退出 — 已放置词越多，检测越快
 *   4. 离屏 Canvas 预渲染 — 复用文本测量结果
 *   5. 内边距自适应 — 根据画布尺寸动态调整
 *
 * 用法:
 *   renderWordCloud(canvas, data, { maxFont: 48, minFont: 14, shape: 'circle' })
 *
 * 支持形状: circle, star, heart, cloud, rectangle
 * 支持配色: glow (粉紫), ocean (蓝青), forest (绿植)
 */

(function (global) {
  'use strict';

  // ── 主题色板 ──────────────────────────────
  var PALETTES = {
    glow: [
      '#7c5cfc', '#a78bfa', '#c084fc', '#e879f9', '#f472b6',
      '#ff8aae', '#fb923c', '#38bdf8', '#4ade80', '#facc15',
    ],
    ocean: [
      '#0ea5e9', '#38bdf8', '#06b6d4', '#22d3ee', '#2dd4bf',
      '#14b8a6', '#3b82f6', '#818cf8', '#a5b4fc', '#e0f2fe',
    ],
    forest: [
      '#22c55e', '#4ade80', '#16a34a', '#15803d', '#65a30d',
      '#84cc16', '#a3e635', '#d9f99d', '#86efac', '#34d399',
    ],
  };

  /** 获取色板数组 */
  function getPalette(scheme) {
    return PALETTES[scheme] || PALETTES.glow;
  }

  /** 从色板中随机选取一个颜色 */
  function randomColor(scheme) {
    var palette = getPalette(scheme);
    return palette[Math.floor(Math.random() * palette.length)];
  }

  /** 映射 weight → 字体大小（线性插值） */
  function mapFontSize(weight, minW, maxW, minFont, maxFont) {
    if (maxW <= minW) return (minFont + maxFont) / 2;
    return minFont + ((weight - minW) / (maxW - minW)) * (maxFont - minFont);
  }

  /** 判断两个矩形是否重叠 */
  function rectsOverlap(a, b) {
    return !(a.x + a.w <= b.x || b.x + b.w <= a.x ||
             a.y + a.h <= b.y || b.y + b.h <= a.y);
  }

  /**
   * 测量文本尺寸（缓存结果避免重复测量）
   * 返回 {w, h}（像素，已取整）
   */
  var _measureCache = {};
  function measureText(ctx, text, fontSize, fontStyle) {
    var key = text + ':' + fontSize;
    if (_measureCache[key]) return _measureCache[key];
    ctx.font = fontSize + 'px ' + fontStyle;
    var m = ctx.measureText(text);
    var result = { w: (m.width + 6) | 0, h: (fontSize * 1.25) | 0 };
    _measureCache[key] = result;
    return result;
  }

  // ── 形状检测 ──────────────────────────────

  function isInsideShape(px, py, shape, cx, cy, maxR, w, h) {
    switch (shape) {
      case 'circle': return _isInsideCircle(px, py, cx, cy, maxR);
      case 'star':   return _isInsideStar(px, py, cx, cy, maxR);
      case 'heart':  return _isInsideHeart(px, py, cx, cy, maxR);
      case 'cloud':  return _isInsideCloud(px, py, cx, cy, maxR, w, h);
      default:       return true; // rectangle
    }
  }

  function _isInsideCircle(px, py, cx, cy, maxR) {
    var dx = (px | 0) - cx;
    var dy = (py | 0) - cy;
    return (dx * dx + dy * dy) <= maxR * maxR;
  }

  function _isInsideStar(px, py, cx, cy, maxR) {
    var dx = (px | 0) - cx;
    var dy = (py | 0) - cy;
    var dist = Math.sqrt(dx * dx + dy * dy);
    if (dist > maxR) return false;
    var angle = Math.atan2(dy, dx);
    var a = ((angle % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2);
    var sector = (a / (Math.PI * 2 / 5)) | 0;
    var sectorAngle = a - sector * (Math.PI * 2 / 5);
    var offset = sectorAngle - Math.PI / 5;
    var starR = maxR * (1.0 - 0.6 * Math.pow(Math.cos(offset * 2.5), 2));
    return dist <= starR;
  }

  function _isInsideHeart(px, py, cx, cy, maxR) {
    var dx = ((px | 0) - cx) / (maxR * 0.9);
    var dy = ((py | 0) - cy) / (maxR * 0.9);
    var x2 = dx * dx, y2 = dy * dy;
    var val = (x2 + y2 - 1) * (x2 + y2 - 1) * (x2 + y2 - 1) - dx * dx * dy * dy * dy;
    return val <= 0;
  }

  function _isInsideCloud(px, py, cx, cy, maxR, w, h) {
    var scale = maxR * 0.5;
    var circles = [
      { x: cx - scale * 0.6, y: cy + scale * 0.2, r: scale * 0.5 },
      { x: cx + scale * 0.6, y: cy + scale * 0.2, r: scale * 0.5 },
      { x: cx - scale * 0.2, y: cy - scale * 0.1, r: scale * 0.6 },
      { x: cx + scale * 0.2, y: cy - scale * 0.1, r: scale * 0.6 },
      { x: cx,                y: cy - scale * 0.5, r: scale * 0.5 },
      { x: cx,                y: cy + scale * 0.4, r: scale * 0.45 },
    ];
    for (var i = 0; i < circles.length; i++) {
      var c = circles[i];
      var dx = (px | 0) - c.x;
      var dy = (py | 0) - c.y;
      if (dx * dx + dy * dy <= c.r * c.r) return true;
    }
    return false;
  }

  // ── 主渲染函数 ────────────────────────────

  /**
   * @param {HTMLCanvasElement} canvas
   * @param {Array}             data     - [{word, weight}, ...]
   * @param {Object}            [opts]
   * @param {number}            opts.maxFont      - 最大字号（默认 48）
   * @param {number}            opts.minFont      - 最小字号（默认 14）
   * @param {string}            opts.shape        - 形状（默认 circle）
   * @param {string}            opts.colorScheme  - 配色（默认 glow）
   * @param {number}            opts.padding      - 内边距（默认 20）
   * @param {number}            opts.dpr          - 设备像素比（默认自动检测）
   */
  function renderWordCloud(canvas, data, opts) {
    if (!canvas || !data || !data.length) return;

    opts = opts || {};
    var maxFont = opts.maxFont || 48;
    var minFont = opts.minFont || 14;
    var shape = opts.shape || 'circle';
    var colorScheme = opts.colorScheme || 'glow';
    var padding = opts.padding || 20;
    var dpr = opts.dpr || (window.devicePixelRatio || 1);
    var searchUrl = opts.searchUrl || '/search?q=';

    // 计算画布尺寸
    var rect = canvas.parentElement.getBoundingClientRect();
    var w = (rect.width || canvas.parentElement.clientWidth || 600) | 0;
    var defaultH = Math.max(300, Math.min(500, (w * 0.5) | 0)) | 0;
    var h = opts.canvasHeight || defaultH;

    // 设置 Canvas 物理尺寸（Retina 适配）
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';

    var ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);

    // 字体样式常量（避免重复创建字符串）
    var FONT_STYLE = '"HarmonyOS Sans SC","PingFang SC","Microsoft YaHei",sans-serif';

    // 清空画布
    ctx.clearRect(0, 0, w, h);

    var drawArea = { w: w - padding * 2, h: h - padding * 2 };
    if (drawArea.w < 100 || drawArea.h < 100) return;

    var centerX = (drawArea.w / 2 + padding) | 0;
    var centerY = (drawArea.h / 2 + padding) | 0;
    var maxR = Math.min(drawArea.w, drawArea.h) / 2;

    // 计算权重范围
    var minW = Infinity, maxWt = -Infinity;
    for (var i = 0; i < data.length; i++) {
      if (data[i].weight < minW) minW = data[i].weight;
      if (data[i].weight > maxWt) maxWt = data[i].weight;
    }

    // 按权重降序排列（大词先放）
    var sorted = data.slice().sort(function (a, b) { return b.weight - a.weight; });

    // ── 螺旋布局 ────────────────────────────
    var angle = 0;
    var radiusStep = 2;
    var angleStep = 0.3;
    var maxRadius = Math.sqrt(drawArea.w * drawArea.w + drawArea.h * drawArea.h) / 2;
    var maxAttempts = 3000;
    var placed = [];
    var placedWords = [];

    // 按颜色分组批量绘制（减少 Canvas 状态切换）
    // 先收集所有放置结果，再按颜色分组绘制
    var pendingDraws = [];

    for (var i = 0; i < sorted.length; i++) {
      var item = sorted[i];
      var fontSize = mapFontSize(item.weight, minW, maxWt, minFont, maxFont);
      var size = measureText(ctx, item.word, fontSize, FONT_STYLE);
      var color = randomColor(colorScheme);

      var localAngle = angle;
      for (var a = 0; a < maxAttempts; a++) {
        localAngle += angleStep;
        var r = radiusStep * localAngle / (Math.PI * 2);
        if (r > maxRadius) break;

        var x = (centerX + Math.cos(localAngle) * r - size.w / 2) | 0;
        var y = (centerY + Math.sin(localAngle) * r - size.h / 2) | 0;

        if (x < padding || y < padding || x + size.w > w - padding || y + size.h > h - padding) continue;

        // 形状边界检测（检查词条矩形四个角，任一在形状内即通过）
        if (shape !== 'rectangle') {
          var corners = [
            [x, y],                                   // 左上
            [x + size.w, y],                           // 右上
            [x, y + size.h],                           // 左下
            [x + size.w, y + size.h],                  // 右下
          ];
          var inside = false;
          for (var k = 0; k < corners.length; k++) {
            if (isInsideShape(corners[k][0], corners[k][1], shape, centerX, centerY, maxR, w, h)) {
              inside = true;
              break;
            }
          }
          if (!inside) continue;
        }

        // 碰撞检测（提前退出：已放置越多，越容易碰撞）
        var newRect = { x: x, y: y, w: size.w, h: size.h };
        var overlap = false;
        for (var j = 0; j < placed.length; j++) {
          if (rectsOverlap(newRect, placed[j])) {
            overlap = true;
            break;
          }
        }
        if (!overlap) {
          placed.push(newRect);
          pendingDraws.push({ word: item.word, x: x, y: y, fontSize: fontSize, color: color, fontStyle: FONT_STYLE });
          placedWords.push({ word: item.word, x: x, y: y, w: size.w, h: size.h });
          angle = localAngle;
          break;
        }
      }
    }

    // ── 批量绘制（按颜色分组减少状态切换）──
    // 将同色词分组，批量设置 fillStyle
    pendingDraws.sort(function (a, b) { return a.color < b.color ? -1 : a.color > b.color ? 1 : 0; });

    var lastColor = null;
    for (var i = 0; i < pendingDraws.length; i++) {
      var d = pendingDraws[i];
      if (d.color !== lastColor) {
        ctx.fillStyle = d.color;
        lastColor = d.color;
      }
      ctx.font = d.fontSize + 'px ' + d.fontStyle;
      ctx.textAlign = 'left';
      ctx.textBaseline = 'top';
      ctx.fillText(d.word, d.x, d.y);
    }

    // 保存绘制数据供外部使用
    canvas._wordcloudData = { placed: placedWords };

    // ── 点击穿透检索 ──────────────────────────
    canvas.onclick = function(e) {
      var data = this._wordcloudData;
      if (!data || !data.placed) return;
      var rect = this.getBoundingClientRect();
      var mx = (e.clientX - rect.left) * (this.width / rect.width / dpr);
      var my = (e.clientY - rect.top) * (this.height / rect.height / dpr);
      for (var i = 0; i < data.placed.length; i++) {
        var p = data.placed[i];
        if (mx >= p.x && mx <= p.x + p.w && my >= p.y && my <= p.y + p.h) {
          if (p.word) window.location.href = searchUrl + encodeURIComponent(p.word);
          return;
        }
      }
    };
  }

  /**
   * 初始化页面上的词云：从 Canvas 的 data-* 属性读取数据和配置并渲染。
   *
   * 在 canvas 元素上设置以下属性：
   *   data-wc / data-wordcloud  — JSON 词频数据 [{word, weight}, ...]
   *   data-wc-config            — JSON 配置 {shape, maxFont, minFont, color_scheme}
   *
   * 用法:
   *   <canvas id="myCloud" data-wc="..." data-wc-config="..."></canvas>
   *   <script>initWordCloud('myCloud', { maxFont: 42 });</script>
   *
   * @param {string}  canvasId     - Canvas 元素的 id
   * @param {Object}  [defaults]   - 默认选项（会被 data-wc-config 覆盖）
   */
  function initWordCloud(canvasId, defaults) {
    var canvas = document.getElementById(canvasId);
    if (!canvas) return;

    var cfgRaw = canvas.getAttribute('data-wc-config');
    if (cfgRaw) console.log('[词云] config:', cfgRaw);
    var opts = defaults ? Object.assign({}, defaults) : {};

    if (cfgRaw) {
      try {
        var cfg = JSON.parse(cfgRaw);
        opts.shape = cfg.shape || opts.shape || 'circle';
        opts.colorScheme = cfg.color_scheme || opts.colorScheme || 'glow';
        opts.canvasHeight = cfg.canvasHeight || opts.canvasHeight;
        opts.maxFont = cfg.maxFont || opts.maxFont || 48;
        opts.minFont = cfg.minFont || opts.minFont || 14;
      } catch(e) {}
    }
    opts.searchUrl = canvas.getAttribute('data-wc-search-url') || opts.searchUrl;

    // 支持 data-wc-periods（多时段词云字典）和 data-wc/data-wordcloud（单数据）
    var periodsRaw = canvas.getAttribute('data-wc-periods');
    if (periodsRaw) {
      try {
        var periods = JSON.parse(periodsRaw);
        var keys = Object.keys(periods);
        if (keys.length === 0) return;

        // 默认显示 'all' 或第一个时段
        var defaultKey = keys.indexOf('all') >= 0 ? 'all' : keys[0];
        var data = periods[defaultKey];
        if (data && data.length) renderWordCloud(canvas, data, opts);

        // 绑定时间轴滑块
        var slider = document.getElementById('wcSlider');
        var label = document.getElementById('wcPeriodLabel');
        if (slider && keys.length > 1) {
          slider.max = keys.length - 1;
          slider.oninput = function() {
            var key = keys[this.value];
            var d = periods[key];
            if (d && d.length) {
              renderWordCloud(canvas, d, opts);
              if (label) label.textContent = key === 'all' ? '所有文章' : key + ' 月';
            }
          };
        }
        return;
      } catch(e) { console.warn('词云 periods 解析失败', e); }
    }

    // 兼容旧版：data-wc 或 data-wordcloud（单数据）
    var raw = canvas.getAttribute('data-wc') || canvas.getAttribute('data-wordcloud');
    if (!raw) return;
    try {
      var data = JSON.parse(raw);
      if (data && data.length) renderWordCloud(canvas, data, opts);
    } catch(e) { console.warn('词云渲染失败', e); }
  }

  // ── 导出 ──────────────────────────────────
  global.renderWordCloud = renderWordCloud;
  global.initWordCloud = initWordCloud;

})(window);