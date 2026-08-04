import { NextResponse } from "next/server";
import { addCharacter, getCampaign } from "../../../../lib/campaigns";
import { badRequest, isInteger, isRecord, jsonBody } from "../../../../lib/http";

export const runtime = "nodejs";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const body = await jsonBody(request);
  if (!isRecord(body) || typeof body.id !== "string" || body.id.length === 0 || typeof body.name !== "string" || body.name.length === 0 || !isInteger(body.level) || body.level < 1 || typeof body.class !== "string" || body.class.length === 0) {
    return badRequest();
  }
  const campaignId = (await params).id;
  if (!getCampaign(campaignId)) return NextResponse.json({ error: "Unknown campaign" }, { status: 404 });
  if (!addCharacter(campaignId, { id: body.id, name: body.name, level: body.level, class: body.class })) {
    return NextResponse.json({ error: "Character already exists" }, { status: 409 });
  }
  return NextResponse.json({ id: body.id, name: body.name, level: body.level, class: body.class }, { status: 201 });
}
