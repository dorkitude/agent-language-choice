import { getSession } from "../../../store.js";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const session = getSession(id);
  if (!session) {
    return Response.json({ error: "session not found" }, { status: 404 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "invalid JSON" }, { status: 400 });
  }

  if (typeof body !== "object" || body === null) {
    return Response.json({ error: "invalid request" }, { status: 400 });
  }

  const { target, condition, duration_rounds } = body as Record<string, unknown>;

  if (typeof target !== "string" || target.length === 0) {
    return Response.json({ error: "target is required" }, { status: 400 });
  }

  if (!session.order.some((entry) => entry.name === target)) {
    return Response.json({ error: "target is not a combatant in this session" }, { status: 400 });
  }

  if (typeof condition !== "string" || condition.length === 0) {
    return Response.json({ error: "condition is required" }, { status: 400 });
  }

  if (
    typeof duration_rounds !== "number" ||
    !Number.isInteger(duration_rounds) ||
    duration_rounds <= 0
  ) {
    return Response.json({ error: "duration_rounds must be a positive integer" }, { status: 400 });
  }

  const targetConditions = session.conditions[target] ?? [];
  targetConditions.push({ condition, remaining_rounds: duration_rounds });
  session.conditions[target] = targetConditions;

  return Response.json({
    target,
    conditions: targetConditions,
  });
}
