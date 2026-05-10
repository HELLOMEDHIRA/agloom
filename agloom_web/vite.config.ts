import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { resolve } from 'node:path'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      '@': resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3000,
    // Proxy AGP WebSocket to the Python runtime during development.
    // In production the reverse proxy (nginx / Caddy) handles this.
      proxy: {
        '/agp-ws': {
          target: 'ws://localhost:8765',
          ws: true,
          rewrite: (path) => path.replace(/^\/agp-ws/, ''),
        },
        '/api': {
          target: 'http://localhost:8765',
          changeOrigin: true,
        },
        '/observe': {
          target: 'http://localhost:8766',
          changeOrigin: true,
        },
      },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/react') || id.includes('node_modules/react-dom')) return 'react'
          if (id.includes('node_modules/react-router')) return 'router'
          if (id.includes('node_modules/@xyflow')) return 'flow'
          if (id.includes('node_modules/@monaco-editor') || id.includes('node_modules/monaco-editor')) return 'editor'
          if (id.includes('node_modules/recharts')) return 'charts'
        },
      },
    },
  },
})
