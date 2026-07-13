import { getSession } from "../../../store.js";

export async function POST(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const session = getSession(id);
  if (!session) {
    return Response.json({ error: "session not found" }, { status: 404 });
  }

  const nextIndex = session.turn_index + 1;
  if (nextIndex >= session.order.length) {
    session.turn_index = 0;
    session.round += 1;
  } else {
    session.turn_index = nextIndex;
  }

  const active = session.order[session.turn_index];
  const activeConditions = session.conditions[active.name] ?? [];
  const remaining = activeConditions
    .map((c) => ({ condition: c.condition, remaining_rounds: c.remaining_rounds - 1 }))
    .filter((c) => c.remaining_rounds > 0);
  if (remaining.length > 0) {
    session.conditions[active.name] = remaining;
  } else {
    delete session.conditions[active.name];
  }

  const conditions: Record<string, { condition: string; remaining_rounds: number }[]> = {};
  for (const [name, list] of Object.entries(session.conditions)) {
    if (list.length > 0) conditions[name] = list;
  }
  if (!(active.name in conditions)) {
    conditions[active.name] = [];
  }

  return Response.json({
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: { name: active.name, score: active.score },
    conditions,
  });
}
