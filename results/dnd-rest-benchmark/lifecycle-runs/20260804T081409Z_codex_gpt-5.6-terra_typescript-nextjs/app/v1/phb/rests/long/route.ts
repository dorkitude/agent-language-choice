import { NextResponse } from "next/server";
import { badRequest, isInteger, isRecord, jsonBody } from "../../../../lib/http";

export async function POST(request: Request) {
  const body = await jsonBody(request);
  if (
    !isRecord(body) ||
    !isInteger(body.level) || body.level < 1 ||
    !isInteger(body.hp_current) || body.hp_current < 0 ||
    !isInteger(body.hp_max) || body.hp_max < 0 ||
    !isInteger(body.hit_dice_spent) || body.hit_dice_spent < 0 ||
    !isInteger(body.exhaustion_level) || body.exhaustion_level < 0
  ) {
    return badRequest();
  }

  const restoredHitDice = Math.max(1, Math.floor(body.level / 2));
  return NextResponse.json({
    hp_current: body.hp_max,
    hit_dice_spent: Math.max(0, body.hit_dice_spent - restoredHitDice),
    exhaustion_level: Math.max(0, body.exhaustion_level - 1),
  });
}
