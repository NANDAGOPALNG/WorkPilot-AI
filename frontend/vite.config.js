import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // The backend's CORS allow-list is http://localhost:5173, so fail loudly instead of picking another port.
  server: { port: 5173, strictPort: true },
})
