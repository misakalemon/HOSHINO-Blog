// 滚动位置恢复：分页/翻页链接点击时保存滚动位置，新页面加载后恢复，
// 避免翻页后页面跳到顶部打断阅读/操作流。
(function () {
  var STORAGE_KEY = 'hoshino_scroll_y';
  var MARK_CLASS = 'js-scroll-restore'; // 标记分页/翻页链接

  // 匹配分页链接：带 .js-scroll-restore 标记，或在 .pagination / .page-jump 容器内
  document.addEventListener('click', function (e) {
    var link = e.target && e.target.closest
      ? e.target.closest('a.' + MARK_CLASS + ', .pagination a, .page-jump a')
      : null;
    if (!link) return;
    var href = link.getAttribute('href');
    if (!href || href.indexOf('#') === 0) return; // 纯锚点不处理
    var url;
    try { url = new URL(href, location.origin); } catch (err) { return; }
    // 同源才保存（跨站/下载链接不处理）
    if (url.origin !== location.origin) return;
    try { sessionStorage.setItem(STORAGE_KEY, String(window.scrollY || 0)); } catch (err) {}
  });

  // 页面加载后恢复滚动位置（仅一次）
  function restore() {
    try {
      var raw = sessionStorage.getItem(STORAGE_KEY);
      if (raw === null) return;
      sessionStorage.removeItem(STORAGE_KEY); // 只恢复一次
      var y = parseInt(raw, 10);
      if (!isNaN(y) && y > 0) {
        // 等待布局稳定后恢复
        window.scrollTo(0, y);
      }
    } catch (err) {}
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', restore);
  } else {
    restore();
  }
})();
