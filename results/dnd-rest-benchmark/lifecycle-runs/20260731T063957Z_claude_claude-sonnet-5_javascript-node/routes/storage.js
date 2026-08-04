import { sendJson } from '../lib/http.js';
import { SCHEMA_VERSION, dbState, resetSchema } from '../lib/db.js';

export function registerStorageRoutes(router) {
  router.get('/health', (req, res) => {
    sendJson(res, 200, { ok: true });
  });

  router.get('/v1/storage/status', (req, res) => {
    sendJson(res, 200, {
      driver: 'sqlite',
      schema_version: SCHEMA_VERSION,
      initialized: dbState.initialized,
    });
  });

  router.post('/v1/storage/reset', (req, res) => {
    resetSchema();
    sendJson(res, 200, { ok: true, schema_version: SCHEMA_VERSION });
  });
}
