import { createServer } from 'node:http';
import { createRouter } from './lib/router.js';
import { sendJson } from './lib/http.js';
import { registerStorageRoutes } from './routes/storage.js';
import { registerDiceRoutes } from './routes/dice.js';
import { registerEncounterRoutes } from './routes/encounters.js';
import { registerCharacterRoutes } from './routes/characters.js';
import { registerCombatRoutes } from './routes/combat.js';
import { registerAuthRoutes } from './routes/auth.js';
import { registerCompendiumRoutes } from './routes/compendium.js';
import { registerCampaignRoutes } from './routes/campaigns.js';
import { registerPhbRoutes } from './routes/phb.js';
import { registerDmRoutes } from './routes/dm.js';
import { registerQuestRoutes } from './routes/quests.js';
import { registerNpcRoutes } from './routes/npcs.js';
import { registerInventoryRoutes } from './routes/inventory.js';
import { registerCraftingRoutes } from './routes/crafting.js';
import { registerSessionRoutes } from './routes/sessions.js';
import { registerAuditRoutes } from './routes/audit.js';
import { registerAnalyticsRoutes } from './routes/analytics.js';
import { registerPlayRoutes } from './routes/play.js';
import { isMaintenance } from './lib/service-mode.js';

const PORT = process.env.PORT;

const router = createRouter();
router.get('/healthz', async (req, res) => {
  sendJson(res, 200, { status: 'ok' });
});
router.get('/readyz', async (req, res) => {
  if (isMaintenance()) {
    sendJson(res, 503, { status: 'maintenance', schema_version: 2 });
  } else {
    sendJson(res, 200, { status: 'ready', schema_version: 2 });
  }
});
router.get('/v1/schema', async (req, res) => {
  sendJson(res, 200, {
    version: '2026-07-29',
    endpoints: [
      { method: 'GET', path: '/v1/play/campaigns/{id}/rng-ledger', auth: 'member' },
      { method: 'GET', path: '/v1/schema', auth: 'public' },
      { method: 'POST', path: '/v1/play/campaigns', auth: 'dm' },
      { method: 'POST', path: '/v1/play/campaigns/{id}/fixture-seeds', auth: 'dm' },
      { method: 'POST', path: '/v1/play/campaigns/{id}/members', auth: 'member' },
      { method: 'POST', path: '/v1/play/campaigns/{id}/moderation/reports', auth: 'member' },
      { method: 'POST', path: '/v1/play/campaigns/{id}/rng-rolls', auth: 'member' },
      { method: 'PUT', path: '/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution', auth: 'dm' },
      { method: 'PUT', path: '/v1/play/campaigns/{id}/rng-seed', auth: 'dm' },
      { method: 'PUT', path: '/v1/play/campaigns/{id}/safety-boundaries', auth: 'dm' },
    ],
  });
});
registerStorageRoutes(router);
registerDiceRoutes(router);
registerEncounterRoutes(router);
registerCharacterRoutes(router);
registerCombatRoutes(router);
registerAuthRoutes(router);
registerCompendiumRoutes(router);
registerCampaignRoutes(router);
registerPhbRoutes(router);
registerDmRoutes(router);
registerQuestRoutes(router);
registerNpcRoutes(router);
registerInventoryRoutes(router);
registerCraftingRoutes(router);
registerSessionRoutes(router);
registerAuditRoutes(router);
registerAnalyticsRoutes(router);
registerPlayRoutes(router);

const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url, 'http://localhost');
    const matched = await router.dispatch(req, res, url.pathname);
    if (!matched) {
      sendJson(res, 404, { error: 'not found' });
    }
  } catch (err) {
    sendJson(res, 500, { error: 'internal error' });
  }
});

server.listen(PORT, '127.0.0.1');
