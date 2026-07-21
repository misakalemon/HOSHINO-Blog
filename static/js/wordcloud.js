/**
 * HOSHINO Blog — 词云 Canvas 渲染器
 *
 * 纯前端词云渲染引擎，无外部依赖。
 * 接受 [{word, weight}, ...] 数据，在 Canvas 上按螺旋布局排列词语。
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
      '#7c5cfc', // 主紫
      '#a78bfa', // 淡紫
      '#c084fc', // 粉紫
      '#e879f9', // 品红
      '#f472b6', // 粉红
      '#ff8aae', // 樱花粉
      '#fb923c', // 暖橙
      '#38bdf8', // 天蓝
      '#4ade80', // 草绿
      '#facc15', // 浅黄
    ],
    ocean: [
      '#0ea5e9', // 天蓝
      '#38bdf8', // 淡蓝
      '#06b6d4', // 青
      '#22d3ee', // 淡青
      '#2dd4bf', // 碧蓝
      '#14b8a6', // 翡翠
      '#3b82f6', // 蓝
      '#818cf8', // 淡紫蓝
      '#a5b4fc', // 极淡紫
      '#e0f2fe', // 雪蓝
    ],
    forest: [
      '#22c55e', // 草绿
      '#4ade80', // 淡绿
      '#16a34a', // 深绿
      '#15803d', // 墨绿
      '#65a30d', // 橄榄
      '#84cc16', // 叶绿
      '#a3e635', // 嫩绿
      '#d9f99d', // 浅绿
      '#86efac', // 薄荷
      '#34d399', // 翠绿
    ],
  };

  /** 获取当前选中的色板 */
  function getPalette(scheme) {
    return PALETTES[scheme] || PALETTES.glow;
  }

  /** 从色板中随机选取一个颜色 */
  function randomColor(scheme) {
    var palette = getPalette(scheme);
    return palette[Math.floor(Math.random() * palette.length)];
  }

  /** 映射 weight → 字体大小 */
  function mapFontSize(weight, minW, maxW, minFont, maxFont) {
    if (maxW === minW) return (minFont + maxFont) / 2;
    return minFont + ((weight - minW) / (maxW - minW)) * (maxFont - minFont);
  }

  /** 判断两个矩形是否重叠 */
  function rectsOverlap(a, b) {
    return !(a.x + a.w <= b.x || b.x + b.w <= a.x ||
             a.y + a.h <= b.y || b.y + b.h <= a.y);
  }

  /**
   * 测量文本在 Canvas 中的尺寸
   * 返回 {w, h}（像素）
   */
  function measureText(ctx, text, fontSize) {
    ctx.font = fontSize + 'px "HarmonyOS Sans SC","PingFang SC","Microsoft YaHei",sans-serif';
    var m = ctx.measureText(text);
    // 实际高度 ≈ fontSize * 1.2（留一些上下间距）
    return { w: m.width + 6, h: fontSize * 1.25 };
  }

  // ── 形状检测 ──────────────────────────────

  /**
   * 判断点 (px, py) 是否在形状内部
   *
   * @param {number}  px     - 点的 x 坐标
   * @param {number}  py     - 点的 y 坐标
   * @param {string}  shape  - 形状名称
   * @param {number}  cx     - 形状中心 x
   * @param {number}  cy     - 形状中心 y
   * @param {number}  maxR   - 形状最大半径
   * @param {number}  w      - 画布宽度
   * @param {number}  h      - 画布高度
   * @returns {boolean} 点在形状内部返回 true
   */
  function isInsideShape(px, py, shape, cx, cy, maxR, w, h) {
    switch (shape) {
      case 'circle':
        return _isInsideCircle(px, py, cx, cy, maxR);
      case 'star':
        return _isInsideStar(px, py, cx, cy, maxR);
      case 'heart':
        return _isInsideHeart(px, py, cx, cy, maxR);
      case 'cloud':
        return _isInsideCloud(px, py, cx, cy, maxR, w, h);
      default: // rectangle — 不做形状裁剪
        return true;
    }
  }

  /** 圆形：距离中心小于半径 */
  function _isInsideCircle(px, py, cx, cy, maxR) {
    var dx = px + 0.5 - cx;
    var dy = py + 0.5 - cy;
    return (dx * dx + dy * dy) <= maxR * maxR;
  }

  /** 五角星形 */
  function _isInsideStar(px, py, cx, cy, maxR) {
    // 使用极坐标：计算角度，判断是否在星形区域内
    var dx = px + 0.5 - cx;
    var dy = py + 0.5 - cy;
    var dist = Math.sqrt(dx * dx + dy * dy);
    if (dist > maxR) return false;

    var angle = Math.atan2(dy, dx);
    // 五角星：5 个尖角，每个尖角 36 度，凹角 18 度
    // 映射到 [0, 2π) 并计算在哪个扇区
    var a = ((angle % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2);
    var sector = Math.floor(a / (Math.PI * 2 / 5)); // 0-4
    var sectorAngle = a - sector * (Math.PI * 2 / 5);
    // 每个扇区中心线角度
    var centerAngle = Math.PI * 2 / 10; // 18度
    var offset = sectorAngle - centerAngle;
    // 星形边界半径随角度变化
    var starR = maxR * (1.0 - 0.6 * Math.pow(Math.cos(offset * 2.5), 2));
    return dist <= starR;
  }

  /** 心形 */
  function _isInsideHeart(px, py, cx, cy, maxR) {
    var dx = (px + 0.5 - cx) / (maxR * 0.9);
    var dy = (py + 0.5 - cy) / (maxR * 0.9);
    // 心形方程: (x² + y² - 1)³ - x²·y³ <= 0
    var x2 = dx * dx;
    var y2 = dy * dy;
    var val = (x2 + y2 - 1) * (x2 + y2 - 1) * (x2 + y2 - 1) - dx * dx * dy * dy * dy;
    return val <= 0;
  }

  /** 云朵形：多个重叠圆形的并集 */
  function _isInsideCloud(px, py, cx, cy, maxR, w, h) {
    var scale = maxR * 0.5;
    // 用 6 个圆形近似云朵
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
      var dx = px + 0.5 - c.x;
      var dy = py + 0.5 - c.y;
      if (dx * dx + dy * dy <= c.r * c.r) return true;
    }
    return false;
  }

  /**
   * 在 Canvas 上渲染词云
   *
   * @param {HTMLCanvasElement} canvas   - 目标 Canvas 元素
   * @param {Array}             data     - [{word, weight}, ...] 词频数据
   * @param {Object}            [opts]   - 可选选项
   * @param {number}            opts.maxFont      - 最大字号（默认 48）
   * @param {number}            opts.minFont      - 最小字号（默认 14）
   * @param {string}            opts.shape        - 形状：circle/star/heart/cloud/rectangle（默认 circle）
   * @param {string}            opts.colorScheme  - 配色：glow/ocean/forest（默认 glow）
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

    var rect = canvas.parentElement.getBoundingClientRect();
    var w = rect.width || canvas.parentElement.clientWidth || 600;
    var h = Math.max(300, Math.min(500, w * 0.5));

    // 设置 Canvas 物理尺寸（适配 Retina）
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';

    var ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);

    // 透明背景
    ctx.clearRect(0, 0, w, h);

    var drawArea = { w: w - padding * 2, h: h - padding * 2 };
    if (drawArea.w < 100 || drawArea.h < 100) return;

    var centerX = drawArea.w / 2 + padding;
    var centerY = drawArea.h / 2 + padding;
    var maxR = Math.min(drawArea.w, drawArea.h) / 2;

    // 映射权重范围
    var minW = Infinity, maxWt = -Infinity;
    for (var i = 0; i < data.length; i++) {
      if (data[i].weight < minW) minW = data[i].weight;
      if (data[i].weight > maxWt) maxWt = data[i].weight;
    }

    // 按权重降序排列
    var sorted = data.slice().sort(function (a, b) { return b.weight - a.weight; });

    // 螺旋布局 + 绘制
    var angle = 0;
    var radiusStep = 2;
    var angleStep = 0.3;
    var maxRadius = Math.sqrt(drawArea.w * drawArea.w + drawArea.h * drawArea.h) / 2;
    var maxAttempts = 3000;
    var placed = [];

    for (var i = 0; i < sorted.length; i++) {
      var item = sorted[i];
      var fontSize = mapFontSize(item.weight, minW, maxWt, minFont, maxFont);
      var size = measureText(ctx, item.word, fontSize);
      var color = randomColor(colorScheme);
      var placedOk = false;

      // 每个词从当前角度继续螺旋
      var localAngle = angle;
      for (var a = 0; a < maxAttempts; a++) {
        localAngle += angleStep;
        var r = radiusStep * localAngle / (Math.PI * 2);

        if (r > maxRadius) break;

        var x = centerX + Math.cos(localAngle) * r - size.w / 2;
        var y = centerY + Math.sin(localAngle) * r - size.h / 2;

        if (x < padding || y < padding || x + size.w > w - padding || y + size.h > h - padding) continue;

        // 形状边界检测
        if (shape !== 'rectangle') {
          // 检查词语的四个角是否都在形状内
          var cx = size.w / 2, cy = size.h / 2;
          if (!isInsideShape(x + cx, y + cy, shape, centerX, centerY, maxR, w, h)) continue;
        }

        // 碰撞检测
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
          ctx.save();
          ctx.fillStyle = color;
          ctx.font = fontSize + 'px "HarmonyOS Sans SC","PingFang SC","Microsoft YaHei",sans-serif';
          ctx.textAlign = 'left';
          ctx.textBaseline = 'top';
          ctx.fillText(item.word, x, y);
          ctx.restore();
          angle = localAngle;
          placedOk = true;
          break;
        }
      }
    }

    // 保存绘制数据到 Canvas 元素上
    canvas._wordcloudData = { placed: placed, data: sorted };
  }

  // ── 导出 ──────────────────────────────────
  global.renderWordCloud = renderWordCloud;

})(window);