import { defineConfig } from 'vite';

// In dev the frontend runs on :5173 and the backend on :8000. With API_BASE=''
// the app calls same-origin paths like /api/... and /health; this proxy forwards
// those to the backend so the same code works in dev and in the packaged build.
export default defineConfig({
  server: {
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/health': { target: 'http://localhost:8000', changeOrigin: true },
      '/ws': { target: 'http://localhost:8000', ws: true, changeOrigin: true },
    },
  },
});
