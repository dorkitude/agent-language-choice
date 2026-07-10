import { NextResponse } from "next/server";
import { activeCombatant, conditionRecord, sessions } from "../../../state.js";

type RouteContext = {
  params: Promise<{ id: string }>;
};

function notFound() {
  return NextResponse.json({ error: "not found" }, { status: 404 });
}

export async function POST(_request: Request, context: RouteContext) {
  const { id } = await context.params;
  const session = sessions.get(id);
  if (session === undefined) {
    return notFound();
  }

  session.turn_index += 1;
  if (session.turn_index >= session.order.length) {
    session.turn_index = 0;
    session.round += 1;
  }

  const active = session.order[session.turn_index];
  const activeConditions = session.conditions.get(active.name);
  let includeEmptyConditionNames: string[] = [];
  if (activeConditions !== undefined) {
    const hadConditions = activeConditions.length > 0;
    const remaining = activeConditions
      .map(({ condition, remaining_rounds }) => ({
        condition,
        remaining_rounds: remaining_rounds - 1,
      }))
      .filter(({ remaining_rounds }) => remaining_rounds > 0);
    session.conditions.set(active.name, remaining);
    if (hadConditions && remaining.length === 0) {
      includeEmptyConditionNames = [active.name];
    }
  }

  return NextResponse.json({
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: activeCombatant(session),
    conditions: conditionRecord(session, includeEmptyConditionNames),
  });
}
