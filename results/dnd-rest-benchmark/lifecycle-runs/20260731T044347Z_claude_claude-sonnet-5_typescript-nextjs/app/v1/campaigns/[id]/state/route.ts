import { countCampaignEvents, listCampaignCharacters } from "../../store.js";
import { requireCampaign } from "../../http.js";

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const campaign = requireCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  return Response.json({
    id: campaign.id,
    name: campaign.name,
    dm: campaign.dm,
    characters: listCampaignCharacters(campaignId),
    log_count: countCampaignEvents(campaignId),
  });
}
