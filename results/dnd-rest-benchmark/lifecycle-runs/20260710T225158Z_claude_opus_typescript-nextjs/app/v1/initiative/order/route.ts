import { NextResponse } from "next/server";

export async function POST(req: Request) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON" }, { status: 400 });
  }

  const obj =
    body && typeof body === "object" ? (body as Record<string, unknown>) : {};
  const combatants = obj.combatants;

  if (!Array.isArray(combatants)) {
    return NextResponse.json({ error: "invalid request" }, { status: 400 });
  }

  const parsed: { name: string; dex: number; score: number }[] = [];
  for (const c of combatants) {
    const co =
      c && typeof c === "object" ? (c as Record<string, unknown>) : {};
    const name = co.name;
    const dex = co.dex;
    const roll = co.roll;
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
