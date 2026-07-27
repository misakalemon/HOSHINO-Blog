import { showModal, uploadImageWithCrop, importFile, sanitizeHTML } from './utils'
import createElement from 'lucide/dist/esm/createElement.mjs'
import {
  Undo, Redo, Bold, Italic, Underline, Strikethrough, Superscript, Subscript,
  AlignLeft, AlignCenter, AlignRight, AlignJustify, List, ListOrdered, CheckSquare,
  Outdent, Indent, Link, Image, Table, Minus, Code, FileUp, Plus, Search,
  RemoveFormatting,
} from 'lucide'

const iconMap = {
  Undo, Redo, Bold, Italic, Underline, Strikethrough, Superscript, Subscript,
  AlignLeft, AlignCenter, AlignRight, AlignJustify, List, ListOrdered, CheckSquare,
  Outdent, Indent, Link, Image, Table, Minus, Code, FileUp, Plus, Search,
  RemoveFormatting,
}

function createIcon(name, size = 18) {
  const icon = document.createElement('i')
  icon.className = 'rte-icon'
  const iconData = iconMap[name]
  if (iconData) {
    const svg = createElement(iconData, { width: size, height: size })
    icon.appendChild(svg)
  }
  return icon
}

function el(tag, attrs, children) {
  const e = document.createElement(tag)
  if (attrs) {
    Object.entries(attrs).forEach(([k, v]) => {
      if (k === 'className') e.className = v
      else if (k === 'innerHTML') e.innerHTML = v
      else if (k === 'onclick') e.addEventListener('click', v)
      else if (k.startsWith('on')) e.addEventListener(k.slice(2).toLowerCase(), v)
      else e.setAttribute(k, v)
    })
  }
  if (children) {
    ;(Array.isArray(children) ? children : [children]).forEach(c => {
      if (c) e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c)
    })
  }
  return e
}

function group(className) {
  return el('div', { className: `rte-toolbar-group ${className}` })
}

function sep() {
  return el('span', { className: 'rte-sep' })
}

function btn(iconName, title, onclick, size = 18) {
  const b = el('button', { type: 'button', title, onclick })
  b.appendChild(createIcon(iconName, size))
  return b
}

function colorInput(title, onchange) {
  const input = el('input', {
    type: 'color',
    title,
  })
  input.style.cssText =
    'width:24px;height:24px;padding:0;border:1px solid rgba(255,255,255,0.15);border-radius:4px;background:transparent;cursor:pointer'
  input.addEventListener('input', e => onchange(e.target.value))
  return input
}

function createSelect(label, options, onchange, iconName = null) {
  const wrap = el('div', { className: 'rte-select-wrap' })
  const trigger = el('div', { className: 'rte-select-trigger' })
  if (iconName) {
    trigger.appendChild(createIcon(iconName, 16))
    trigger.appendChild(el('span', { className: 'rte-select-spacer' }, ' '))
  }
  const valueSpan = el('span', { className: 'rte-select-value' }, label)
  const arrow = el('span', { className: 'rte-select-arrow' }, '▾')
  trigger.appendChild(valueSpan)
  trigger.appendChild(arrow)
  const menu = el('div', { className: 'rte-select-menu' })
  options.forEach(opt => {
    const item = el('div', { className: 'rte-select-option' }, opt.label)
    item.setAttribute('data-value', opt.value)
    item.addEventListener('click', () => {
      valueSpan.textContent = opt.label
      wrap.classList.remove('is-open')
      onchange(opt.value)
    })
    menu.appendChild(item)
  })
  trigger.addEventListener('click', e => {
    e.stopPropagation()
    document.querySelectorAll('.rte-select-wrap.is-open').forEach(w => {
      if (w !== wrap) w.classList.remove('is-open')
    })
    wrap.classList.toggle('is-open')
  })
  wrap.appendChild(trigger)
  wrap.appendChild(menu)
  return { wrap, setValue: v => { valueSpan.textContent = v } }
}

export function createFullToolbar(editor, options) {
  const toolbar = el('div', { className: 'rte-toolbar' })

  // ── Group 1: History ─────────────────────────────────────────
  const historyGroup = group('rte-group-history')
  historyGroup.appendChild(btn('Undo', '撤销 (Ctrl+Z)', () => editor.chain().focus().undo().run()))
  historyGroup.appendChild(btn('Redo', '重做 (Ctrl+Y)', () => editor.chain().focus().redo().run()))
  toolbar.appendChild(historyGroup)
  toolbar.appendChild(sep())

  // ── Group 2: Font ────────────────────────────────────────────
  const fontGroup = group('rte-group-font')

  // Format block
  const formatSelect = createSelect('正文', [
    { value: 'paragraph', label: '正文' },
    { value: 'h1', label: '标题 1' },
    { value: 'h2', label: '标题 2' },
    { value: 'h3', label: '标题 3' },
    { value: 'h4', label: '标题 4' },
    { value: 'codeBlock', label: '代码块' },
    { value: 'blockquote', label: '引用' },
  ], val => {
    if (val === 'paragraph') editor.chain().focus().setParagraph().run()
    else if (val === 'codeBlock') {
      showModal({
        title: '插入代码块',
        fields: [{
          key: 'lang', label: '代码语言', type: 'select', value: 'python',
          options: [
            { value: 'python', label: 'Python' },
            { value: 'javascript', label: 'JavaScript' },
            { value: 'typescript', label: 'TypeScript' },
            { value: 'html', label: 'HTML' },
            { value: 'css', label: 'CSS' },
            { value: 'java', label: 'Java' },
            { value: 'kotlin', label: 'Kotlin' },
            { value: 'go', label: 'Go' },
            { value: 'rust', label: 'Rust' },
            { value: 'c', label: 'C' },
            { value: 'cpp', label: 'C++' },
            { value: 'csharp', label: 'C#' },
            { value: 'swift', label: 'Swift' },
            { value: 'php', label: 'PHP' },
            { value: 'ruby', label: 'Ruby' },
            { value: 'sql', label: 'SQL' },
            { value: 'bash', label: 'Bash' },
            { value: 'json', label: 'JSON' },
            { value: 'yaml', label: 'YAML' },
            { value: 'xml', label: 'XML' },
            { value: 'markdown', label: 'Markdown' },
            { value: 'plaintext', label: '纯文本' },
          ],
        }],
        onConfirm: vals => {
          editor.chain().focus().toggleCodeBlock({ language: vals.lang }).run()
        },
      })
    } else if (val === 'blockquote') editor.chain().focus().toggleBlockquote().run()
    else {
      const level = parseInt(val.replace('h', ''))
      editor.chain().focus().toggleHeading({ level }).run()
    }
  })
  fontGroup.appendChild(formatSelect.wrap)

  // Font size
  const fontSizeSelect = createSelect('字号', [
    { value: '', label: '默认' },
    { value: '10', label: '10' },
    { value: '12', label: '12' },
    { value: '14', label: '14' },
    { value: '16', label: '16' },
    { value: '18', label: '18' },
    { value: '20', label: '20' },
    { value: '24', label: '24' },
    { value: '28', label: '28' },
    { value: '32', label: '32' },
    { value: '36', label: '36' },
  ], val => {
    if (val) editor.chain().focus().setFontSize(val).run()
  })
  fontGroup.appendChild(fontSizeSelect.wrap)

  fontGroup.appendChild(btn('Bold', '粗体 (Ctrl+B)', () => editor.chain().focus().toggleBold().run()))
  fontGroup.appendChild(btn('Italic', '斜体 (Ctrl+I)', () => editor.chain().focus().toggleItalic().run()))
  fontGroup.appendChild(btn('Underline', '下划线 (Ctrl+U)', () => editor.chain().focus().toggleUnderline().run()))
  fontGroup.appendChild(btn('Strikethrough', '删除线', () => editor.chain().focus().toggleStrike().run()))
  fontGroup.appendChild(btn('Superscript', '上标', () => editor.chain().focus().toggleSuperscript().run()))
  fontGroup.appendChild(btn('Subscript', '下标', () => editor.chain().focus().toggleSubscript().run()))
  fontGroup.appendChild(colorInput('文字颜色', val => {
    editor.chain().focus().setColor(val).run()
  }))
  fontGroup.appendChild(colorInput('背景色', val => {
    editor.chain().focus().toggleHighlight({ color: val }).run()
  }))
  toolbar.appendChild(fontGroup)
  toolbar.appendChild(sep())

  // ── Group 3: Paragraph ───────────────────────────────────────
  const paraGroup = group('rte-group-paragraph')
  paraGroup.appendChild(btn('AlignLeft', '左对齐', () => editor.chain().focus().setTextAlign('left').run()))
  paraGroup.appendChild(btn('AlignCenter', '居中', () => editor.chain().focus().setTextAlign('center').run()))
  paraGroup.appendChild(btn('AlignRight', '右对齐', () => editor.chain().focus().setTextAlign('right').run()))
  paraGroup.appendChild(btn('AlignJustify', '两端对齐', () => editor.chain().focus().setTextAlign('justify').run()))

  // Line height
  const lineHeightSelect = createSelect('行距', [
    { value: '', label: '默认' },
    { value: '1', label: '1.0' },
    { value: '1.15', label: '1.15' },
    { value: '1.5', label: '1.5' },
    { value: '1.8', label: '1.8' },
    { value: '2', label: '2.0' },
    { value: '2.5', label: '2.5' },
    { value: '3', label: '3.0' },
  ], val => {
    if (val) editor.chain().focus().setLineHeight(val).run()
  })
  paraGroup.appendChild(lineHeightSelect.wrap)

  paraGroup.appendChild(btn('List', '无序列表', () => editor.chain().focus().toggleBulletList().run()))
  paraGroup.appendChild(btn('ListOrdered', '有序列表', () => editor.chain().focus().toggleOrderedList().run()))
  paraGroup.appendChild(btn('CheckSquare', '任务列表', () => editor.chain().focus().toggleTaskList().run()))
  paraGroup.appendChild(btn('Outdent', '减少缩进', () => editor.chain().focus().outdent().run()))
  paraGroup.appendChild(btn('Indent', '增加缩进', () => editor.chain().focus().indent().run()))
  toolbar.appendChild(paraGroup)
  toolbar.appendChild(sep())

  // ── Group 4: Insert ──────────────────────────────────────────
  const insertGroup = group('rte-group-insert')
  insertGroup.appendChild(btn('Link', '插入链接', () => {
    showModal({
      title: '插入链接',
      fields: [{ key: 'url', label: '链接地址', type: 'text', placeholder: 'https://', value: 'https://' }],
      onConfirm: vals => {
        if (vals.url) {
          if (vals.url.trim().toLowerCase().startsWith('javascript:')) {
            if (typeof showToast === 'function') showToast('不允许 javascript: 链接', 'error')
            return
          }
          editor.chain().focus().setLink({ href: vals.url }).run()
        }
      },
    })
  }))
  insertGroup.appendChild(btn('Image', '插入图片', () => {
    uploadImageWithCrop(options.uploadUrl, options.csrfToken).then(url => {
      showModal({
        title: '图片设置',
        fields: [{
          key: 'align', label: '对齐方式', type: 'select', value: 'none',
          options: [
            { value: 'none', label: '默认' },
            { value: 'left', label: '左浮动' },
            { value: 'center', label: '居中' },
            { value: 'right', label: '右浮动' },
          ],
        }],
        onConfirm: vals => {
          let style = ''
          if (vals.align === 'left') style = 'float:left; margin-right:16px; max-width:50%'
          else if (vals.align === 'right') style = 'float:right; margin-left:16px; max-width:50%'
          else if (vals.align === 'center') style = 'display:block; margin:0 auto; text-align:center'
          editor.chain().focus().setImage({ src: url, style, alt: 'image' }).run()
        },
      })
    }).catch(() => {
      if (typeof showToast === 'function') showToast('图片上传失败', 'error')
    })
  }))
  insertGroup.appendChild(btn('Table', '插入表格', () => {
    showModal({
      title: '插入表格',
      fields: [
        { key: 'rows', label: '行数', type: 'number', value: '3', min: '1', max: '50' },
        { key: 'cols', label: '列数', type: 'number', value: '3', min: '1', max: '20' },
      ],
      onConfirm: vals => {
        editor.chain().focus().insertTable({
          rows: parseInt(vals.rows),
          cols: parseInt(vals.cols),
          withHeaderRow: true,
        }).run()
      },
    })
  }))
  insertGroup.appendChild(btn('Minus', '分割线', () => editor.chain().focus().setHorizontalRule().run()))
  insertGroup.appendChild(btn('Code', '行内代码', () => editor.chain().focus().toggleCode().run()))
  insertGroup.appendChild(btn('FileUp', '导入文件', () => {
    importFile().then(html => {
      editor.chain().focus().insertContent(sanitizeHTML(html)).run()
    })
  }))
  toolbar.appendChild(insertGroup)
  toolbar.appendChild(sep())

  // ── Group 5: Table Operations ────────────────────────────────
  const tableGroup = group('rte-group-table')
  tableGroup.appendChild(btn('Plus', '添加行列', () => {
    showModal({
      title: '表格操作',
      fields: [{
        key: 'action', label: '操作', type: 'select', value: 'addColumnAfter',
        options: [
          { value: 'addColumnBefore', label: '在左侧插入列' },
          { value: 'addColumnAfter', label: '在右侧插入列' },
          { value: 'addRowBefore', label: '在上方插入行' },
          { value: 'addRowAfter', label: '在下方插入行' },
          { value: 'deleteColumn', label: '删除当前列' },
          { value: 'deleteRow', label: '删除当前行' },
          { value: 'mergeCells', label: '合并单元格' },
          { value: 'splitCell', label: '拆分单元格' },
          { value: 'toggleHeaderRow', label: '切换标题行' },
        ],
      }],
      onConfirm: vals => {
        const cmd = editor.chain().focus()
        if (vals.action === 'mergeCells') cmd.mergeCells().run()
        else if (vals.action === 'splitCell') cmd.splitCell().run()
        else if (vals.action === 'toggleHeaderRow') cmd.toggleHeaderRow().run()
        else cmd[vals.action]().run()
      },
    })
  }))
  toolbar.appendChild(tableGroup)
  toolbar.appendChild(sep())

  // ── Group 6: Tools ───────────────────────────────────────────
  const toolsGroup = group('rte-group-tools')
  toolsGroup.appendChild(btn('Search', '查找替换', () => {
    let dialog = document.getElementById('rte-find-dialog')
    if (dialog) {
      dialog.remove()
      return
    }
    dialog = document.createElement('div')
    dialog.id = 'rte-find-dialog'
    dialog.className = 'rte-find-dialog'
    dialog.innerHTML = `
      <h4>查找与替换</h4>
      <input type="text" id="rte-find-input" placeholder="查找内容">
      <input type="text" id="rte-replace-input" placeholder="替换为">
      <div class="rte-find-dialog-actions">
        <button class="btn btn-ghost" id="rte-find-prev">上一个</button>
        <button class="btn btn-ghost" id="rte-find-next">下一个</button>
        <button class="btn btn-primary" id="rte-replace-btn">替换</button>
        <button class="btn btn-ghost" id="rte-replace-all">全部</button>
      </div>
    `
    document.body.appendChild(dialog)

    const findInput = document.getElementById('rte-find-input')
    const replaceInput = document.getElementById('rte-replace-input')
    let matches = []
    let currentMatch = -1

    function findText(dir = 1) {
      const query = findInput.value
      if (!query) return
      const text = editor.getText()
      matches = []
      let pos = 0
      while ((pos = text.indexOf(query, pos)) !== -1) {
        matches.push({ from: pos, to: pos + query.length })
        pos++
      }
      if (matches.length === 0) return
      currentMatch = (currentMatch + dir + matches.length) % matches.length
      const m = matches[currentMatch]
      editor.chain().focus().setTextSelection({ from: m.from + 1, to: m.to + 1 }).run()
    }

    document.getElementById('rte-find-prev').onclick = () => findText(-1)
    document.getElementById('rte-find-next').onclick = () => findText(1)
    document.getElementById('rte-replace-btn').onclick = () => {
      const query = findInput.value
      const replacement = replaceInput.value
      if (!query || currentMatch < 0) return
      const m = matches[currentMatch]
      editor.chain().focus().setTextSelection({ from: m.from + 1, to: m.to + 1 }).insertContent(replacement).run()
      findText(1)
    }
    document.getElementById('rte-replace-all').onclick = () => {
      const query = findInput.value
      const replacement = replaceInput.value
      if (!query) return
      const content = editor.getHTML()
      const newContent = content.split(query).join(replacement)
      editor.commands.setContent(newContent)
    }

    findInput.focus()
    findInput.onkeydown = (e) => {
      if (e.key === 'Enter') findText(1)
      if (e.key === 'Escape') dialog.remove()
    }
  }))
  toolsGroup.appendChild(btn('RemoveFormatting', '清除格式', () => {
    editor.chain().focus().clearNodes().unsetAllMarks().run()
  }))
  toolbar.appendChild(toolsGroup)

  // ── Update active states on selection change ────────────────
  const boldBtn = fontGroup.querySelector('button[title*="粗体"]')
  const italicBtn = fontGroup.querySelector('button[title*="斜体"]')
  const underlineBtn = fontGroup.querySelector('button[title*="下划线"]')
  const strikeBtn = fontGroup.querySelector('button[title*="删除线"]')
  const superBtn = fontGroup.querySelector('button[title*="上标"]')
  const subBtn = fontGroup.querySelector('button[title*="下标"]')
  const ulBtn = paraGroup.querySelector('button[title*="无序列表"]')
  const olBtn = paraGroup.querySelector('button[title*="有序列表"]')

  editor.on('selectionUpdate', () => {
    boldBtn.classList.toggle('is-active', editor.isActive('bold'))
    italicBtn.classList.toggle('is-active', editor.isActive('italic'))
    underlineBtn.classList.toggle('is-active', editor.isActive('underline'))
    strikeBtn.classList.toggle('is-active', editor.isActive('strike'))
    superBtn.classList.toggle('is-active', editor.isActive('superscript'))
    subBtn.classList.toggle('is-active', editor.isActive('subscript'))
    ulBtn.classList.toggle('is-active', editor.isActive('bulletList'))
    olBtn.classList.toggle('is-active', editor.isActive('orderedList'))

    // Update format select display
    if (editor.isActive('heading', { level: 1 })) formatSelect.setValue('标题 1')
    else if (editor.isActive('heading', { level: 2 })) formatSelect.setValue('标题 2')
    else if (editor.isActive('heading', { level: 3 })) formatSelect.setValue('标题 3')
    else if (editor.isActive('heading', { level: 4 })) formatSelect.setValue('标题 4')
    else if (editor.isActive('codeBlock')) formatSelect.setValue('代码块')
    else if (editor.isActive('blockquote')) formatSelect.setValue('引用')
    else formatSelect.setValue('正文')
  })

  // Close selects on outside click
  document.addEventListener('click', () => {
    toolbar.querySelectorAll('.rte-select-wrap.is-open').forEach(w => w.classList.remove('is-open'))
  })

  return toolbar
}
