import { NextResponse } from "next/server";
import { badRequest, isRecord, jsonBody } from "../../../lib/http";

const EXPRESSION = /^(\d+)d(\d+)(?:([+-])(\d+))?$/;

export async function POST(request: Request) {
  const body = await jsonBody(request);
  if (!isRecord(body) || typeof body.expression !== "string") {
    return badRequest();
  }

  const match = EXPRESSION.exec(body.expression);
  if (!match) return badRequest("Invalid dice expression");

  const diceCount = Number(match[1]);
  const sides = Number(match[2]);
  const modifierValue = Number(match[4] ?? "0");
  if (!Number.isSafeInteger(diceCount) || !Number.isSafeInteger(sides) ||
      !Number.isSafeInteger(modifierValue) || diceCount <= 0 || sides <= 0) {
    return badRequest("Invalid dice expression");
  }
  const modifier = match[3] === "-" ? -modifierValue : modifierValue;
  const min = diceCount + modifier;
  const max = diceCount * sides + modifier;

  return NextResponse.json({
    dice_count: diceCount,
    sides,
    modifier,
    min,
    max,
    average: (min + max) / 2,
  });
}
