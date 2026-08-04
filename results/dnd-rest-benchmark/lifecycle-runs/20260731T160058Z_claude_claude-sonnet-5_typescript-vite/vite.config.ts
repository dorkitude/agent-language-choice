import { defineConfig } from 'vite';
import { dndApiPlugin } from './src/api-plugin.ts';

export default defineConfig({
  plugins: [dndApiPlugin()],
});
