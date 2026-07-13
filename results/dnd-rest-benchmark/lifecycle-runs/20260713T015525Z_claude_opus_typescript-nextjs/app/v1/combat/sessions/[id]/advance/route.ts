import { NextResponse } from "next/server";
import { getSession, saveSession, activeView, conditionsView } from "../../../store";

export async function POST(
  _req: Request,
  ctx: { params: Promise<{ id: string }> }
) {
  const { id } = await ctx.params;

  const session = getSession(id);
  if (!session) {
    return NextResponse.json({ error: "unknown session" }, { status: 404 });
  }

  session.turn_index += 1;
  if (session.turn_index >= session.order.length) {
    session.turn_index = 0;
    session.round += 1;
  }

  const active = session.order[session.turn_index];
  active.conditions = active.conditions
    .map((c) => ({ ...c, remaining_rounds: c.remaining_rounds - 1 }))
    .filter((c) => c.remaining_rounds > 0);

  saveSession(session);

  return NextResponse.json({
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: activeView(session),
    conditions: conditionsView(session),
  });
}
