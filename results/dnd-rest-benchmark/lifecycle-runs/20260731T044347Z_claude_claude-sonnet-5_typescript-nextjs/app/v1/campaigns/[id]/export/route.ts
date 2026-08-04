import {
  listCampaignCharacters,
  listCampaignInventory,
  listCampaignNpcs,
  listCampaignQuests,
  listCampaignSessions,
} from "../../store.js";
import { requireCampaign } from "../../http.js";

const SCHEMA_VERSION = 1;

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const campaign = requireCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  return Response.json({
    campaign_id: campaign.id,
    name: campaign.name,
    characters: listCampaignCharacters(campaignId).length,
    quests: listCampaignQuests(campaignId).length,
    npcs: listCampaignNpcs(campaignId).length,
    inventory_items: listCampaignInventory(campaignId).length,
    sessions: listCampaignSessions(campaignId).length,
    schema_version: SCHEMA_VERSION,
  });
}
