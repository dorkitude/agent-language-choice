import { NextResponse } from "next/server";
import { getCampaign, nextCampaignSession } from "../../../../../lib/campaigns";

export const runtime = "nodejs";

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const campaignId = (await params).id;
  if (!getCampaign(campaignId)) return NextResponse.json({ error: "Unknown campaign" }, { status: 404 });
  const session = nextCampaignSession(campaignId);
  if (!session) return NextResponse.json({ error: "No scheduled sessions" }, { status: 404 });
  return NextResponse.json(session);
}
