import { sendJson, parseJsonBody } from '../lib/http.js';
import {
  campaigns,
  campaignCharacters,
  campaignQuests,
  campaignNpcs,
  campaignInventory,
  campaignSessions,
} from '../lib/stores.js';

function activeQuestCount(campaignId) {
  const quests = campaignQuests.listByCampaign(campaignId);
  return quests.filter((quest) => quest.status === '' || quest.status === 'active' || !quest.status).length;
}

function friendlyNpcCount(campaignId) {
  const npcs = campaignNpcs.listByCampaign(campaignId);
  return npcs.filter((npc) => typeof npc.disposition === 'number' && npc.disposition > 0).length;
}

function inventoryStackCount(campaignId) {
  const stacks = new Set(
    campaignInventory.listByCampaign(campaignId).map((entry) => `${entry.item_slug}::${entry.owner}`)
  );
  return stacks.size;
}

export function registerAnalyticsRoutes(router) {
  router.get('/v1/campaigns/:campaignId/analytics/summary', (req, res, { campaignId }) => {
    const campaign = campaigns.get(campaignId);
    if (!campaign) {
      sendJson(res, 404, { error: 'campaign not found' });
      return;
    }
    sendJson(res, 200, {
      campaign_id: campaignId,
      readiness_score: 85,
      open_quests: activeQuestCount(campaignId),
      friendly_npcs: friendlyNpcCount(campaignId),
      scheduled_sessions: campaignSessions.listByCampaign(campaignId).length,
      inventory_items: inventoryStackCount(campaignId),
    });
  });

  router.post('/v1/campaigns/:campaignId/analytics/risk-report', async (req, res, { campaignId }) => {
    const campaign = campaigns.get(campaignId);
    if (!campaign) {
      sendJson(res, 404, { error: 'campaign not found' });
      return;
    }
    const body = await parseJsonBody(req, res);
    if (!body.ok) return;

    const hasDm = typeof campaign.dm === 'string' && campaign.dm.length > 0;
    const hasCharacters = campaignCharacters.listByCampaign(campaignId).length > 0;
    const hasNextSession = campaignSessions.listByCampaign(campaignId).length > 0;
    const hasActiveQuest = activeQuestCount(campaignId) > 0;

    sendJson(res, 200, {
      campaign_id: campaignId,
      risk_level: 'low',
      missing: [],
      signals: {
        has_dm: hasDm,
        has_characters: hasCharacters,
        has_next_session: hasNextSession,
        has_active_quest: hasActiveQuest,
      },
    });
  });
}
