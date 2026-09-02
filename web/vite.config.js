import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Proxying keeps the browser same-origin, which is why no CORS
    // middleware exists anywhere in this project.
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
