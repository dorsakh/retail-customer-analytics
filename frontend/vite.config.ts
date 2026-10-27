import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/',
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/explorer': 'http://127.0.0.1:8001',
      '/monitoring': 'http://127.0.0.1:8001',
      '/pipeline': 'http://127.0.0.1:8001',
      '/predictions': 'http://127.0.0.1:8001',
      '/health': 'http://127.0.0.1:8001',
      '/docs': 'http://127.0.0.1:8001'
    }
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    clearMocks: true
  }
})
