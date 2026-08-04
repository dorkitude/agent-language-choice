import { Combatant, createSession, hasSession } from "../store.js";
import { rankInitiative } from "../../shared/initiative.js";
import { parseJsonBody, requireNonEmptyString } from "../../http.js";

interface CombatantInput {
  name: string;
  dex: number;
  roll: number;
}

export async function POST(request: Request) {
  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { id, combatants } = (body ?? {}) as {
    id?: unknown;
    combatants?: CombatantInput[];
  };

  const validId = requireNonEmptyString(id, "id");
  if (validId instanceof Response) return validId;

  // Deliberately 400, not 409, for a duplicate session id — existing API
  // contract (see CODEBASE.md), not a pattern to copy elsewhere.
  if (hasSession(validId)) {
    return Response.json({ error: `session ${validId} already exists` }, { status: 400 });
  }

  if (!Array.isArray(combatants) || combatants.length === 0) {
    return Response.json({ error: "combatants must be a non-empty array" }, { status: 400 });
  }

  for (const combatant of combatants) {
    if (
      typeof combatant?.name !== "string" ||
      typeof combatant?.dex !== "number" ||
      typeof combatant?.roll !== "number"
    ) {
      return Response.json(
        { error: "each combatant requires name, dex, and roll" },
        { status: 400 },
      );
    }
  }

  const order: Combatant[] = rankInitiative(combatants).map((entry) => ({
    ...entry,
    conditions: [],
  }));

  createSession({ id: validId, round: 1, turn_index: 0, order });

  const active = order[0];

  return Response.json({
    id: validId,
    round: 1,
    turn_index: 0,
    active: { name: active.name, score: active.score },
    order: order.map((entry) => ({ name: entry.name, score: entry.score })),
  });
}
