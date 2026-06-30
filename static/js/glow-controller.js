/* ═══════════════════════════════════════════════
   Glow Controller v2.0
   光感设计系统 — 鼠标追踪光效 & 交互控制
   ═══════════════════════════════════════════════ */

/* ── 1. 卡片鼠标追踪光效 (CSS custom property) ── */
(function() {
  var CONFIG = { maxDist: 200, opacityMin: 0, opacityMax: 1 };
  var cards = document.querySelectorAll('.glass-card[data-glow], .admin-card[data-glow], .featured-card[data-glow]');
  if (!cards.length) return;

  var cardData = [];
  cards.forEach(function(card) { cardData.push({ card: card, rect: null }); });

  /* 仅在 resize/scroll 时更新 rect，rAF 循环中不再调用 */
  function updateRects() {
    cardData.forEach(function(data) { data.rect = data.card.getBoundingClientRect(); });
  }

  var mouseX = -9999, mouseY = -9999, rafId = null;

  function onMouseMove(e) {
    mouseX = e.clientX; mouseY = e.clientY;
    if (rafId) return;
    rafId = requestAnimationFrame(function() { updateGlow(); rafId = null; });
  }

  /* 核心计算：使用缓存的 rect，不触发回流 */
  function updateGlow() {
    var mx = mouseX, my = mouseY, maxDist = CONFIG.maxDist;
    cardData.forEach(function(data) {
      var rect = data.rect;
      if (!rect) return;
      var dx = 0;
      if (mx < rect.left) dx = rect.left - mx;
      else if (mx > rect.right) dx = mx - rect.right;
      var dy = 0;
      if (my < rect.top) dy = rect.top - my;
      else if (my > rect.bottom) dy = my - rect.bottom;
      var dist = Math.sqrt(dx * dx + dy * dy);
      var opacity = 0;
      if (dist < maxDist) {
        var t = 1 - (dist / maxDist);
        t = t * t;
        opacity = CONFIG.opacityMin + (CONFIG.opacityMax - CONFIG.opacityMin) * t;
      }
      var px = 50, py = 50;
      if (mx < rect.left) px = 0;
      else if (mx > rect.right) px = 100;
      else px = ((mx - rect.left) / rect.width) * 100;
      if (my < rect.top) py = 0;
      else if (my > rect.bottom) py = 100;
      else py = ((my - rect.top) / rect.height) * 100;
      px = Math.min(100, Math.max(0, px));
      py = Math.min(100, Math.max(0, py));
      data.card.style.setProperty('--gx', px + '%');
      data.card.style.setProperty('--gy', py + '%');
      data.card.style.setProperty('--glow-opacity', opacity);
      data.card.style.setProperty('--glow-intensity', opacity);
    });
  }

  document.addEventListener('mousemove', onMouseMove);
  document.addEventListener('mouseleave', function() {
    cardData.forEach(function(data) {
      data.card.style.setProperty('--glow-opacity', 0);
      data.card.style.setProperty('--glow-intensity', 0);
    });
  });
  /* resize 只更新 rect；scroll 更新 rect 后触发一次 glow 刷新 */
  window.addEventListener('resize', updateRects);
  window.addEventListener('scroll', function() { updateRects(); updateGlow(); });

  updateRects();
  cardData.forEach(function(data) {
    data.card.style.setProperty('--glow-opacity', 0);
    data.card.style.setProperty('--glow-intensity', 0);
  });

  var observer = new MutationObserver(function() {
    document.querySelectorAll('.glass-card[data-glow], .admin-card[data-glow], .featured-card[data-glow]').forEach(function(card) {
      if (!card._glowInit) {
        card._glowInit = true;
        cardData.push({ card: card, rect: null });
      }
    });
  });
  observer.observe(document.body, { childList: true, subtree: true });
})();

/* ── 2. 导航控制 ────────────────────────────── */
/** 切换移动端抽屉菜单的打开/关闭状态 */
function toggleDrawer() {
  document.getElementById('mobileDrawer').classList.toggle('open');
  document.getElementById('drawerOverlay').classList.toggle('show');
}

/** 切换后台管理侧边栏的打开/关闭状态 */
function toggleAdminSidebar() {
  document.getElementById('adminToggle').classList.toggle('open');
  document.getElementById('adminSidebar').classList.toggle('open');
  document.getElementById('adminOverlay').classList.toggle('show');
}

/* ── 3. 工具函数 ────────────────────────────── */
/**
 * 在工具页中切换到指定工具面板。
 * @param {string} name - 工具名称，对应 tool-pane 的 id 后缀
 */
function switchTool(name) {
  document.querySelectorAll('.tool-pane').forEach(function(p) { p.classList.remove('active'); });
  document.querySelectorAll('.tools-nav-btn').forEach(function(t) { t.classList.remove('active'); });
  document.getElementById('tool-' + name).classList.add('active');
  var btn = document.querySelector('.tools-nav-btn[data-tool="' + name + '"]');
  if (btn) btn.classList.add('active');
}

/* ---- Base64 编解码 ---- */
/** 将输入文本编码为 Base64（先 UTF-8 编码再 btoa） */
function b64Encode() {
  document.getElementById('b64-output').value = btoa(unescape(encodeURIComponent(document.getElementById('b64-input').value)));
}
/** 将 Base64 解码为原文，解码失败时显示中文错误提示 */
function b64Decode() {
  try {
    document.getElementById('b64-output').value = decodeURIComponent(escape(atob(document.getElementById('b64-input').value)));
  } catch(e) {
    document.getElementById('b64-output').value = '解码失败: 无效的 Base64';
  }
}

/* ---- 字数统计 ---- */
/** 统计输入文本的字符数（去空格/含空格）、行数，实时更新到 DOM */
function wordCount() {
  var t = document.getElementById('wc-input').value;
  document.getElementById('wc-chars').textContent = t.replace(/\s/g,'').length;
  document.getElementById('wc-chars-sp').textContent = t.length;
  document.getElementById('wc-lines').textContent = t ? t.split('\n').length : 0;
}

/* ---- 颜色转换 — 重新排版 ──────────────── */
(function(){
'use strict';

function hexToRgb(hex){var c=hex.replace('#','');if(!/^[0-9a-f]{6}$/i.test(c))return null;return{r:parseInt(c[0]+c[1],16),g:parseInt(c[2]+c[3],16),b:parseInt(c[4]+c[5],16)}}
function rgbToHsl(r,g,b){var rr=r/255,gg=g/255,bb=b/255,mx=Math.max(rr,gg,bb),mn=Math.min(rr,gg,bb),h,s,l=(mx+mn)/2;if(mx===mn){h=s=0}else{var d=mx-mn;s=l>0.5?d/(2-mx-mn):d/(mx+mn);switch(mx){case rr:h=((gg-bb)/d+(gg<bb?6:0))/6;break;case gg:h=((bb-rr)/d+2)/6;break;case bb:h=((rr-gg)/d+4)/6;break}}return{h:Math.round(h*360),s:Math.round(s*100),l:Math.round(l*100)}}
function hslToRgb(h,s,l){var ss=s/100,ll=l/100,k=function(n){return(n+h/30)%12},a=ss*Math.min(ll,1-ll),f=function(n){return ll-a*Math.max(-1,Math.min(k(n)-3,9-k(n),1))};return{r:Math.round(f(0)*255),g:Math.round(f(8)*255),b:Math.round(f(4)*255)}}
function toHex(n){return Math.min(255,Math.max(0,Math.round(n))).toString(16).padStart(2,'0').toUpperCase()}
function clamp(v,mi,ma){return Math.min(ma,Math.max(mi,v))}

var presetColors=['#EF4444','#F97316','#EAB308','#22C55E','#14B8A6','#3B82F6','#8B5CF6','#EC4899','#6C42D1','#1E293B','#64748B','#94A3B8','#F8FAFC','#FFFFFF','#000000','#FCD34D'];
var currentHue=258,currentSat=62,currentLight=54,currentHex='#6C42D1';
var panelOpen=false,draggingSV=false,draggingHue=false;
var toastTimer=null;

function renderSV(){
  var wrap=document.getElementById('svWrap');if(!wrap)return;
  var c=document.getElementById('svCanvas'),w=wrap.clientWidth,h=wrap.clientHeight||w,dpr=window.devicePixelRatio||1;
  c.width=w*dpr;c.height=h*dpr;c.style.width=w+'px';c.style.height=h+'px';
  var ctx=c.getContext('2d');ctx.scale(dpr,dpr);
  var img=ctx.createImageData(w,h),d=img.data;
  for(var y=0;y<h;y++)for(var x=0;x<w;x++){var s=x/w*100,l=(1-y/h)*100,rgb=hslToRgb(currentHue,s,l),idx=(y*w+x)*4;d[idx]=rgb.r;d[idx+1]=rgb.g;d[idx+2]=rgb.b;d[idx+3]=255;}
  ctx.putImageData(img,0,0);
  var cur=document.getElementById('svCursor');if(cur){cur.style.left=(currentSat/100*w)+'px';cur.style.top=((1-currentLight/100)*h)+'px';}
}
function renderHue(){
  var wrap=document.getElementById('hueWrap');if(!wrap)return;
  var c=document.getElementById('hueCanvas'),w=wrap.clientWidth,h=wrap.clientHeight||200,dpr=window.devicePixelRatio||1;
  c.width=w*dpr;c.height=h*dpr;c.style.width=w+'px';c.style.height=h+'px';
  var ctx=c.getContext('2d');ctx.scale(dpr,dpr);
  var grd=ctx.createLinearGradient(0,0,0,h);
  for(var i=0;i<=6;i++){var hue=(i/6)*360,rgb=hslToRgb(hue,100,50);grd.addColorStop(i/6,'rgb('+rgb.r+','+rgb.g+','+rgb.b+')');}
  ctx.fillStyle=grd;ctx.fillRect(0,0,w,h);
  var hdl=document.getElementById('hueHandle');if(hdl)hdl.style.top=(currentHue/360*h)+'px';
}
function updateAllUI(){
  var rgb=hslToRgb(currentHue,currentSat,currentLight),hex='#'+toHex(rgb.r)+toHex(rgb.g)+toHex(rgb.b);currentHex=hex;
  var ps=document.getElementById('previewSwatch'),ts=document.getElementById('triggerSwatch');
  if(ps)ps.style.background=hex;if(ts)ts.style.background=hex;
  var ph=document.getElementById('previewHex');if(ph)ph.textContent=hex.replace('#','');
  var pr=document.getElementById('previewRgb'),phsl=document.getElementById('previewHsl');
  if(pr)pr.textContent='rgb('+rgb.r+','+rgb.g+','+rgb.b+')';
  if(phsl)phsl.textContent='hsl('+Math.round(rgbToHsl(rgb.r,rgb.g,rgb.b).h)+','+Math.round(rgbToHsl(rgb.r,rgb.g,rgb.b).s)+'%,'+Math.round(rgbToHsl(rgb.r,rgb.g,rgb.b).l)+'%)';
  var hx=document.getElementById('colorHex');if(hx)hx.value=hex.replace('#','');
  var rE=document.getElementById('colorR'),gE=document.getElementById('colorG'),bE=document.getElementById('colorB');
  if(rE)rE.value=rgb.r;if(gE)gE.value=rgb.g;if(bE)bE.value=rgb.b;
  var hsl=rgbToHsl(rgb.r,rgb.g,rgb.b);
  var hE=document.getElementById('colorH'),sE=document.getElementById('colorS'),lE=document.getElementById('colorL');
  if(hE)hE.value=hsl.h;if(sE)sE.value=hsl.s;if(lE)lE.value=hsl.l;
  document.querySelectorAll('.preset-swatch').forEach(function(el){el.classList.toggle('active',el.dataset.hex.toLowerCase()===hex.toLowerCase())});
}
function renderAll(){renderSV();renderHue();updateAllUI();}

function updateFromHex(hex){
  var rgb=hexToRgb(hex);if(!rgb)return;
  var hsl=rgbToHsl(rgb.r,rgb.g,rgb.b);currentHue=hsl.h;currentSat=hsl.s;currentLight=hsl.l;
  updateAllUI();if(panelOpen){renderSV();renderHue();}
}
function updateFromHexInput(){
  var v=document.getElementById('colorHex').value.replace(/[^0-9a-f]/gi,'').toUpperCase().slice(0,6);
  document.getElementById('colorHex').value=v;if(v.length===6)updateFromHex('#'+v);
}
function updateFromRgbInputs(){
  var r=clamp(parseInt(document.getElementById('colorR').value)||0,0,255);
  var g=clamp(parseInt(document.getElementById('colorG').value)||0,0,255);
  var b=clamp(parseInt(document.getElementById('colorB').value)||0,0,255);
  var hsl=rgbToHsl(r,g,b);currentHue=hsl.h;currentSat=hsl.s;currentLight=hsl.l;
  updateAllUI();if(panelOpen){renderSV();renderHue();}
}
function updateFromHslInputs(){
  var h=clamp(parseFloat(document.getElementById('colorH').value)||0,0,360);
  var s=clamp(parseFloat(document.getElementById('colorS').value)||0,0,100);
  var l=clamp(parseFloat(document.getElementById('colorL').value)||0,0,100);
  currentHue=h;currentSat=s;currentLight=l;
  updateAllUI();if(panelOpen){renderSV();renderHue();}
}

function showToast(msg){
  var t=document.getElementById('colorToast');if(!t)return;
  t.textContent=msg||'✅ 已复制';t.classList.add('show');
  clearTimeout(toastTimer);toastTimer=setTimeout(function(){t.classList.remove('show')},1500);
}
window.copyColor=function(type){
  var rgb=hexToRgb(currentHex);if(!rgb)return;
  var hsl=rgbToHsl(rgb.r,rgb.g,rgb.b),text=type==='hex'?currentHex:type==='rgb'?'rgb('+rgb.r+','+rgb.g+','+rgb.b+')':'hsl('+hsl.h+','+hsl.s+'%,'+hsl.l+'%)';
  if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(text).then(function(){showToast('✅ 已复制 '+type.toUpperCase());});}
  else{var inp=document.createElement('input');inp.value=text;document.body.appendChild(inp);inp.select();try{document.execCommand('copy');showToast('✅ 已复制');}catch(e){alert('复制失败: '+text);}document.body.removeChild(inp);}
};

function openPanel(){
  document.getElementById('colorPanelOverlay').classList.add('open');
  document.getElementById('triggerArrow').classList.add('open');
  panelOpen=true;setTimeout(function(){renderSV();renderHue();},50);
}
function closePanel(){
  document.getElementById('colorPanelOverlay').classList.remove('open');
  document.getElementById('triggerArrow').classList.remove('open');
  panelOpen=false;
}
function togglePanel(){if(panelOpen)closePanel();else openPanel();}

document.addEventListener('DOMContentLoaded',function(){
  var grid=document.getElementById('presetsGrid');if(!grid||grid._init)return;grid._init=true;
  presetColors.forEach(function(hex){
    var el=document.createElement('div');el.className='preset-swatch';
    el.style.background=hex;el.dataset.hex=hex;el.setAttribute('title',hex);
    if(hex==='#FFFFFF'||hex==='#F8FAFC'||hex==='#FCD34D')el.classList.add('bl');
    el.addEventListener('click',function(){updateFromHex(this.dataset.hex);});
    grid.appendChild(el);
  });
  updateAllUI();

  var ps=document.getElementById('previewSwatch');if(ps)ps.addEventListener('click',function(){window.copyColor('hex');});
  var tr=document.getElementById('colorTrigger');if(tr)tr.addEventListener('click',togglePanel);
  var pb=document.getElementById('panelCloseBtn');if(pb)pb.addEventListener('click',closePanel);
  var cb=document.getElementById('confirmColorBtn');if(cb)cb.addEventListener('click',function(){closePanel();showToast('✅ 颜色已应用');});
  var eb=document.getElementById('eyedropperBtn');if(eb)eb.addEventListener('click',async function(){
    if(!window.EyeDropper){showToast('⚠️ 当前浏览器不支持吸管');return;}
    try{var res=await new EyeDropper().open();updateFromHex(res.sRGBHex);showToast('✅ 已取色: '+res.sRGBHex);renderSV();renderHue();}
    catch(e){if(e.message!=='User cancelled')showToast('⚠️ 取色取消');}
  });
  var ov=document.getElementById('colorPanelOverlay');if(ov)ov.addEventListener('click',function(e){if(e.target===ov)closePanel();});

  var sv=document.getElementById('svWrap');
  if(sv){sv.addEventListener('mousedown',function(e){draggingSV=true;handleSVMove(e);});
    document.addEventListener('mousemove',function(e){if(draggingSV)handleSVMove(e);});
    document.addEventListener('mouseup',function(){draggingSV=false;});
    sv.addEventListener('touchstart',function(e){draggingSV=true;handleSVMove(e);},{passive:false});
    sv.addEventListener('touchmove',function(e){if(draggingSV)handleSVMove(e);},{passive:false});
    sv.addEventListener('touchend',function(){draggingSV=false;});}
  function getSVCoords(e){var r=document.getElementById('svWrap').getBoundingClientRect();return{x:clamp(((e.clientX||e.touches?.[0]?.clientX||0)-r.left)/r.width,0,1),y:clamp(((e.clientY||e.touches?.[0]?.clientY||0)-r.top)/r.height,0,1)};}
  function handleSVMove(e){e.preventDefault();var p=getSVCoords(e);currentSat=Math.round(p.x*100);currentLight=Math.round((1-p.y)*100);updateAllUI();renderSV();renderHue();}

  var hu=document.getElementById('hueWrap');
  if(hu){hu.addEventListener('mousedown',function(e){draggingHue=true;handleHueMove(e);});
    document.addEventListener('mousemove',function(e){if(draggingHue)handleHueMove(e);});
    document.addEventListener('mouseup',function(){draggingHue=false;});
    hu.addEventListener('touchstart',function(e){draggingHue=true;handleHueMove(e);},{passive:false});
    hu.addEventListener('touchmove',function(e){if(draggingHue)handleHueMove(e);},{passive:false});
    hu.addEventListener('touchend',function(){draggingHue=false;});}
  function handleHueMove(e){e.preventDefault();var r=document.getElementById('hueWrap').getBoundingClientRect(),y=clamp(((e.clientY||e.touches?.[0]?.clientY||0)-r.top)/r.height,0,1);currentHue=Math.round(y*360);updateAllUI();renderSV();renderHue();}

  var hx=document.getElementById('colorHex');if(hx)hx.addEventListener('input',updateFromHexInput);
  [document.getElementById('colorR'),document.getElementById('colorG'),document.getElementById('colorB')].forEach(function(el){
    if(!el)return;el.addEventListener('input',updateFromRgbInputs);
    el.addEventListener('blur',function(){var v=parseInt(this.value);if(isNaN(v))v=0;this.value=clamp(v,0,255);updateFromRgbInputs();});
  });
  [document.getElementById('colorH'),document.getElementById('colorS'),document.getElementById('colorL')].forEach(function(el){
    if(!el)return;el.addEventListener('input',updateFromHslInputs);
    el.addEventListener('blur',function(){var v=parseInt(this.value);if(isNaN(v))v=0;var mx=this.id==='colorH'?360:100;this.value=clamp(v,0,mx);updateFromHslInputs();});
  });

  document.addEventListener('keydown',function(e){if(e.key==='Escape'&&panelOpen)closePanel();if(e.key==='Enter'&&panelOpen){closePanel();showToast('✅ 颜色已应用');}});
  var rt;window.addEventListener('resize',function(){clearTimeout(rt);rt=setTimeout(function(){if(panelOpen){renderSV();renderHue();}},100);});
});
})();

/* ---- JSON 格式化 ---- */
/** 美化 JSON（带缩进 2 空格），解析失败则显示错误信息 */
function jsonFormat() {
  try { var o = JSON.parse(document.getElementById('json-input').value); document.getElementById('json-output').value = JSON.stringify(o,null,2); }
  catch(e) { document.getElementById('json-output').value = 'JSON 格式错误: ' + e.message; }
}
/** 压缩 JSON（无多余空格） */
function jsonCompact() {
  try { var o = JSON.parse(document.getElementById('json-input').value); document.getElementById('json-output').value = JSON.stringify(o); }
  catch(e) { document.getElementById('json-output').value = 'JSON 格式错误: ' + e.message; }
}

/* ---- 时间戳 ---- */
/** 初始化时间戳工具：填充当前 Unix 秒数和可读时间 */
function initTimestamp() {
  document.getElementById('ts-unix').value = Math.floor(Date.now()/1000);
  document.getElementById('ts-datetime').value = new Date().toISOString().slice(0,19).replace('T',' ');
  tsFromUnix(document.getElementById('ts-unix').value);
}
/** 从 Unix 秒数转换为可读时间 */
function tsFromUnix(ts) {
  var n = parseInt(ts); if (!isNaN(n)) { var d=new Date(n*1000); document.getElementById('ts-datetime').value=d.toISOString().slice(0,19).replace('T',' '); showTsResult(n); }
}
/** 从可读时间字符串转换为 Unix 秒数 */
function tsFromDatetime(dt) {
  var d = new Date(dt); if (!isNaN(d.getTime())) { var u=Math.floor(d.getTime()/1000); document.getElementById('ts-unix').value=u; showTsResult(u); }
}
/** 获取当前时间戳（快捷按钮） */
function tsNow() { initTimestamp(); }
/** 显示时间戳详信息：Unix 秒/毫秒、UTC 时间、本地时间 */
function showTsResult(ts) {
  var d = new Date(ts*1000);
  document.getElementById('ts-result').innerHTML = 'Unix 秒: <strong>'+ts+'</strong><br>Unix 毫秒: <strong>'+(ts*1000)+'</strong><br>UTC: <strong>'+d.toUTCString()+'</strong><br>本地: <strong>'+d.toLocaleString()+'</strong>';
}

/* ---- 哈希计算 ---- */
function calcHash() {
  var t = document.getElementById('hash-input').value;
  var ids = ['hash-md5','hash-sha1','hash-sha256','hash-sha384','hash-sha512'];
  if (!t) { ids.forEach(function(id){document.getElementById(id).value='';}); return; }
  document.getElementById('hash-md5').value = md5(t);
  var enc = new TextEncoder().encode(t);
  crypto.subtle.digest('SHA-1', enc).then(function(b){ document.getElementById('hash-sha1').value = buf2hex(b); });
  crypto.subtle.digest('SHA-256', enc).then(function(b){ document.getElementById('hash-sha256').value = buf2hex(b); });
  crypto.subtle.digest('SHA-384', enc).then(function(b){ document.getElementById('hash-sha384').value = buf2hex(b); });
  crypto.subtle.digest('SHA-512', enc).then(function(b){ document.getElementById('hash-sha512').value = buf2hex(b); });
}
function buf2hex(b) { return Array.from(new Uint8Array(b)).map(function(x){return ('0'+x.toString(16)).slice(-2)}).join(''); }
/* 纯 JS MD5 实现（Web Crypto API 不支持 MD5） */
function md5(s) {
  function F(x,y,z){return (x&y)|(~x&z);} function G(x,y,z){return (x&z)|(y&~z);} function H(x,y,z){return x^y^z;} function I(x,y,z){return y^(x|~z);}
  function R(x,s){return (x<<s)|(x>>>(32-s));}
  function FF(a,b,c,d,x,s,ac){a=R((a+F(b,c,d)+x+ac)|0,s)+b|0;return a;}
  function GG(a,b,c,d,x,s,ac){a=R((a+G(b,c,d)+x+ac)|0,s)+b|0;return a;}
  function HH(a,b,c,d,x,s,ac){a=R((a+H(b,c,d)+x+ac)|0,s)+b|0;return a;}
  function II(a,b,c,d,x,s,ac){a=R((a+I(b,c,d)+x+ac)|0,s)+b|0;return a;}
  var T=[], i, n, X=[], blk, a=0x67452301,b=0xefcdab89,c=0x98badcfe,d=0x10325476;
  for(i=1;i<=64;i++) T[i]=(0x100000000*Math.abs(Math.sin(i)))|0;
  s=unescape(encodeURIComponent(s));
  n=s.length;
  for(i=0;i<n;i++) X[i>>2]|=s.charCodeAt(i)<<((i%4)*8);
  X[n>>2]|=0x80<<((n%4)*8);
  X[((n+8)>>6)+15]=(n*8);
  for(blk=0;blk<X.length;blk+=16) {
    var aa=a,bb=b,cc=c,dd=d, x=X.slice(blk,blk+16);
    a=FF(a,b,c,d,x[0],7,T[1]);d=FF(d,a,b,c,x[1],12,T[2]);c=FF(c,d,a,b,x[2],17,T[3]);b=FF(b,c,d,a,x[3],22,T[4]);
    a=FF(a,b,c,d,x[4],7,T[5]);d=FF(d,a,b,c,x[5],12,T[6]);c=FF(c,d,a,b,x[6],17,T[7]);b=FF(b,c,d,a,x[7],22,T[8]);
    a=FF(a,b,c,d,x[8],7,T[9]);d=FF(d,a,b,c,x[9],12,T[10]);c=FF(c,d,a,b,x[10],17,T[11]);b=FF(b,c,d,a,x[11],22,T[12]);
    a=FF(a,b,c,d,x[12],7,T[13]);d=FF(d,a,b,c,x[13],12,T[14]);c=FF(c,d,a,b,x[14],17,T[15]);b=FF(b,c,d,a,x[15],22,T[16]);
    a=GG(a,b,c,d,x[1],5,T[17]);d=GG(d,a,b,c,x[6],9,T[18]);c=GG(c,d,a,b,x[11],14,T[19]);b=GG(b,c,d,a,x[0],20,T[20]);
    a=GG(a,b,c,d,x[5],5,T[21]);d=GG(d,a,b,c,x[10],9,T[22]);c=GG(c,d,a,b,x[15],14,T[23]);b=GG(b,c,d,a,x[4],20,T[24]);
    a=GG(a,b,c,d,x[9],5,T[25]);d=GG(d,a,b,c,x[14],9,T[26]);c=GG(c,d,a,b,x[3],14,T[27]);b=GG(b,c,d,a,x[8],20,T[28]);
    a=GG(a,b,c,d,x[13],5,T[29]);d=GG(d,a,b,c,x[2],9,T[30]);c=GG(c,d,a,b,x[7],14,T[31]);b=GG(b,c,d,a,x[12],20,T[32]);
    a=HH(a,b,c,d,x[5],4,T[33]);d=HH(d,a,b,c,x[8],11,T[34]);c=HH(c,d,a,b,x[11],16,T[35]);b=HH(b,c,d,a,x[14],23,T[36]);
    a=HH(a,b,c,d,x[1],4,T[37]);d=HH(d,a,b,c,x[4],11,T[38]);c=HH(c,d,a,b,x[7],16,T[39]);b=HH(b,c,d,a,x[10],23,T[40]);
    a=HH(a,b,c,d,x[13],4,T[41]);d=HH(d,a,b,c,x[0],11,T[42]);c=HH(c,d,a,b,x[3],16,T[43]);b=HH(b,c,d,a,x[6],23,T[44]);
    a=HH(a,b,c,d,x[9],4,T[45]);d=HH(d,a,b,c,x[12],11,T[46]);c=HH(c,d,a,b,x[15],16,T[47]);b=HH(b,c,d,a,x[2],23,T[48]);
    a=II(a,b,c,d,x[0],6,T[49]);d=II(d,a,b,c,x[7],10,T[50]);c=II(c,d,a,b,x[14],15,T[51]);b=II(b,c,d,a,x[5],21,T[52]);
    a=II(a,b,c,d,x[12],6,T[53]);d=II(d,a,b,c,x[3],10,T[54]);c=II(c,d,a,b,x[10],15,T[55]);b=II(b,c,d,a,x[1],21,T[56]);
    a=II(a,b,c,d,x[8],6,T[57]);d=II(d,a,b,c,x[15],10,T[58]);c=II(c,d,a,b,x[6],15,T[59]);b=II(b,c,d,a,x[13],21,T[60]);
    a=II(a,b,c,d,x[4],6,T[61]);d=II(d,a,b,c,x[11],10,T[62]);c=II(c,d,a,b,x[2],15,T[63]);b=II(b,c,d,a,x[9],21,T[64]);
    a=(a+aa)|0;b=(b+bb)|0;c=(c+cc)|0;d=(d+dd)|0;
  }
  return [a,b,c,d].map(function(v){return ('00000000'+(v>>>0).toString(16)).slice(-8);}).join('');
}

/** 清空指定工具面板下所有 textarea 的内容 */
function clearTool(name) {
  document.querySelectorAll('#tool-' + name + ' textarea').forEach(function(t){ t.value=''; });
}

/* ---- 图片压缩 ---- */
var izSrcImg = null, izBlobUrl = null;
/** 触发文件选择器（隐藏 input） */
function izSelect() { document.getElementById('iz-input').click(); }
/** 加载用户选择的图片，读取到 Image 对象并显示原始预览和基本信息 */
function izLoad() {
  var f = document.getElementById('iz-input').files[0];
  if (!f) return;
  var reader = new FileReader();
  reader.onload = function(e) {
    var img = new Image();
    img.onload = function() {
      izSrcImg = img;
      document.getElementById('iz-original').innerHTML = '<img src="'+e.target.result+'" style="max-width:100%;max-height:140px;border-radius:6px">';
      var kb = (f.size / 1024).toFixed(1);
      document.getElementById('iz-originfo').textContent = img.width+'\u00D7'+img.height+' \u00B7 '+kb+'KB \u00B7 '+f.type;
      izUpdate();
    };
    img.src = e.target.result;
  };
  reader.readAsDataURL(f);
}
/**
 * 根据用户调节的质量、最大宽度、输出格式参数，
 * 在 Canvas 上重绘并导出为 Blob，实时显示压缩预览和文件大小。
 */
function izUpdate() {
  if (!izSrcImg) return;
  var q = parseInt(document.getElementById('iz-quality').value);
  document.getElementById('iz-q-val').textContent = q + '%';
  var maxw = parseInt(document.getElementById('iz-maxw').value);
  var fmt = document.getElementById('iz-fmt').value;
  var w = izSrcImg.width, h = izSrcImg.height;
  if (maxw > 0 && w > maxw) { h = Math.round(h * maxw / w); w = maxw; }
  var c = document.createElement('canvas');
  c.width = w; c.height = h;
  var ctx = c.getContext('2d');
  ctx.drawImage(izSrcImg, 0, 0, w, h);
  c.toBlob(function(blob) {
    /* 释放上一次生成的 Blob URL，避免内存泄漏 */
    if (izBlobUrl) URL.revokeObjectURL(izBlobUrl);
    izBlobUrl = URL.createObjectURL(blob);
    document.getElementById('iz-result').innerHTML = '<img src="'+izBlobUrl+'" style="max-width:100%;max-height:140px;border-radius:6px">';
    var kb = (blob.size / 1024).toFixed(1);
    document.getElementById('iz-resinfo').textContent = w+'\u00D7'+h+' \u00B7 '+kb+'KB';
    document.getElementById('iz-dlbtn').disabled = false;
  }, fmt, q/100);
}
/** 将压缩后的图片作为文件下载到本地 */
function izDownload() {
  if (!izBlobUrl) return;
  var a = document.createElement('a');
  a.href = izBlobUrl;
  var ext = { 'image/jpeg':'.jpg','image/webp':'.webp','image/png':'.png' };
  a.download = 'compressed' + (ext[document.getElementById('iz-fmt').value] || '.jpg');
  a.click();
}

/* ── 4. 自定义下拉框 ────────────────────────── */
/**
 * 初始化所有自定义下拉框：
 * 1. 自动将原生 <select> 包装为 glow-select-wrap
 * 2. 绑定点击展开/收起、选项选择、全局点击关闭等交互
 */
function initGlowSelects() {
  /* 自动包装原生 <select> → glow-select-wrap（排除已包装的） */
  document.querySelectorAll('select:not([multiple])').forEach(function(select) {
    if (select.closest('.glow-select-wrap')) return;
    if (!select.options.length) return;
    var selected = select.options[select.selectedIndex];
    var wrap = document.createElement('div');
    wrap.className = 'glow-select-wrap';
    var trigger = document.createElement('div');
    trigger.className = 'glow-select-trigger';
    var label = document.createElement('span');
    label.textContent = selected ? selected.text : '选择';
    var arrow = document.createElement('span');
    arrow.className = 'glow-select-arrow';
    arrow.textContent = '▼';
    trigger.appendChild(label); trigger.appendChild(arrow);
    var menu = document.createElement('div');
    menu.className = 'glow-select-menu';
    /* 遍历原生 option 生成自定义菜单项 */
    Array.from(select.options).forEach(function(opt) {
      var item = document.createElement('div');
      item.className = 'glow-select-option' + (opt.selected ? ' is-selected' : '');
      item.dataset.value = opt.value; item.textContent = opt.text;
      menu.appendChild(item);
    });
    select.style.display = 'none';
    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(trigger); wrap.appendChild(select); wrap.appendChild(menu);
  });

  /* 初始化所有 wrap：绑定事件、设置默认值 */
  document.querySelectorAll('.glow-select-wrap').forEach(function(wrap) {
    if (wrap._glowSelectInit) return;
    wrap._glowSelectInit = true;
    var native = wrap.querySelector('.glow-select-native') || wrap.querySelector('select');
    var trigger = wrap.querySelector('.glow-select-trigger');
    var menu = wrap.querySelector('.glow-select-menu');
    if (!native || !trigger || !menu) return;

    /**
     * 更新下拉框的选中状态：
     * 修改 trigger 文本、标记菜单项、更新原生 select 的值。
     * @param {string} val - 新选中的 value
     * @param {boolean} fireChange - 是否触发原生 change 事件
     */
    function update(val, fireChange) {
      var label = val;
      menu.querySelectorAll('.glow-select-option').forEach(function(o) {
        var isSel = o.dataset.value === val;
        o.classList.toggle('is-selected', isSel);
        if (isSel) label = o.textContent;
      });
      trigger.childNodes[0].textContent = label;
      native.value = val;
      if (fireChange) {
        native.dispatchEvent(new Event('change', { bubbles: true }));
      }
    }

    /* 点击 trigger 切换展开状态，同时关闭其他已展开的下拉框 */
    trigger.addEventListener('click', function(e) {
      e.stopPropagation();
      var wasOpen = wrap.classList.contains('is-open');
      document.querySelectorAll('.glow-select-wrap.is-open').forEach(function(w) {
        w.classList.remove('is-open');
      });
      if (!wasOpen) wrap.classList.add('is-open');
    });

    /* 点击选项后选中该项并收起菜单 */
    menu.querySelectorAll('.glow-select-option').forEach(function(opt) {
      opt.addEventListener('click', function() {
        update(opt.dataset.value, true);
        wrap.classList.remove('is-open');
      });
    });

    native.style.display = 'none';
    update(native.value, false);
  });

  /* 点击页面任意空白处关闭所有已展开的下拉框 */
  document.addEventListener('click', function() {
    document.querySelectorAll('.glow-select-wrap.is-open').forEach(function(w) {
      w.classList.remove('is-open');
    });
  });
}

initGlowSelects();

/* ── 5. 图片灯箱 ────────────────────────────── */
/** 以全屏灯箱方式展示大图，滚动条锁定防止背景滚动 */
function openLightbox(src) {
  var lb = document.getElementById('lightbox');
  var img = document.getElementById('lightboxImg');
  img.src = src;
  lb.style.display = 'flex';
  document.body.style.overflow = 'hidden';
}
/** 关闭灯箱，恢复页面滚动 */
function closeLightbox() {
  document.getElementById('lightbox').style.display = 'none';
  document.body.style.overflow = '';
}

/* ── 6. 星空粒子生成器 ──────────────────────── */
(function() {
  var bg = document.querySelector('.glow-bg');
  if (!bg || bg.querySelector('.stars')) return;
  var container = document.createElement('div');
  container.className = 'stars';
  container.style.cssText = 'position:absolute;inset:0;overflow:hidden;pointer-events:none';
  bg.appendChild(container);
  var frag = document.createDocumentFragment();
  for (var i = 0; i < 90; i++) {
    var el = document.createElement('div');
    el.className = 'star' + (i % 7 === 0 ? ' star-lg' : '');
    el.style.cssText = 'left:' + (Math.random() * 100) + '%;top:' + (Math.random() * 100) + '%;--dur:' + (2 + Math.random() * 4) + 's;animation-delay:' + (Math.random() * 5) + 's';
    frag.appendChild(el);
  }
  container.appendChild(frag);
})();

/* ── 7. 密码 & 密钥生成器 ────────────────────── */
var _pwCache = [];
function pwGenerate() {
  var len = parseInt(document.getElementById('pwLen').value) || 16;
  var count = parseInt(document.getElementById('pwCount').value) || 5;
  var chars = '';
  if (document.getElementById('pwUpper').checked) chars += 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
  if (document.getElementById('pwLower').checked) chars += 'abcdefghijklmnopqrstuvwxyz';
  if (document.getElementById('pwDigit').checked) chars += '0123456789';
  if (document.getElementById('pwSym').checked) chars += '!@#$%^&*()_+-=[]{}|;:,.<>?/~`';
  if (!chars) { document.getElementById('pwOutput').value = '请至少选择一种字符类型'; return; }
  if (document.getElementById('pwAmb').checked) {
    chars = chars.replace(/[0O1lI|]/g,'');
    if (!chars) { document.getElementById('pwOutput').value = '排除后无可用字符，请调整选项'; return; }
  }
  var arr = new Uint32Array(len * count + 256);
  crypto.getRandomValues(arr);
  var ri = 0;
  function nextRand(n) { return arr[ri++ % arr.length] % n; }
  _pwCache = [];
  for (var c = 0; c < count; c++) {
    var pwd = '';
    for (var i = 0; i < len; i++) pwd += chars[nextRand(chars.length)];
    _pwCache.push(pwd);
  }
  document.getElementById('pwOutput').value = _pwCache.join('\n');
  pwShowStrength(len, chars.length);
}
function pwShowStrength(len, pool) {
  var entropy = Math.log2(pool) * len;
  var el = document.getElementById('pwStrengthText');
  if (!el) return;
  var text = '', color = '';
  if (entropy < 40) { text = '极弱'; color = '#f87171'; }
  else if (entropy < 60) { text = '弱'; color = '#fbbf24'; }
  else if (entropy < 80) { text = '中等'; color = '#34d399'; }
  else if (entropy < 120) { text = '强'; color = '#22c55e'; }
  else { text = '极强'; color = '#6ee7b7'; }
  el.textContent = text; el.style.color = color;
}
function pwCopy() {
  var t = document.getElementById('pwOutput').value;
  if (!t) return;
  if (navigator.clipboard) { navigator.clipboard.writeText(t); }
  else { var inp = document.createElement('input'); inp.value = t; document.body.appendChild(inp); inp.select(); document.execCommand('copy'); document.body.removeChild(inp); }
}
function keyGenerate() {
  var bits = parseInt(document.getElementById('keyBits').value) || 256;
  var count = parseInt(document.getElementById('keyCount').value) || 3;
  var fmt = document.querySelector('input[name="keyFmt"]:checked');
  fmt = fmt ? fmt.value : 'hex';
  var bytes = bits / 8;
  var lines = [];
  for (var c = 0; c < count; c++) {
    var buf = new Uint8Array(bytes);
    crypto.getRandomValues(buf);
    if (fmt === 'hex') {
      lines.push(Array.from(buf).map(function(x){return ('0'+x.toString(16)).slice(-2)}).join(''));
    } else if (fmt === 'base64') {
      lines.push(btoa(String.fromCharCode.apply(null, buf)));
    } else if (fmt === 'base64url') {
      lines.push(btoa(String.fromCharCode.apply(null, buf)).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,''));
    }
  }
  document.getElementById('keyOutput').value = lines.join('\n');
}
function keyCopy() {
  var t = document.getElementById('keyOutput').value;
  if (!t) return;
  if (navigator.clipboard) { navigator.clipboard.writeText(t); }
  else { var inp = document.createElement('input'); inp.value = t; document.body.appendChild(inp); inp.select(); document.execCommand('copy'); document.body.removeChild(inp); }
}


