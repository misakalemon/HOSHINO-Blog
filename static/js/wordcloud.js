/**
 * HOSHINO Blog — 词云 Canvas 渲染器
 *
 * 纯前端词云渲染引擎，无外部依赖。
 * 接受 [{word, weight}, ...] 数据，在 Canvas 上按螺旋布局排列词语。
 *
 * 用法:
 *   renderWordCloud(canvas, data, { maxFont: 48, minFont: 14 })
 *
 * 配色方案:
 *   从暗色粉紫主题色板中随机选取，与站点 glow-design 风格一致。
 */

(function (global) {
  'use strict';

  // ── 主题色板 ──────────────────────────────
  var PALETTE = [
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
  ];

  // ── 工具函数 ──────────────────────────────

  /** 从色板中随机选取一个颜色 */
  function randomColor() {
    return PALETTE[Math.floor(Math.random() * PALETTE.length)];
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

  // ── 螺旋布局 ──────────────────────────────

  /**
   * 使用阿基米德螺旋算法放置词语
   * 从中心开始，按螺旋路径逐个尝试放置，直到找到不重叠的位置
   */
  function spiralLayout(items, ctx, maxW, maxH, opts) {
    var placed = [];
    var centerX = maxW / 2;
    var centerY = maxH / 2;

    // 计算权重范围
    var minW = Infinity, maxWt = -Infinity;
    for (var i = 0; i < items.length; i++) {
      if (items[i].weight < minW) minW = items[i].weight;
      if (items[i].weight > maxWt) maxWt = items[i].weight;
    }

    var minFont = opts.minFont || 14;
    var maxFont = opts.maxFont || 48;

    // 按权重降序排列（大词先放，更容易布局）
    items.sort(function (a, b) { return b.weight - a.weight; });

    for (var i = 0; i < items.length; i++) {
      var item = items[i];
      var fontSize = mapFontSize(item.weight, minW, maxWt, minFont, maxFont);
      var size = measureText(ctx, item.word, fontSize);
      var color = randomColor();
      var placed_ = false;

      // 螺旋参数
      var angle = 0;
      var radiusStep = 2;      // 每圈半径增量
      var angleStep = 0.3;     // 弧度步长
      var maxRadius = Math.sqrt(maxW * maxW + maxH * maxH) / 2;
      var maxAttempts = 3000;  // 最多尝试次数

      for (var a = 0; a < maxAttempts; a++) {
        angle += angleStep;
        var r = radiusStep * angle / (Math.PI * 2);

        if (r > maxRadius) break; // 超出画布范围

        var x = centerX + Math.cos(angle) * r - size.w / 2;
        var y = centerY + Math.sin(angle) * r - size.h / 2;

        // 边界检查
        if (x < 0 || y < 0 || x + size.w > maxW || y + size.h > maxH) continue;

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
          placed_.push(item, x, y, fontSize, color);
          break;
        }
      }
    }

    return placed_;
  }

  /**
   * 在 Canvas 上渲染词云
   *
   * @param {HTMLCanvasElement} canvas   - 目标 Canvas 元素
   * @param {Array}             data     - [{word, weight}, ...] 词频数据
   * @param {Object}            [opts]   - 可选选项
   * @param {number}            opts.maxFont  - 最大字号（默认 48）
   * @param {number}            opts.minFont  - 最小字号（默认 14）
   * @param {number}            opts.padding  - 内边距（默认 20）
   * @param {number}            opts.dpr      - 设备像素比（默认自动检测）
   */
  function renderWordCloud(canvas, data, opts) {
    if (!canvas || !data || !data.length) return;

    opts = opts || {};
    var maxFont = opts.maxFont || 48;
    var minFont = opts.minFont || 14;
    var padding = opts.padding || 20;
    var dpr = opts.dpr || (window.devicePixelRatio || 1);

    var rect = canvas.parentElement.getBoundingClientRect();
    var w = rect.width || canvas.parentElement.clientWidth || 600;
    var h = Math.max(300, Math.min(500, w * 0.5)); // 高度自适应

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

    var centerX = drawArea.w / 2 + padding;
    var centerY = drawArea.h / 2 + padding;

    for (var i = 0; i < sorted.length; i++) {
      var item = sorted[i];
      var fontSize = mapFontSize(item.weight, minW, maxWt, minFont, maxFont);
      var size = measureText(ctx, item.word, fontSize);
      var color = randomColor();
      var placedOk = false;

      // 重置角度，每个词从当前角度继续
      var localAngle = angle;
      for (var a = 0; a < maxAttempts; a++) {
        localAngle += angleStep;
        var r = radiusStep * localAngle / (Math.PI * 2);

        if (r > maxRadius) break;

        var x = centerX + Math.cos(localAngle) * r - size.w / 2;
        var y = centerY + Math.sin(localAngle) * r - size.h / 2;

        if (x < padding || y < padding || x + size.w > w - padding || y + size.h > h - padding) continue;

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
          angle = localAngle; // 记住当前角度
          placedOk = true;
          break;
        }
      }
    }

    // 保存绘制数据到 Canvas 元素上，供 hover 使用
    canvas._wordcloudData = { placed: placed, data: sorted };
  }

  // ── 导出 ──────────────────────────────────
  global.renderWordCloud = renderWordCloud;

})(window);