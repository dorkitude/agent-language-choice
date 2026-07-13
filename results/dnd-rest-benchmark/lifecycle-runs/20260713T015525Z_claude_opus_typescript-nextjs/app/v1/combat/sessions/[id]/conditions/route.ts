import { NextResponse } from "next/server";
import { getSession, saveSession } from "../../../store";

export async function POST(
  req: Request,
  ctx: { params: Promise<{ id: string }> }
) {
  const { id } = await ctx.params;

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }

  const session = getSession(id);
  if (!session) {
    return NextResponse.json({ error: "unknown session" }, { status: 404 });
  }

  const obj =
    typeof body === "object" && body !== null
      ? (body as Record<string, unknown>)
      : {};
  const target = obj.target;
  const condition = obj.condition;
  const duration_rounds = obj.duration_rounds;

  if (
    typeof target !== "string" ||
    typeof condition !== "string" ||
    typeof duration_rounds !== "number" ||
    !Number.isInteger(duration_rounds) ||
    duration_rounds <= 0
  ) {
    return NextResponse.json({ error: "invalid request" }, { status: 400 });
  }

  const combatant = session.order.find((c) => c.name === target);
  if (!combatant) {
    return NextResponse.json({ error: "unknown target" }, { status: 400 });
  }

  combatant.conditions.push({ condition, remaining_rounds: duration_rounds });
  combatant.hadCondition = true;

  saveSession(session);

  return NextResponse.json({
    target: combatant.name,
    conditions: combatant.conditions.map((x) => ({ ...x })),
  });
}
