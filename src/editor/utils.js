const UNSAFE_URL_PROTOCOLS = /^(javascript|data|vbscript|file):/i

export function isSafeUrl(url) {
  if (!url) return true
  const v = String(url).trim()
  if (!v) return true
  if (UNSAFE_URL_PROTOCOLS.test(v)) return false
  return true
}

export function sanitizeHTML(html) {
  if (!html) return html
  const doc = new DOMParser().parseFromString(String(html), 'text/html')
  // 移除可执行/表单/外部加载元素（后端 bleach 白名单的纵深防御镜像）
  doc
    .querySelectorAll('script, iframe, object, embed, form, input, button, select, textarea, meta, link, noscript')
    .forEach(el => el.remove())
  // 清理事件属性与危险协议 URL
  doc.querySelectorAll('*').forEach(el => {
    ;[...el.attributes].forEach(attr => {
      const name = attr.name.toLowerCase()
      if (name.startsWith('on')) {
        el.removeAttribute(attr.name)
        return
      }
      if (['href', 'src', 'xlink:href', 'action', 'poster', 'formaction', 'cite'].includes(name)) {
        if (!isSafeUrl(attr.value)) el.removeAttribute(attr.name)
      }
    })
  })
  return doc.body.innerHTML
}

export function showModal(options) {
  let overlay = document.getElementById('rte-modal-overlay')
  if (!overlay) {
    overlay = document.createElement('div')
    overlay.id = 'rte-modal-overlay'
    overlay.className = 'rte-modal-overlay'
    overlay.addEventListener('click', e => {
      if (e.target === overlay) overlay.style.display = 'none'
    })
    document.body.appendChild(overlay)
  }
  overlay.innerHTML = ''
  const modal = document.createElement('div')
  modal.className = 'rte-modal'
  const title = document.createElement('h4')
  title.textContent = options.title || ''
  modal.appendChild(title)
  const fieldsDiv = document.createElement('div')
  fieldsDiv.className = 'rte-modal-fields'
  const inputs = {}
  ;(options.fields || []).forEach(f => {
    const label = document.createElement('label')
    label.textContent = f.label
    fieldsDiv.appendChild(label)
    if (f.type === 'select') {
      // 使用项目的 glow-select-wrap 组件
      const wrap = document.createElement('div')
      wrap.className = 'glow-select-wrap'
      
      const trigger = document.createElement('div')
      trigger.className = 'glow-select-trigger'
      
      const valueSpan = document.createElement('span')
      valueSpan.className = 'glow-select-value'
      const selectedOption = (f.options || []).find(o => o.value === (f.value || ''))
      valueSpan.textContent = selectedOption ? selectedOption.label : ''
      
      const arrow = document.createElement('span')
      arrow.className = 'glow-select-arrow'
      arrow.textContent = '▼'
      
      trigger.appendChild(valueSpan)
      trigger.appendChild(arrow)
      
      const menu = document.createElement('div')
      menu.className = 'glow-select-menu'
      
      let currentValue = f.value || ''
      
      ;(f.options || []).forEach(o => {
        const item = document.createElement('div')
        item.className = 'glow-select-option'
        if (o.value === currentValue) item.classList.add('is-selected')
        item.textContent = o.label
        item.addEventListener('click', (e) => {
          e.stopPropagation()
          valueSpan.textContent = o.label
          currentValue = o.value
          menu.querySelectorAll('.glow-select-option').forEach(opt => opt.classList.remove('is-selected'))
          item.classList.add('is-selected')
          wrap.classList.remove('is-open')
        })
        menu.appendChild(item)
      })
      
      trigger.addEventListener('click', (e) => {
        e.stopPropagation()
        document.querySelectorAll('.glow-select-wrap.is-open').forEach(w => {
          if (w !== wrap) w.classList.remove('is-open')
        })
        wrap.classList.toggle('is-open')
      })
      
      wrap.appendChild(trigger)
      wrap.appendChild(menu)
      inputs[f.key] = { getValue: () => currentValue }
      fieldsDiv.appendChild(wrap)
    } else {
      const input = document.createElement('input')
      input.type = f.type || 'text'
      input.value = f.value || ''
      input.placeholder = f.placeholder || ''
      if (f.min !== undefined) input.min = f.min
      if (f.max !== undefined) input.max = f.max
      inputs[f.key] = input
      fieldsDiv.appendChild(input)
    }
  })
  modal.appendChild(fieldsDiv)
  const actions = document.createElement('div')
  actions.className = 'rte-modal-actions'
  const cancelBtn = document.createElement('button')
  cancelBtn.className = 'btn btn-ghost'
  cancelBtn.textContent = '取消'
  cancelBtn.onclick = () => {
    overlay.style.display = 'none'
  }
  const confirmBtn = document.createElement('button')
  confirmBtn.className = 'btn btn-primary'
  confirmBtn.textContent = '确定'
  confirmBtn.onclick = () => {
    const result = {}
    ;(options.fields || []).forEach(f => {
      const input = inputs[f.key]
      result[f.key] = input.getValue ? input.getValue() : input.value
    })
    overlay.style.display = 'none'
    if (options.onConfirm) options.onConfirm(result)
  }
  actions.appendChild(cancelBtn)
  actions.appendChild(confirmBtn)
  modal.appendChild(actions)
  overlay.appendChild(modal)
  overlay.style.display = 'flex'
  const first = modal.querySelector('input')
  if (first) setTimeout(() => first.focus(), 100)
  modal.addEventListener('keydown', e => {
    if (e.key === 'Enter') confirmBtn.click()
    if (e.key === 'Escape') cancelBtn.click()
  })
  
  // 点击外部关闭下拉菜单
  document.addEventListener('click', () => {
    document.querySelectorAll('.glow-select-wrap.is-open').forEach(w => {
      w.classList.remove('is-open')
    })
  })
}

export function simpleMDtoHTML(md) {
  if (!md) return ''
  function inline(text) {
    return text
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/__(.+?)__/g, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g, '<em>$1</em>')
      .replace(/_(.+?)_/g, '<em>$1</em>')
      .replace(/~~(.+?)~~/g, '<del>$1</del>')
      .replace(/\$\$(.+?)\$\$/g, '<code>$1</code>')
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (m, text, url) => '<a href="' + (isSafeUrl(url) ? url : '#') + '">' + text + '</a>')
      .replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (m, alt, url) => '<img src="' + (isSafeUrl(url) ? url : '') + '" alt="' + alt + '">')
  }
  const lines = md.split('\n')
  let html = ''
  let inCode = false
  let codeLang = ''
  let inUl = false
  let inOl = false
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const codeMatch = line.match(/^(`{3,}|~{3,})\s*(\w*)/)
    if (codeMatch) {
      if (inCode) {
        html += '</code></pre>\n'
        inCode = false
      } else {
        codeLang = codeMatch[2]
        html +=
          '<pre><code' +
          (codeLang ? ' class="language-' + codeLang + '"' : '') +
          '>'
        inCode = true
      }
      if (inUl) {
        html += '</ul>\n'
        inUl = false
      }
      if (inOl) {
        html += '</ol>\n'
        inOl = false
      }
      continue
    }
    if (inCode) {
      html += line + '\n'
      continue
    }
    if (inUl && !/^[\s]*[-*+]\s+/.test(line) && !/^[\s]*$/.test(line)) {
      html += '</ul>\n'
      inUl = false
    }
    if (inOl && !/^[\s]*\d+\.\s+/.test(line) && !/^[\s]*$/.test(line)) {
      html += '</ol>\n'
      inOl = false
    }
    const hMatch = line.match(/^(#{1,6})\s+(.+)/)
    if (hMatch) {
      html +=
        '<h' + hMatch[1].length + '>' + inline(hMatch[2]) + '</h' + hMatch[1].length + '>\n'
      continue
    }
    if (/^(-{3,}|\*{3,})[\s]*$/.test(line)) {
      html += '<hr>\n'
      continue
    }
    if (!line.trim()) {
      html += '\n'
      continue
    }
    const qMatch = line.match(/^>\s*(.*)/)
    if (qMatch) {
      html += '<blockquote>' + inline(qMatch[1]) + '</blockquote>\n'
      continue
    }
    const ulMatch = line.match(/^[\s]*[-*+]\s+(.+)/)
    if (ulMatch) {
      if (!inUl) {
        html += '<ul>\n'
        inUl = true
      }
      const taskMatch = ulMatch[1].match(/^\[([ xX])\]\s*(.+)/)
      if (taskMatch) {
        const checked = taskMatch[1].toLowerCase() === 'x'
        html +=
          '<li' +
          (checked ? ' class="task-done"' : '') +
          '><input type="checkbox" disabled' +
          (checked ? ' checked' : '') +
          '> ' +
          inline(taskMatch[2]) +
          '</li>\n'
      } else {
        html += '<li>' + inline(ulMatch[1]) + '</li>\n'
      }
      continue
    }
    const olMatch = line.match(/^[\s]*(\d+)\.\s+(.+)/)
    if (olMatch) {
      if (!inOl) {
        html += '<ol start="' + olMatch[1] + '">\n'
        inOl = true
      }
      html += '<li>' + inline(olMatch[2]) + '</li>\n'
      continue
    }
    if (
      line.includes('|') &&
      i + 1 < lines.length &&
      /^[\s]*\|[\s]*[-:]+\|/.test(lines[i + 1])
    ) {
      let tableHtml = '<table>\n'
      const headers = line.split('|').filter(c => c.trim())
      tableHtml += '<thead><tr>'
      for (let h = 0; h < headers.length; h++)
        tableHtml += '<th>' + inline(headers[h].trim()) + '</th>'
      tableHtml += '</tr></thead>\n<tbody>\n'
      i += 2
      while (i < lines.length && lines[i].includes('|')) {
        const cells = lines[i].split('|').filter(c => c.trim())
        tableHtml += '<tr>'
        for (let c = 0; c < cells.length; c++)
          tableHtml += '<td>' + inline(cells[c].trim()) + '</td>'
        tableHtml += '</tr>\n'
        i++
      }
      i--
      tableHtml += '</tbody>\n</table>\n'
      html += tableHtml
      continue
    }
    let paragraph = line
    while (
      i + 1 < lines.length &&
      lines[i + 1].trim() &&
      !/^(#{1,6}\s|```|>|---|\*{3,}|[\s]*[-*+]\s|[\s]*\d+\.\s)/.test(lines[i + 1])
    ) {
      i++
      paragraph += '\n' + lines[i]
    }
    html += '<p>' + inline(paragraph) + '</p>\n'
  }
  if (inCode) html += '</code></pre>\n'
  if (inUl) html += '</ul>\n'
  if (inOl) html += '</ol>\n'
  return html
}

function loadPDFJS() {
  return new Promise((resolve, reject) => {
    if (window.pdfjsLib) {
      resolve(window.pdfjsLib)
      return
    }
    const s = document.createElement('script')
    s.src = '/static/vendor/pdf.min.js'
    s.onload = () => {
      pdfjsLib.GlobalWorkerOptions.workerSrc = '/static/vendor/pdf.worker.min.js'
      resolve(window.pdfjsLib)
    }
    s.onerror = reject
    document.head.appendChild(s)
  })
}

function loadMammoth() {
  return new Promise((resolve, reject) => {
    if (window.mammoth) {
      resolve(window.mammoth)
      return
    }
    const s = document.createElement('script')
    s.src = '/static/vendor/mammoth.browser.min.js'
    s.onload = () => resolve(window.mammoth)
    s.onerror = reject
    document.head.appendChild(s)
  })
}

function esc(s) {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function pdfItemsToHTML(items) {
  if (!items || !items.length) return ''
  let totalSize = 0,
    count = 0
  items.forEach(it => {
    const s = it.height || it.transform[0] || 0
    if (s > 0) {
      totalSize += s
      count++
    }
  })
  const avgSize = count > 0 ? totalSize / count : 12
  const sorted = items.slice().sort((a, b) => {
    const ya = a.transform[5],
      yb = b.transform[5]
    if (Math.abs(ya - yb) > 2) return yb - ya
    return a.transform[4] - b.transform[4]
  })
  const lines = []
  let cur = null
  sorted.forEach(it => {
    const y = it.transform[5]
    if (!cur || Math.abs(cur.y - y) > 2) {
      cur = { y, items: [it] }
      lines.push(cur)
    } else {
      cur.items.push(it)
    }
  })
  let out = '',
    prevY = null
  lines.forEach(ln => {
    const text = ln.items
      .map(it => it.str)
      .join('')
      .trim()
    if (!text) return
    let maxSize = 0,
      hasBold = false
    ln.items.forEach(it => {
      const s = it.height || it.transform[0] || 0
      if (s > maxSize) maxSize = s
      if (it.fontName && /bold|heavy|black/i.test(it.fontName)) hasBold = true
    })
    const ratio = avgSize > 0 ? maxSize / avgSize : 1
    let tag = 'p'
    if (ratio > 2.0) tag = 'h1'
    else if (ratio > 1.6) tag = 'h2'
    else if (ratio > 1.3) tag = 'h3'
    else if (ratio > 1.1) tag = 'h4'
    const gap = prevY !== null ? prevY - ln.y : 0
    if (gap > 15 && tag === 'p') out += '</p><p>'
    if (tag !== 'p') out += '<' + tag + '>' + esc(text) + '</' + tag + '>'
    else if (hasBold) out += '<strong>' + esc(text) + '</strong> '
    else out += esc(text) + ' '
    prevY = ln.y
  })
  return '<p>' + out.trim() + '</p>'
}

function importPDFStyled(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = e => {
      const data = new Uint8Array(e.target.result)
      loadPDFJS()
        .then(pdfjsLib => {
          pdfjsLib
            .getDocument({ data })
            .promise.then(pdf => {
              const ps = []
              for (let i = 1; i <= pdf.numPages; i++) {
                ps.push(
                  pdf
                    .getPage(i)
                    .then(page => page.getTextContent().then(tc => pdfItemsToHTML(tc.items)))
                )
              }
              Promise.all(ps).then(pages => resolve(pages.join('\n')))
            })
            .catch(reject)
        })
        .catch(reject)
    }
    reader.readAsArrayBuffer(file)
  })
}

function importDOCX(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = e => {
      loadMammoth()
        .then(mammoth => {
          mammoth
            .convertToHtml({
              arrayBuffer: e.target.result,
              styleMap: [
                "p[style-name='Title'] => h1:fresh",
                "p[style-name='Subtitle'] => h2:fresh",
                "p[style-name='Heading 1'] => h1:fresh",
                "p[style-name='Heading 2'] => h2:fresh",
                "p[style-name='Heading 3'] => h3:fresh",
                "p[style-name='Heading 4'] => h4:fresh",
                "r[style-name='Strong'] => strong",
                "r[style-name='Emphasis'] => em",
              ],
            })
            .then(result => resolve(result.value))
            .catch(reject)
        })
        .catch(reject)
    }
    reader.readAsArrayBuffer(file)
  })
}

export function importFile() {
  return new Promise((resolve, reject) => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.md,.markdown,.pdf,.docx,.html,.htm'
    input.onchange = () => {
      const file = input.files[0]
      if (!file) return
      const ext = file.name.split('.').pop().toLowerCase()
      if (ext === 'md' || ext === 'markdown') {
        const reader = new FileReader()
        reader.onload = e => resolve(simpleMDtoHTML(e.target.result))
        reader.readAsText(file, 'UTF-8')
      } else if (ext === 'pdf') {
        importPDFStyled(file).then(resolve).catch(reject)
      } else if (ext === 'docx') {
        importDOCX(file).then(resolve).catch(reject)
      } else if (ext === 'html' || ext === 'htm') {
        const reader = new FileReader()
        // HTML 文件导入必须过净化（原实现直接 resolve 原文，脚本原样进入编辑器）
        reader.onload = e => resolve(sanitizeHTML(e.target.result))
        reader.readAsText(file, 'UTF-8')
      }
    }
    input.click()
  })
}

export function uploadImageWithCrop(uploadUrl, csrfToken) {
  return new Promise((resolve, reject) => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = 'image/*'
    input.style.cssText =
      'position:absolute;left:-9999px;opacity:0;width:1px;height:1px'
    document.body.appendChild(input)
    input.onchange = () => {
      document.body.removeChild(input)
      const file = input.files[0]
      if (!file) return
      if (typeof openCropModal === 'function') {
        openCropModal(file, cropped => {
          if (!cropped) return
          const formData = new FormData()
          formData.append('file', cropped, file.name)
          if (typeof showToast === 'function') showToast('上传中…')
          fetch(uploadUrl, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken },
            body: formData,
          })
            .then(r => r.json())
            .then(data => {
              if (data.url) resolve(data.url)
              else reject(new Error('上传失败'))
            })
            .catch(reject)
        })
      } else {
        const formData = new FormData()
        formData.append('file', file)
        fetch(uploadUrl, {
          method: 'POST',
          headers: { 'X-CSRFToken': csrfToken },
          body: formData,
        })
          .then(r => r.json())
          .then(data => {
            if (data.url) resolve(data.url)
            else reject(new Error('上传失败'))
          })
          .catch(reject)
      }
    }
    input.click()
  })
}