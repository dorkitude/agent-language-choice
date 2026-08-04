import { sendJson, parseJsonBody } from '../lib/http.js';
import { campaigns, campaignFactions, campaignNpcs } from '../lib/stores.js';

const VALID_STANCES = new Set(['friendly', 'neutral', 'hostile']);

export function registerNpcRoutes(router) {
  router.post('/v1/campaigns/:campaignId/factions', async (req, res, { campaignId }) => {
    const campaign = campaigns.get(campaignId);
    if (!campaign) {
      sendJson(res, 404, { error: 'campaign not found' });
      return;
    }
    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const id = body.data && body.data.id;
    const name = body.data && body.data.name;
    const stance = body.data && body.data.stance;
    if (
      typeof id !== 'string' ||
      id.length === 0 ||
      typeof name !== 'string' ||
      name.length === 0 ||
      typeof stance !== 'string' ||
      !VALID_STANCES.has(stance)
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (campaignFactions.has(campaignId, id)) {
      sendJson(res, 409, { error: 'faction already exists' });
      return;
    }
    const record = { id, name, stance };
    campaignFactions.set(campaignId, id, record);
    sendJson(res, 201, record);
  });

  router.post('/v1/campaigns/:campaignId/npcs', async (req, res, { campaignId }) => {
    const campaign = campaigns.get(campaignId);
    if (!campaign) {
      sendJson(res, 404, { error: 'campaign not found' });
      return;
    }
    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const id = body.data && body.data.id;
    const name = body.data && body.data.name;
    const factionId = body.data && body.data.faction_id;
    const disposition = body.data && body.data.disposition;
    if (
      typeof id !== 'string' ||
      id.length === 0 ||
      typeof name !== 'string' ||
      name.length === 0 ||
      typeof factionId !== 'string' ||
      factionId.length === 0 ||
      typeof disposition !== 'number' ||
      !Number.isInteger(disposition)
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (!campaignFactions.has(campaignId, factionId)) {
      sendJson(res, 400, { error: 'faction not found' });
      return;
    }
    if (campaignNpcs.has(campaignId, id)) {
      sendJson(res, 409, { error: 'npc already exists' });
      return;
    }
    const record = { id, name, faction_id: factionId, disposition };
    campaignNpcs.set(campaignId, id, record);
    sendJson(res, 201, record);
  });

  router.get('/v1/campaigns/:campaignId/relationships', (req, res, { campaignId }) => {
    const campaign = campaigns.get(campaignId);
    if (!campaign) {
      sendJson(res, 404, { error: 'campaign not found' });
      return;
    }
    const factions = campaignFactions.listByCampaign(campaignId);
    const npcs = campaignNpcs.listByCampaign(campaignId);
    const factionStances = new Map(factions.map((f) => [f.id, f.stance]));
    const friendlyNpcs = npcs.filter((npc) => factionStances.get(npc.faction_id) === 'friendly').length;
    sendJson(res, 200, {
      campaign_id: campaignId,
      factions: factions.length,
      npcs: npcs.length,
      friendly_npcs: friendlyNpcs,
    });
  });
}
