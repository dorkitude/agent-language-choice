import { NextResponse } from "next/server";
import { campaignResourceCounts, getCampaign } from "../../../../lib/campaigns";
import { SCHEMA_VERSION } from "../../../../lib/storage";

export const runtime = "nodejs";

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const campaignId = (await params).id;
  const campaign = getCampaign(campaignId);
  if (!campaign) return NextResponse.json({ error: "Unknown campaign" }, { status: 404 });
  const counts = campaignResourceCounts(campaignId);
  return NextResponse.json({
    campaign_id: campaignId,
    name: campaign.name,
    characters: counts.characters,
    quests: counts.quests,
    npcs: counts.npcs,
    inventory_items: counts.inventory_items,
    sessions: counts.sessions,
    schema_version: SCHEMA_VERSION,
  });
}
