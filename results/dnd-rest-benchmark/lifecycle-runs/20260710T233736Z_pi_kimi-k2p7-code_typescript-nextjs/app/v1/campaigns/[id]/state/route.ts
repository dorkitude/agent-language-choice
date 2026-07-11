import { getCampaignState } from "../../../../lib/campaign.js";

function campaignIdFromUrl(url: string): string {
  const segments = new URL(url).pathname.split("/").filter(Boolean);
  const campaignsIndex = segments.indexOf("campaigns");
  return segments[campaignsIndex + 1];
}

export async function GET(request: Request) {
  try {
    const id = campaignIdFromUrl(request.url);
    const state = getCampaignState(id);
    return Response.json(state);
  } catch (error) {
    const message = error instanceof Error ? error.message : "invalid request";
    if (message === "campaign not found") {
      return Response.json({ error: message }, { status: 404 });
    }
    return Response.json({ error: message }, { status: 400 });
  }
}
