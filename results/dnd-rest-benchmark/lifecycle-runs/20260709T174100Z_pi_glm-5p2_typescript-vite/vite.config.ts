import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import { apiMiddleware } from './src/api';

// Vite plugin that mounts the D&D REST engine as dev-server middleware.
// The API runs inside the Vite dev server (no separate Node-only server).
const dndRestPlugin: Plugin = {
  name: 'dnd-rest-api',
  configureServer(server) {
    // Hook runs before Vite's internal middlewares, so /health and /v1/*
    // are handled before static/asset serving.
    server.middlewares.use(apiMiddleware);
  },
  configurePreviewServer(server) {
    server.middlewares.use(apiMiddleware);
  },
};

export default defineConfig({
  plugins: [dndRestPlugin, react()],
  server: {
    host: '127.0.0.1',
  },
});
