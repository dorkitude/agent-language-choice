import { NextResponse } from "next/server";
import { activeCombatant, publicOrder, sessions, type CombatSession, type InitiativeEntry } from "../state.js";

function badRequest() {
  return NextResponse.json({ error: "invalid request" }, { status: 400 });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export async function POST(request: Request) {
  let body: unknown;

  try {
    body = await request.json();
  } catch {
    return badRequest();
  }

  if (!isRecord(body)) {
    return badRequest();
  }

  const { id, combatants } = body;
  if (typeof id !== "string" || sessions.has(id) || !Array.isArray(combatants) || combatants.length === 0) {
    return badRequest();
  }

  const order: InitiativeEntry[] = [];

  for (const combatant of combatants) {
    if (!isRecord(combatant)) {
      return badRequest();
    }

    const { name, dex, roll } = combatant;
    if (typeof name !== "string" || !isNumber(dex) || !isNumber(roll)) {
      return badRequest();
    }

    order.push({ name, dex, score: roll + dex });
  }

  order.sort((left, right) => {
    if (left.score !== right.score) return right.score - left.score;
    if (left.dex !== right.dex) return right.dex - left.dex;
    return left.name.localeCompare(right.name);
  });

  const session: CombatSession = {
    id,
    round: 1,
    turn_index: 0,
    order,
    conditions: new Map(order.map(({ name }) => [name, []] as const)),
  };

  sessions.set(id, session);

  return NextResponse.json({
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: activeCombatant(session),
    order: publicOrder(session.order),
  });
}
