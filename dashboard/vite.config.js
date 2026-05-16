import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      filename: 'sw.js',
      manifestFilename: 'site.webmanifest',
      includeAssets: ['favicon.svg', 'robots.txt', 'sitemap.xml'],
      manifest: {
        id: '/panel/',
        name: "Cat's Bot",
        short_name: "Cat's Bot",
        description: 'Bot de Discord con panel propio en español. Modera, da la bienvenida, premia con niveles y abre tickets sin escribir un comando.',
        lang: 'es',
        dir: 'ltr',
        start_url: '/panel/',
        scope: '/panel/',
        display: 'standalone',
        display_override: ['window-controls-overlay', 'standalone', 'minimal-ui'],
        orientation: 'any',
        background_color: '#0b0a10',
        theme_color: '#0b0a10',
        categories: ['productivity', 'social', 'utilities'],
        icons: [
          { src: '/panel/icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: '/panel/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: '/panel/icons/icon-192-maskable.png', sizes: '192x192', type: 'image/png', purpose: 'maskable' },
          { src: '/panel/icons/icon-512-maskable.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
          { src: '/panel/favicon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,woff2,png,ico}'],
        navigateFallback: '/panel/index.html',
        navigateFallbackDenylist: [/^\/api\//, /^\/auth\//],
        runtimeCaching: [
          {
            urlPattern: /\/api\/.*/i,
            handler: 'NetworkOnly',
            options: { cacheName: 'api-no-cache' },
          },
          {
            urlPattern: /\.(?:woff2?|ttf)$/i,
            handler: 'CacheFirst',
            options: {
              cacheName: 'fonts',
              expiration: { maxEntries: 30, maxAgeSeconds: 60 * 60 * 24 * 365 },
            },
          },
          {
            urlPattern: /\.(?:png|svg|webp|avif|jpg|jpeg|gif|ico)$/i,
            handler: 'CacheFirst',
            options: {
              cacheName: 'images',
              expiration: { maxEntries: 60, maxAgeSeconds: 60 * 60 * 24 * 90 },
            },
          },
          {
            urlPattern: /^https:\/\/cdn\.discordapp\.com\//i,
            handler: 'StaleWhileRevalidate',
            options: {
              cacheName: 'discord-cdn',
              expiration: { maxEntries: 80, maxAgeSeconds: 60 * 60 * 24 * 30 },
            },
          },
        ],
        cleanupOutdatedCaches: true,
        clientsClaim: true,
        skipWaiting: true,
      },
      devOptions: { enabled: false },
    }),
  ],
  base: '/panel/',
  build: {
    outDir: 'dist',
    cssCodeSplit: true,
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('react-router')) return 'router'
            if (id.includes('react-dom')) return 'react'
            if (id.includes('react/') || id.endsWith('react')) return 'react'
            if (id.includes('@fortawesome')) return 'icons'
            if (id.includes('@fontsource')) return 'fonts'
            return 'vendor'
          }
        },
      },
    },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },
})
