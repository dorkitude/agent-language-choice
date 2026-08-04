import { parseJsonBody } from "../../http.js";

export async function POST(request: Request) {
  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const expression = (body as { expression?: unknown })?.expression;
  if (typeof expression !== "string") {
    return Response.json({ error: "expression must be a string" }, { status: 400 });
  }

  const match = /^(\d+)d(\d+)(?:([+-])(\d+))?$/.exec(expression.trim());
  if (!match) {
    return Response.json({ error: "invalid dice expression" }, { status: 400 });
  }

  const diceCount = parseInt(match[1], 10);
  const sides = parseInt(match[2], 10);
  const sign = match[3];
  const modifierValue = match[4] ? parseInt(match[4], 10) : 0;
  const modifier = sign === "-" ? -modifierValue : modifierValue;

  if (diceCount <= 0 || sides <= 0) {
    return Response.json({ error: "count and sides must be positive" }, { status: 400 });
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
