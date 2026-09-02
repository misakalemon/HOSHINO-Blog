/**
 * interactions.js — HOSHINO Blog 全站统一交互层
 *
 * 职责（与成熟博客方案对齐）：
 *   1. 事件委托 — 全站 data-action / data-arg 属性驱动的声明式交互
 *      （替代散落各模板的内联 onclick，为收紧 CSP 铺路）
 *   2. 返回顶部按钮 — 滚动 400px 后出现，平滑滚动
 *   3. 图片灯箱升级 — Esc 关闭 / ←→ 切换同页图片 / 缩放状态
 *   4. Ctrl+K 全局搜索弹层 — 防抖即时搜索，↑↓ 选择 Enter 跳转
 *   5. 导航栏滚动手势 — 向下滚隐藏、向上滚显示（主流博客行为）
 *   6. Skip-link — 键盘用户跳转主内容
 *   7. 平滑滚动 — 尊重 prefers-reduced-motion
 *
 * 设计原则：
 *   - 全部使用 addEventListener（CSP-safe，无内联 JS）
 *   - 渐进增强：JS 不可用时页面功能不受影响（链接/表单仍可用）
 *   - 不修改任何既有全局函数名，data-action 映射到 window 上的函数
 */

(function () {
  'use strict';

  // ═══════════════════════════════════════════════
  // 工具函数：节流 / 防抖
  // ═══════════════════════════════════════════════

  /**
   * requestAnimationFrame 节流 — 把高频 scroll/resize 回调限制到每帧一次
   * 比 setTimeout 更顺滑，且会在页面不可见时自动暂停（节能）
   */
  function throttleByRAF(fn) {
    var ticking = false;
    return function () {
      var self = this, args = arguments;
      if (!ticking) {
        window.requestAnimationFrame(function () {
          ticking = false;
          fn.apply(self, args);
        });
        ticking = true;
      }
    };
  }

  /**
   * 防抖 — 延迟执行，连续触发时重置计时器
   * @param {number} wait 等待毫秒
   * @param {boolean} leading 是否在首次触发时立即执行
   */
  function debounce(fn, wait, leading) {
    var timer, lastCall = 0;
    return function () {
      var self = this, args = arguments, now = Date.now();
      if (leading && now - lastCall >= wait) {
        lastCall = now;
        fn.apply(self, args);
        return;
      }
      clearTimeout(timer);
      timer = setTimeout(function () { fn.apply(self, args); }, wait);
    };
  }

  var prefersReduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function smoothScrollTo(y) {
    if (prefersReduced) { window.scrollTo(0, y); return; }
    window.scrollTo({ top: y, behavior: 'smooth' });
  }

  // ── 1. 事件委托（data-action）─────────────────────────────
  // 用法：
  //   <button data-action="fnName" data-arg="optional">…</button>
  //   点击时调用 window.fnName(arg?)，若函数不存在则忽略（渐进增强安全）。
  document.addEventListener('click', function (e) {
    var el = e.target.closest ? e.target.closest('[data-action]') : null;
    if (!el) return;
    // 若元素本身是链接且 data-action 为空则交给默认行为
    var action = el.getAttribute('data-action');
    if (!action) return;
    var arg = el.getAttribute('data-arg');
    // 纯数字字符串自动转 number：模板 data-arg="1" 传字符串会导致
    // goStep 的 n === 3 严格比较、changeYear 的 calYear += delta 字符串拼接出错
    if (arg !== null && arg !== undefined && /^-?\d+(\.\d+)?$/.test(arg)) {
      arg = parseFloat(arg);
    }
    // 支持点号路径（如 window.print）与全局函数名
    var fn = null;
    try {
      fn = action.split('.').reduce(function (o, k) { return o ? o[k] : o; }, window);
    } catch (err) { fn = null; }
    if (typeof fn === 'function') {
      try {
        if (arg !== null && arg !== undefined) { fn(arg, el, e); }
        else { fn(el, e); }
      } catch (err) {
        // 委托执行异常不阻断默认行为
      }
    }
  });

  // ── 捕获阶段拦截 [data-stop] 元素（如移除按钮）──────────────
  // 移除按钮通常嵌套在上传容器内（容器有元素级 click 监听器打开文件选择框），
  // 冒泡阶段的 stopPropagation 来不及阻止元素级监听器。
  // 在捕获阶段提前 stopPropagation，并在此手动执行其 data-action。
  document.addEventListener('click', function (e) {
    var el = e.target && e.target.closest ? e.target.closest('[data-stop]') : null;
    if (!el) return;
    e.stopPropagation();
    e.preventDefault();
    var action = el.getAttribute('data-action');
    if (!action) return;
    var fn = null;
    try {
      fn = action.split('.').reduce(function (o, k) { return o ? o[k] : o; }, window);
    } catch (err) { fn = null; }
    if (typeof fn === 'function') {
      var arg = el.getAttribute('data-arg');
      if (arg !== null && arg !== undefined && /^-?\d+(\.\d+)?$/.test(arg)) arg = parseFloat(arg);
      try { fn(el, e); } catch (err) {}
    }
  }, true);

  // ── 禁用分页链接拦截（替代 onclick="return false"）─────────
  document.addEventListener('click', function (e) {
    var el = e.target.closest ? e.target.closest('a.page-link.disabled') : null;
    if (el) { e.preventDefault(); }
  });

  // ── 2. 返回顶部按钮 ──────────────────────────────────────
  var backTop = document.createElement('button');
  backTop.type = 'button';
  backTop.className = 'back-to-top';
  backTop.setAttribute('aria-label', '返回顶部');
  backTop.innerHTML = '↑';
  backTop.addEventListener('click', function () { smoothScrollTo(0); });
  document.body.appendChild(backTop);
  var backTopShow = false;
  var updateBackTop = throttleByRAF(function () {
    var show = window.scrollY > 400;
    if (show !== backTopShow) {
      backTopShow = show;
      backTop.classList.toggle('visible', show);
    }
  });
  window.addEventListener('scroll', updateBackTop, { passive: true });
  updateBackTop();

  // ── 3. 图片灯箱升级 ──────────────────────────────────────
  // 收集当前页面所有带 data-lightbox 属性的图片；正文中的图片
  // 通过标记自动加入集合。支持 Esc 关闭、←→ 切换、再次点击放大切换。
  var lightbox = document.getElementById('lightbox');
  var lightboxImg = document.getElementById('lightboxImg');
  var lbImages = [];
  var lbIndex = 0;
  var lbZoomed = false;

  // 使用 Set 去重，避免同一图片被多次加入
  var lbImageSet = new Set();

  function _addLightboxImg(img) {
    if (lbImageSet.has(img)) return;
    lbImageSet.add(img);
    lbImages.push(img);
  }

  function collectLightboxImages() {
    lbImages = [];
    lbImageSet.clear();
    var imgs = document.querySelectorAll('img[data-lightbox]');
    for (var i = 0; i < imgs.length; i++) _addLightboxImg(imgs[i]);
  }
  collectLightboxImages();

  // MutationObserver：懒加载或动态插入的图片自动加入灯箱集合
  if ('MutationObserver' in window) {
    new MutationObserver(function (mutations) {
      var needUpdate = false;
      for (var m = 0; m < mutations.length; m++) {
        var nodes = mutations[m].addedNodes;
        for (var n = 0; n < nodes.length; n++) {
          var node = nodes[n];
          if (node.nodeType === 1) {
            if (node.tagName === 'IMG' && node.hasAttribute('data-lightbox')) {
              _addLightboxImg(node);
              needUpdate = true;
            } else if (node.querySelectorAll) {
              var imgs = node.querySelectorAll('img[data-lightbox]');
              for (var i = 0; i < imgs.length; i++) { _addLightboxImg(imgs[i]); needUpdate = true; }
            }
          }
        }
      }
    }).observe(document.body, { childList: true, subtree: true });
  }

  function openLightboxAt(idx) {
    if (!lightbox || !lightboxImg || !lbImages.length) return;
    lbIndex = ((idx % lbImages.length) + lbImages.length) % lbImages.length;
    var img = lbImages[lbIndex];
    var src = img.getAttribute('data-full') || img.src || img.getAttribute('src');
    lightboxImg.src = src;
    lightboxImg.classList.remove('zoomed');
    lbZoomed = false;
    lightbox.style.display = 'flex';
    document.body.style.overflow = 'hidden';
  }
  function closeLightboxBox() {
    if (!lightbox) return;
    lightbox.style.display = 'none';
    document.body.style.overflow = '';
  }
  function lbNext(step) { openLightboxAt(lbIndex + step); }
  function lbToggleZoom() {
    if (!lightboxImg) return;
    lbZoomed = !lbZoomed;
    lightboxImg.classList.toggle('zoomed', lbZoomed);
  }

  // 点击带 data-lightbox 的图片打开灯箱（含正文图片）
  document.addEventListener('click', function (e) {
    var img = e.target.closest ? e.target.closest('img[data-lightbox]') : null;
    if (!img) return;
    var idx = lbImages.indexOf(img);
    if (idx === -1) { collectLightboxImages(); idx = lbImages.indexOf(img); }
    openLightboxAt(idx);
  });

  // 灯箱内部点击：空白区域关闭（兼容原有 openLightbox/closeLightbox 全局函数）
  if (lightbox) {
    lightbox.addEventListener('click', function (e) {
      if (e.target === lightbox) { closeLightboxBox(); return; }
      if (e.target === lightboxImg) { lbToggleZoom(); }
    });
  }
  document.addEventListener('keydown', function (e) {
    if (!lightbox || lightbox.style.display !== 'flex') return;
    if (e.key === 'Escape') { closeLightboxBox(); }
    else if (e.key === 'ArrowLeft') { lbNext(-1); }
    else if (e.key === 'ArrowRight') { lbNext(1); }
  });

  // 兼容旧代码：模板中 openLightbox/closeLightbox 全局函数保持可用
  window.openLightbox = function (src) {
    if (!lightbox || !lightboxImg) return;
    lightboxImg.src = src;
    lightboxImg.classList.remove('zoomed');
    lightbox.style.display = 'flex';
    document.body.style.overflow = 'hidden';
  };
  window.closeLightbox = closeLightboxBox;

  // ── 4. Ctrl+K 全局搜索弹层 ────────────────────────────────
  var searchModal = null;
  var searchInput = null;
  var searchResults = null;
  var searchTimer = null;
  var searchItems = [];
  var searchActiveIndex = -1;
  var searchUrl = '/api/search';

  function buildSearchModal() {
    if (document.getElementById('globalSearchModal')) return;
    var overlay = document.createElement('div');
    overlay.id = 'globalSearchModal';
    overlay.className = 'search-modal-overlay';
    overlay.innerHTML =
      '<div class="search-modal" role="dialog" aria-modal="true" aria-label="站内搜索">' +
        '<div class="search-modal-input-row">' +
          '<span class="search-modal-icon">🔍</span>' +
          '<input type="text" class="search-modal-input" placeholder="搜索文章标题、摘要…" aria-label="搜索关键词">' +
          '<button type="button" class="search-modal-close" aria-label="关闭搜索">Esc</button>' +
        '</div>' +
        '<div class="search-modal-results" role="listbox"></div>' +
        '<div class="search-modal-hint">↑↓ 选择 · Enter 打开 · Esc 关闭</div>' +
      '</div>';
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) closeSearchModal();
    });
    document.body.appendChild(overlay);
    searchModal = overlay;
    searchInput = overlay.querySelector('.search-modal-input');
    searchResults = overlay.querySelector('.search-modal-results');
    searchModal.querySelector('.search-modal-close').addEventListener('click', closeSearchModal);
    searchInput.addEventListener('input', onSearchInput);
    searchInput.addEventListener('keydown', onSearchKeydown);
  }

  function openSearchModal() {
    buildSearchModal();
    searchModal.classList.add('open');
    searchInput.value = '';
    searchResults.innerHTML = '';
    searchItems = [];
    searchActiveIndex = -1;
    setTimeout(function () { searchInput.focus(); }, 50);
  }
  function closeSearchModal() {
    if (!searchModal) return;
    searchModal.classList.remove('open');
  }

  // 搜索防抖：首次输入立即搜索（leading），连续输入时 250ms 后执行最后一次
  var onSearchInput = debounce(function () {
    var q = searchInput.value.trim();
    if (!q) { searchResults.innerHTML = ''; searchItems = []; searchActiveIndex = -1; return; }
    doSearch(q);
  }, 250, true);

  function doSearch(q) {
    fetch(searchUrl + '?q=' + encodeURIComponent(q), {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        renderSearchResults(data.items || []);
      })
      .catch(function () {
        searchResults.innerHTML = '<div class="search-modal-empty">搜索失败，请重试</div>';
      });
  }

  function renderSearchResults(items) {
    searchItems = items;
    searchActiveIndex = items.length ? 0 : -1;
    if (!items.length) {
      searchResults.innerHTML = '<div class="search-modal-empty">没有找到相关文章</div>';
      return;
    }
    var html = '';
    for (var i = 0; i < items.length; i++) {
      var it = items[i];
      // url 同样经 escHtml（含引号转义），防止属性注入
      html += '<a class="search-modal-item' + (i === 0 ? ' active' : '') + '"' +
        ' href="' + escHtml(it.url) + '" data-idx="' + i + '">' +
        '<span class="search-modal-item-title">' + escHtml(it.title) + '</span>' +
        (it.date ? '<span class="search-modal-item-date">' + escHtml(it.date) + '</span>' : '') +
        '</a>';
    }
    searchResults.innerHTML = html;
  }

  function escHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function onSearchKeydown(e) {
    if (e.key === 'Escape') { closeSearchModal(); return; }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!searchItems.length) return;
      var dir = e.key === 'ArrowDown' ? 1 : -1;
      searchActiveIndex = (searchActiveIndex + dir + searchItems.length) % searchItems.length;
      var nodes = searchResults.querySelectorAll('.search-modal-item');
      for (var i = 0; i < nodes.length; i++) {
        nodes[i].classList.toggle('active', i === searchActiveIndex);
      }
      nodes[searchActiveIndex].scrollIntoView({ block: 'nearest' });
      return;
    }
    if (e.key === 'Enter') {
      if (searchItems.length && searchActiveIndex >= 0) {
        window.location.href = searchItems[searchActiveIndex].url;
      } else if (searchInput.value.trim()) {
        window.location.href = '/search?q=' + encodeURIComponent(searchInput.value.trim());
      }
    }
  }

  document.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
      e.preventDefault();
      openSearchModal();
      return;
    }
    if (e.key === '/' && !isTypingTarget(e.target)) {
      // 主流博客的 / 快捷搜索（输入框中不触发）
      e.preventDefault();
      openSearchModal();
    }
  });

  function isTypingTarget(el) {
    var tag = el && el.tagName;
    return tag === 'INPUT' || tag === 'TEXTAREA' || (el && el.isContentEditable);
  }

  // ── Enter 键触发（data-enter，用于页码跳转输入框等）───────
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter') return;
    var el = e.target && e.target.closest ? e.target.closest('[data-enter]') : null;
    if (!el) return;
    var action = el.getAttribute('data-enter');
    var fn = window[action];
    if (typeof fn === 'function') {
      e.preventDefault();
      try { fn(el, e); } catch (err) {}
    }
  });

  // ── change 事件委托（data-change，用于每页条数选择器等）────
  document.addEventListener('change', function (e) {
    var el = e.target && e.target.closest ? e.target.closest('[data-change]') : null;
    if (!el) return;
    var action = el.getAttribute('data-change');
    var fn = window[action];
    if (typeof fn === 'function') {
      try { fn(el, e); } catch (err) {}
    }
  });

  // ── input 事件委托（data-input，工具页实时计算等）─────────
  document.addEventListener('input', function (e) {
    var el = e.target && e.target.closest ? e.target.closest('[data-input]') : null;
    if (!el) return;
    var action = el.getAttribute('data-input');
    var fn = window[action];
    if (typeof fn === 'function') {
      try { fn(el, e); } catch (err) {}
    }
  });

  // ── 工具页辅助函数（配合 data-input/data-change）──────────
  // 包装各工具函数，统一适配委托参数（el 元素 / e 事件）
  window.pwLenSync = function (el) {
    var out = document.getElementById('pwLenVal');
    if (out) out.textContent = el.value;
  };
  window.izUpdateSel = function (el) {
    if (typeof izUpdate === 'function') izUpdate();
  };
  window.izLoadSel = function (el, e) {
    if (typeof izLoad === 'function') izLoad({ target: el });
  };
  // tsFromUnix/tsFromDatetime 签名是 (val)，委托传入元素 → 取 value
  var _origTsFromUnix = window.tsFromUnix;
  var _origTsFromDatetime = window.tsFromDatetime;
  window.tsFromUnixEl = function (el) {
    if (typeof _origTsFromUnix === 'function') _origTsFromUnix(el.value);
  };
  window.tsFromDatetimeEl = function (el) {
    if (typeof _origTsFromDatetime === 'function') _origTsFromDatetime(el.value);
  };
  // copyColor 签名 (type, e)：e 用于 currentTarget 反馈，传按钮元素
  window.copyColorEl = function (type, el) {
    if (typeof copyColor === 'function') copyColor(type, { currentTarget: el });
  };

  // ── 每页条数选择（data-change="changePerPage"）─────────────
  window.changePerPage = function (select) {
    var usp = new URLSearchParams(window.location.search);
    usp.set('per_page', select.value);
    usp.set('page', '1');
    window.location.search = usp.toString();
  };

  // ── 首页滚动到精选卡片区 ─────────────────────────────────
  window.scrollToFeatured = function () {
    var target = document.querySelector('.featured-grid') || document.querySelector('.site-wordcloud') || document.querySelector('.content');
    if (target) target.scrollIntoView({ behavior: prefersReduced ? 'auto' : 'smooth' });
  };

  // ── B站对比页辅助 ─────────────────────────────────────────
  window.gotoVideo = function (vid) {
    window.location = '/bilibili/video/' + vid;
  };
  window.confirmRemoveCompare = function (vid) {
    if (typeof showConfirm === 'function') {
      showConfirm('从对比中移除此视频？', function (r) {
        if (r && typeof removeFromCompare === 'function') removeFromCompare(vid);
      });
    }
  };

  // ── 管理后台辅助包装（部分函数首参为 event）────────────────
  // 这些包装让 data-action 委托统一以 (el, e) 调用，内部适配原函数签名。
  window.hideScrapeLog = function () {
    var el = document.getElementById('scrapeLog');
    var c = document.getElementById('scrapeLogContent');
    var s = document.getElementById('scrapeStats');
    if (el) el.style.display = 'none';
    if (c) c.innerHTML = '';
    if (s) s.textContent = '';
  };
  window.hideMissingResult = function () {
    var el = document.getElementById('missingResult');
    if (el) el.style.display = 'none';
  };
  window.closeBiliQrIfSelf = function (el, e) {
    if (e && e.target === el && typeof closeBiliQr === 'function') closeBiliQr();
  };
  window.triggerFileInput = function (inputId) {
    // 防重入：程序化 input.click() 的冒泡可能再次命中容器 data-action，
    // 导致重复打开文件选择框
    if (triggerFileInput._busy) return;
    triggerFileInput._busy = true;
    try {
      var el = document.getElementById(inputId);
      if (el) el.click();
    } finally {
      setTimeout(function () { triggerFileInput._busy = false; }, 100);
    }
  };
  window.removeIconW = function (el, e) {
    if (typeof removeIcon === 'function') removeIcon({ stopPropagation: function () {} });
  };
  window.removeCoverW = function (el, e) {
    if (typeof removeCover === 'function') removeCover({ stopPropagation: function () {} });
  };
  window.removeHtmlFileW = function (el, e) {
    if (typeof removeHtmlFile === 'function') removeHtmlFile({ stopPropagation: function () {} });
  };
  window.removeHeroImageW = function (el, e) {
    if (typeof removeHeroImage === 'function') removeHeroImage({ stopPropagation: function () {} });
  };
  window.deleteShapeImageW = function (el, e) {
    if (typeof deleteShapeImage === 'function') deleteShapeImage({ stopPropagation: function () {} });
  };
  // addSingleVideo 签名 (forceUpdate)，按钮点击应传 false（否则 el 会被当 truthy）
  window.addSingleVideoW = function () {
    if (typeof addSingleVideo === 'function') addSingleVideo(false);
  };
  // startScrape 无参，Enter 触发时委托传 (el, e) 无害
  window.confirmFormSubmit = function (el, e) {    if (e) e.preventDefault();
    var f = el.form;
    if (typeof showConfirm === 'function') {
      var days = (f && f.days && f.days.value) || '';
      showConfirm('确定删除近 ' + days + ' 天的历史快照？\n此操作不可恢复！', function (r) {
        if (r) { f.onsubmit = null; f.submit(); }
      });
    }
  };
  window.showConfirmResetWc = function () {
    if (typeof showConfirm === 'function') {
      showConfirm('确定重置所有词云配置吗？此操作需要重新生成！', function (r) {
        if (r) {
          var f = document.querySelector('form');
          if (f) {
            var inp = document.createElement('input');
            inp.type = 'hidden';
            inp.name = 'reset_defaults';
            inp.value = '1';
            f.appendChild(inp);
            f.submit();
          }
        }
      });
    }
  };
  // 重新计算所有词云（跳转后台刷新接口）
  window.resetWordcloud = function (arg, el) {
    if (typeof showConfirm === 'function') {
      showConfirm('确定重新计算所有词云？此操作可能需要几秒钟。', function (r) {
        if (r) {
          var url = (el && el.getAttribute('data-wc-url')) || '';
          if (url) window.location = url;
        }
      });
    }
  };

  // ── 9. 评论 AJAX 提交（无刷新 + 防重复提交）────────────────
  // 匹配 .comment-form form：fetch POST 提交，成功后显示提示并重置表单。
  // 失败时保留原生行为（整页提交），保证功能不丢失。
  document.addEventListener('submit', function (e) {
    var form = e.target && e.target.closest ? e.target.closest('.comment-form form') : null;
    if (!form) return;
    var submitBtn = form.querySelector('button[type="submit"]');
    if (!submitBtn || submitBtn.disabled || submitBtn.classList.contains('is-loading')) return;
    e.preventDefault();
    submitBtn.disabled = true;
    submitBtn.classList.add('is-loading');
    var fd = new FormData(form);
    // CSRF token 由表单 hidden_tag 提供
    fetch(form.action, {
      method: 'POST',
      body: fd,
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        submitBtn.disabled = false;
        submitBtn.classList.remove('is-loading');
        if (data && data.ok) {
          // 成功提示（替换为 toast 样式提示条）
          showCommentToast(data.message || '评论已提交');
          form.reset();
        } else {
          showCommentToast((data && data.message) || '提交失败，请重试', true);
        }
      })
      .catch(function () {
        // 网络错误回退到原生提交
        submitBtn.disabled = false;
        submitBtn.classList.remove('is-loading');
        form.submit();
      });
  });

  var _toastEl = null;
  function showCommentToast(msg, isError) {
    if (!_toastEl) {
      _toastEl = document.createElement('div');
      _toastEl.className = 'comment-toast';
      document.body.appendChild(_toastEl);
    }
    _toastEl.textContent = msg;
    _toastEl.classList.toggle('is-error', !!isError);
    _toastEl.classList.add('show');
    if (_toastEl._timer) clearTimeout(_toastEl._timer);
    _toastEl._timer = setTimeout(function () {
      _toastEl.classList.remove('show');
    }, 3200);
  }

  // ── 5. 导航栏滚动手势（向下隐藏 / 向上显示）───────────────
  (function () {
    var nav = document.querySelector('.navbar');
    if (!nav || nav.hasAttribute('data-nav-auto')) return; // 首页有自己的渐显逻辑
    var lastY = window.scrollY;
    var hidden = false;
    var onScroll = throttleByRAF(function () {
      var y = window.scrollY;
      if (y < 60) { nav.classList.remove('nav-hidden'); hidden = false; lastY = y; return; }
      if (y > lastY + 6 && !hidden) {
        hidden = true;
        nav.classList.add('nav-hidden');
      } else if (y < lastY - 6 && hidden) {
        hidden = false;
        nav.classList.remove('nav-hidden');
      }
      lastY = y;
    });
    window.addEventListener('scroll', onScroll, { passive: true });
  })();

  // ── 6. Skip-link ─────────────────────────────────────────
  var skip = document.createElement('a');
  skip.className = 'skip-link';
  skip.href = '#content';
  skip.textContent = '跳转到主内容';
  document.body.insertBefore(skip, document.body.firstChild);
  skip.addEventListener('click', function (e) {
    e.preventDefault();
    var target = document.getElementById('content') || document.querySelector('.content');
    if (target) {
      target.setAttribute('tabindex', '-1');
      target.focus({ preventScroll: false });
    }
  });

  // ── 7. 图片懒加载占位骨架 ────────────────────────────────
  // 对带 .skeleton-img 类的容器内的 img 提供加载完成淡入
  document.addEventListener('load', function (e) {
    var img = e.target;
    if (img && img.tagName === 'IMG' && img.closest && img.closest('.skeleton-img')) {
      img.classList.add('loaded');
    }
  }, true);

  // ── 图片加载失败自动隐藏（替代模板内联 onerror）────────────
  document.addEventListener('error', function (e) {
    var img = e.target;
    if (img && img.tagName === 'IMG' && img.hasAttribute && img.hasAttribute('data-hide-on-error')) {
      img.style.display = 'none';
    }
  }, true);

  // ── 8. 分页跳转输入框（data-enter="jumpPage"）─────────────
  // 用法：<input data-enter="jumpPage" data-base-url="/category/x" data-max="10">
  // Enter 时按当前值跳转到 base_url?page=N（保留现有查询参数中的 per_page/q）
  window.jumpPage = function (input) {
    var p = parseInt(input.value, 10);
    var max = parseInt(input.getAttribute('data-max') || '1', 10);
    var base = input.getAttribute('data-base-url') || '';
    if (isNaN(p) || p < 1 || p > max) return;
    var usp = new URLSearchParams(window.location.search);
    usp.set('page', String(p));
    window.location = base + '?' + usp.toString();
  };
})();
