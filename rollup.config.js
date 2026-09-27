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
      // extract: true → 样式提取到与 output.file 同名同目录的文件，
      // 即 static/js/tiptap-editor.css。模板（admin/post-form.html、
      // admin/profile.html）引用同一路径，构建产物即页面加载的文件。
      //
      // 历史问题：模板曾引用 static/css/tiptap-editor.css（另一份手工副本），
      // 与构建产物长期漂移（实测 90 vs 137 条规则，代码块高亮主题缺失）。
      // 注意 rollup 限制：extract 的路径只能相对 output.file 目录且不能用
      // '../'，因此无法直接输出到 static/css/，故统一采用本目录下的产物。
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