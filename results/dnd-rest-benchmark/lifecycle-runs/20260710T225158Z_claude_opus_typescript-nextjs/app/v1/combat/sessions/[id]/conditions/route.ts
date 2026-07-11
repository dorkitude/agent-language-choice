import { NextResponse } from "next/server";
import { store, type Condition } from "../../../../../lib/combat";

export async function POST(
  req: Request,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON" }, { status: 400 });
  }

  const s = store();
  const session = s.sessions.get(id);
  if (!session) {
    return NextResponse.json({ error: "unknown session" }, { status: 404 });
  }

  const obj =
    body && typeof body === "object" ? (body as Record<string, unknown>) : {};
  const target = obj.target;
  const condition = obj.condition;
  const duration = obj.duration_rounds;

  if (typeof target !== "string" || typeof condition !== "string") {
    return NextResponse.json({ error: "invalid request" }, { status: 400 });
  }
  if (
    typeof duration !== "number" ||
    !Number.isInteger(duration) ||
    duration <= 0
  ) {
    return NextResponse.json({ error: "invalid duration" }, { status: 400 });
  }
  if (!session.order.some((c) => c.name === target)) {
    return NextResponse.json({ error: "unknown target" }, { status: 400 });
  }

  const list = session.conditions.get(target) ?? [];
  list.push({ condition, remaining_rounds: duration });
  session.conditions.set(target, list);

  return NextResponse.json({
    target,
    conditions: list.map((c: Condition) => ({ ...c })),
  });
}
