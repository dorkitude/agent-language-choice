import { NextResponse } from "next/server";
import { assignEquipment, getCampaign, hasCampaignCharacter } from "../../../../../../lib/campaigns";
import { badRequest, isInteger, isRecord, jsonBody } from "../../../../../../lib/http";

export const runtime = "nodejs";

export async function POST(request: Request, { params }: { params: Promise<{ id: string; character_id: string }> }) {
  const body = await jsonBody(request);
  if (!isRecord(body) || typeof body.item_slug !== "string" || body.item_slug.length === 0 ||
    !isInteger(body.quantity) || body.quantity <= 0) {
    return badRequest();
  }
  const { id: campaignId, character_id: characterId } = await params;
  if (!getCampaign(campaignId)) return NextResponse.json({ error: "Unknown campaign" }, { status: 404 });
  if (!hasCampaignCharacter(campaignId, characterId)) return NextResponse.json({ error: "Unknown character" }, { status: 404 });
  if (!assignEquipment(campaignId, characterId, body.item_slug, body.quantity)) {
    return badRequest("Insufficient party inventory");
  }
  return NextResponse.json({ character_id: characterId, item_slug: body.item_slug, quantity: body.quantity });
}
