import './style.css'
import { createFullEditor } from './full'
import { createMinimalEditor } from './minimal'

const HoshinoEditor = {
  createFull: createFullEditor,
  createMinimal: createMinimalEditor,
}

// 直接赋值给 window，确保全局可访问
window.HoshinoEditor = HoshinoEditor

export default HoshinoEditor
export { createFullEditor, createMinimalEditor }