const DICE_EXPRESSION = /^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$/;

type DiceRequest = {
  expression?: unknown;
};

function badRequest() {
  return Response.json({ error: "bad_request" }, { status: 400 });
}

export async function POST(request: Request) {
  let body: DiceRequest;

  try {
    body = await request.json();
  } catch {
    return badRequest();
  }

  if (typeof body.expression !== "string") {
    return badRequest();
  }

  const match = DICE_EXPRESSION.exec(body.expression);
  if (!match) {
    return badRequest();
  }

  const diceCount = Number(match[1]);
  const sides = Number(match[2]);
  const modifierValue = match[4] === undefined ? 0 : Number(match[4]);
  const modifier = match[3] === "-" ? -modifierValue : modifierValue;

  if (!Number.isSafeInteger(diceCount) || !Number.isSafeInteger(sides) || diceCount <= 0 || sides <= 0) {
    return badRequest();
  }

  return Response.json({
    dice_count: diceCount,
    sides,
    modifier,
    min: diceCount + modifier,
    max: diceCount * sides + modifier,
    average: diceCount * (sides + 1) / 2 + modifier,
  });
}
