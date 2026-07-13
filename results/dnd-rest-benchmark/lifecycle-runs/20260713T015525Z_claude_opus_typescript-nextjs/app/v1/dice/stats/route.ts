import { NextResponse } from "next/server";

const DICE_RE = /^(\d+)d(\d+)([+-]\d+)?$/;

export async function POST(req: Request) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }

  const expression =
    typeof body === "object" && body !== null
      ? (body as Record<string, unknown>).expression
      : undefined;

  if (typeof expression !== "string") {
    return NextResponse.json({ error: "invalid expression" }, { status: 400 });
  }

  const match = DICE_RE.exec(expression.trim());
  if (!match) {
    return NextResponse.json({ error: "invalid expression" }, { status: 400 });
  }

  const count = Number.parseInt(match[1], 10);
  const sides = Number.parseInt(match[2], 10);
  const modifier = match[3] ? Number.parseInt(match[3], 10) : 0;

  if (count <= 0 || sides <= 0) {
    return NextResponse.json({ error: "invalid expression" }, { status: 400 });
  }

  const min = count * 1 + modifier;
  const max = count * sides + modifier;
  const average = (min + max) / 2;

  return NextResponse.json({
    dice_count: count,
    sides,
    modifier,
    min,
    max,
    average,
  });
}
