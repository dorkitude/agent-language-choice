import { NextResponse, type NextRequest } from "next/server";

export async function POST(request: NextRequest) {
  let body: { expression?: unknown };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const expression = body?.expression;
  if (typeof expression !== "string") {
    return NextResponse.json({ error: "Missing expression" }, { status: 400 });
  }

  const match = expression.match(/^(\d+)d(\d+)(?:([+-])(\d+))?$/);
  if (!match) {
    return NextResponse.json({ error: "Invalid expression" }, { status: 400 });
  }

  const dice_count = parseInt(match[1], 10);
  const sides = parseInt(match[2], 10);
  const modifier = match[3]
    ? (match[3] === "+" ? 1 : -1) * parseInt(match[4], 10)
    : 0;

  if (dice_count <= 0 || sides <= 0) {
    return NextResponse.json({ error: "Invalid expression" }, { status: 400 });
  }

  const min = dice_count + modifier;
  const max = dice_count * sides + modifier;
  const average = (min + max) / 2;

  return NextResponse.json({
    dice_count,
    sides,
    modifier,
    min,
    max,
    average,
  });
}
