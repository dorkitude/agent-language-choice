import { NextResponse } from "next/server";
import { getCampaign, hasCampaignCharacter, recordSessionAttendance } from "../../../../../../lib/campaigns";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../../lib/http";

export const runtime = "nodejs";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; session_id: string }> },
) {
  const body = await jsonBody(request);
  if (!isRecord(body)) return badRequest();
  const { present, absent } = body;
  if (!Array.isArray(present) || !Array.isArray(absent) ||
    !present.every(isNonEmptyString) || !absent.every(isNonEmptyString) ||
    new Set(present).size !== present.length || new Set(absent).size !== absent.length ||
    present.some((characterId) => absent.includes(characterId))) {
    return badRequest();
  }
  const { id: campaignId, session_id: sessionId } = await params;
  if (!getCampaign(campaignId)) return NextResponse.json({ error: "Unknown campaign" }, { status: 404 });
  if (![...present, ...absent].every((characterId) => hasCampaignCharacter(campaignId, characterId))) {
    return NextResponse.json({ error: "Unknown character" }, { status: 404 });
  }
  const attendance = recordSessionAttendance(campaignId, sessionId, present, absent);
  if (!attendance) return NextResponse.json({ error: "Unknown session" }, { status: 404 });
  return NextResponse.json(attendance);
}
