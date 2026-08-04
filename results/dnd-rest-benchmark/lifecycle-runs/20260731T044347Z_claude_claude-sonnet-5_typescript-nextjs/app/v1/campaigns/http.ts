import { Campaign, getCampaign } from "./store.js";

// Every campaign-scoped route needs the same "does this campaign exist"
// check before doing anything else. Returns the campaign on success, or the
// 404 Response every caller returned by hand before this was extracted.
export function requireCampaign(campaignId: string): Campaign | Response {
  const campaign = getCampaign(campaignId);
  if (campaign) return campaign;
  return Response.json({ error: `campaign ${campaignId} not found` }, { status: 404 });
}
