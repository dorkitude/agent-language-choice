import { NextResponse } from "next/server";
import {
  store,
  sortCombatants,
  type Combatant,
  type Session,
} from "../../../lib/combat";

export async function POST(req: Request) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON" }, { status: 400 });
  }

  const obj =
    body && typeof body === "object" ? (body as Record<string, unknown>) : {};
  const id = obj.id;
  const combatants = obj.combatants;

  if (typeof id !== "string" || id.length === 0) {
    return NextResponse.json({ error: "invalid id" }, { status: 400 });
  }
  if (!Array.isArray(combatants) || combatants.length === 0) {
    return NextResponse.json({ error: "invalid combatants" }, { status: 400 });
  }

  const s = store();
  if (s.sessions.has(id)) {
    return NextResponse.json({ error: "duplicate id" }, { status: 400 });
  }

  const parsed: Combatant[] = [];
  const seen = new Set<string>();
  for (const c of combatants) {
    const co =
      c && typeof c === "object" ? (c as Record<string, unknown>) : {};
    const name = co.name;
    const dex = co.dex;
    const roll = co.roll;
    if (
      typeof name !== "string" ||
      name.length === 0 ||
      typeof dex !== "number" ||
      typeof roll !== "number"
    ) {
      return NextResponse.json({ error: "invalid combatant" }, { status: 400 });
    }
    if (seen.has(name)) {
      return NextResponse.json(
        { error: "duplicate combatant" },
        { status: 400 },
      );
    }
    seen.add(name);
    parsed.push({ name, dex, score: roll + dex });
  }

  const order = sortCombatants(parsed);
  const session: Session = {
    id,
    round: 1,
    turn_index: 0,
    order,
    conditions: new Map(),
  };
  s.sessions.set(id, session);

  const active = order[session.turn_index];
  return NextResponse.json({
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: { name: active.name, score: active.score },
    order: order.map((c) => ({ name: c.name, score: c.score })),
  });
}
