import type { Connect, Plugin, ViteDevServer } from 'vite';
import { defineConfig } from 'vite';
import type { IncomingMessage, ServerResponse } from 'node:http';
import { dispatch } from './src/api.ts';

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  const payload = JSON.stringify(body);
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json');
  res.end(payload);
}

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on('data', (chunk) => chunks.push(chunk as Buffer));
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}

function dndApi(): Plugin {
  return {
    name: 'dnd-rest-api',
    configureServer(server: ViteDevServer) {
      const mw: Connect.NextHandleFunction = async (req, res, next) => {
        const method = (req.method || 'GET').toUpperCase();
        const url = (req.url || '').split('?')[0];

        if (method === 'GET' && url === '/health') {
          return sendJson(res, 200, { ok: true });
        }

        // Only API routes are namespaced under /v1; let everything else fall
        // through to Vite. Probe with an empty body first so unknown routes
        // fall through before we consume the request body.
        if (!url.startsWith('/v1/')) return next();

        let parsed: unknown;
        try {
          const raw = await readBody(req);
          parsed = raw.length ? JSON.parse(raw) : {};
        } catch {
          return sendJson(res, 400, { error: 'invalid JSON body' });
        }

        try {
          const result = dispatch(method, url, parsed);
          if (!result) return next();
          return sendJson(res, result.status, result.body);
        } catch {
          return sendJson(res, 500, { error: 'internal error' });
        }
      };

      // Handle API routes before Vite's own middleware (SPA/index fallback).
      server.middlewares.use(mw);
    },
  };
}

export default defineConfig({
  plugins: [dndApi()],
});
