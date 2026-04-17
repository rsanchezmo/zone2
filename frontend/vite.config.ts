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
        // Split heavy libs so they're cached once and loaded on-demand
        // rather than being inlined into the main bundle. Recharts and
        // Leaflet together are ~400KB; without this they bloat initial
        // page load even for users who never open the map/chart pages.
        manualChunks: {
          recharts: ['recharts'],
          leaflet: ['leaflet', 'react-leaflet'],
          'date-fns': ['date-fns'],
        },
      },
    },
  },
})
