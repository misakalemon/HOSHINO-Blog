import { Editor } from '@tiptap/core'
import StarterKit from '@tiptap/starter-kit'
import Underline from '@tiptap/extension-underline'
import TextAlign from '@tiptap/extension-text-align'
import TextStyle from '@tiptap/extension-text-style'
import { Color } from '@tiptap/extension-color'
import Highlight from '@tiptap/extension-highlight'
import Superscript from '@tiptap/extension-superscript'
import Subscript from '@tiptap/extension-subscript'
import { Table } from '@tiptap/extension-table'
import TableRow from '@tiptap/extension-table-row'
import TableCell from '@tiptap/extension-table-cell'
import TableHeader from '@tiptap/extension-table-header'
import Link from '@tiptap/extension-link'
import CodeBlockLowlight from '@tiptap/extension-code-block-lowlight'
import Placeholder from '@tiptap/extension-placeholder'
import TaskList from '@tiptap/extension-task-list'
import TaskItem from '@tiptap/extension-task-item'
import Gapcursor from '@tiptap/extension-gapcursor'
import Dropcursor from '@tiptap/extension-dropcursor'
import { common, createLowlight } from 'lowlight'
import { FontSize, Indent, CustomImage } from './extensions'
import { createFullToolbar } from './toolbar-full'

const lowlight = createLowlight(common)

export function createFullEditor(containerSelector, options = {}) {
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
        codeBlock: false,
        heading: { levels: [1, 2, 3, 4] },
      }),
      Underline,
      TextAlign.configure({ types: ['heading', 'paragraph'] }),
      TextStyle,
      Color,
      Highlight.configure({ multicolor: true }),
      Superscript,
      Subscript,
      Table.configure({ resizable: true }),
      TableRow,
      TableCell,
      TableHeader,

      CustomImage.configure({ inline: true, allowBase64: true }),
      Link.configure({
        openOnClick: false,
        HTMLAttributes: { rel: 'noopener noreferrer', target: '_blank' },
      }),
      CodeBlockLowlight.configure({ lowlight }),
      Placeholder.configure({ placeholder: '开始写作…' }),
      FontSize,
      Indent,
      TaskList,
      TaskItem.configure({ nested: true }),
      Gapcursor,
      Dropcursor,
    ],
  })

  const toolbar = createFullToolbar(editor, options)
  container.insertBefore(toolbar, editorEl)

  return {
    editor,
    getHTML: () => editor.getHTML(),
    setHTML: html => editor.commands.setContent(html),
    destroy: () => editor.destroy(),
  }
}