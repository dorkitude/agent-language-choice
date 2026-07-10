import { sessions, publicCombatant, Condition } from "../../../_store.js";

function notFound(message: string) {
  return Response.json({ error: message }, { status: 404 });
}

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const session = sessions.get(id);
  if (!session) {
    return notFound("unknown session id");
  }

  session.turn_index += 1;
  if (session.turn_index >= session.order.length) {
    session.turn_index = 0;
    session.round += 1;
  }

  const active = session.order[session.turn_index];
  const activeHadConditions = active.conditions.length > 0;
  active.conditions = active.conditions
    .map((c: Condition) => ({ ...c, remaining_rounds: c.remaining_rounds - 1 }))
    .filter((c: Condition) => c.remaining_rounds > 0);

  const conditions: Record<string, Condition[]> = {};
  for (const combatant of session.order) {
    if (combatant.conditions.length > 0 || (combatant === active && activeHadConditions)) {
      conditions[combatant.name] = combatant.conditions.map((c: Condition) => ({
        condition: c.condition,
        remaining_rounds: c.remaining_rounds,
      }));
    }
  }

  return Response.json({
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: publicCombatant(active),
    conditions,
  });
}
