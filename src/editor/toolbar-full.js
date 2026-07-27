import { showModal, uploadImageWithCrop, importFile, sanitizeHTML } from './utils'

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

function sep() {
  return el('span', { className: 'rte-sep' })
}

function btn(label, title, onclick) {
  const b = el('button', { type: 'button', title, innerHTML: label, onclick })
  return b
}

function colorInput(title, onchange) {
  const input = el('input', {
    type: 'color',
    title,
  })
  input.style.cssText =
    'width:28px;height:28px;padding:2px;border:1px solid var(--border-subtle);border-radius:6px;background:transparent;cursor:pointer'
  input.addEventListener('input', e => onchange(e.target.value))
  return input
}

function createSelect(label, options, onchange) {
  const wrap = el('div', { className: 'rte-select-wrap' })
  const trigger = el('div', { className: 'rte-select-trigger' })
  const valueSpan = el('span', { className: 'rte-select-value' }, label)
  const arrow = el('span', { className: 'rte-select-arrow' }, '▼')
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

  // Undo / Redo
  toolbar.appendChild(btn('↩', '撤销', () => editor.chain().focus().undo().run()))
  toolbar.appendChild(btn('↪', '重做', () => editor.chain().focus().redo().run()))
  toolbar.appendChild(sep())

  // Format block
  const formatSelect = createSelect('段落', [
    { value: 'paragraph', label: '段落' },
    { value: 'h1', label: 'H1 标题' },
    { value: 'h2', label: 'H2 标题' },
    { value: 'h3', label: 'H3 标题' },
    { value: 'h4', label: 'H4 标题' },
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
            { value: 'scala', label: 'Scala' },
            { value: 'php', label: 'PHP' },
            { value: 'ruby', label: 'Ruby' },
            { value: 'perl', label: 'Perl' },
            { value: 'lua', label: 'Lua' },
            { value: 'dart', label: 'Dart' },
            { value: 'r', label: 'R' },
            { value: 'matlab', label: 'MATLAB' },
            { value: 'sql', label: 'SQL' },
            { value: 'bash', label: 'Bash/Shell' },
            { value: 'json', label: 'JSON' },
            { value: 'yaml', label: 'YAML' },
            { value: 'xml', label: 'XML' },
            { value: 'markdown', label: 'Markdown' },
            { value: 'dockerfile', label: 'Dockerfile' },
            { value: 'nginx', label: 'Nginx' },
            { value: 'ini', label: 'INI' },
            { value: 'diff', label: 'Diff' },
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
  toolbar.appendChild(formatSelect.wrap)

  // Font size
  const fontSizeSelect = createSelect('字号', [
    { value: '', label: '字号' },
    { value: '10', label: '极小' },
    { value: '13', label: '小' },
    { value: '16', label: '正常' },
    { value: '18', label: '中大' },
    { value: '24', label: '大' },
    { value: '32', label: '很大' },
    { value: '48', label: '极大' },
  ], val => {
    if (val) editor.chain().focus().setFontSize(val).run()
  })
  toolbar.appendChild(fontSizeSelect.wrap)
  toolbar.appendChild(sep())

  // Bold / Italic / Underline / Strike / Superscript / Subscript
  const boldBtn = btn('<b>B</b>', '粗体', () => editor.chain().focus().toggleBold().run())
  const italicBtn = btn('<i>I</i>', '斜体', () => editor.chain().focus().toggleItalic().run())
  const underlineBtn = btn('<u>U</u>', '下划线', () => editor.chain().focus().toggleUnderline().run())
  const strikeBtn = btn('<s>S</s>', '删除线', () => editor.chain().focus().toggleStrike().run())
  const superBtn = btn('x²', '上标', () => editor.chain().focus().toggleSuperscript().run())
  const subBtn = btn('x₂', '下标', () => editor.chain().focus().toggleSubscript().run())
  toolbar.appendChild(boldBtn)
  toolbar.appendChild(italicBtn)
  toolbar.appendChild(underlineBtn)
  toolbar.appendChild(strikeBtn)
  toolbar.appendChild(superBtn)
  toolbar.appendChild(subBtn)
  toolbar.appendChild(sep())

  // Text color / Highlight color
  toolbar.appendChild(colorInput('文字颜色', val => {
    editor.chain().focus().setColor(val).run()
  }))
  toolbar.appendChild(colorInput('背景高亮', val => {
    editor.chain().focus().toggleHighlight({ color: val }).run()
  }))
  toolbar.appendChild(sep())

  // Text alignment
  toolbar.appendChild(btn('◀', '左对齐', () => editor.chain().focus().setTextAlign('left').run()))
  toolbar.appendChild(btn('≡', '居中', () => editor.chain().focus().setTextAlign('center').run()))
  toolbar.appendChild(btn('▶', '右对齐', () => editor.chain().focus().setTextAlign('right').run()))
  toolbar.appendChild(sep())

  // Lists
  const ulBtn = btn('UL', '无序列表', () => editor.chain().focus().toggleBulletList().run())
  const olBtn = btn('OL', '有序列表', () => editor.chain().focus().toggleOrderedList().run())
  toolbar.appendChild(ulBtn)
  toolbar.appendChild(olBtn)
  toolbar.appendChild(sep())

  // Indent / Outdent
  toolbar.appendChild(btn('⇤', '减少缩进', () => editor.chain().focus().outdent().run()))
  toolbar.appendChild(btn('⇥', '增加缩进', () => editor.chain().focus().indent().run()))
  toolbar.appendChild(sep())

  // Horizontal rule / Table / Inline code / Link
  toolbar.appendChild(btn('—', '分割线', () => editor.chain().focus().setHorizontalRule().run()))
  toolbar.appendChild(btn('⊞', '插入表格', () => {
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
  toolbar.appendChild(btn('&lt;/&gt;', '行内代码', () => editor.chain().focus().toggleCode().run()))
  toolbar.appendChild(btn('🔗', '插入链接', () => {
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
  toolbar.appendChild(sep())

  // Image upload
  toolbar.appendChild(btn('🖼', '插入图片', () => {
    uploadImageWithCrop(options.uploadUrl, options.csrfToken).then(url => {
      showModal({
        title: '图片对齐方式',
        fields: [{
          key: 'align', label: '对齐', type: 'select', value: 'none',
          options: [
            { value: 'none', label: '默认（无对齐）' },
            { value: 'left', label: '左浮动（文字环绕）' },
            { value: 'center', label: '居中显示' },
            { value: 'right', label: '右浮动（文字环绕）' },
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
  toolbar.appendChild(btn('<span style="font-size:10px">◀ 🖼</span>', '图片左浮动', () => {
    uploadImageWithCrop(options.uploadUrl, options.csrfToken).then(url => {
      editor.chain().focus().setImage({
        src: url,
        style: 'float:left; margin-right:16px; max-width:50%',
        alt: 'image',
      }).run()
    })
  }))
  toolbar.appendChild(btn('<span style="font-size:10px">≡ 🖼</span>', '图片居中', () => {
    uploadImageWithCrop(options.uploadUrl, options.csrfToken).then(url => {
      editor.chain().focus().setImage({
        src: url,
        style: 'display:block; margin:0 auto; text-align:center',
        alt: 'image',
      }).run()
    })
  }))
  toolbar.appendChild(btn('<span style="font-size:10px">🖼 ▶</span>', '图片右浮动', () => {
    uploadImageWithCrop(options.uploadUrl, options.csrfToken).then(url => {
      editor.chain().focus().setImage({
        src: url,
        style: 'float:right; margin-left:16px; max-width:50%',
        alt: 'image',
      }).run()
    })
  }))

  // File import
  toolbar.appendChild(btn('📄', '导入文件 (Markdown/PDF/DOCX/HTML)', () => {
    importFile().then(html => {
      editor.chain().focus().insertContent(sanitizeHTML(html)).run()
    })
  }))
  toolbar.appendChild(sep())

  // Clear format
  toolbar.appendChild(btn('✕', '清除格式', () => {
    editor.chain().focus().clearNodes().unsetAllMarks().run()
  }))

  // Update active states on selection change
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
    if (editor.isActive('heading', { level: 1 })) formatSelect.setValue('H1 标题')
    else if (editor.isActive('heading', { level: 2 })) formatSelect.setValue('H2 标题')
    else if (editor.isActive('heading', { level: 3 })) formatSelect.setValue('H3 标题')
    else if (editor.isActive('heading', { level: 4 })) formatSelect.setValue('H4 标题')
    else if (editor.isActive('codeBlock')) formatSelect.setValue('代码块')
    else if (editor.isActive('blockquote')) formatSelect.setValue('引用')
    else formatSelect.setValue('段落')
  })

  // Close selects on outside click
  document.addEventListener('click', () => {
    toolbar.querySelectorAll('.rte-select-wrap.is-open').forEach(w => w.classList.remove('is-open'))
  })

  return toolbar
}