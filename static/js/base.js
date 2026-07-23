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
    /** 滚动监听：滚过英雄区 15% 高度后导航栏渐显 */
    function checkNav() { nav.classList.toggle('visible', window.scrollY > hero.offsetHeight * 0.15); }
    window.addEventListener('scroll', checkNav, {passive:true});
    checkNav();
  }
})();

// ── 滚动进度条（全站通用）──────────────────
(function(){
  var bar = document.getElementById('scrollProgress');
  if (!bar) return;
  function updateProgress(){
    var scrollTop = window.scrollY;
    var docHeight = document.documentElement.scrollHeight - window.innerHeight;
    var progress = docHeight > 0 ? (scrollTop / docHeight) * 100 : 0;
    bar.style.width = Math.min(progress, 100) + '%';
  }
  window.addEventListener('scroll', updateProgress, {passive: true});
  window.addEventListener('resize', updateProgress);
  updateProgress();
})();

// ── 移动端抽屉菜单 ─────────────────────────
/** 切换移动端侧滑抽屉菜单的展开/收起状态 */
function toggleDrawer(){
  document.getElementById('mobileDrawer').classList.toggle('open');
  document.getElementById('drawerOverlay').classList.toggle('show');
}
// 抽屉 logo 点击（小屏时触发抽屉）+ 遮罩层点击关闭
// 使用 addEventListener 而非 onclick，兼容 CSP 策略
document.getElementById('navLogo')?.addEventListener('click', function(e) {
  if (window.innerWidth < 640) { e.preventDefault(); toggleDrawer(); }
});
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
    titleEl.textContent = '提示'; msgEl.innerHTML = msg;
    actionsEl.innerHTML = '<button class="btn btn-primary" style="flex:1;justify-content:center">确定</button>';
    actionsEl.querySelector('button').onclick = hideOverlay;
    overlay.style.display = 'flex';
  };
  // 替换原生 confirm：显示标题+消息+取消/确定按钮，回调返回 true/false
  window.confirm = function(msg, cb) {
    if (typeof cb !== 'function') return true;
    titleEl.textContent = '确认操作'; msgEl.innerHTML = msg;
    actionsEl.innerHTML = '<button class="btn btn-ghost" style="flex:1;justify-content:center">取消</button><button class="btn btn-primary" style="flex:1;justify-content:center">确定</button>';
    const btns = actionsEl.querySelectorAll('button');
    btns[0].onclick = function() { hideOverlay(); cb(false); };
    btns[1].onclick = function() { hideOverlay(); cb(true); };
    overlay.style.display = 'flex';
  };
  // 替换原生 prompt：显示标题+消息+输入框+取消/确定按钮
  window.prompt = function(msg, def) {
    titleEl.textContent = '输入'; msgEl.innerHTML = msg;
    inputEl.style.display = 'block'; inputEl.value = def || '';
    actionsEl.innerHTML = '<button class="btn btn-ghost" style="flex:1;justify-content:center">取消</button><button class="btn btn-primary" style="flex:1;justify-content:center">确定</button>';
    const btns = actionsEl.querySelectorAll('button');
    btns[0].onclick = function() { hideOverlay(); inputEl.style.display = 'none'; };
    btns[1].onclick = function() { hideOverlay(); inputEl.style.display = 'none'; };
    overlay.style.display = 'flex';
    return def || '';
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
  document.getElementById('gmd-msg').innerHTML = msg;
  const actionsEl = document.getElementById('gmd-actions');
  actionsEl.innerHTML = '<button class="btn btn-ghost" style="flex:1;justify-content:center">取消</button><button class="btn btn-primary" style="flex:1;justify-content:center">确定</button>';
  const btns = actionsEl.querySelectorAll('button');
  btns[0].onclick = function() { overlay.style.display = 'none'; if (cb) cb(false); };
  btns[1].onclick = function() { overlay.style.display = 'none'; if (cb) cb(true); };
  overlay.style.display = 'flex';
}
