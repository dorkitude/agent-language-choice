import { NextResponse } from "next/server";
import { Combatant, Session, hasSession, saveSession, activeView } from "../store";

export async function POST(req: Request) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }

  const obj =
    typeof body === "object" && body !== null
      ? (body as Record<string, unknown>)
      : {};
  const id = obj.id;
  const combatants = obj.combatants;

  if (typeof id !== "string" || id.length === 0) {
    return NextResponse.json({ error: "invalid id" }, { status: 400 });
  }
  if (!Array.isArray(combatants) || combatants.length === 0) {
    return NextResponse.json({ error: "invalid combatants" }, { status: 400 });
  }

  if (hasSession(id)) {
    return NextResponse.json({ error: "duplicate id" }, { status: 400 });
  }

  const parsed: Combatant[] = [];
  const names = new Set<string>();
  for (const c of combatants) {
    const o = c && typeof c === "object" ? (c as Record<string, unknown>) : {};
    const name = o.name;
    const dex = o.dex;
    const roll = o.roll;
    if (
      typeof name !== "string" ||
      typeof dex !== "number" ||
      typeof roll !== "number"
    ) {
      return NextResponse.json({ error: "invalid combatant" }, { status: 400 });
    }
    if (names.has(name)) {
      return NextResponse.json({ error: "duplicate combatant" }, { status: 400 });
    }
    names.add(name);
    parsed.push({ name, dex, score: roll + dex, conditions: [], hadCondition: false });
  }

  parsed.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
  });

  const session: Session = { id, round: 1, turn_index: 0, order: parsed };
  saveSession(session);

  return NextResponse.json({
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: activeView(session),
    order: session.order.map((c) => ({ name: c.name, score: c.score })),
  });
}
