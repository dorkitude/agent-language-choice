import { defineConfig } from 'vite';
import { dndApiPlugin } from './src/dndApiPlugin.js';

export default defineConfig({
  plugins: [dndApiPlugin()],
});
