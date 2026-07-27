import { defineConfig } from 'vite'
import { resolve } from 'path'

export default defineConfig({
  build: {
    lib: {
      entry: resolve(__dirname, 'src/editor/main.js'),
      name: 'HoshinoEditor',
      formats: ['iife'],
      fileName: () => 'js/tiptap-editor.js',
    },
    outDir: resolve(__dirname, 'static'),
    emptyOutDir: false,
    minify: true,
    sourcemap: true,
    rollupOptions: {
      output: {
        assetFileNames: 'css/tiptap-editor.[ext]',
      },
    },
  },
})