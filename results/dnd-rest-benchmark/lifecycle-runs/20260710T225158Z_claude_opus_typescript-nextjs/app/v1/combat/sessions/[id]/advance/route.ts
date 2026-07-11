import { NextResponse } from "next/server";
import { store, conditionsObject } from "../../../../../lib/combat";

export async function POST(
  _req: Request,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;

  const s = store();
  const session = s.sessions.get(id);
  if (!session) {
    return NextResponse.json({ error: "unknown session" }, { status: 404 });
  }

  const n = session.order.length;
  const next = session.turn_index + 1;
  if (next >= n) {
    session.turn_index = 0;
    session.round += 1;
  } else {
    session.turn_index = next;
  }

  const active = session.order[session.turn_index];
  const list = session.conditions.get(active.name);
  if (list) {
    const kept = [];
    for (const c of list) {
      c.remaining_rounds -= 1;
      if (c.remaining_rounds > 0) kept.push(c);
    }
    session.conditions.set(active.name, kept);
  }

  return NextResponse.json({
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: { name: active.name, score: active.score },
    conditions: conditionsObject(session),
  });
}
