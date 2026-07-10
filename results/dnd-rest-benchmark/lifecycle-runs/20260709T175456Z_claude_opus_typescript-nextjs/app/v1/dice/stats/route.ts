import { NextResponse } from "next/server";

const DICE_RE = /^(\d+)d(\d+)([+-]\d+)?$/;

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }

  const expression = (body as { expression?: unknown } | null)?.expression;
  if (typeof expression !== "string") {
    return NextResponse.json({ error: "invalid expression" }, { status: 400 });
  }

  const match = DICE_RE.exec(expression);
  if (!match) {
    return NextResponse.json({ error: "invalid expression" }, { status: 400 });
  }

  const diceCount = Number.parseInt(match[1], 10);
  const sides = Number.parseInt(match[2], 10);
  const modifier = match[3] ? Number.parseInt(match[3], 10) : 0;

  if (diceCount <= 0 || sides <= 0) {
    return NextResponse.json({ error: "invalid expression" }, { status: 400 });
  }

  const min = diceCount * 1 + modifier;
  const max = diceCount * sides + modifier;
  const average = (min + max) / 2;

  return NextResponse.json({
    dice_count: diceCount,
    sides,
    modifier,
    min,
    max,
    average,
  });
}
