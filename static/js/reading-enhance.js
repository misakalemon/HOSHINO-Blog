/**
 * reading-enhance.js — 文章阅读体验增强
 *
 * 对齐主流博客方案（Medium/掘金/少数派）：
 *   1. 目录 TOC — 从正文 h1~h3 自动生成，滚动高亮当前位置
 *   2. 阅读进度 — 文章页专属进度条（基于正文滚动位置）
 *   3. 阅读时长 — 按正文字数/阅读速度估算，显示在标题区
 *
 * 渐进增强：正文无标题时 TOC 不显示；所有 DOM 通过 JS 注入。
 */
(function () {
  'use strict';

  var article = document.querySelector('.post-content');
  if (!article) return;

  // ── 0. 正文图片启用灯箱 ─────────────────────────
  article.querySelectorAll('img').forEach(function (img) {
    if (!img.hasAttribute('data-lightbox')) {
      img.setAttribute('data-lightbox', '');
      img.setAttribute('data-full', img.getAttribute('src') || img.src);
    }
  });

  // ── 1. 阅读时长估算 ─────────────────────────────
  var words = (article.textContent || '').replace(/\s+/g, '').length;
  var minutes = Math.max(1, Math.round(words / 400)); // 中文 ~400 字/分钟
  var metaTarget = document.getElementById('readingTime');
  if (metaTarget && !metaTarget.dataset.filled) {
    metaTarget.textContent = '约 ' + minutes + ' 分钟读完';
    metaTarget.dataset.filled = '1';
  }

  // ── 2. 收集正文标题生成 TOC ─────────────────────
  var headings = article.querySelectorAll('h1, h2, h3');
  var tocWrap = document.getElementById('articleToc');
  if (!tocWrap || headings.length < 2) {
    if (tocWrap) tocWrap.style.display = 'none';
    return;
  }

  var tocList = tocWrap.querySelector('.toc-list') || tocWrap;
  tocList.innerHTML = '';
  var items = [];
  headings.forEach(function (h, i) {
    if (!h.id) h.id = 'section-' + i;
    var level = parseInt(h.tagName.charAt(1), 10);
    var a = document.createElement('a');
    a.href = '#' + h.id;
    a.className = 'toc-item toc-level-' + level;
    a.textContent = h.textContent;
    tocList.appendChild(a);
    items.push({ link: a, heading: h });
  });

  // ── 3. 滚动高亮当前章节（IntersectionObserver）──
  var currentLink = null;
  function setActive(link) {
    if (currentLink === link) return;
    if (currentLink) currentLink.classList.remove('active');
    currentLink = link;
    if (link) link.classList.add('active');
  }
  if ('IntersectionObserver' in window) {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          var idx = items.findIndex(function (it) { return it.heading === entry.target; });
          if (idx !== -1) setActive(items[idx].link);
        }
      });
    }, { rootMargin: '-15% 0px -70% 0px', threshold: 0 });
    items.forEach(function (it) { observer.observe(it.heading); });
  }

  // ── 4. 文章阅读进度条 ───────────────────────────
  var progressBar = document.getElementById('articleProgress');
  if (progressBar) {
    function updateReadingProgress() {
      var rect = article.getBoundingClientRect();
      var docTop = window.scrollY;
      var start = rect.top + docTop;
      var height = rect.height - window.innerHeight;
      var pos = docTop - start;
      var pct = height > 0 ? Math.min(100, Math.max(0, (pos / height) * 100)) : 0;
      progressBar.style.width = pct + '%';
    }
    window.addEventListener('scroll', updateReadingProgress, { passive: true });
    window.addEventListener('resize', updateReadingProgress);
    updateReadingProgress();
  }
})();
