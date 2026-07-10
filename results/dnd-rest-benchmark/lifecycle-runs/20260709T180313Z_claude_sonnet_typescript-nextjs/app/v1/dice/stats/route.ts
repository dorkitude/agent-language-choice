function badRequest(message: string) {
  return Response.json({ error: message }, { status: 400 });
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return badRequest("invalid JSON body");
  }

  if (
    typeof body !== "object" ||
    body === null ||
    typeof (body as { expression?: unknown }).expression !== "string"
  ) {
    return badRequest("expression is required");
  }

  const expression = (body as { expression: string }).expression;
  const match = /^(\d+)d(\d+)([+-]\d+)?$/.exec(expression.trim());
  if (!match) {
    return badRequest("invalid dice expression");
  }

  const diceCount = parseInt(match[1], 10);
  const sides = parseInt(match[2], 10);
  const modifier = match[3] ? parseInt(match[3], 10) : 0;

  if (diceCount <= 0 || sides <= 0) {
    return badRequest("count and sides must be positive");
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
