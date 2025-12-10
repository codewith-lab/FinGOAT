import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react({
      babel: {
        plugins: [['babel-plugin-react-compiler']],
      },
    }),
  ],
  server: {
    proxy: {
      // Proxy API calls to backend during local dev to keep VITE_API_URL empty/relative.
      '/api': 'http://localhost:3000',
      '/trading': 'http://localhost:8001',
    },
  },
})
