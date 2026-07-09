import { NextResponse } from "next/server";

const DICE_RE = /^(\d+)d(\d+)([+-]\d+)?$/;

export async function POST(req: Request) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }

  const expression = (body as { expression?: unknown })?.expression;
  if (typeof expression !== "string") {
    return NextResponse.json({ error: "invalid expression" }, { status: 400 });
  }

  const m = DICE_RE.exec(expression.trim());
  if (!m) {
    return NextResponse.json({ error: "invalid expression" }, { status: 400 });
  }

  const dice_count = parseInt(m[1], 10);
  const sides = parseInt(m[2], 10);
  const modifier = m[3] ? parseInt(m[3], 10) : 0;

  if (dice_count <= 0 || sides <= 0) {
    return NextResponse.json({ error: "invalid expression" }, { status: 400 });
  }

  const min = dice_count * 1 + modifier;
  const max = dice_count * sides + modifier;
  const average = (min + max) / 2;

  return NextResponse.json({ dice_count, sides, modifier, min, max, average });
}
