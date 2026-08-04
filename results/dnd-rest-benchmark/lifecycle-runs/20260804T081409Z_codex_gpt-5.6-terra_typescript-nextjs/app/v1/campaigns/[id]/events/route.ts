import { NextResponse } from "next/server";
import { addEvent, getCampaign } from "../../../../lib/campaigns";
import { badRequest, isRecord, jsonBody } from "../../../../lib/http";

export const runtime = "nodejs";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const body = await jsonBody(request);
  if (!isRecord(body) || typeof body.id !== "string" || body.id.length === 0 || typeof body.kind !== "string" || body.kind.length === 0 || typeof body.summary !== "string" || body.summary.length === 0) {
    return badRequest();
  }
  const campaignId = (await params).id;
  if (!getCampaign(campaignId)) return NextResponse.json({ error: "Unknown campaign" }, { status: 404 });
  if (!addEvent(campaignId, { id: body.id, kind: body.kind, summary: body.summary })) {
    return NextResponse.json({ error: "Event already exists" }, { status: 409 });
  }
  return NextResponse.json({ id: body.id, kind: body.kind }, { status: 201 });
}
