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
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const session = sessions.get(id);
  if (!session) {
    return NextResponse.json({ error: 'unknown session' }, { status: 404 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'invalid json' }, { status: 400 });
  }

  const data = body as {
    target?: unknown;
    condition?: unknown;
    duration_rounds?: unknown;
  };

  const target = data?.target;
  const condition = data?.condition;
  const duration = data?.duration_rounds;

  if (typeof target !== 'string' || target.length === 0) {
    return NextResponse.json({ error: 'invalid target' }, { status: 400 });
  }
  if (typeof condition !== 'string' || condition.length === 0) {
    return NextResponse.json({ error: 'invalid condition' }, { status: 400 });
  }
  if (
    typeof duration !== 'number' ||
    !Number.isInteger(duration) ||
    duration <= 0
  ) {
    return NextResponse.json({ error: 'invalid duration_rounds' }, { status: 400 });
  }

  const exists = session.order.some((c) => c.name === target);
  if (!exists) {
    return NextResponse.json({ error: 'unknown target' }, { status: 400 });
  }

  const entry: ConditionEntry = { condition, remaining_rounds: duration };
  let list = session.conditions.get(target);
  if (!list) {
    list = [];
    session.conditions.set(target, list);
  }
  list.push(entry);

  return NextResponse.json({
    target,
    conditions: list.map((e) => ({
      condition: e.condition,
      remaining_rounds: e.remaining_rounds,
    })),
  });
}
