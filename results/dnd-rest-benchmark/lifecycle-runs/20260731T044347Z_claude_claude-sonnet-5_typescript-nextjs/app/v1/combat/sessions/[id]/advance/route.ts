import { Condition, getSession, saveSession } from "../../../store.js";

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;

  const session = getSession(id);
  if (!session) {
    return Response.json({ error: `session ${id} not found` }, { status: 404 });
  }

  session.turn_index += 1;
  if (session.turn_index >= session.order.length) {
    session.turn_index = 0;
    session.round += 1;
  }

  const active = session.order[session.turn_index];
  active.conditions = active.conditions
    .map((entry: Condition) => ({ ...entry, remaining_rounds: entry.remaining_rounds - 1 }))
    .filter((entry: Condition) => entry.remaining_rounds > 0);

  saveSession(session);

  const conditions: Record<string, Condition[]> = {};
  for (const combatant of session.order) {
    if (combatant.conditions.length > 0 || combatant.name === active.name) {
      conditions[combatant.name] = combatant.conditions.map((entry: Condition) => ({
        condition: entry.condition,
        remaining_rounds: entry.remaining_rounds,
      }));
    }
  }

  return Response.json({
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: { name: active.name, score: active.score },
    conditions,
  });
}
