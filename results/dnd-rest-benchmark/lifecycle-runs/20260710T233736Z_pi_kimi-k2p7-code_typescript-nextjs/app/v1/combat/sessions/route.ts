import { createSession } from "../../../lib/combat.js";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const session = createSession(body.id, body.combatants);
    return Response.json({
      id: session.id,
      round: session.round,
      turn_index: session.turn_index,
      active: session.order[session.turn_index],
      order: session.order,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "invalid request";
    return Response.json({ error: message }, { status: 400 });
  }
}
