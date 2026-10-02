import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        // Heavy libs in their own chunks, cached once and loaded with the
        // pages that use them. React gets its own chunk: grouped with a lib
        // that depends on it, every page would preload that lib.
        manualChunks(id) {
          const pkg = id.match(/\/node_modules\/((?:@[^/]+\/)?[^/]+)\//)?.[1]
          if (!pkg) return undefined
          if (['react', 'react-dom', 'scheduler'].includes(pkg)) return 'react'
          if (['leaflet', 'react-leaflet', '@react-leaflet'].includes(pkg)) return 'leaflet'
          if (pkg === 'recharts') return 'recharts'
          if (pkg === 'date-fns') return 'date-fns'
          // The app's other direct deps: shared by every page, and kept out of
          // the chunk of a heavy lib that also uses them (clsx under Recharts)
          if (['clsx', 'axios', '@tanstack/react-query', 'react-router', 'react-router-dom', '@mapbox/polyline'].includes(pkg)) return 'vendor'
          return undefined
        },
      },
    },
  },
})
