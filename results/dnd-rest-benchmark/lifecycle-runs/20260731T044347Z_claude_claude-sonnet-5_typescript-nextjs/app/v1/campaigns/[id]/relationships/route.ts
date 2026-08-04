import { getCampaignFaction, listCampaignFactions, listCampaignNpcs } from "../../store.js";
import { requireCampaign } from "../../http.js";

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const campaign = requireCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const factions = listCampaignFactions(campaignId);
  const npcs = listCampaignNpcs(campaignId);

  const friendlyNpcs = npcs.filter((npc) => {
    if (npc.faction_id === null) return false;
    const faction = getCampaignFaction(campaignId, npc.faction_id);
    return faction?.stance === "friendly";
  }).length;

  return Response.json({
    campaign_id: campaignId,
    factions: factions.length,
    npcs: npcs.length,
    friendly_npcs: friendlyNpcs,
  });
}
