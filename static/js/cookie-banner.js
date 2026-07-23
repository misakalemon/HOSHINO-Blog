/**
 * cookie-banner.js — Cookie 同意横幅
 *
 * 职责：
 *   1. 检查 localStorage 中是否已有 Cookie 同意记录
 *   2. 未同意时显示横幅，用户点击"接受"或"拒绝"后持久化选择
 *   3. 8 秒无操作自动接受（避免横幅长期遮挡内容）
 *
 * 存储键：cookie_consent
 * 存储值：'accepted' | 'rejected'
 */
(function() {
  var banner = document.getElementById('cookieBanner');
  if (!banner) return;
  // 检查是否已有同意记录，有则移除横幅
  try {
    if (localStorage.getItem('cookie_consent')) {
      banner.remove();
      return;
    }
  } catch(e) {} // localStorage 不可用时静默降级
  var acceptBtn = banner.querySelector('.cookie-btn--primary');
  var rejectBtn = banner.querySelector('.cookie-btn--secondary');
  /**
   * 关闭横幅并持久化用户选择
   * @param {string} consent - 'accepted' 或 'rejected'
   */
  function dismiss(consent) {
    banner.remove();
    try { localStorage.setItem('cookie_consent', consent); } catch(e) {}
  }
  if (acceptBtn) acceptBtn.addEventListener('click', function(){ dismiss('accepted'); });
  if (rejectBtn) rejectBtn.addEventListener('click', function(){ dismiss('rejected'); });
  // 8 秒后自动接受（横幅仍在 DOM 中说明用户未操作）
  setTimeout(function(){
    if (document.getElementById('cookieBanner')) {
      dismiss('accepted');
    }
  }, 8000);
})();
