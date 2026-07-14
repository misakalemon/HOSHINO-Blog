(function() {
  var banner = document.getElementById('cookieBanner');
  if (!banner) return;
  try {
    if (localStorage.getItem('cookie_consent')) {
      banner.remove();
      return;
    }
  } catch(e) {}
  var acceptBtn = banner.querySelector('.cookie-btn--primary');
  var rejectBtn = banner.querySelector('.cookie-btn--secondary');
  function dismiss(consent) {
    banner.remove();
    try { localStorage.setItem('cookie_consent', consent); } catch(e) {}
  }
  if (acceptBtn) acceptBtn.addEventListener('click', function(){ dismiss('accepted'); });
  if (rejectBtn) rejectBtn.addEventListener('click', function(){ dismiss('rejected'); });
  setTimeout(function(){
    if (document.getElementById('cookieBanner')) {
      dismiss('accepted');
    }
  }, 8000);
})();
