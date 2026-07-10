import { abilityModifier, isInt, proficiencyBonus } from "../_lib.js";

const ABILITY_KEYS = ["str", "dex", "con", "int", "wis", "cha"] as const;

function badRequest(message: string) {
  return Response.json({ error: message }, { status: 400 });
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return badRequest("invalid JSON body");
  }

  if (typeof body !== "object" || body === null) {
    return badRequest("body must be an object");
  }

  const { level, abilities, armor } = body as {
    level?: unknown;
    abilities?: unknown;
    armor?: unknown;
  };

  if (!isInt(level) || level < 1 || level > 20) {
    return badRequest("level must be an integer from 1 through 20");
  }

  if (typeof abilities !== "object" || abilities === null) {
    return badRequest("abilities must be an object");
  }

  const modifiers: Record<string, number> = {};
  for (const key of ABILITY_KEYS) {
    const score = (abilities as Record<string, unknown>)[key];
    if (!isInt(score) || score < 1 || score > 30) {
      return badRequest(`abilities.${key} must be an integer from 1 through 30`);
    }
    modifiers[key] = abilityModifier(score);
  }

  if (typeof armor !== "object" || armor === null) {
    return badRequest("armor must be an object");
  }

  const { base, shield, dex_cap } = armor as {
    base?: unknown;
    shield?: unknown;
    dex_cap?: unknown;
  };

  if (typeof base !== "number") {
    return badRequest("armor.base must be a number");
  }
  if (typeof shield !== "boolean") {
    return badRequest("armor.shield must be a boolean");
  }
  if (typeof dex_cap !== "number") {
    return badRequest("armor.dex_cap must be a number");
  }

  const proficiency_bonus = proficiencyBonus(level);
  const hp_max = level * (6 + modifiers.con);
  const shield_bonus = shield ? 2 : 0;
  const armor_class = base + Math.min(modifiers.dex, dex_cap) + shield_bonus;

  return Response.json({
    level,
    proficiency_bonus,
    hp_max,
    armor_class,
    modifiers,
  });
}
