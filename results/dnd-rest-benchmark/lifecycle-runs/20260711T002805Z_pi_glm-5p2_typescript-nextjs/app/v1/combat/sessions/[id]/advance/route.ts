import { NextResponse } from 'next/server';

interface ConditionEntry {
  condition: string;
  remaining_rounds: number;
}

interface CombatSession {
  id: string;
  order: { name: string; score: number }[];
  round: number;
  turn_index: number;
  conditions: Map<string, ConditionEntry[]>;
}

interface CombatGlobal {
  __combatSessions?: Map<string, CombatSession>;
}

const g = globalThis as unknown as CombatGlobal;
if (!g.__combatSessions) {
  g.__combatSessions = new Map<string, CombatSession>();
}
const sessions = g.__combatSessions;

export const dynamic = 'force-dynamic';

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const session = sessions.get(id);
  if (!session) {
    return NextResponse.json({ error: 'unknown session' }, { status: 404 });
  }

  // Advance to the next combatant; wrap and increment round at the end.
  let nextIndex = session.turn_index + 1;
  if (nextIndex >= session.order.length) {
    nextIndex = 0;
    session.round += 1;
  }
  session.turn_index = nextIndex;

  const active = session.order[nextIndex];

  // At the start of this combatant's turn, decrement their conditions and
  // remove any whose remaining duration reaches 0. Retain the combatant's
  // key with an empty array so callers can see the target still exists but
  // has no active conditions.
  const list = session.conditions.get(active.name);
  if (list) {
    for (const e of list) {
      e.remaining_rounds -= 1;
    }
    const filtered = list.filter((e) => e.remaining_rounds > 0);
    session.conditions.set(active.name, filtered);
  }

  // Report combatants that have (or had) conditions, including empty arrays
  // for those whose conditions have all expired.
  const conditionsOut: Record<
    string,
    { condition: string; remaining_rounds: number }[]
  > = {};
  for (const [name, entries] of session.conditions) {
    conditionsOut[name] = entries.map((e) => ({
      condition: e.condition,
      remaining_rounds: e.remaining_rounds,
    }));
  }

  return NextResponse.json({
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: { name: active.name, score: active.score },
    conditions: conditionsOut,
  });
}
