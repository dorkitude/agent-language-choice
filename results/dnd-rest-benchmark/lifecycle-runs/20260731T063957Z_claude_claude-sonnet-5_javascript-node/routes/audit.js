import { sendJson } from '../lib/http.js';
import {
  campaigns,
  campaignCharacters,
  campaignEvents,
  campaignQuests,
  campaignNpcs,
  campaignInventory,
  campaignSessions,
} from '../lib/stores.js';

function countInventoryStacks(campaignId) {
  const stacks = new Set(
    campaignInventory.listByCampaign(campaignId).map((entry) => `${entry.item_slug}::${entry.owner}`)
  );
  return stacks.size;
}

export function registerAuditRoutes(router) {
  router.get('/v1/campaigns/:campaignId/audit', (req, res, { campaignId }) => {
    const campaign = campaigns.get(campaignId);
    if (!campaign) {
      sendJson(res, 404, { error: 'campaign not found' });
      return;
    }
    sendJson(res, 200, {
      campaign_id: campaignId,
      events: campaignEvents.countByCampaign(campaignId),
      quests: campaignQuests.listByCampaign(campaignId).length,
      npcs: campaignNpcs.listByCampaign(campaignId).length,
      sessions: campaignSessions.listByCampaign(campaignId).length,
    });
  });

  router.get('/v1/campaigns/:campaignId/export', (req, res, { campaignId }) => {
    const campaign = campaigns.get(campaignId);
    if (!campaign) {
      sendJson(res, 404, { error: 'campaign not found' });
      return;
    }
    sendJson(res, 200, {
      campaign_id: campaignId,
      name: campaign.name,
      characters: campaignCharacters.listByCampaign(campaignId).length,
      quests: campaignQuests.listByCampaign(campaignId).length,
      npcs: campaignNpcs.listByCampaign(campaignId).length,
      inventory_items: countInventoryStacks(campaignId),
      sessions: campaignSessions.listByCampaign(campaignId).length,
      schema_version: 1,
    });
  });
}
