import { NextResponse } from "next/server";
import { conditionSummary, getSession, saveSession } from "../../../../../lib/combat";

export const runtime = "nodejs";

export async function POST(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const session = getSession((await params).id);
  if (!session) return NextResponse.json({ error: "Unknown session" }, { status: 404 });

  session.turnIndex += 1;
  if (session.turnIndex === session.order.length) {
    session.turnIndex = 0;
    session.round += 1;
  }
  const active = session.order[session.turnIndex];
  const existing = session.conditions.get(active.name);
  if (existing) {
    const remaining = existing
      .map((item) => ({ ...item, remaining_rounds: item.remaining_rounds - 1 }))
      .filter((item) => item.remaining_rounds > 0);
    // A combatant's condition list remains addressable after its final
    // condition expires; only the expired condition itself is removed.
    session.conditions.set(active.name, remaining);
  }
  saveSession(session);
  return NextResponse.json({
    id: session.id,
    round: session.round,
    turn_index: session.turnIndex,
    active: { name: active.name, score: active.score },
    conditions: conditionSummary(session),
  });
}
