export function createStatusBar(editor) {
  const bar = document.createElement('div')
  bar.className = 'rte-statusbar'

  const wordCount = document.createElement('span')
  wordCount.className = 'rte-wordcount'

  const charCount = document.createElement('span')
  charCount.className = 'rte-charcount'

  const lineCount = document.createElement('span')
  lineCount.className = 'rte-linecount'

  bar.appendChild(wordCount)
  bar.appendChild(charCount)
  bar.appendChild(lineCount)

  function updateStats() {
    const text = editor.getText()
    const chars = text.length
    const words = text.trim() ? text.trim().split(/\s+/).length : 0
    const lines = editor.getHTML().split(/<p|<h[1-6]|<pre|<blockquote|<li/).length - 1

    wordCount.textContent = `字数: ${words}`
    charCount.textContent = `字符: ${chars}`
    lineCount.textContent = `段落: ${Math.max(0, lines)}`
  }

  updateStats()
  editor.on('update', updateStats)

  return bar
}