import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

interface Combatant {
  name: string;
  dex: number;
  roll: number;
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
    return NextResponse.json({ error: 'invalid input' }, { status: 400 });
  }

  const scored = (combatants as Combatant[]).map((c) => ({
    name: c.name,
    dex: c.dex,
    score: c.roll + c.dex,
  }));

  // Sort: score desc, then dex desc, then name asc.
  scored.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    if (a.name < b.name) return -1;
    if (a.name > b.name) return 1;
    return 0;
  });

  const order = scored.map((s) => ({ name: s.name, score: s.score }));

  return NextResponse.json({ order });
}
