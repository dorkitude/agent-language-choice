import {
  listCampaignInventory,
  listCampaignNpcs,
  listCampaignQuests,
  listCampaignSessions,
} from "../../../store.js";
import { requireCampaign } from "../../../http.js";

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const campaign = requireCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const quests = listCampaignQuests(campaignId);
  const npcs = listCampaignNpcs(campaignId);
  const sessions = listCampaignSessions(campaignId);
  const inventory = listCampaignInventory(campaignId);

  const openQuests = quests.filter((quest) => quest.status === "active").length;
  const friendlyNpcs = npcs.filter((npc) => npc.disposition > 0).length;
  const scheduledSessions = sessions.length;
  const inventoryItems = inventory.length;

  const hasDm = typeof campaign?.dm === "string" && campaign.dm.length > 0;

  let readinessScore = 0;
  if (hasDm) readinessScore += 20;
  if (openQuests > 0) readinessScore += 20;
  if (scheduledSessions > 0) readinessScore += 20;
  if (friendlyNpcs > 0) readinessScore += 15;
  if (inventoryItems > 0) readinessScore += 10;

  const summary = {
    campaign_id: campaignId,
    readiness_score: readinessScore,
    open_quests: openQuests,
    friendly_npcs: friendlyNpcs,
    scheduled_sessions: scheduledSessions,
    inventory_items: inventoryItems,
  };

  return Response.json(summary);
}
