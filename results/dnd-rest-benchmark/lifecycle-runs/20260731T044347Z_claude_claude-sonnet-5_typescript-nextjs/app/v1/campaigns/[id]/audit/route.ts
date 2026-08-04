import {
  countCampaignEvents,
  listCampaignNpcs,
  listCampaignQuests,
  listCampaignSessions,
} from "../../store.js";
import { requireCampaign } from "../../http.js";

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const campaign = requireCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  return Response.json({
    campaign_id: campaign.id,
    events: countCampaignEvents(campaignId),
    quests: listCampaignQuests(campaignId).length,
    npcs: listCampaignNpcs(campaignId).length,
    sessions: listCampaignSessions(campaignId).length,
  });
}
