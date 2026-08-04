import { NextResponse } from "next/server";
import {
  createCombatSession,
  type SessionCombatantInput,
} from "../../../lib/engine.js";
import { badRequest, conflict, parseJsonBody } from "../../../lib/http.js";
import { getCombatSession, insertCombatSession } from "../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (typeof b.id !== "string" || !Array.isArray(b.combatants)) {
    return badRequest();
  }

  const session = createCombatSession(
    b.id,
    b.combatants as SessionCombatantInput[]
  );
  if (!session) {
    return badRequest();
  }

  if (getCombatSession(session.id)) {
    return conflict();
  }

  if (!insertCombatSession(session.id, session.combatants)) {
    return conflict();
  }

  const active = session.combatants[session.turn_index];

  return NextResponse.json({
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: { name: active.name, score: active.score },
    order: session.combatants.map((c) => ({ name: c.name, score: c.score })),
  });
}
