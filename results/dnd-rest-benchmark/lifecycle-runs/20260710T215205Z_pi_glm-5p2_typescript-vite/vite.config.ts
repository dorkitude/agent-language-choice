import { defineConfig } from 'vite'
import { dndApiPlugin } from './src/dndPlugin.ts'

export default defineConfig({
  plugins: [dndApiPlugin()],
  server: {
    host: '127.0.0.1',
    port: Number(process.env.PORT) || 3000,
    open: false,
  },
})
