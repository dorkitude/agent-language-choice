import { badRequest, isRecord, json, readJson } from "../../../api.js";

const DICE_EXPRESSION = /^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$/;

export async function POST(request: Request) {
  const body = await readJson(request);
  if (!isRecord(body) || typeof body.expression !== "string") {
    return badRequest();
  }

  const match = DICE_EXPRESSION.exec(body.expression);
  if (match === null) {
    return badRequest();
  }

  const diceCount = Number(match[1]);
  const sides = Number(match[2]);
  if (!Number.isSafeInteger(diceCount) || !Number.isSafeInteger(sides) || diceCount <= 0 || sides <= 0) {
    return badRequest();
  }

  const modifierValue = match[4] === undefined ? 0 : Number(match[4]);
  if (!Number.isSafeInteger(modifierValue)) {
    return badRequest();
  }

  const modifier = match[3] === "-" ? -modifierValue : modifierValue;

  return json({
    dice_count: diceCount,
    sides,
    modifier,
    min: diceCount + modifier,
    max: diceCount * sides + modifier,
    average: diceCount * ((sides + 1) / 2) + modifier,
  });
}
