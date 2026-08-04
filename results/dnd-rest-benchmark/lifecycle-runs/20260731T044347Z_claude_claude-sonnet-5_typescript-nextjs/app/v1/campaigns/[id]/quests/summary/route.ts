import { listCampaignQuests } from "../../../store.js";
import { requireCampaign } from "../../../http.js";

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const campaign = requireCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const quests = listCampaignQuests(campaignId);

  const summary = {
    campaign_id: campaignId,
    active: quests.filter((q) => q.status === "active").length,
    completed: quests.filter((q) => q.status === "completed").length,
    blocked: quests.filter((q) => q.status === "blocked").length,
  };

  return Response.json(summary);
}
