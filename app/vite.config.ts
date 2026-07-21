import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';

// Served from https://linweihan7.github.io/college-toolkit/ , so assets need this base.
export default defineConfig({
  base: '/college-toolkit/',
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icons/icon-192.png', 'icons/icon-512.png'],
      manifest: {
        name: "Weihan's AI Tools — College Toolkit",
        short_name: 'AI Tools',
        description: 'Canvas sync, expenses, to-do, schedule, GPA, timer, habits, and more.',
        id: '/college-toolkit/',
        start_url: '/college-toolkit/',
        scope: '/college-toolkit/',
        display: 'standalone',
        background_color: '#eef1f7',
        theme_color: '#5546e0',
        icons: [
          { src: 'icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: 'icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: 'icons/icon-192-maskable.png', sizes: '192x192', type: 'image/png', purpose: 'maskable' },
          { src: 'icons/icon-512-maskable.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        // Don't cache cross-origin API calls (Canvas, weather, Supabase, Anthropic).
        navigateFallbackDenylist: [/^\/college-toolkit\/api/],
        runtimeCaching: [],
      },
    }),
  ],
  test: {
    environment: 'node',
    globals: true,
    include: ['src/**/*.test.ts'],
  },
});
