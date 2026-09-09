import { NextResponse } from "next/server";
import { createNpc, getCampaign, getFaction } from "../../../../lib/campaigns";
import { badRequest, isInteger, isNonEmptyString, isRecord, jsonBody } from "../../../../lib/http";

export const runtime = "nodejs";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.id) || !isNonEmptyString(body.name) ||
    !isNonEmptyString(body.faction_id) || !isInteger(body.disposition)) {
    return badRequest();
  }
  const campaignId = (await params).id;
  if (!getCampaign(campaignId)) return NextResponse.json({ error: "Unknown campaign" }, { status: 404 });
  if (!getFaction(campaignId, body.faction_id)) return NextResponse.json({ error: "Unknown faction" }, { status: 404 });
  if (!createNpc(campaignId, {
    id: body.id,
    name: body.name,
    faction_id: body.faction_id,
    disposition: body.disposition,
  })) {
    return NextResponse.json({ error: "NPC already exists" }, { status: 409 });
  }
  return NextResponse.json({
    id: body.id,
    name: body.name,
    faction_id: body.faction_id,
    disposition: body.disposition,
  }, { status: 201 });
}
