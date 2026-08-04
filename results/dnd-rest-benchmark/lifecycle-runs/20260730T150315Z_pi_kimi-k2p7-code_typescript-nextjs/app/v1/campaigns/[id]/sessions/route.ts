import { NextResponse } from "next/server";
import { badRequest, conflict, notFound, parseJsonBody } from "../../../../lib/http.js";
import { isNonEmptyString, isNonEmptyStringArray, isPositiveInteger } from "../../../../lib/validate.js";
import { createSession, getCampaign } from "../../../../lib/storage.js";
import type { CreateSessionInput } from "../../../../lib/storage.js";

export const dynamic = "force-dynamic";

const ISO8601_Z = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;

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
  if (
    !isNonEmptyString(b.id) ||
    typeof b.starts_at !== "string" ||
    !ISO8601_Z.test(b.starts_at) ||
    !isPositiveInteger(b.duration_minutes) ||
    !isNonEmptyStringArray(b.agenda)
  ) {
    return badRequest();
  }

  const input: CreateSessionInput = {
    id: b.id,
    starts_at: b.starts_at,
    duration_minutes: b.duration_minutes,
    agenda: b.agenda,
  };

  const result = createSession(id, input);
  if (!result) {
    return conflict();
  }

  return NextResponse.json(result, { status: 201 });
}
