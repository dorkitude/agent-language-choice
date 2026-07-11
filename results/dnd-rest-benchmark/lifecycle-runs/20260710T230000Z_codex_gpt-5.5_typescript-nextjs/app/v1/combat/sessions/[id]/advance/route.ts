import { json } from "../../../../../api.js";
import { publicConditions, sessions } from "../../../state.js";

export const runtime = "nodejs";

type RouteContext = {
  params: Promise<{ id: string }>;
};

export async function POST(_request: Request, context: RouteContext) {
  const { id } = await context.params;
  const session = sessions.get(id);
  if (session === undefined) {
    return json({ error: "not_found" }, 404);
  }

  session.turn_index += 1;
  if (session.turn_index >= session.order.length) {
    session.turn_index = 0;
    session.round += 1;
  }

  const active = session.order[session.turn_index];
  const activeConditions = session.conditions.get(active.name);
  if (activeConditions !== undefined) {
    const remainingConditions = activeConditions
      .map(({ condition, remaining_rounds }) => ({ condition, remaining_rounds: remaining_rounds - 1 }))
      .filter(({ remaining_rounds }) => remaining_rounds > 0);

    session.conditions.set(active.name, remainingConditions);
  }

  sessions.set(session.id, session);

  return json({
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: { name: active.name, score: active.score },
    conditions: publicConditions(session),
  });
}
