import { NextResponse } from "next/server";
import { campaignResourceCounts, getCampaign } from "../../../../lib/campaigns";

export const runtime = "nodejs";

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const campaignId = (await params).id;
  if (!getCampaign(campaignId)) return NextResponse.json({ error: "Unknown campaign" }, { status: 404 });
  const counts = campaignResourceCounts(campaignId);
  return NextResponse.json({
    campaign_id: campaignId,
    events: counts.events,
    quests: counts.quests,
    npcs: counts.npcs,
    sessions: counts.sessions,
  });
}
