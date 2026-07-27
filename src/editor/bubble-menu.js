import { PluginKey } from '@tiptap/pm/state'

export function createBubbleMenu(editor) {
  const menu = document.createElement('div')
  menu.className = 'rte-bubble-menu'

  const buttons = [
    { icon: '<b>B</b>', title: '粗体', action: () => editor.chain().focus().toggleBold().run(), isActive: () => editor.isActive('bold') },
    { icon: '<i>I</i>', title: '斜体', action: () => editor.chain().focus().toggleItalic().run(), isActive: () => editor.isActive('italic') },
    { icon: '<u>U</u>', title: '下划线', action: () => editor.chain().focus().toggleUnderline().run(), isActive: () => editor.isActive('underline') },
    { icon: '<s>S</s>', title: '删除线', action: () => editor.chain().focus().toggleStrike().run(), isActive: () => editor.isActive('strike') },
    { icon: '<span style="font-size:11px">H1</span>', title: '标题1', action: () => editor.chain().focus().toggleHeading({ level: 1 }).run(), isActive: () => editor.isActive('heading', { level: 1 }) },
    { icon: '<span style="font-size:11px">H2</span>', title: '标题2', action: () => editor.chain().focus().toggleHeading({ level: 2 }).run(), isActive: () => editor.isActive('heading', { level: 2 }) },
    { icon: '🔗', title: '链接', action: () => {
      const url = window.prompt('链接地址', 'https://')
      if (url && !url.toLowerCase().startsWith('javascript:')) {
        editor.chain().focus().setLink({ href: url }).run()
      }
    }, isActive: () => editor.isActive('link') },
  ]

  buttons.forEach(btn => {
    const button = document.createElement('button')
    button.type = 'button'
    button.title = btn.title
    button.innerHTML = btn.icon
    button.addEventListener('click', btn.action)
    menu.appendChild(button)
  })

  menu.style.display = 'none'
  document.body.appendChild(menu)

  function updatePosition() {
    const { from, to } = editor.state.selection
    if (from === to) {
      menu.style.display = 'none'
      return
    }

    const selectedText = editor.state.doc.textBetween(from, to)
    if (!selectedText.trim()) {
      menu.style.display = 'none'
      return
    }

    menu.style.display = 'flex'

    buttons.forEach((btn, i) => {
      const button = menu.children[i]
      button.classList.toggle('is-active', btn.isActive())
    })

    const { view } = editor
    const start = view.coordsAtPos(from)
    const end = view.coordsAtPos(to)

    const left = (start.left + end.left) / 2 - menu.offsetWidth / 2
    const top = start.top - menu.offsetHeight - 8

    menu.style.left = `${Math.max(8, left)}px`
    menu.style.top = `${top}px`
  }

  editor.on('selectionUpdate', updatePosition)
  editor.on('focus', updatePosition)
  editor.on('blur', () => { menu.style.display = 'none' })

  document.addEventListener('mousedown', (e) => {
    if (!menu.contains(e.target)) {
      menu.style.display = 'none'
    }
  })

  return menu
}