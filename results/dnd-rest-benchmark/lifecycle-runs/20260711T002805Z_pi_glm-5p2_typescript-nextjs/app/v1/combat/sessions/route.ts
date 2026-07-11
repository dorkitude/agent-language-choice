import { NextResponse } from 'next/server';

interface Combatant {
  name: string;
  dex: number;
  roll: number;
  score: number;
}

interface ConditionEntry {
  condition: string;
  remaining_rounds: number;
}

interface CombatSession {
  id: string;
  order: Combatant[];
  round: number;
  turn_index: number;
  conditions: Map<string, ConditionEntry[]>;
}

interface CombatGlobal {
  __combatSessions?: Map<string, CombatSession>;
}

// Shared in-memory store. Attached to globalThis so it survives Next.js
// dev-mode hot reloads and is shared across all route handlers.
const g = globalThis as unknown as CombatGlobal;
if (!g.__combatSessions) {
  g.__combatSessions = new Map<string, CombatSession>();
}
const sessions = g.__combatSessions;

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

export const dynamic = 'force-dynamic';

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'invalid json' }, { status: 400 });
  }

  const data = body as { id?: unknown; combatants?: unknown };

  const id = data?.id;
  if (typeof id !== 'string' || id.length === 0) {
    return NextResponse.json({ error: 'invalid id' }, { status: 400 });
  }

  const rawCombatants = data?.combatants;
  if (!Array.isArray(rawCombatants) || rawCombatants.length === 0) {
    return NextResponse.json({ error: 'invalid combatants' }, { status: 400 });
  }

  const order: Combatant[] = [];
  for (const entry of rawCombatants) {
    const c = entry as { name?: unknown; dex?: unknown; roll?: unknown };
    if (
      typeof c?.name !== 'string' ||
      c.name.length === 0 ||
      !isFiniteNumber(c?.dex) ||
      !isFiniteNumber(c?.roll)
    ) {
      return NextResponse.json({ error: 'invalid combatant' }, { status: 400 });
    }
    order.push({
      name: c.name,
      dex: c.dex,
      roll: c.roll,
      score: c.roll + c.dex,
    });
  }

  // Sort: score descending, then dex descending, then name ascending.
  order.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    if (a.name < b.name) return -1;
    if (a.name > b.name) return 1;
    return 0;
  });

  if (sessions.has(id)) {
    return NextResponse.json({ error: 'session already exists' }, { status: 400 });
  }

  const session: CombatSession = {
    id,
    order,
    round: 1,
    turn_index: 0,
    conditions: new Map<string, ConditionEntry[]>(),
  };
  sessions.set(id, session);

  const active = order[0];
  return NextResponse.json({
    id,
    round: session.round,
    turn_index: session.turn_index,
    active: { name: active.name, score: active.score },
    order: order.map((c) => ({ name: c.name, score: c.score })),
  });
}
