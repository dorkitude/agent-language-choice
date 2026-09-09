import { NextResponse } from "next/server";
import { campaignAnalytics, getCampaign } from "../../../../../lib/campaigns";

export const runtime = "nodejs";

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const campaignId = (await params).id;
  if (!getCampaign(campaignId)) return NextResponse.json({ error: "Unknown campaign" }, { status: 404 });
  const { signals: _signals, ...summary } = campaignAnalytics(campaignId);
  return NextResponse.json({ campaign_id: campaignId, ...summary });
}
