# -*- coding: utf-8 -*-
import re

path = 'D:\\Project\\hoshino-blog\\templates\\bilibili.html'
content = open(path, 'r', encoding='utf-8').read()

# 1. Replace the two buttons: remove inline styles, add correct classes
# Grid button: is-active by default, no inline styles. List button: no inline styles.
content = re.sub(
    r'<button id="viewGridBtn" onclick="switchView\(\'grid\'\)" style="[^"]*"[^>]*>▦ 网格</button>\s+<button id="viewListBtn" onclick="switchView\(\'list\'\)"',
    '<button id="viewGridBtn" onclick="switchView(\'grid\')" class="is-active">▦ 网格</button>\n            <button id="viewListBtn" onclick="switchView(\'list\')" class=""',
    content
)

# 2. Update switchView JS: remove all inline style assignments, only toggle classes
old_js = '''    if (mode === 'grid') {
        c.classList.remove('up-list-view'); c.classList.add('up-grid-view');
        if (g) { g.classList.add('is-active'); g.style.background='rgba(255,107,157,0.15)'; g.style.borderColor='rgba(255,107,157,0.25)'; g.style.color='#ff8aae'; }
        if (l) { l.classList.remove('is-active'); l.style.background=''; l.style.borderColor=''; l.style.color=''; }
        try { localStorage.setItem('bili_up_view', 'grid'); } catch(e) {}
    } else {
        c.classList.remove('up-grid-view'); c.classList.add('up-list-view');
        if (l) { l.classList.add('is-active'); l.style.background='rgba(255,107,157,0.15)'; l.style.borderColor='rgba(255,107,157,0.25)'; l.style.color='#ff8aae'; }
        if (g) { g.classList.remove('is-active'); g.style.background=''; g.style.borderColor=''; g.style.color=''; }
        try { localStorage.setItem('bili_up_view', 'list'); } catch(e) {}
    }'''

new_js = '''    if (mode === 'grid') {
        c.classList.remove('up-list-view'); c.classList.add('up-grid-view');
        if (g) { g.classList.add('is-active'); }
        if (l) { l.classList.remove('is-active'); }
        try { localStorage.setItem('bili_up_view', 'grid'); } catch(e) {}
    } else {
        c.classList.remove('up-grid-view'); c.classList.add('up-list-view');
        if (l) { l.classList.add('is-active'); }
        if (g) { g.classList.remove('is-active'); }
        try { localStorage.setItem('bili_up_view', 'list'); } catch(e) {}
    }'''

content = content.replace(old_js, new_js)

# 3. Update CSS: add inactive button state
old_css = '''/* 视图切换按钮激活状态 */
#viewGridBtn.is-active, #viewListBtn.is-active { background: rgba(255,107,157,0.15) !important; border-color: rgba(255,107,157,0.25) !important; color: #ff8aae !important; }'''

new_css = '''/* 视图切换按钮 — 未选中：低调灰色 */
#viewGridBtn, #viewListBtn {
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.08);
    color: rgba(255,255,255,0.35);
    padding: 6px 14px; border-radius: 8px;
    cursor: pointer; font-size: 0.75rem;
    transition: all 0.2s;
}
/* 视图切换按钮 — 选中：粉紫高亮 */
#viewGridBtn.is-active, #viewListBtn.is-active {
    background: rgba(255,107,157,0.15) !important;
    border-color: rgba(255,107,157,0.25) !important;
    color: #ff8aae !important;
}'''

content = content.replace(old_css, new_css)

open(path, 'w', encoding='utf-8').write(content)
print('Done!')
print('  - Buttons: inline styles removed, defaults use CSS')
print('  - JS: inline style assignments removed, only toggles classes')
print('  - CSS: inactive (grey) + active (pink) clearly separated')