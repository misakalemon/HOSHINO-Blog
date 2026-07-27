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

import { common, createLowlight } from 'lowlight'
import ts from 'highlight.js/lib/languages/typescript'
import go from 'highlight.js/lib/languages/go'
import rust from 'highlight.js/lib/languages/rust'
import java from 'highlight.js/lib/languages/java'
import kotlin from 'highlight.js/lib/languages/kotlin'
import swift from 'highlight.js/lib/languages/swift'
import csharp from 'highlight.js/lib/languages/csharp'
import cpp from 'highlight.js/lib/languages/cpp'
import c from 'highlight.js/lib/languages/c'
import scala from 'highlight.js/lib/languages/scala'
import r from 'highlight.js/lib/languages/r'
import matlab from 'highlight.js/lib/languages/matlab'
import lua from 'highlight.js/lib/languages/lua'
import perl from 'highlight.js/lib/languages/perl'
import ruby from 'highlight.js/lib/languages/ruby'
import php from 'highlight.js/lib/languages/php'
import dart from 'highlight.js/lib/languages/dart'
import xml from 'highlight.js/lib/languages/xml'
import markdown from 'highlight.js/lib/languages/markdown'
import dockerfile from 'highlight.js/lib/languages/dockerfile'
import nginx from 'highlight.js/lib/languages/nginx'
import ini from 'highlight.js/lib/languages/ini'
import diff from 'highlight.js/lib/languages/diff'
import plaintext from 'highlight.js/lib/languages/plaintext'
import { FontSize, Indent, CustomImage, LineHeight } from './extensions'
import { createFullToolbar } from './toolbar-full'
import { createBubbleMenu } from './bubble-menu'
import { createStatusBar } from './status-bar'
import { createContextMenu } from './context-menu'

const lowlight = createLowlight(common)
lowlight.register('typescript', ts)
lowlight.register('go', go)
lowlight.register('rust', rust)
lowlight.register('java', java)
lowlight.register('kotlin', kotlin)
lowlight.register('swift', swift)
lowlight.register('csharp', csharp)
lowlight.register('cpp', cpp)
lowlight.register('c', c)
lowlight.register('scala', scala)
lowlight.register('r', r)
lowlight.register('matlab', matlab)
lowlight.register('lua', lua)
lowlight.register('perl', perl)
lowlight.register('ruby', ruby)
lowlight.register('php', php)
lowlight.register('dart', dart)
lowlight.register('xml', xml)
lowlight.register('markdown', markdown)
lowlight.register('dockerfile', dockerfile)
lowlight.register('nginx', nginx)
lowlight.register('ini', ini)
lowlight.register('diff', diff)
lowlight.register('plaintext', plaintext)

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
      LineHeight,
      TaskList,
      TaskItem.configure({ nested: true }),

    ],
  })

  const toolbar = createFullToolbar(editor, options)
  container.insertBefore(toolbar, editorEl)

  createBubbleMenu(editor)

  createContextMenu(editor, options)

  const statusBar = createStatusBar(editor)
  container.appendChild(statusBar)

  return {
    editor,
    getHTML: () => editor.getHTML(),
    setHTML: html => editor.commands.setContent(html),
    destroy: () => editor.destroy(),
  }
}