import os
import re
os.chdir(r'D:\Project\hoshino-blog')

path = 'templates/bilibili.html'
with open(path, 'r', encoding='utf-8') as f:
    c = f.read()

changes = 0

# 1. Remove the custom base button CSS
pat = r'#viewGridBtn,\s*#viewListBtn\s*\{[^}]*\}'
c, n = re.subn(pat, '', c)
changes += n

# 2. Format .is-active CSS properly
old = '#viewGridBtn.is-active, #viewListBtn.is-active { background: rgba(255,107,157,0.15) !important; border-color: rgba(255,107,157,0.25) !important; color: #ff8aae !important; }'
new = '\n#viewGridBtn.is-active, #viewListBtn.is-active {\n    background: rgba(255,107,157,0.15) !important;\n    border-color: rgba(255,107,157,0.25) !important;\n    color: #ff8aae !important;\n}'
if old in c:
    c = c.replace(old, new, 1)
    changes += 1

# 3. Add console.log to switchView
old_js = 'function switchView(mode) {\n    var c = document.getElementById'
new_js = 'function switchView(mode) {\n    console.log(\'[view]\', mode);\n    var c = document.getElementById'
if old_js in c:
    c = c.replace(old_js, new_js, 1)
    changes += 1

with open(path, 'w', encoding='utf-8') as f:
    f.write(c)

print('OK -', changes, 'changes')
print('base CSS:', 'viewGridBtn' in c[:1300])
print('console.log:', 'console.log' in c)