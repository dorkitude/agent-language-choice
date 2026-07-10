import { NextResponse } from 'next/server';

export async function POST(request: Request) {
  let body: {
    combatants?: Array<{ name?: string; dex?: number; roll?: number }>;
  };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const combatants = Array.isArray(body?.combatants) ? body.combatants : [];

  const scored = combatants.map((c) => {
    if (typeof c?.name !== 'string' || typeof c?.dex !== 'number' || typeof c?.roll !== 'number') {
      return null;
    }
    return { name: c.name, score: c.roll + c.dex, dex: c.dex };
  });

  if (scored.some((c) => c === null)) {
    return NextResponse.json({ error: 'combatants require name, dex, and roll' }, { status: 400 });
  }

  const order = scored
    .filter((c): c is { name: string; score: number; dex: number } => c !== null)
    .sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      if (b.dex !== a.dex) return b.dex - a.dex;
      return a.name.localeCompare(b.name);
    })
    .map(({ name, score }) => ({ name, score }));

  return NextResponse.json({ order });
}
