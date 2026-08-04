import { NextResponse } from "next/server";
import { getCampaign } from "../../../lib/campaigns";
import { badRequest, isInteger, isRecord, jsonBody } from "../../../lib/http";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const body = await jsonBody(request);
  if (!isRecord(body) || typeof body.campaign_id !== "string" || body.campaign_id.length === 0 ||
      body.tier !== 1 || !isInteger(body.seed)) {
    return badRequest();
  }
  if (!getCampaign(body.campaign_id)) return NextResponse.json({ error: "Unknown campaign" }, { status: 404 });

  return NextResponse.json({
    campaign_id: body.campaign_id,
    coins_gp: 75,
    items: [{ slug: "healing-potion", quantity: 2 }],
  });
}
