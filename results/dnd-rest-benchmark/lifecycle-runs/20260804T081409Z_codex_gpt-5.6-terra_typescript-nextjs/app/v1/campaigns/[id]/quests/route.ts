import { NextResponse } from "next/server";
import { createQuest, getCampaign, type QuestStatus } from "../../../../lib/campaigns";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../lib/http";

export const runtime = "nodejs";

const validStatuses = new Set<QuestStatus>(["active", "completed", "blocked"]);

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.id) || !isNonEmptyString(body.title) ||
    !isNonEmptyString(body.status) || !validStatuses.has(body.status as QuestStatus) ||
    !Array.isArray(body.milestones) || !body.milestones.every(isNonEmptyString) ||
    new Set(body.milestones).size !== body.milestones.length) {
    return badRequest();
  }
  const campaignId = (await params).id;
  if (!getCampaign(campaignId)) return NextResponse.json({ error: "Unknown campaign" }, { status: 404 });
  const quest = createQuest(campaignId, {
    id: body.id,
    title: body.title,
    status: body.status as QuestStatus,
    milestones: body.milestones,
  });
  if (!quest) return NextResponse.json({ error: "Quest already exists" }, { status: 409 });
  return NextResponse.json(quest, { status: 201 });
}
