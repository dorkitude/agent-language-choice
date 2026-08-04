import { NextResponse } from "next/server";
import { addConditionToSession } from "../../../../../lib/engine.js";
import { badRequest, notFound, parseJsonBody } from "../../../../../lib/http.js";
import { getCombatSession, replaceCombatSession } from "../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  const session = getCombatSession(id);
  if (!session) {
    return notFound();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (
    typeof b.target !== "string" ||
    typeof b.condition !== "string" ||
    !Number.isInteger(b.duration_rounds)
  ) {
    return badRequest();
  }

  const result = addConditionToSession(
    session,
    b.target,
    b.condition,
    Number(b.duration_rounds)
  );
  if (!result) {
    return badRequest();
  }

  replaceCombatSession(session);

  return NextResponse.json(result);
}
