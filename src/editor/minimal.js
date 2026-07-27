import { Editor } from '@tiptap/core'
import StarterKit from '@tiptap/starter-kit'
import Underline from '@tiptap/extension-underline'
import Link from '@tiptap/extension-link'
import Placeholder from '@tiptap/extension-placeholder'
import { createMinimalToolbar } from './toolbar-minimal'

export function createMinimalEditor(containerSelector, options = {}) {
  const container = document.querySelector(containerSelector)
  if (!container) throw new Error('Editor container not found: ' + containerSelector)

  container.innerHTML = ''
  container.classList.add('rte-container')

  const editorEl = document.createElement('div')
  editorEl.className = 'rte-content'
  container.appendChild(editorEl)

  const editor = new Editor({
    element: editorEl,
    content: options.content || '',
    extensions: [
      StarterKit.configure({
        heading: { levels: [2, 3] },
      }),
      Underline,
      Link.configure({
        openOnClick: false,
        HTMLAttributes: { rel: 'noopener noreferrer', target: '_blank' },
      }),
      Placeholder.configure({ placeholder: '开始编辑…' }),
    ],
  })

  const toolbar = createMinimalToolbar(editor)
  container.insertBefore(toolbar, editorEl)

  return {
    editor,
    getHTML: () => editor.getHTML(),
    setHTML: html => editor.commands.setContent(html),
    destroy: () => editor.destroy(),
  }
}