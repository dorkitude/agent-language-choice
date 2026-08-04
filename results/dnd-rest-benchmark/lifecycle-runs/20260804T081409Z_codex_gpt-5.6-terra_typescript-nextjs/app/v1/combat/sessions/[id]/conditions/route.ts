import { NextResponse } from "next/server";
import { getSession, saveSession } from "../../../../../lib/combat";
import { badRequest, isInteger, isRecord, jsonBody } from "../../../../../lib/http";

export const runtime = "nodejs";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const body = await jsonBody(request);
  if (!isRecord(body) || typeof body.target !== "string" || typeof body.condition !== "string" || !isInteger(body.duration_rounds) || body.duration_rounds <= 0) {
    return badRequest();
  }
  const session = getSession((await params).id);
  if (!session) return NextResponse.json({ error: "Unknown session" }, { status: 404 });
  if (!session.order.some(({ name }) => name === body.target)) return badRequest("Unknown combatant");

  const conditions = session.conditions.get(body.target) ?? [];
  conditions.push({ condition: body.condition, remaining_rounds: body.duration_rounds });
  session.conditions.set(body.target, conditions);
  saveSession(session);
  return NextResponse.json({ target: body.target, conditions });
}
