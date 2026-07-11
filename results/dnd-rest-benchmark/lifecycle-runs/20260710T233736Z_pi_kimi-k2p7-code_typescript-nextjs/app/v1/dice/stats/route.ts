const DICE_RE = /^(\d+)d(\d+)(?:([+-])(\d+))?$/;

export async function POST(request: Request) {
  const body = await request.json();
  const expression = typeof body?.expression === "string" ? body.expression : "";
  const match = expression.replace(/\s+/g, "").match(DICE_RE);
  if (!match) {
    return Response.json({ error: "invalid expression" }, { status: 400 });
  }

  const diceCount = parseInt(match[1], 10);
  const sides = parseInt(match[2], 10);
  const modifierSign = match[3] ?? "+";
  const modifierValue = match[4] ? parseInt(match[4], 10) : 0;
  const modifier = modifierSign === "-" ? -modifierValue : modifierValue;

  if (diceCount <= 0 || sides <= 0) {
    return Response.json({ error: "invalid expression" }, { status: 400 });
  }

  const min = diceCount + modifier;
  const max = diceCount * sides + modifier;
  const average = (diceCount * (sides + 1)) / 2 + modifier;

  return Response.json({
    dice_count: diceCount,
    sides,
    modifier,
    min,
    max,
    average,
  });
}
