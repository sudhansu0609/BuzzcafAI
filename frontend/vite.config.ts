import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    react(),
    {
      name: 'allow-all-hosts',
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          req.headers.host = 'localhost:3005';
          next();
        });
      }
    }
  ],
  server: {
    port: 3005,
    host: '0.0.0.0',
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8095',
        changeOrigin: true,
        secure: false,
      }
    }
  }
})
