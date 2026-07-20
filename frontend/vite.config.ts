import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
        // Long-running SSE (Whisper + Claude) — never idle-timeout the proxy.
        timeout: 0,
        proxyTimeout: 0,
        // Don't buffer SSE — flush each event to the browser immediately.
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            const ct = proxyRes.headers['content-type'] || ''
            if (String(ct).includes('text/event-stream')) {
              proxyRes.headers['cache-control'] = 'no-cache'
              proxyRes.headers['x-accel-buffering'] = 'no'
              // Disable Node socket timeouts on the proxied long-lived response.
              proxyRes.socket?.setTimeout?.(0)
            }
          })
        },
      },
    },
  },
})
