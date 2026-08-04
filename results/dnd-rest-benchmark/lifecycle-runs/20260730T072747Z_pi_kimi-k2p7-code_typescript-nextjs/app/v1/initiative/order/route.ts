import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

interface Combatant {
  name: string;
  dex: number;
  roll: number;
}

interface InitiativeRequest {
  combatants: Combatant[];
}

export async function POST(request: Request) {
  let body: Partial<InitiativeRequest>;
  try {
    body = (await request.json()) as Partial<InitiativeRequest>;
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const combatants = Array.isArray(body?.combatants) ? body.combatants : [];

  const order = combatants
    .map((c) => ({
      name: String(c.name),
      dex: Number(c.dex),
      score: Number(c.roll) + Number(c.dex),
    }))
    .sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      const dexDiff = b.dex - a.dex;
      if (dexDiff !== 0) return dexDiff;
      return a.name.localeCompare(b.name);
    })
    .map(({ name, score }) => ({ name, score }));

  return NextResponse.json({ order });
}
