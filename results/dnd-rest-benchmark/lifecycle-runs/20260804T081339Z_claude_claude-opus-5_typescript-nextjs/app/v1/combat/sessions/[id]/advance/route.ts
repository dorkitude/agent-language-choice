import { json, notFound } from "../../../../../../lib/http";
import {
  activeCombatant,
  getSession,
  saveSession,
  sessionState,
} from "../../../../../../lib/combat";

export const dynamic = "force-dynamic";

export async function POST(
  _request: Request,
  context: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await context.params;
  const session = getSession(id);
  if (!session) return notFound("unknown session");

  const next = session.turn_index + 1;
  if (next >= session.order.length) {
    session.turn_index = 0;
    session.round += 1;
  } else {
    session.turn_index = next;
  }

  // The newly active combatant's conditions tick at the start of their turn.
  const active = activeCombatant(session);
  active.conditions = active.conditions
    .map((entry) => ({ ...entry, remaining_rounds: entry.remaining_rounds - 1 }))
    .filter((entry) => entry.remaining_rounds > 0);

  saveSession(session);
  return json(sessionState(session));
}
