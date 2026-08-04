import { NextResponse } from "next/server";
import { badRequest, parseJsonBody } from "../../../../lib/http.js";

export async function POST(req: Request) {
  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  const level = Number(b.level);
  const hpMax = Number(b.hp_max);
  let hitDiceSpent = Number(b.hit_dice_spent);
  let exhaustionLevel = Number(b.exhaustion_level);

  if (
    !Number.isFinite(level) ||
    !Number.isFinite(hpMax) ||
    !Number.isFinite(hitDiceSpent) ||
    !Number.isFinite(exhaustionLevel)
  ) {
    return badRequest();
  }

  const recovered = Math.max(1, Math.floor(level / 2));
  hitDiceSpent = Math.max(0, hitDiceSpent - recovered);
  exhaustionLevel = Math.max(0, exhaustionLevel - 1);

  return NextResponse.json({
    hp_current: hpMax,
    hit_dice_spent: hitDiceSpent,
    exhaustion_level: exhaustionLevel,
  });
}
