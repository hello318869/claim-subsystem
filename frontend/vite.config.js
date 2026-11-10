import { resolve } from 'node:path'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

export default defineConfig(({ command }) => ({
  root: resolve(import.meta.dirname, 'spa'),
  base: command === 'build' ? '/ui-assets/' : '/',
  plugins: [vue()],
  build: { outDir: resolve(import.meta.dirname, 'dist'), emptyOutDir: true },
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': process.env.API_PROXY_TARGET || 'http://127.0.0.1:8000' },
  },
  test: { environment: 'jsdom', include: ['src/**/*.spec.js'], restoreMocks: true },
}))
