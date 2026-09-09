import { NextResponse } from "next/server";
import { createFaction, getCampaign } from "../../../../lib/campaigns";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../lib/http";

export const runtime = "nodejs";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.id) || !isNonEmptyString(body.name) || !isNonEmptyString(body.stance)) {
    return badRequest();
  }
  const campaignId = (await params).id;
  if (!getCampaign(campaignId)) return NextResponse.json({ error: "Unknown campaign" }, { status: 404 });
  if (!createFaction(campaignId, { id: body.id, name: body.name, stance: body.stance })) {
    return NextResponse.json({ error: "Faction already exists" }, { status: 409 });
  }
  return NextResponse.json({ id: body.id, name: body.name, stance: body.stance }, { status: 201 });
}
