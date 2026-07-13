const EXPRESSION_RE = /^(\d+)d(\d+)([+-]\d+)?$/;

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "invalid JSON" }, { status: 400 });
  }

  if (
    typeof body !== "object" ||
    body === null ||
    typeof (body as Record<string, unknown>).expression !== "string"
  ) {
    return Response.json({ error: "expression is required" }, { status: 400 });
  }

  const expression = (body as Record<string, unknown>).expression as string;
  const match = EXPRESSION_RE.exec(expression.trim());
  if (!match) {
    return Response.json({ error: "invalid expression" }, { status: 400 });
  }

  const diceCount = parseInt(match[1], 10);
  const sides = parseInt(match[2], 10);
  const modifier = match[3] ? parseInt(match[3], 10) : 0;

  if (diceCount <= 0 || sides <= 0) {
    return Response.json({ error: "invalid expression" }, { status: 400 });
  }

  const min = diceCount * 1 + modifier;
  const max = diceCount * sides + modifier;
  const average = (diceCount * (1 + sides)) / 2 + modifier;

  return Response.json({
    dice_count: diceCount,
    sides,
    modifier,
    min,
    max,
    average,
  });
}
