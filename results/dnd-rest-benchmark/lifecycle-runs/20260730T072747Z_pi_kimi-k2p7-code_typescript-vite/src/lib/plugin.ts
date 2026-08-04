// Vite plugin that installs the D&D REST API as dev-server middleware. The
// database schema is reset once when the server starts so each run begins with
// a clean slate, and the middleware catches all errors and converts them to JSON
// responses.

import type { Plugin } from 'vite';
import type { IncomingMessage, ServerResponse } from 'node:http';
import { resetSchema } from './db.js';
import { sendJson } from './http.js';
import { route } from './router.js';

const dndApiPlugin: Plugin = {
  name: 'dnd-api',
  configureServer(server) {
    resetSchema();
    server.middlewares.use(async (req: IncomingMessage, res: ServerResponse, next: (err?: unknown) => void) => {
      try {
        await route(req, res, next);
      } catch (err) {
        if (!res.headersSent) {
          sendJson(res, 500, { error: 'internal server error' });
        } else {
          next(err);
        }
      }
    });
  },
};

export default dndApiPlugin;
