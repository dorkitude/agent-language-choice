import { createSession, hasSession, type CombatSession, type OrderEntry } from "../store.js";

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

interface RawCombatant {
  name: string;
  dex: number;
  roll: number;
}

function isRawCombatant(value: unknown): value is RawCombatant {
  if (typeof value !== "object" || value === null) return false;
  const { name, dex, roll } = value as Record<string, unknown>;
  return typeof name === "string" && name.length > 0 && isFiniteNumber(dex) && isFiniteNumber(roll);
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "invalid JSON" }, { status: 400 });
  }

  if (typeof body !== "object" || body === null) {
    return Response.json({ error: "invalid request" }, { status: 400 });
  }

  const { id, combatants } = body as Record<string, unknown>;

  if (typeof id !== "string" || id.length === 0) {
    return Response.json({ error: "id is required" }, { status: 400 });
  }

  if (hasSession(id)) {
    return Response.json({ error: "session id already exists" }, { status: 400 });
  }

  if (!Array.isArray(combatants) || combatants.length === 0 || !combatants.every(isRawCombatant)) {
    return Response.json({ error: "combatants array is required" }, { status: 400 });
  }

  const order: OrderEntry[] = (combatants as RawCombatant[]).map((combatant) => ({
    name: combatant.name,
    dex: combatant.dex,
    score: combatant.roll + combatant.dex,
  }));

  order.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
  });

  const session: CombatSession = {
    id,
    round: 1,
    turn_index: 0,
    order,
    conditions: {},
  };

  createSession(session);

  const active = order[0];

  return Response.json({
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: { name: active.name, score: active.score },
    order: order.map(({ name, score }) => ({ name, score })),
  });
}
