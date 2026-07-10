import { NextResponse } from "next/server";

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }

  const combatants = (body as { combatants?: unknown } | null)?.combatants;
  if (!Array.isArray(combatants)) {
    return NextResponse.json({ error: "invalid input" }, { status: 400 });
  }

  const parsed: { name: string; dex: number; score: number }[] = [];
  for (const c of combatants) {
    const name = (c as { name?: unknown }).name;
    const dex = (c as { dex?: unknown }).dex;
    const roll = (c as { roll?: unknown }).roll;
    if (
      typeof name !== "string" ||
      typeof dex !== "number" ||
      typeof roll !== "number"
    ) {
      return NextResponse.json({ error: "invalid combatant" }, { status: 400 });
    }
    parsed.push({ name, dex, score: roll + dex });
  }

  parsed.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
  });

  return NextResponse.json({
    order: parsed.map((c) => ({ name: c.name, score: c.score })),
  });
}
