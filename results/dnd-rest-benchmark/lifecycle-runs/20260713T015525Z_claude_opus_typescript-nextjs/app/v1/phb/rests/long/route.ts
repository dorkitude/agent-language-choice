import { NextResponse } from "next/server";

export async function POST(req: Request) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }

  const obj =
    typeof body === "object" && body !== null
      ? (body as Record<string, unknown>)
      : {};
  const level = obj.level;
  const hpMax = obj.hp_max;
  const hitDiceSpent = obj.hit_dice_spent;
  const exhaustionLevel = obj.exhaustion_level;

  if (
    typeof level !== "number" ||
    !Number.isInteger(level) ||
    level < 1 ||
    typeof hpMax !== "number" ||
    typeof hitDiceSpent !== "number" ||
    !Number.isInteger(hitDiceSpent) ||
    hitDiceSpent < 0 ||
    typeof exhaustionLevel !== "number" ||
    !Number.isInteger(exhaustionLevel) ||
    exhaustionLevel < 0
  ) {
    return NextResponse.json({ error: "invalid request" }, { status: 400 });
  }

  const recovered = Math.max(1, Math.floor(level / 2));
  const newHitDiceSpent = Math.max(0, hitDiceSpent - recovered);
  const newExhaustion = Math.max(0, exhaustionLevel - 1);

  return NextResponse.json({
    hp_current: hpMax,
    hit_dice_spent: newHitDiceSpent,
    exhaustion_level: newExhaustion,
  });
}
