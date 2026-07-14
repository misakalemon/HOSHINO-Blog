// 移动端抽屉菜单
function toggleDrawer(){
  document.getElementById('mobileDrawer').classList.toggle('open');
  document.getElementById('drawerOverlay').classList.toggle('show');
}
function openLightbox(src) {
  document.getElementById('lightboxImg').src = src;
  document.getElementById('lightbox').style.display = 'flex';
}
function closeLightbox() {
  document.getElementById('lightbox').style.display = 'none';
}

// ── 浏览器返回时恢复滚动位置 ──────────────
if ('scrollRestoration' in history) history.scrollRestoration = 'auto';

function toggleGlowSelect(t){
  var r=t.parentNode,u=r.classList.contains('is-open');
  if(u){r.classList.remove('is-open');return;}
  if(!r.getAttribute('data-multiple')){
    document.querySelectorAll('.glow-select-wrap.is-open').forEach(function(w){w.classList.remove('is-open')});
  }
  if(r.getAttribute('data-multiple')!==null){
    var c=r.querySelectorAll('.glow-select-option.is-selected').length;
    r.querySelector('.glow-select-value').textContent='已选 '+c+' 项';
  }
  r.classList.add('is-open');
}
document.addEventListener('click',function(e){
  var o=e.target.closest('.glow-select-option');
  if(o){
    var w=o.closest('.glow-select-wrap');if(!w)return;
    var v=o.getAttribute('data-value');
    if(w.getAttribute('data-multiple')!==null){
      o.classList.toggle('is-selected');
      var sel=w.querySelector('select');
      if(sel){
        for(var i=0;i<sel.options.length;i++){
          sel.options[i].selected=(sel.options[i].value===v)?!sel.options[i].selected:sel.options[i].selected;
        }
        sel.dispatchEvent(new Event('change',{bubbles:true}));
      }
      var c=w.querySelectorAll('.glow-select-option.is-selected').length;
      w.querySelector('.glow-select-value').textContent='已选 '+c+' 项';
    }else{
      var t=w.querySelector('.glow-select-trigger');
      if(t)t.querySelector('.glow-select-value').textContent=o.textContent;
      w.querySelectorAll('.glow-select-option').forEach(function(x){x.classList.toggle('is-selected',x===o)});
      w.classList.remove('is-open');
      var n=w.querySelector('select');
      if(n){n.value=v;n.dispatchEvent(new Event('change',{bubbles:true}))}
    }
    return;
  }
  if(!e.target.closest('.glow-select-wrap')){
    document.querySelectorAll('.glow-select-wrap.is-open').forEach(function(w){w.classList.remove('is-open')});
  }
});

// ── 全局弹窗（暗色粉紫风格，替换原生 alert/confirm/prompt）──
(function() {
  var overlay = document.createElement('div');
  overlay.className = 'glow-modal-overlay';
  overlay.innerHTML =
    '<div class="glow-modal">' +
      '<h4 id="gmd-title"></h4>' +
      '<p id="gmd-msg"></p>' +
      '<input class="glow-modal-input" id="gmd-input" style="display:none">' +
      '<div class="glow-modal-actions" id="gmd-actions"></div>' +
    '</div>';
  overlay.addEventListener('click', function(e) {
    if (e.target === overlay) overlay.style.display = 'none';
  });
  document.body.appendChild(overlay);
  var titleEl = document.getElementById('gmd-title');
  var msgEl = document.getElementById('gmd-msg');
  var inputEl = document.getElementById('gmd-input');
  var actionsEl = document.getElementById('gmd-actions');
  function hideOverlay() { overlay.style.display = 'none'; }
  window.alert = function(msg) {
    titleEl.textContent = '提示'; msgEl.innerHTML = msg;
    actionsEl.innerHTML = '<button class="btn btn-primary" style="flex:1;justify-content:center">确定</button>';
    actionsEl.querySelector('button').onclick = hideOverlay;
    overlay.style.display = 'flex';
  };
  window.confirm = function(msg, cb) {
    if (typeof cb !== 'function') return true;
    titleEl.textContent = '确认操作'; msgEl.innerHTML = msg;
    actionsEl.innerHTML = '<button class="btn btn-ghost" style="flex:1;justify-content:center">取消</button><button class="btn btn-primary" style="flex:1;justify-content:center">确定</button>';
    var btns = actionsEl.querySelectorAll('button');
    btns[0].onclick = function() { hideOverlay(); cb(false); };
    btns[1].onclick = function() { hideOverlay(); cb(true); };
    overlay.style.display = 'flex';
  };
  window.prompt = function(msg, def) {
    titleEl.textContent = '输入'; msgEl.innerHTML = msg;
    inputEl.style.display = 'block'; inputEl.value = def || '';
    actionsEl.innerHTML = '<button class="btn btn-ghost" style="flex:1;justify-content:center">取消</button><button class="btn btn-primary" style="flex:1;justify-content:center">确定</button>';
    var btns = actionsEl.querySelectorAll('button');
    btns[0].onclick = function() { hideOverlay(); inputEl.style.display = 'none'; };
    btns[1].onclick = function() { hideOverlay(); inputEl.style.display = 'none'; };
    overlay.style.display = 'flex';
    return def || '';
  };
})();

// showConfirm — 用于替换 onsubmit 中的 return confirm()
function showConfirm(msg, cb) {
  var overlay = document.querySelector('.glow-modal-overlay');
  if (!overlay) { if (cb) cb(true); return; }
  document.getElementById('gmd-input').style.display = 'none';
  document.getElementById('gmd-title').textContent = '确认操作';
  document.getElementById('gmd-msg').innerHTML = msg;
  var actionsEl = document.getElementById('gmd-actions');
  actionsEl.innerHTML = '<button class="btn btn-ghost" style="flex:1;justify-content:center">取消</button><button class="btn btn-primary" style="flex:1;justify-content:center">确定</button>';
  var btns = actionsEl.querySelectorAll('button');
  btns[0].onclick = function() { overlay.style.display = 'none'; if (cb) cb(false); };
  btns[1].onclick = function() { overlay.style.display = 'none'; if (cb) cb(true); };
  overlay.style.display = 'flex';
}
