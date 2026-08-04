import { sendJson, parseJsonBody } from '../lib/http.js';
import { campaigns, campaignCharacters, campaignCraftingProjects, campaignInventory } from '../lib/stores.js';

function toSummary(record) {
  return {
    id: record.id,
    character_id: record.character_id,
    item_slug: record.item_slug,
    days_required: record.days_required,
    days_completed: record.days_completed,
    status: record.status,
  };
}

export function registerCraftingRoutes(router) {
  router.post('/v1/campaigns/:campaignId/downtime/crafting', async (req, res, { campaignId }) => {
    const campaign = campaigns.get(campaignId);
    if (!campaign) {
      sendJson(res, 404, { error: 'campaign not found' });
      return;
    }
    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const id = body.data && body.data.id;
    const characterId = body.data && body.data.character_id;
    const itemSlug = body.data && body.data.item_slug;
    const daysRequired = body.data && body.data.days_required;
    const costGp = body.data && body.data.cost_gp;
    if (
      typeof id !== 'string' ||
      id.length === 0 ||
      typeof characterId !== 'string' ||
      characterId.length === 0 ||
      typeof itemSlug !== 'string' ||
      itemSlug.length === 0 ||
      !Number.isInteger(daysRequired) ||
      daysRequired <= 0 ||
      !Number.isInteger(costGp) ||
      costGp < 0
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (!campaignCharacters.has(campaignId, characterId)) {
      sendJson(res, 404, { error: 'character not found' });
      return;
    }
    if (campaignCraftingProjects.has(campaignId, id)) {
      sendJson(res, 409, { error: 'crafting project already exists' });
      return;
    }
    const record = {
      id,
      character_id: characterId,
      item_slug: itemSlug,
      days_required: daysRequired,
      cost_gp: costGp,
      days_completed: 0,
      status: 'active',
    };
    campaignCraftingProjects.set(campaignId, id, record);
    sendJson(res, 201, toSummary(record));
  });

  router.post(
    '/v1/campaigns/:campaignId/downtime/crafting/:projectId/advance',
    async (req, res, { campaignId, projectId }) => {
      const campaign = campaigns.get(campaignId);
      if (!campaign) {
        sendJson(res, 404, { error: 'campaign not found' });
        return;
      }
      const record = campaignCraftingProjects.get(campaignId, projectId);
      if (!record) {
        sendJson(res, 404, { error: 'crafting project not found' });
        return;
      }
      const body = await parseJsonBody(req, res);
      if (!body.ok) return;
      const days = body.data && body.data.days;
      if (!Number.isInteger(days) || days <= 0) {
        sendJson(res, 400, { error: 'invalid request' });
        return;
      }
      if (record.status !== 'active') {
        sendJson(res, 400, { error: 'crafting project is not active' });
        return;
      }
      record.days_completed = Math.min(record.days_completed + days, record.days_required);
      if (record.days_completed >= record.days_required) {
        record.status = 'complete';
        campaignInventory.add(campaignId, { item_slug: record.item_slug, owner: 'party', quantity: 1 });
      }
      campaignCraftingProjects.set(campaignId, projectId, record);
      sendJson(res, 200, {
        id: record.id,
        days_completed: record.days_completed,
        status: record.status,
      });
    }
  );
}
