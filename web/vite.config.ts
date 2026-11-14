import { realpathSync } from 'node:fs'
import { dirname } from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// node_modules là junction tới C:\tv-data\web-deps (ngoài OneDrive).
// Vite cần được phép đọc thư mục thật mà junction trỏ tới.
const depsRoot = dirname(realpathSync('node_modules'))

// /api đi qua proxy tới server Python, nên trình duyệt không gặp lỗi CORS.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    fs: { allow: ['.', depsRoot] },
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false },
    },
  },
})
