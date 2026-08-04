import { badRequest, json, readObject } from "../../../../lib/http";

export const dynamic = "force-dynamic";

const EXPRESSION = /^(\d+)d(\d+)(?:([+-])(\d+))?$/i;

export async function POST(request: Request): Promise<Response> {
  const body = await readObject(request);
  if (!body) return badRequest("body must be a JSON object");

  const expression = body.expression;
  if (typeof expression !== "string") return badRequest("expression must be a string");

  const match = EXPRESSION.exec(expression.trim());
  if (!match) return badRequest("invalid dice expression");

  const diceCount = Number.parseInt(match[1]!, 10);
  const sides = Number.parseInt(match[2]!, 10);
  const magnitude = match[4] === undefined ? 0 : Number.parseInt(match[4], 10);
  const modifier = match[3] === "-" ? -magnitude : magnitude;

  if (!Number.isSafeInteger(diceCount) || !Number.isSafeInteger(sides)) {
    return badRequest("invalid dice expression");
  }
  if (diceCount <= 0 || sides <= 0) return badRequest("count and sides must be positive");

  return json({
    dice_count: diceCount,
    sides,
    modifier,
    min: diceCount + modifier,
    max: diceCount * sides + modifier,
    average: (diceCount * (sides + 1)) / 2 + modifier,
  });
}
