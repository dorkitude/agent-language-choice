import { NextResponse } from "next/server";

function badRequest() {
  return NextResponse.json({ error: "invalid request" }, { status: 400 });
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

  if (typeof body !== "object" || body === null) {
    return badRequest();
  }

  const { roll, modifier, dc } = body as Record<string, unknown>;
  if (!isNumber(roll) || !isNumber(modifier) || !isNumber(dc)) {
    return badRequest();
  }

  const total = roll + modifier;
  const margin = total - dc;

  return NextResponse.json({
    total,
    success: total >= dc,
    margin,
  });
}
