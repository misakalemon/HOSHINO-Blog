import { showModal } from './utils'

function el(tag, attrs, children) {
  const e = document.createElement(tag)
  if (attrs) {
    Object.entries(attrs).forEach(([k, v]) => {
      if (k === 'className') e.className = v
      else if (k === 'innerHTML') e.innerHTML = v
      else if (k === 'onclick') e.addEventListener('click', v)
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
  return el('button', { type: 'button', title, innerHTML: label, onclick })
}

export function createMinimalToolbar(editor) {
  const toolbar = el('div', { className: 'rte-toolbar rte-toolbar-minimal' })

  // Undo / Redo
  toolbar.appendChild(btn('↩', '撤销', () => editor.chain().focus().undo().run()))
  toolbar.appendChild(btn('↪', '重做', () => editor.chain().focus().redo().run()))
  toolbar.appendChild(sep())

  // Bold / Italic / Underline
  const boldBtn = btn('<b>B</b>', '粗体', () => editor.chain().focus().toggleBold().run())
  const italicBtn = btn('<i>I</i>', '斜体', () => editor.chain().focus().toggleItalic().run())
  const underlineBtn = btn('<u>U</u>', '下划线', () => editor.chain().focus().toggleUnderline().run())
  toolbar.appendChild(boldBtn)
  toolbar.appendChild(italicBtn)
  toolbar.appendChild(underlineBtn)
  toolbar.appendChild(sep())

  // H2 / H3
  const h2Btn = btn('H2', '标题', () => editor.chain().focus().toggleHeading({ level: 2 }).run())
  const h3Btn = btn('H3', '小标题', () => editor.chain().focus().toggleHeading({ level: 3 }).run())
  toolbar.appendChild(h2Btn)
  toolbar.appendChild(h3Btn)
  toolbar.appendChild(sep())

  // Lists
  const ulBtn = btn('• list', '列表', () => editor.chain().focus().toggleBulletList().run())
  const olBtn = btn('1. list', '编号', () => editor.chain().focus().toggleOrderedList().run())
  toolbar.appendChild(ulBtn)
  toolbar.appendChild(olBtn)
  toolbar.appendChild(sep())

  // Link / Code block / Blockquote
  toolbar.appendChild(btn('🔗', '链接', () => {
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
  toolbar.appendChild(btn('&lt;/&gt;', '代码块', () => editor.chain().focus().toggleCodeBlock().run()))
  toolbar.appendChild(btn('❝', '引用', () => editor.chain().focus().toggleBlockquote().run()))

  // Update active states
  editor.on('selectionUpdate', () => {
    boldBtn.classList.toggle('is-active', editor.isActive('bold'))
    italicBtn.classList.toggle('is-active', editor.isActive('italic'))
    underlineBtn.classList.toggle('is-active', editor.isActive('underline'))
    h2Btn.classList.toggle('is-active', editor.isActive('heading', { level: 2 }))
    h3Btn.classList.toggle('is-active', editor.isActive('heading', { level: 3 }))
    ulBtn.classList.toggle('is-active', editor.isActive('bulletList'))
    olBtn.classList.toggle('is-active', editor.isActive('orderedList'))
  })

  return toolbar
}