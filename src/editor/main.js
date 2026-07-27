import './style.css'
import { createFullEditor } from './full'
import { createMinimalEditor } from './minimal'

const HoshinoEditor = {
  createFull: createFullEditor,
  createMinimal: createMinimalEditor,
}

if (typeof window !== 'undefined') {
  window.HoshinoEditor = HoshinoEditor
}

export default HoshinoEditor
export { createFullEditor, createMinimalEditor }