import './style.css'
import { createFullEditor } from './full'
import { createMinimalEditor } from './minimal'

const HoshinoEditor = {
  createFull: createFullEditor,
  createMinimal: createMinimalEditor,
}


export default HoshinoEditor
export { createFullEditor, createMinimalEditor }