import { NextResponse } from "next/server";

const EXPR_RE = /^(\d+)d(\d+)(?:([+-])(\d+))?$/;

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON" }, { status: 400 });
  }

  const expression = (body as { expression?: unknown })?.expression;
  if (typeof expression !== "string") {
    return NextResponse.json({ error: "expression is required" }, { status: 400 });
  }

  const match = EXPR_RE.exec(expression.trim());
  if (!match) {
    return NextResponse.json({ error: "invalid expression" }, { status: 400 });
  }

  const diceCount = parseInt(match[1], 10);
  const sides = parseInt(match[2], 10);
  const sign = match[3] === "-" ? -1 : 1;
  const modifier = match[4] ? sign * parseInt(match[4], 10) : 0;

  if (diceCount <= 0 || sides <= 0) {
    return NextResponse.json({ error: "count and sides must be positive" }, { status: 400 });
  }

  const min = diceCount * 1 + modifier;
  const max = diceCount * sides + modifier;
  const average = (diceCount * (1 + sides)) / 2 + modifier;

  return NextResponse.json({
    dice_count: diceCount,
    sides,
    modifier,
    min,
    max,
    average,
  });
}
