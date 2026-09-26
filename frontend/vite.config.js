import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Bind IPv4 explicitly. Left to itself, Vite may listen only on [::1], and
    // then http://127.0.0.1:5173 refuses the connection while
    // http://localhost:5173 works - which looks exactly like "the site is
    // down". Pinning the address makes both spellings resolve.
    host: '127.0.0.1',
    // The Flask API runs separately in development; proxying keeps the browser
    // on one origin so no CORS configuration is needed.
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.js'],
    include: ['tests/**/*.test.{js,jsx}'],
  },
});
