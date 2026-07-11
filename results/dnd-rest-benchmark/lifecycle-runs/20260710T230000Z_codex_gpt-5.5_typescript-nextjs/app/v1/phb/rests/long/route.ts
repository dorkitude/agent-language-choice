import { badRequest, isRecord, json, readJson } from "../../../../api.js";
import { isIntegerInRange } from "../../../characters/rules.js";

export async function POST(request: Request) {
  const body = await readJson(request);
  if (
    !isRecord(body) ||
    !isIntegerInRange(body.level, 1, 20) ||
    !isIntegerInRange(body.hp_current, 0, Number.MAX_SAFE_INTEGER) ||
    !isIntegerInRange(body.hp_max, 1, Number.MAX_SAFE_INTEGER) ||
    !isIntegerInRange(body.hit_dice_spent, 0, Number.MAX_SAFE_INTEGER) ||
    !isIntegerInRange(body.exhaustion_level, 0, 6) ||
    body.hp_current > body.hp_max
  ) {
    return badRequest();
  }

  const hitDiceRestored = Math.max(1, Math.floor(body.level / 2));

  return json({
    hp_current: body.hp_max,
    hit_dice_spent: Math.max(0, body.hit_dice_spent - hitDiceRestored),
    exhaustion_level: Math.max(0, body.exhaustion_level - 1),
  });
}
