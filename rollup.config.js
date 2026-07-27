import resolve from '@rollup/plugin-node-resolve'
import commonjs from '@rollup/plugin-commonjs'
import terser from '@rollup/plugin-terser'
import postcss from 'rollup-plugin-postcss'

export default {
  input: 'src/editor/main.js',
  output: {
    file: 'static/js/tiptap-editor.js',
    format: 'iife',
    name: 'HoshinoEditor',
    sourcemap: true,
    footer: 'window.HoshinoEditor = HoshinoEditor.default;',
  },
  plugins: [
    postcss({
      extract: true,
      minimize: true,
    }),
    resolve({
      browser: true,
      dedupe: ['@tiptap/core'],
    }),
    commonjs(),
    terser({
      format: { comments: false },
    }),
  ],
}