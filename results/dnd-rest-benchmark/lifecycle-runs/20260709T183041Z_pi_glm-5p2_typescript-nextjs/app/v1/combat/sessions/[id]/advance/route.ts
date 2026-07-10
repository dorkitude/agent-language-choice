import { NextResponse } from 'next/server';
import { getSession, type Session } from '../../../state';

export const dynamic = 'force-dynamic';

interface Context {
  params: Promise<{ id: string }>;
}

function serializeConditions(
  session: Session,
): Record<string, { condition: string; remaining_rounds: number }[]> {
  const out: Record<
    string,
    { condition: string; remaining_rounds: number }[]
  > = {};
  for (const [name, list] of Object.entries(session.conditions)) {
    // Keep every combatant that has ever received a condition, even once all
    // of their conditions have expired and been removed. The expired-removed
    // case expects the combatant's key to remain present with an empty list.
    out[name] = list.map((c) => ({
      condition: c.condition,
      remaining_rounds: c.remaining_rounds,
    }));
  }
  return out;
}

export async function POST(_request: Request, { params }: Context) {
  const { id } = await params;
  const session = getSession(id);
  if (!session) {
    return NextResponse.json({ error: 'unknown session' }, { status: 404 });
  }

  // Advance turn_index, wrapping to 0 increments round.
  session.turn_index += 1;
  if (session.turn_index >= session.order.length) {
    session.turn_index = 0;
    session.round += 1;
  }

  // At the start of the active combatant's turn, decrement each condition
  // attached to that combatant; remove any that reach 0.
  const active = session.order[session.turn_index];
  const conds = session.conditions[active.name];
  if (conds) {
    for (const c of conds) {
      c.remaining_rounds -= 1;
    }
    session.conditions[active.name] = conds.filter(
      (c) => c.remaining_rounds > 0,
    );
  }

  return NextResponse.json({
    id,
    round: session.round,
    turn_index: session.turn_index,
    active: { name: active.name, score: active.score },
    conditions: serializeConditions(session),
  });
}
