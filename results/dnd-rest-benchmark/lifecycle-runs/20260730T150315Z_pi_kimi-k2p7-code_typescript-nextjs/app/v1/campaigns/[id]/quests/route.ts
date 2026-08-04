import { NextResponse } from "next/server";
import { badRequest, conflict, notFound, parseJsonBody } from "../../../../lib/http.js";
import { isNonEmptyString } from "../../../../lib/validate.js";
import {
  createQuest,
  getCampaign,
  isValidQuestStatus,
} from "../../../../lib/storage.js";
import type { CreateQuestInput } from "../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  if (!getCampaign(id)) {
    return notFound();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  const milestones = Array.isArray(b.milestones)
    ? (b.milestones as unknown[])
    : [];
  if (
    !isNonEmptyString(b.id) ||
    typeof b.title !== "string" ||
    !isValidQuestStatus(b.status) ||
    milestones.some((m) => typeof m !== "string") ||
    new Set(milestones).size !== milestones.length
  ) {
    return badRequest();
  }

  const input: CreateQuestInput = {
    id: b.id,
    title: b.title,
    status: b.status,
    milestones: milestones as string[],
  };

  const result = createQuest(id, input);
  if (!result) {
    return conflict();
  }

  return NextResponse.json(result, { status: 201 });
}
