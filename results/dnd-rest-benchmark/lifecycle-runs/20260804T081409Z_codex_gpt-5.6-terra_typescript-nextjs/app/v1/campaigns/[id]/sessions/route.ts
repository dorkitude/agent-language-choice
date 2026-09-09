import { NextResponse } from "next/server";
import { createCampaignSession, getCampaign } from "../../../../lib/campaigns";
import { badRequest, isInteger, isNonEmptyString, isRecord, jsonBody } from "../../../../lib/http";

export const runtime = "nodejs";

function isTimestamp(value: unknown): value is string {
  return isNonEmptyString(value) && Number.isFinite(Date.parse(value));
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.id) || !isTimestamp(body.starts_at) ||
    !isInteger(body.duration_minutes) || body.duration_minutes <= 0 ||
    !Array.isArray(body.agenda) || !body.agenda.every(isNonEmptyString)) {
    return badRequest();
  }
  const campaignId = (await params).id;
  if (!getCampaign(campaignId)) return NextResponse.json({ error: "Unknown campaign" }, { status: 404 });
  const session = createCampaignSession(campaignId, {
    id: body.id,
    starts_at: body.starts_at,
    duration_minutes: body.duration_minutes,
    agenda: body.agenda,
  });
  if (!session) return NextResponse.json({ error: "Session already exists" }, { status: 409 });
  return NextResponse.json(session, { status: 201 });
}
