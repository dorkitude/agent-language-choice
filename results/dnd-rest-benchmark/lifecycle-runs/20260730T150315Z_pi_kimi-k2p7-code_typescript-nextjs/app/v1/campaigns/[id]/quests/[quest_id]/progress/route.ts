import { NextResponse } from "next/server";
import { badRequest, notFound, parseJsonBody } from "../../../../../../lib/http.js";
import {
  getCampaign,
  getQuest,
  updateQuestProgress,
} from "../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; quest_id: string }> }
) {
  const { id, quest_id } = await params;

  if (!getCampaign(id)) {
    return notFound();
  }

  const quest = getQuest(id, quest_id);
  if (!quest) {
    return notFound();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  const completed = Array.isArray(b.completed) ? (b.completed as unknown[]) : [];
  if (completed.some((m) => typeof m !== "string")) {
    return badRequest();
  }

  const completedTitles = completed as string[];
  const milestoneSet = new Set(quest.milestones.map((m) => m.title));
  if (completedTitles.some((m) => !milestoneSet.has(m))) {
    return badRequest();
  }

  const result = updateQuestProgress(id, quest_id, completedTitles);
  if (!result) {
    return notFound();
  }

  return NextResponse.json(result);
}
