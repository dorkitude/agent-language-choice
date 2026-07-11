import { defineConfig, type Plugin } from 'vite';
import { ddApiMiddleware } from './src/api.ts';

function ddApiPlugin(): Plugin {
  return {
    name: 'dnd-rest-api',
    configureServer(server) {
      server.middlewares.use(ddApiMiddleware());
    },
  };
}

export default defineConfig({
  plugins: [ddApiPlugin()],
});
