import { NextResponse } from "next/server";

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
    return NextResponse.json({ error: "invalid JSON" }, { status: 400 });
  }

  const { combatants } = (body ?? {}) as { combatants?: Combatant[] };
  if (!Array.isArray(combatants)) {
    return NextResponse.json({ error: "combatants must be an array" }, { status: 400 });
  }

  const scored = combatants.map((c) => ({ name: c.name, dex: c.dex, score: c.roll + c.dex }));

  scored.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name.localeCompare(b.name);
  });

  return NextResponse.json({
    order: scored.map(({ name, score }) => ({ name, score })),
  });
}
