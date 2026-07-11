function validateInteger(value: unknown, name: string): number {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new Error(`${name} must be an integer`);
  }
  return value;
}

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const level = validateInteger(body.level, "level");
    if (level < 1 || level > 20) {
      throw new Error("level must be from 1 to 20");
    }
    const hpCurrent = validateInteger(body.hp_current, "hp_current");
    const hpMax = validateInteger(body.hp_max, "hp_max");
    const hitDiceSpent = validateInteger(body.hit_dice_spent, "hit_dice_spent");
    const exhaustionLevel = validateInteger(
      body.exhaustion_level,
      "exhaustion_level"
    );

    if (hpCurrent < 0 || hpMax < 1) {
      throw new Error("invalid HP values");
    }
    if (hitDiceSpent < 0) {
      throw new Error("hit_dice_spent must be non-negative");
    }
    if (exhaustionLevel < 0) {
      throw new Error("exhaustion_level must be non-negative");
    }

    const regain = Math.max(1, Math.floor(level / 2));
    return Response.json({
      hp_current: hpMax,
      hit_dice_spent: Math.max(0, hitDiceSpent - regain),
      exhaustion_level: Math.max(0, exhaustionLevel - 1),
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "invalid request";
    return Response.json({ error: message }, { status: 400 });
  }
}
