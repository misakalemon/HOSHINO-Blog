/**
 * base.js — HOSHINO Blog 前台基础交互
 *
 * 职责：
 *   1. 导航栏渐显 — 首页滚动超过 Hero 区域 20% 后显示导航栏
 *   2. 移动端抽屉菜单 — 侧滑导航 + 遮罩层
 *   3. 图片灯箱 — 点击图片全屏查看
 *   4. 自定义下拉框 (glow-select) — 全站统一的粉紫风格 select 组件
 *   5. 全局弹窗 — 替换原生 alert/confirm/prompt，暗色粉紫风格
 *   6. 滚动位置恢复 — 浏览器返回时自动恢复
 *
 * 所有事件绑定使用 addEventListener（CSP-safe，不依赖 inline onclick）。
 */

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

// ── 导航栏渐显（仅首页滚动触发）────────────
// 首页 Hero 区域覆盖整个视口，导航栏初始透明，
// 滚动超过视口高度 20% 后渐显为半透明玻璃态。
(function(){
  var nav = document.querySelector('.navbar');
  if (!nav) return;
  // data-nav-auto 属性标记需要渐显行为的导航栏（仅首页）
  if (nav.hasAttribute('data-nav-auto')) {
    var hero = document.querySelector('.hero, .hero-particle');
    // 无 Hero 区域时直接显示导航栏（非首页场景）
    if (!hero) { nav.classList.add('visible'); return; }
    /** 滚动监听：滚过英雄区 15% 高度后导航栏渐显（RAF 节流） */
    var checkNav = throttleByRAF(function () {
      nav.classList.toggle('visible', window.scrollY > hero.offsetHeight * 0.15);
    });
    window.addEventListener('scroll', checkNav, { passive: true });
    checkNav();
  }
})();

// ── 滚动进度条（全站通用）──────────────────
(function(){
  var bar = document.getElementById('scrollProgress');
  if (!bar) return;
  var updateProgress = throttleByRAF(function () {
    var scrollTop = window.scrollY;
    var docHeight = document.documentElement.scrollHeight - window.innerHeight;
    var progress = docHeight > 0 ? (scrollTop / docHeight) * 100 : 0;
    bar.style.width = Math.min(progress, 100) + '%';
  });
  window.addEventListener('scroll', updateProgress, { passive: true });
  window.addEventListener('resize', debounce(updateProgress, 150));
  updateProgress();
})();

// ── 移动端抽屉菜单 ─────────────────────────
/** 切换移动端侧滑抽屉菜单的展开/收起状态 */
// 智能返回：同源历史可退则返回，否则跳转到显式链接（避免直接离开网站）
function smartBack(fallbackUrl) {
  try {
    var ref = document.referrer;
    if (ref && ref.indexOf(location.origin) === 0) { history.back(); return; }
  } catch (e) {}
  if (fallbackUrl) { location.href = fallbackUrl; }
}
function toggleDrawer(){
  var drawer = document.getElementById('mobileDrawer');
  var overlay = document.getElementById('drawerOverlay');
  if (!drawer) return;
  var isOpen = drawer.classList.toggle('open');
  if (overlay) overlay.classList.toggle('show', isOpen);
  // 同步汉堡按钮的 aria-expanded 状态
  var hamburger = document.querySelector('.nav-hamburger');
  if (hamburger) hamburger.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
  // 同步关闭按钮 aria-label
  var closeBtn = drawer.querySelector('.nav-drawer-close');
  if (closeBtn) closeBtn.setAttribute('aria-label', isOpen ? '关闭菜单' : '打开菜单');

  // ── 锁定/恢复 body 滚动 ──
  document.body.style.overflow = isOpen ? 'hidden' : '';

  // ── HarmonyOS / 安卓侧边返回手势兼容 ──
  // 抽屉打开时：阻止从左侧边缘开始的水平滑动手势，防止触发系统返回
  // 但保留左边缘 24px 的「逃生通道」，让用户仍能系统返回
  if (isOpen) {
    drawer.addEventListener('touchstart', _drawerEdgeGuard, { passive: false });
  } else {
    drawer.removeEventListener('touchstart', _drawerEdgeGuard);
  }
}

/** 抽屉边缘守卫：阻止左边缘滑动手势冒泡到系统层
    保留左边缘 24px 「逃生通道」，让用户仍能触发系统返回 */
function _drawerEdgeGuard(e) {
  var touch = e.touches[0];
  var rect = e.currentTarget.getBoundingClientRect();
  var x = touch.clientX - rect.left;
  // 触摸点不在最左边缘 24px 内 → 阻止冒泡，防止触发系统返回
  if (x > 24) {
    e.stopPropagation();
  }
}

// 抽屉遮罩层点击关闭
// 使用 addEventListener 而非 onclick，兼容 CSP 策略
document.getElementById('drawerOverlay')?.addEventListener('click', toggleDrawer);

// ── 图片灯箱 ───────────────────────────────
/**
 * 打开灯箱查看大图
 * @param {string} src - 图片 URL
 */
function openLightbox(src) {
  document.getElementById('lightboxImg').src = src;
  document.getElementById('lightbox').style.display = 'flex';
}
/** 关闭灯箱 */
function closeLightbox() {
  document.getElementById('lightbox').style.display = 'none';
}
// 点击灯箱背景区域关闭（CSP-safe）
document.getElementById('lightbox')?.addEventListener('click', closeLightbox);


// ── 浏览器返回时恢复滚动位置 ──────────────
// 设置为 'auto' 让浏览器自动管理滚动恢复
if ('scrollRestoration' in history) history.scrollRestoration = 'auto';

// ── 自定义下拉框 (glow-select) ─────────────
// 全站统一的粉紫风格 select 组件，支持单选和多选模式。
// HTML 结构：.glow-select-wrap > .glow-select-trigger + .glow-select-options
// 多选模式通过 data-multiple 属性标记。

/**
 * 切换 glow-select 下拉框的展开/收起状态
 * @param {HTMLElement} t - 触发器元素（.glow-select-trigger）
 */
function toggleGlowSelect(t){
  const r=t.parentNode, u=r.classList.contains('is-open');
  // 已展开则收起
  if(u){r.classList.remove('is-open');return;}
  // 单选模式：收起其他已展开的下拉框
  if(!r.getAttribute('data-multiple')){
    document.querySelectorAll('.glow-select-wrap.is-open').forEach(function(w){w.classList.remove('is-open')});
  }
  // 多选模式：更新触发器显示已选数量
  if(r.getAttribute('data-multiple')!==null){
    const c=r.querySelectorAll('.glow-select-option.is-selected').length;
    r.querySelector('.glow-select-value').textContent='已选 '+c+' 项';
  }
  r.classList.add('is-open');
}

// 全局点击事件委托：处理 glow-select 选项点击和外部点击关闭
document.addEventListener('click',function(e){
  const o=e.target.closest('.glow-select-option');
  if(o){
    const w=o.closest('.glow-select-wrap');if(!w)return;
    const v=o.getAttribute('data-value');
    // 多选模式：切换选中状态，同步更新隐藏的 <select> 元素
    if(w.getAttribute('data-multiple')!==null){
      o.classList.toggle('is-selected');
      const sel=w.querySelector('select');
      if(sel){
        // 同步 <select> 的 options 选中状态
        for(let i=0;i<sel.options.length;i++){
          sel.options[i].selected=(sel.options[i].value===v)?!sel.options[i].selected:sel.options[i].selected;
        }
        sel.dispatchEvent(new Event('change',{bubbles:true}));
      }
      // 更新触发器文字为已选数量
      const c=w.querySelectorAll('.glow-select-option.is-selected').length;
      w.querySelector('.glow-select-value').textContent='已选 '+c+' 项';
    }else{
      // 单选模式：更新触发器文字，收起下拉框
      const t=w.querySelector('.glow-select-trigger');
      if(t)t.querySelector('.glow-select-value').textContent=o.textContent;
      w.querySelectorAll('.glow-select-option').forEach(function(x){x.classList.toggle('is-selected',x===o)});
      w.classList.remove('is-open');
      // 同步隐藏的 <select> 值
      const n=w.querySelector('select');
      if(n){n.value=v;n.dispatchEvent(new Event('change',{bubbles:true}))}
    }
    return;
  }
  // 点击下拉框外部区域时关闭所有已展开的下拉框
  if(!e.target.closest('.glow-select-wrap')){
    document.querySelectorAll('.glow-select-wrap.is-open').forEach(function(w){w.classList.remove('is-open')});
  }
});

// ── glow-select 键盘无障碍支持 ──
// ↑↓ 导航选项 / Enter 选择 / Esc 关闭 / Space 展开
document.addEventListener('keydown',function(e){
  const wrap=e.target.closest('.glow-select-wrap');
  if(!wrap)return;
  const isOpen=wrap.classList.contains('is-open');
  const options=Array.from(wrap.querySelectorAll('.glow-select-option'));
  let idx=options.findIndex(function(o){return o.classList.contains('is-focused')});
  function clearFocus(){options.forEach(function(o){o.classList.remove('is-focused');o.removeAttribute('tabindex');});}
  function setFocus(i){clearFocus();if(options[i]){options[i].classList.add('is-focused');options[i].setAttribute('tabindex','0');options[i].focus();}}
  switch(e.key){
    case 'Enter':case ' ':
      e.preventDefault();
      if(isOpen && idx>=0){options[idx].click();}
      else{wrap.querySelector('.glow-select-trigger')&&toggleGlowSelect(wrap.querySelector('.glow-select-trigger'));}
      break;
    case 'Escape':
      e.preventDefault();wrap.classList.remove('is-open');wrap.querySelector('.glow-select-trigger')&&wrap.querySelector('.glow-select-trigger').focus();
      break;
    case 'ArrowDown':
      e.preventDefault();
      if(!isOpen){wrap.querySelector('.glow-select-trigger')&&toggleGlowSelect(wrap.querySelector('.glow-select-trigger'));}
      setFocus(idx<options.length-1?idx+1:0);
      break;
    case 'ArrowUp':
      e.preventDefault();
      if(!isOpen){wrap.querySelector('.glow-select-trigger')&&toggleGlowSelect(wrap.querySelector('.glow-select-trigger'));}
      setFocus(idx>0?idx-1:options.length-1);
      break;
    case 'Home':e.preventDefault();setFocus(0);break;
    case 'End':e.preventDefault();setFocus(options.length-1);break;
  }
});

// ── 全局弹窗（暗色粉紫风格，替换原生 alert/confirm/prompt）──
// 创建一个全局模态弹窗，替换浏览器原生的 alert/confirm/prompt，
// 保持与网站暗色粉紫主题一致。弹窗 DOM 只创建一次，后续复用。
(function() {
  // 防止重复创建
  if (document.querySelector('.glow-modal-overlay')) return;
  // 创建弹窗 DOM 结构：标题 + 消息 + 输入框(默认隐藏) + 按钮区
  const overlay = document.createElement('div');
  overlay.className = 'glow-modal-overlay';
  overlay.innerHTML =
    '<div class="glow-modal">' +
      '<h4 id="gmd-title"></h4>' +
      '<p id="gmd-msg"></p>' +
      '<input class="glow-modal-input" id="gmd-input" style="display:none">' +
      '<div class="glow-modal-actions" id="gmd-actions"></div>' +
    '</div>';
  // 点击遮罩层关闭弹窗
  overlay.addEventListener('click', function(e) {
    if (e.target === overlay) overlay.style.display = 'none';
  });
  document.body.appendChild(overlay);
  // 缓存弹窗内部元素引用
  const titleEl = document.getElementById('gmd-title');
  const msgEl = document.getElementById('gmd-msg');
  const inputEl = document.getElementById('gmd-input');
  const actionsEl = document.getElementById('gmd-actions');
  /** 隐藏弹窗遮罩层 */
  function hideOverlay() { overlay.style.display = 'none'; }
  // 替换原生 alert：显示标题+消息+确定按钮
  window.alert = function(msg) {
    titleEl.textContent = '提示'; msgEl.textContent = msg;
    actionsEl.innerHTML = '<button class="btn btn-primary" style="flex:1;justify-content:center">确定</button>';
    actionsEl.querySelector('button').onclick = hideOverlay;
    overlay.style.display = 'flex';
  };
  // 替换原生 confirm：显示标题+消息+取消/确定按钮，回调返回 true/false
  // 无回调时回退到原生 confirm（同步弹窗），避免"确认弹窗永远不弹、静默返回 true"
  const nativeConfirm = window.confirm;
  const nativePrompt = window.prompt;
  window.confirm = function(msg, cb) {
    if (typeof cb !== 'function') return nativeConfirm(msg);
    titleEl.textContent = '确认操作'; msgEl.textContent = msg;
    actionsEl.innerHTML = '<button class="btn btn-ghost" style="flex:1;justify-content:center">取消</button><button class="btn btn-primary" style="flex:1;justify-content:center">确定</button>';
    const btns = actionsEl.querySelectorAll('button');
    btns[0].onclick = function() { hideOverlay(); cb(false); };
    btns[1].onclick = function() { hideOverlay(); cb(true); };
    overlay.style.display = 'flex';
  };
  // 替换原生 prompt：无回调机制，直接恢复原生行为（同步返回用户输入）
  window.prompt = function(msg, def) {
    return nativePrompt(msg, def);
  };
})();

/**
 * 显示确认弹窗 — 用于替换表单 onsubmit 中的 return confirm()
 * 原生 confirm() 是同步阻塞的，此函数改为异步回调模式。
 * @param {string} msg - 确认消息
 * @param {function(boolean)} cb - 回调函数，参数为用户选择结果
 */
function showConfirm(msg, cb) {
  const overlay = document.querySelector('.glow-modal-overlay');
  if (!overlay) { if (cb) cb(true); return; }
  document.getElementById('gmd-input').style.display = 'none';
  document.getElementById('gmd-title').textContent = '确认操作';
  document.getElementById('gmd-msg').textContent = msg;
  const actionsEl = document.getElementById('gmd-actions');
  actionsEl.innerHTML = '<button class="btn btn-ghost" style="flex:1;justify-content:center">取消</button><button class="btn btn-primary" style="flex:1;justify-content:center">确定</button>';
  const btns = actionsEl.querySelectorAll('button');
  btns[0].onclick = function() { overlay.style.display = 'none'; if (cb) cb(false); };
  btns[1].onclick = function() { overlay.style.display = 'none'; if (cb) cb(true); };
  overlay.style.display = 'flex';
}
