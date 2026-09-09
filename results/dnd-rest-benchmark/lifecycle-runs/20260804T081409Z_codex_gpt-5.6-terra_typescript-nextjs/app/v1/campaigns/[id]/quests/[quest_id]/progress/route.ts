import { NextResponse } from "next/server";
import { getCampaign, updateQuestProgress } from "../../../../../../lib/campaigns";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../../lib/http";

export const runtime = "nodejs";

export async function POST(request: Request, { params }: { params: Promise<{ id: string; quest_id: string }> }) {
  const body = await jsonBody(request);
  if (!isRecord(body) || !Array.isArray(body.completed) || !body.completed.every(isNonEmptyString)) return badRequest();
  const { id: campaignId, quest_id: questId } = await params;
  if (!getCampaign(campaignId)) return NextResponse.json({ error: "Unknown campaign" }, { status: 404 });
  const quest = updateQuestProgress(campaignId, questId, body.completed);
  if (quest === undefined) return NextResponse.json({ error: "Unknown quest" }, { status: 404 });
  if (quest === null) return badRequest("Unknown milestone");
  return NextResponse.json(quest);
}
