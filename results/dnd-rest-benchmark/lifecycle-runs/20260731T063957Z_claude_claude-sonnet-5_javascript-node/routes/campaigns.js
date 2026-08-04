import { sendJson, parseJsonBody } from '../lib/http.js';
import { campaigns, campaignCharacters, campaignEvents } from '../lib/stores.js';

export function registerCampaignRoutes(router) {
  router.post('/v1/campaigns', async (req, res) => {
    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const id = body.data && body.data.id;
    const name = body.data && body.data.name;
    const dm = body.data && body.data.dm;
    if (
      typeof id !== 'string' ||
      id.length === 0 ||
      typeof name !== 'string' ||
      name.length === 0 ||
      typeof dm !== 'string' ||
      dm.length === 0
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (campaigns.has(id)) {
      sendJson(res, 409, { error: 'campaign already exists' });
      return;
    }
    const record = { id, name, dm };
    campaigns.set(id, record);
    sendJson(res, 201, record);
  });

  router.post('/v1/campaigns/:campaignId/characters', async (req, res, { campaignId }) => {
    const campaign = campaigns.get(campaignId);
    if (!campaign) {
      sendJson(res, 404, { error: 'campaign not found' });
      return;
    }
    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const id = body.data && body.data.id;
    const name = body.data && body.data.name;
    const level = body.data && body.data.level;
    const charClass = body.data && body.data.class;
    if (
      typeof id !== 'string' ||
      id.length === 0 ||
      typeof name !== 'string' ||
      name.length === 0 ||
      !Number.isInteger(level) ||
      typeof charClass !== 'string' ||
      charClass.length === 0
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (campaignCharacters.has(campaignId, id)) {
      sendJson(res, 409, { error: 'character already exists' });
      return;
    }
    const record = { id, name, level, class: charClass };
    campaignCharacters.set(campaignId, id, record);
    sendJson(res, 201, record);
  });

  router.post('/v1/campaigns/:campaignId/events', async (req, res, { campaignId }) => {
    const campaign = campaigns.get(campaignId);
    if (!campaign) {
      sendJson(res, 404, { error: 'campaign not found' });
      return;
    }
    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const id = body.data && body.data.id;
    const kind = body.data && body.data.kind;
    const summary = body.data && body.data.summary;
    if (
      typeof id !== 'string' ||
      id.length === 0 ||
      typeof kind !== 'string' ||
      kind.length === 0 ||
      typeof summary !== 'string' ||
      summary.length === 0
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (campaignEvents.has(campaignId, id)) {
      sendJson(res, 409, { error: 'event already exists' });
      return;
    }
    campaignEvents.set(campaignId, id, { id, kind, summary });
    sendJson(res, 201, { id, kind });
  });

  router.get('/v1/campaigns/:campaignId/state', (req, res, { campaignId }) => {
    const campaign = campaigns.get(campaignId);
    if (!campaign) {
      sendJson(res, 404, { error: 'campaign not found' });
      return;
    }
    const characters = campaignCharacters.listByCampaign(campaignId);
    const logCount = campaignEvents.countByCampaign(campaignId);
    sendJson(res, 200, {
      id: campaign.id,
      name: campaign.name,
      dm: campaign.dm,
      characters,
      log_count: logCount,
    });
  });
}
