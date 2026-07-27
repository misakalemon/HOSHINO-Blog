import { Mark, Extension, mergeAttributes } from '@tiptap/core'
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
})