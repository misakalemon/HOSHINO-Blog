import * as icons from 'lucide'

function createIcon(name, size = 16) {
  const icon = document.createElement('i')
  icon.className = 'rte-icon'
  const iconFn = icons[name]
  if (iconFn) {
    const svg = iconFn.toSvg({ width: size, height: size })
    icon.innerHTML = svg
  }
  return icon
}

export function createContextMenu(editor, options = {}) {
  let menu = null

  function hide() {
    if (menu) {
      menu.remove()
      menu = null
    }
  }

  function show(x, y) {
    hide()

    menu = document.createElement('div')
    menu.className = 'rte-context-menu'

    const items = [
      {
        icon: 'Cut',
        label: '剪切',
        shortcut: 'Ctrl+X',
        action: () => {
          const { from, to } = editor.state.selection
          const text = editor.state.doc.textBetween(from, to)
          navigator.clipboard.writeText(text).then(() => {
            editor.chain().focus().deleteSelection().run()
          })
        },
        disabled: editor.state.selection.empty,
      },
      {
        icon: 'Copy',
        label: '复制',
        shortcut: 'Ctrl+C',
        action: () => {
          const { from, to } = editor.state.selection
          const text = editor.state.doc.textBetween(from, to)
          navigator.clipboard.writeText(text)
        },
        disabled: editor.state.selection.empty,
      },
      {
        icon: 'Clipboard',
        label: '粘贴',
        shortcut: 'Ctrl+V',
        action: () => {
          navigator.clipboard.readText().then(text => {
            editor.chain().focus().insertContent(text).run()
          })
        },
      },
      { divider: true },
      {
        icon: 'Bold',
        label: '加粗',
        shortcut: 'Ctrl+B',
        action: () => editor.chain().focus().toggleBold().run(),
        active: editor.isActive('bold'),
      },
      {
        icon: 'Italic',
        label: '斜体',
        shortcut: 'Ctrl+I',
        action: () => editor.chain().focus().toggleItalic().run(),
        active: editor.isActive('italic'),
      },
      {
        icon: 'Underline',
        label: '下划线',
        shortcut: 'Ctrl+U',
        action: () => editor.chain().focus().toggleUnderline().run(),
        active: editor.isActive('underline'),
      },
      { divider: true },
      {
        icon: 'Link',
        label: '插入链接',
        action: () => {
          const url = prompt('请输入链接地址:', 'https://')
          if (url && !url.trim().toLowerCase().startsWith('javascript:')) {
            editor.chain().focus().setLink({ href: url }).run()
          }
        },
      },
      {
        icon: 'Image',
        label: '插入图片',
        action: () => {
          if (options.uploadUrl && options.csrfToken && options.uploadImageWithCrop) {
            options.uploadImageWithCrop(options.uploadUrl, options.csrfToken).then(url => {
              editor.chain().focus().setImage({ src: url, alt: 'image' }).run()
            })
          }
        },
      },
      { divider: true },
      {
        icon: 'AlignLeft',
        label: '左对齐',
        action: () => editor.chain().focus().setTextAlign('left').run(),
        active: editor.isActive({ textAlign: 'left' }),
      },
      {
        icon: 'AlignCenter',
        label: '居中',
        action: () => editor.chain().focus().setTextAlign('center').run(),
        active: editor.isActive({ textAlign: 'center' }),
      },
      {
        icon: 'AlignRight',
        label: '右对齐',
        action: () => editor.chain().focus().setTextAlign('right').run(),
        active: editor.isActive({ textAlign: 'right' }),
      },
      { divider: true },
      {
        icon: 'RemoveFormatting',
        label: '清除格式',
        action: () => editor.chain().focus().clearNodes().unsetAllMarks().run(),
      },
    ]

    items.forEach(item => {
      if (item.divider) {
        const divider = document.createElement('div')
        divider.className = 'rte-context-menu-divider'
        menu.appendChild(divider)
      } else {
        const menuItem = document.createElement('div')
        menuItem.className = 'rte-context-menu-item'
        if (item.disabled) menuItem.classList.add('is-disabled')
        if (item.active) menuItem.classList.add('is-active')

        const iconEl = createIcon(item.icon)
        const labelEl = document.createElement('span')
        labelEl.className = 'rte-context-menu-label'
        labelEl.textContent = item.label

        menuItem.appendChild(iconEl)
        menuItem.appendChild(labelEl)

        if (item.shortcut) {
          const shortcutEl = document.createElement('span')
          shortcutEl.className = 'rte-context-menu-shortcut'
          shortcutEl.textContent = item.shortcut
          menuItem.appendChild(shortcutEl)
        }

        if (!item.disabled) {
          menuItem.addEventListener('click', () => {
            item.action()
            hide()
          })
        }

        menu.appendChild(menuItem)
      }
    })

    document.body.appendChild(menu)

    // Position menu
    const menuRect = menu.getBoundingClientRect()
    const viewportWidth = window.innerWidth
    const viewportHeight = window.innerHeight

    let posX = x
    let posY = y

    if (x + menuRect.width > viewportWidth) {
      posX = viewportWidth - menuRect.width - 10
    }
    if (y + menuRect.height > viewportHeight) {
      posY = viewportHeight - menuRect.height - 10
    }

    menu.style.left = `${posX}px`
    menu.style.top = `${posY}px`
  }

  // Event listeners
  editor.view.dom.addEventListener('contextmenu', e => {
    e.preventDefault()
    show(e.clientX, e.clientY)
  })

  document.addEventListener('click', e => {
    if (menu && !menu.contains(e.target)) {
      hide()
    }
  })

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      hide()
    }
  })

  return { show, hide }
}