import { NextResponse } from "next/server";
import { addPartyInventory, getCampaign } from "../../../../lib/campaigns";
import { badRequest, isInteger, isRecord, jsonBody } from "../../../../lib/http";

export const runtime = "nodejs";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const body = await jsonBody(request);
  if (!isRecord(body) || typeof body.item_slug !== "string" || body.item_slug.length === 0 ||
    !isInteger(body.quantity) || body.quantity <= 0 || body.owner !== "party") {
    return badRequest();
  }
  const campaignId = (await params).id;
  if (!getCampaign(campaignId)) return NextResponse.json({ error: "Unknown campaign" }, { status: 404 });
  addPartyInventory(campaignId, body.item_slug, body.quantity);
  return NextResponse.json({ item_slug: body.item_slug, quantity: body.quantity, owner: "party" }, { status: 201 });
}
