import { NextResponse } from 'next/server';
import { putSession, type Combatant, type Session } from '../state';

export const dynamic = 'force-dynamic';

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'invalid json' }, { status: 400 });
  }

  const id = (body as { id?: unknown })?.id;
  if (typeof id !== 'string' || id.length === 0) {
    return NextResponse.json({ error: 'invalid id' }, { status: 400 });
  }

  const combatants = (body as { combatants?: unknown })?.combatants;
  if (!Array.isArray(combatants) || combatants.length === 0) {
    return NextResponse.json({ error: 'invalid combatants' }, { status: 400 });
  }

  const order: Combatant[] = [];
  for (const c of combatants) {
    const name = (c as { name?: unknown })?.name;
    const dex = Number((c as { dex?: unknown })?.dex);
    const roll = Number((c as { roll?: unknown })?.roll);
    if (
      typeof name !== 'string' ||
      name.length === 0 ||
      !Number.isFinite(dex) ||
      !Number.isFinite(roll)
    ) {
      return NextResponse.json(
        { error: 'invalid combatant' },
        { status: 400 },
      );
    }
    order.push({ name, dex, roll, score: roll + dex });
  }

  // Sort: score desc, dex desc, name asc.
  order.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    if (a.name < b.name) return -1;
    if (a.name > b.name) return 1;
    return 0;
  });

  const session: Session = {
    id,
    order,
    round: 1,
    turn_index: 0,
    conditions: {},
  };
  putSession(session);

  const active = order[0];
  return NextResponse.json({
    id,
    round: 1,
    turn_index: 0,
    active: { name: active.name, score: active.score },
    order: order.map((c) => ({ name: c.name, score: c.score })),
  });
}
