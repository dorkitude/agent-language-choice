import { NextResponse } from 'next/server';

interface Scored {
  name: string;
  dex: number;
  roll: number;
  score: number;
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'invalid json' }, { status: 400 });
  }

  const combatants = (body as { combatants?: unknown })?.combatants;
  if (!Array.isArray(combatants)) {
    return NextResponse.json({ error: 'invalid request' }, { status: 400 });
  }

  const scored: Scored[] = [];
  for (const c of combatants) {
    const name = (c as { name?: unknown })?.name;
    const dex = Number((c as { dex?: unknown })?.dex);
    const roll = Number((c as { roll?: unknown })?.roll);
    if (
      typeof name !== 'string' ||
      !Number.isFinite(dex) ||
      !Number.isFinite(roll)
    ) {
      return NextResponse.json({ error: 'invalid combatant' }, { status: 400 });
    }
    scored.push({ name, dex, roll, score: roll + dex });
  }

  scored.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    if (a.name < b.name) return -1;
    if (a.name > b.name) return 1;
    return 0;
  });

  return NextResponse.json({
    order: scored.map((s) => ({ name: s.name, score: s.score })),
  });
}
