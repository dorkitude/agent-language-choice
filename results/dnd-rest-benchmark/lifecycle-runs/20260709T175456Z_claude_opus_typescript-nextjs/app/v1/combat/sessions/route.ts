import { NextResponse } from "next/server";
import {
  sessions,
  orderView,
  type Combatant,
  type Session,
} from "../store";

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }

  const id = (body as { id?: unknown } | null)?.id;
  const combatants = (body as { combatants?: unknown } | null)?.combatants;

  if (typeof id !== "string" || id.length === 0) {
    return NextResponse.json({ error: "invalid id" }, { status: 400 });
  }
  if (!Array.isArray(combatants) || combatants.length === 0) {
    return NextResponse.json({ error: "invalid combatants" }, { status: 400 });
  }
  if (sessions.has(id)) {
    return NextResponse.json({ error: "duplicate session id" }, { status: 400 });
  }

  const parsed: Combatant[] = [];
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
    parsed.push({
      name,
      dex,
      score: roll + dex,
      conditions: [],
      everHadConditions: false,
    });
  }

  parsed.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
  });

  const session: Session = { id, round: 1, turn_index: 0, order: parsed };
  sessions.set(id, session);

  const active = parsed[session.turn_index];
  return NextResponse.json({
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: { name: active.name, score: active.score },
    order: orderView(parsed),
  });
}
