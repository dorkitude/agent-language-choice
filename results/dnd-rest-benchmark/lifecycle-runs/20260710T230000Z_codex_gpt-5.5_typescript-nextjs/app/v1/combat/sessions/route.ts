import { badRequest, isFiniteNumber, isRecord, json, readJson } from "../../../api.js";
import { type CombatSession, sessions, sessionSummary } from "../state.js";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const body = await readJson(request);
  if (!isRecord(body) || typeof body.id !== "string" || !Array.isArray(body.combatants) || body.combatants.length === 0) {
    return badRequest();
  }

  if (sessions.has(body.id)) {
    return badRequest();
  }

  const order = [];
  for (const combatant of body.combatants) {
    if (
      !isRecord(combatant) ||
      typeof combatant.name !== "string" ||
      !isFiniteNumber(combatant.dex) ||
      !isFiniteNumber(combatant.roll)
    ) {
      return badRequest();
    }

    order.push({
      name: combatant.name,
      dex: combatant.dex,
      score: combatant.roll + combatant.dex,
    });
  }

  order.sort((a, b) => b.score - a.score || b.dex - a.dex || a.name.localeCompare(b.name));

  const session: CombatSession = {
    id: body.id,
    round: 1,
    turn_index: 0,
    order,
    conditions: new Map(),
  };
  sessions.set(session.id, session);

  return json(sessionSummary(session));
}
