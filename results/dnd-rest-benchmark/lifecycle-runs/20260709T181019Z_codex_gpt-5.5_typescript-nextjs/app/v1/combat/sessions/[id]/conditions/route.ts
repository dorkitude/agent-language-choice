import { NextResponse } from "next/server";
import { sessions } from "../../../state.js";

type RouteContext = {
  params: Promise<{ id: string }>;
};

function badRequest() {
  return NextResponse.json({ error: "invalid request" }, { status: 400 });
}

function notFound() {
  return NextResponse.json({ error: "not found" }, { status: 404 });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}

export async function POST(request: Request, context: RouteContext) {
  const { id } = await context.params;
  const session = sessions.get(id);
  if (session === undefined) {
    return notFound();
  }

  let body: unknown;

  try {
    body = await request.json();
  } catch {
    return badRequest();
  }

  if (!isRecord(body)) {
    return badRequest();
  }

  const { target, condition, duration_rounds: durationRounds } = body;
  if (
    typeof target !== "string" ||
    typeof condition !== "string" ||
    !isPositiveInteger(durationRounds) ||
    !session.conditions.has(target)
  ) {
    return badRequest();
  }

  const targetConditions = session.conditions.get(target);
  if (targetConditions === undefined) {
    return badRequest();
  }

  targetConditions.push({ condition, remaining_rounds: durationRounds });

  return NextResponse.json({
    target,
    conditions: targetConditions.map(({ condition: name, remaining_rounds }) => ({
      condition: name,
      remaining_rounds,
    })),
  });
}
