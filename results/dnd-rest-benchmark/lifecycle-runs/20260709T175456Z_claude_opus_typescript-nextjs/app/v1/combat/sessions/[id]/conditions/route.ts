import { NextResponse } from "next/server";
import { sessions } from "../../../store";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const session = sessions.get(id);
  if (!session) {
    return NextResponse.json({ error: "unknown session" }, { status: 404 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }

  const target = (body as { target?: unknown } | null)?.target;
  const condition = (body as { condition?: unknown } | null)?.condition;
  const durationRounds = (body as { duration_rounds?: unknown } | null)
    ?.duration_rounds;

  if (typeof target !== "string" || typeof condition !== "string") {
    return NextResponse.json({ error: "invalid input" }, { status: 400 });
  }
  if (
    typeof durationRounds !== "number" ||
    !Number.isInteger(durationRounds) ||
    durationRounds <= 0
  ) {
    return NextResponse.json({ error: "invalid duration" }, { status: 400 });
  }

  const combatant = session.order.find((c) => c.name === target);
  if (!combatant) {
    return NextResponse.json({ error: "unknown target" }, { status: 400 });
  }

  combatant.conditions.push({
    condition,
    remaining_rounds: durationRounds,
  });
  combatant.everHadConditions = true;

  return NextResponse.json({
    target: combatant.name,
    conditions: combatant.conditions.map((c) => ({
      condition: c.condition,
      remaining_rounds: c.remaining_rounds,
    })),
  });
}
