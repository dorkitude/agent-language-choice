import { NextResponse } from 'next/server';

interface Combatant {
  name: string;
  dex: number;
  roll: number;
  score: number;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'invalid json' }, { status: 400 });
  }

  const rawCombatants = (body as { combatants?: unknown })?.combatants;
  const list: unknown[] = Array.isArray(rawCombatants) ? rawCombatants : [];

  const combatants: Combatant[] = [];
  for (const entry of list) {
    const c = entry as { name?: unknown; dex?: unknown; roll?: unknown };
    if (typeof c?.name !== 'string' || !isFiniteNumber(c?.dex) || !isFiniteNumber(c?.roll)) {
      return NextResponse.json({ error: 'invalid combatant' }, { status: 400 });
    }
    combatants.push({
      name: c.name,
      dex: c.dex,
      roll: c.roll,
      score: c.roll + c.dex,
    });
  }

  combatants.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    if (a.name < b.name) return -1;
    if (a.name > b.name) return 1;
    return 0;
  });

  return NextResponse.json({
    order: combatants.map((c) => ({ name: c.name, score: c.score })),
  });
}
