import { Mark, Extension, mergeAttributes } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import Image from '@tiptap/extension-image'

const FONT_SIZE_MAP = {
  '1': '10', '2': '13', '3': '16', '4': '18',
  '5': '24', '6': '32', '7': '48',
}

export const FontSize = Mark.create({
  name: 'fontSize',

  addOptions() {
    return { HTMLAttributes: {} }
  },

  addAttributes() {
    return {
      size: {
        default: null,
        parseHTML: element => {
          const fs = element.style?.fontSize
          if (fs) return String(parseInt(fs, 10))
          const fontAttr = element.getAttribute?.('size')
          if (fontAttr) return FONT_SIZE_MAP[fontAttr] || null
          return null
        },
        renderHTML: attributes => {
          if (!attributes.size) return {}
          return { style: `font-size: ${attributes.size}px` }
        },
      },
    }
  },

  parseHTML() {
    return [
      { tag: 'span[style*="font-size"]' },
      { tag: 'font[size]' },
    ]
  },

  renderHTML({ HTMLAttributes }) {
    return ['span', mergeAttributes(this.options.HTMLAttributes, HTMLAttributes), 0]
  },

  addCommands() {
    return {
      setFontSize:
        size =>
        ({ chain }) => {
          if (!size || size === '16') {
            return chain().unsetMark('fontSize').run()
          }
          return chain().setMark('fontSize', { size }).run()
        },
      unsetFontSize:
        () =>
        ({ chain }) => {
          return chain().unsetMark('fontSize').run()
        },
    }
  },
})

export const Indent = Extension.create({
  name: 'indent',

  addOptions() {
    return {
      types: ['paragraph', 'heading', 'blockquote'],
      minLevel: 0,
      maxLevel: 8,
      indentSize: 40,
    }
  },

  addGlobalAttributes() {
    return [
      {
        types: this.options.types,
        attributes: {
          indent: {
            default: 0,
            parseHTML: element => {
              const ml = parseInt(element.style.marginLeft, 10) || 0
              return Math.round(ml / this.options.indentSize)
            },
            renderHTML: attributes => {
              if (!attributes.indent || attributes.indent <= 0) return {}
              return { style: `margin-left: ${attributes.indent * this.options.indentSize}px` }
            },
          },
        },
      },
    ]
  },

  addCommands() {
    return {
      indent:
        () =>
        ({ tr, state, dispatch }) => {
          const { from, to } = state.selection
          const types = this.options.types
          const maxLevel = this.options.maxLevel
          let modified = false
          state.doc.nodesBetween(from, to, (node, pos) => {
            if (node.isBlock && types.includes(node.type.name)) {
              const cur = node.attrs.indent || 0
              if (cur < maxLevel) {
                tr.setNodeMarkup(pos, null, { ...node.attrs, indent: cur + 1 })
                modified = true
              }
            }
          })
          if (modified && dispatch) dispatch(tr)
          return modified
        },
      outdent:
        () =>
        ({ tr, state, dispatch }) => {
          const { from, to } = state.selection
          const types = this.options.types
          let modified = false
          state.doc.nodesBetween(from, to, (node, pos) => {
            if (node.isBlock && types.includes(node.type.name)) {
              const cur = node.attrs.indent || 0
              if (cur > 0) {
                tr.setNodeMarkup(pos, null, { ...node.attrs, indent: cur - 1 })
                modified = true
              }
            }
          })
          if (modified && dispatch) dispatch(tr)
          return modified
        },
    }
  },

  addKeyboardShortcuts() {
    return {
      Tab: () => this.editor.commands.indent(),
      'Shift-Tab': () => this.editor.commands.outdent(),
    }
  },
})

export const CustomImage = Image.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      width: {
        default: null,
        parseHTML: element => element.getAttribute('width'),
        renderHTML: attributes => {
          if (!attributes.width) return {}
          return { width: attributes.width }
        },
      },
      height: {
        default: null,
        parseHTML: element => element.getAttribute('height'),
        renderHTML: attributes => {
          if (!attributes.height) return {}
          return { height: attributes.height }
        },
      },
      style: {
        default: null,
        parseHTML: element => element.getAttribute('style'),
        renderHTML: attributes => {
          if (!attributes.style) return {}
          return { style: attributes.style }
        },
      },
    }
  },

  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: new PluginKey('imageResize'),
        props: {
          handleDOMEvents: {
            mousedown: (view, event) => {
              const target = event.target
              if (target.tagName !== 'IMG') return false

              const img = target
              const startX = event.clientX
              const startY = event.clientY
              const startWidth = img.offsetWidth
              const startHeight = img.offsetHeight
              const aspectRatio = startWidth / startHeight

              const onMouseMove = (e) => {
                const deltaX = e.clientX - startX
                const deltaY = e.clientY - startY
                const delta = Math.max(deltaX, deltaY)
                const newWidth = Math.max(50, startWidth + delta)
                const newHeight = Math.round(newWidth / aspectRatio)

                img.style.width = newWidth + 'px'
                img.style.height = newHeight + 'px'
              }

              const onMouseUp = () => {
                document.removeEventListener('mousemove', onMouseMove)
                document.removeEventListener('mouseup', onMouseUp)

                const { from } = view.state.selection
                const node = view.state.doc.nodeAt(from)
                if (node && node.type.name === 'image') {
                  const tr = view.state.tr.setNodeMarkup(from, null, {
                    ...node.attrs,
                    width: img.style.width,
                    height: img.style.height,
                  })
                  view.dispatch(tr)
                }
              }

              document.addEventListener('mousemove', onMouseMove)
              document.addEventListener('mouseup', onMouseUp)

              return true
            },
          },
        },
      }),
    ]
  },
})

export const LineHeight = Mark.create({
  name: 'lineHeight',

  addOptions() {
    return { HTMLAttributes: {} }
  },

  addAttributes() {
    return {
      height: {
        default: null,
        parseHTML: element => {
          const lh = element.style?.lineHeight
          if (lh) return lh
          return null
        },
        renderHTML: attributes => {
          if (!attributes.height) return {}
          return { style: `line-height: ${attributes.height}` }
        },
      },
    }
  },

  parseHTML() {
    return [{ tag: 'span[style*="line-height"]' }]
  },

  renderHTML({ HTMLAttributes }) {
    return ['span', mergeAttributes(this.options.HTMLAttributes, HTMLAttributes), 0]
  },

  addCommands() {
    return {
      setLineHeight:
        height =>
        ({ chain }) => {
          if (!height || height === '1.8') {
            return chain().unsetMark('lineHeight').run()
          }
          return chain().setMark('lineHeight', { height }).run()
        },
    }
  },
})