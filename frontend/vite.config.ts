import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The backend lives on 8099 (8000 collides with other local apps) and the
// desktop shell may still have to move it when even that is taken (see
// backend/desktop_app.py _resolve_port); it passes the real port to this
// process as BUZZCAF_PORT, so point the dev proxy there, never at a literal.
const backendTarget = `http://127.0.0.1:${process.env.BUZZCAF_PORT || '8099'}`

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  // The desktop app serves this bundle from FastAPI (backend/app/static is
  // mounted at '/'), so the build writes straight into that folder.
  base: './',
  build: {
    outDir: '../backend/app/static',
    emptyOutDir: true,
  },
  server: {
    // The desktop shell picks a free port (5173 is often another project's
    // Vite) and passes it as BUZZCAF_DEV_PORT / --port. strictPort: if that
    // port is taken, fail - never drift to a neighbour the window won't open.
    port: Number(process.env.BUZZCAF_DEV_PORT || 5173),
    strictPort: true,
    host: true,
    proxy: {
      '/api': {
        target: backendTarget,
        changeOrigin: true,
        secure: false
      },
      '/projects': {
        target: backendTarget,
        changeOrigin: true,
        secure: false
      },
      '/health': {
        target: backendTarget,
        changeOrigin: true,
        secure: false
      }
    }
  }
})
