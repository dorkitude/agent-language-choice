import { NextResponse } from "next/server";

const DICE_EXPRESSION = /^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$/;

function badRequest() {
  return NextResponse.json({ error: "invalid request" }, { status: 400 });
}

export async function POST(request: Request) {
  let body: unknown;

  try {
    body = await request.json();
  } catch {
    return badRequest();
  }

  if (
    typeof body !== "object" ||
    body === null ||
    !("expression" in body) ||
    typeof body.expression !== "string"
  ) {
    return badRequest();
  }

  const match = DICE_EXPRESSION.exec(body.expression);
  if (!match) {
    return badRequest();
  }

  const diceCount = Number(match[1]);
  const sides = Number(match[2]);
  const modifierAmount = match[4] === undefined ? 0 : Number(match[4]);
  const modifier = match[3] === "-" ? -modifierAmount : modifierAmount;

  if (
    !Number.isSafeInteger(diceCount) ||
    !Number.isSafeInteger(sides) ||
    !Number.isSafeInteger(modifierAmount) ||
    diceCount <= 0 ||
    sides <= 0
  ) {
    return badRequest();
  }

  const min = diceCount + modifier;
  const max = diceCount * sides + modifier;
  const average = diceCount * (sides + 1) / 2 + modifier;

  return NextResponse.json({
    dice_count: diceCount,
    sides,
    modifier,
    min,
    max,
    average,
  });
}
