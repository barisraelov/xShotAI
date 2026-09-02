import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The dev proxy is only used when VITE_API_URL is empty. When VITE_API_URL is
// set (see .env) the app calls that origin directly and these entries are moot.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/analyze': 'http://localhost:8000',
      '/jobs': 'http://localhost:8000',
      '/auth': 'http://localhost:8000',
      '/users': 'http://localhost:8000',
    },
  },
})
