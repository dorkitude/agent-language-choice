import { badRequest, json, readObject } from "../../../../../lib/http";
import { hitDiceRecovered } from "../../../../../lib/phb";
import { asCount, asIntegerInRange } from "../../../../../lib/validation";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  const body = await readObject(request);
  if (!body) return badRequest("body must be a JSON object");

  const level = asIntegerInRange(body.level, 1, 20);
  if (level === undefined) {
    return badRequest("level must be an integer from 1 through 20");
  }

  const hpMax = asCount(body.hp_max, 1);
  if (hpMax === undefined) {
    return badRequest("hp_max must be a positive integer");
  }

  // Validated so a malformed body is still a 400, but a long rest always
  // restores full hit points, so the value itself does not affect the result.
  if (asCount(body.hp_current, 0) === undefined) {
    return badRequest("hp_current must be a non-negative integer");
  }

  const hitDiceSpent = asCount(body.hit_dice_spent ?? 0, 0);
  if (hitDiceSpent === undefined) {
    return badRequest("hit_dice_spent must be a non-negative integer");
  }

  const exhaustionLevel = asCount(body.exhaustion_level ?? 0, 0);
  if (exhaustionLevel === undefined) {
    return badRequest("exhaustion_level must be a non-negative integer");
  }

  return json({
    hp_current: hpMax,
    hit_dice_spent: Math.max(0, hitDiceSpent - hitDiceRecovered(level)),
    exhaustion_level: Math.max(0, exhaustionLevel - 1),
  });
}
