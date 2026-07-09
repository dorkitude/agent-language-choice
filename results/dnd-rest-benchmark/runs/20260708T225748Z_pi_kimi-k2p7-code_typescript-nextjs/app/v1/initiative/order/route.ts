import { NextResponse, type NextRequest } from "next/server";

export async function POST(request: NextRequest) {
  let body: {
    combatants?: Array<{ name?: unknown; dex?: unknown; roll?: unknown }>;
  };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const combatants = body?.combatants;
  if (!Array.isArray(combatants)) {
    return NextResponse.json({ error: "Invalid combatants" }, { status: 400 });
  }

  const scored = combatants.map((c) => {
    const name = c?.name;
    const dex = Number(c?.dex);
    const roll = Number(c?.roll);
    if (typeof name !== "string" || !Number.isInteger(dex) || !Number.isInteger(roll)) {
      return null;
    }
    return { name, score: roll + dex, dex };
  });

  if (scored.some((c) => c === null)) {
    return NextResponse.json({ error: "Invalid combatant" }, { status: 400 });
  }

  const sorted = scored
    .filter((c): c is NonNullable<typeof c> => c !== null)
    .sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      if (b.dex !== a.dex) return b.dex - a.dex;
      return a.name.localeCompare(b.name);
    });

  const order = sorted.map(({ name, score }) => ({ name, score }));
  return NextResponse.json({ order });
}
