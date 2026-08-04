import { sendJson, parseJsonBody } from '../lib/http.js';
import { campaigns, campaignCharacters, campaignInventory, campaignEquipment } from '../lib/stores.js';

// Naive pluralization: "healing-potion" -> "healing_potions_available".
function availabilityKey(itemSlug) {
  return `${itemSlug.replace(/-/g, '_')}s_available`;
}

export function registerInventoryRoutes(router) {
  router.post('/v1/campaigns/:campaignId/inventory', async (req, res, { campaignId }) => {
    const campaign = campaigns.get(campaignId);
    if (!campaign) {
      sendJson(res, 404, { error: 'campaign not found' });
      return;
    }
    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const itemSlug = body.data && body.data.item_slug;
    const quantity = body.data && body.data.quantity;
    const owner = body.data && body.data.owner;
    if (
      typeof itemSlug !== 'string' ||
      itemSlug.length === 0 ||
      !Number.isInteger(quantity) ||
      quantity <= 0 ||
      typeof owner !== 'string' ||
      owner.length === 0
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    campaignInventory.add(campaignId, { item_slug: itemSlug, owner, quantity });
    sendJson(res, 201, { item_slug: itemSlug, quantity, owner });
  });

  router.post(
    '/v1/campaigns/:campaignId/characters/:characterId/equipment',
    async (req, res, { campaignId, characterId }) => {
      const campaign = campaigns.get(campaignId);
      if (!campaign) {
        sendJson(res, 404, { error: 'campaign not found' });
        return;
      }
      if (!campaignCharacters.has(campaignId, characterId)) {
        sendJson(res, 404, { error: 'character not found' });
        return;
      }
      const body = await parseJsonBody(req, res);
      if (!body.ok) return;
      const itemSlug = body.data && body.data.item_slug;
      const quantity = body.data && body.data.quantity;
      if (typeof itemSlug !== 'string' || itemSlug.length === 0 || !Number.isInteger(quantity) || quantity <= 0) {
        sendJson(res, 400, { error: 'invalid request' });
        return;
      }
      campaignEquipment.add(campaignId, { character_id: characterId, item_slug: itemSlug, quantity });
      sendJson(res, 200, { character_id: characterId, item_slug: itemSlug, quantity });
    }
  );

  router.get('/v1/campaigns/:campaignId/inventory/summary', (req, res, { campaignId }) => {
    const campaign = campaigns.get(campaignId);
    if (!campaign) {
      sendJson(res, 404, { error: 'campaign not found' });
      return;
    }
    const inventory = campaignInventory.listByCampaign(campaignId);
    const equipment = campaignEquipment.listByCampaign(campaignId);

    const partyItems = inventory.filter((entry) => entry.owner === 'party').length;
    const assignedItems = equipment.length;

    const partyQuantityBySlug = new Map();
    for (const entry of inventory) {
      if (entry.owner !== 'party') continue;
      partyQuantityBySlug.set(entry.item_slug, (partyQuantityBySlug.get(entry.item_slug) || 0) + entry.quantity);
    }
    const assignedQuantityBySlug = new Map();
    for (const entry of equipment) {
      assignedQuantityBySlug.set(
        entry.item_slug,
        (assignedQuantityBySlug.get(entry.item_slug) || 0) + entry.quantity
      );
    }

    const summary = {
      campaign_id: campaignId,
      party_items: partyItems,
      assigned_items: assignedItems,
    };
    for (const [itemSlug, quantity] of partyQuantityBySlug) {
      const assigned = assignedQuantityBySlug.get(itemSlug) || 0;
      summary[availabilityKey(itemSlug)] = quantity - assigned;
    }
    sendJson(res, 200, summary);
  });
}
