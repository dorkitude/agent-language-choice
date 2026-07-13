import { abilityModifier } from "../ability-modifier/route";
import { proficiencyBonus } from "../proficiency/route";

const ABILITY_KEYS = ["str", "dex", "con", "int", "wis", "cha"] as const;

function isInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}

function isAbilityScore(value: unknown): value is number {
  return isInteger(value) && value >= 1 && value <= 30;
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "invalid JSON" }, { status: 400 });
  }

  if (typeof body !== "object" || body === null) {
    return Response.json({ error: "invalid request" }, { status: 400 });
  }

  const { level, abilities, armor } = body as Record<string, unknown>;

  if (!isInteger(level) || level < 1 || level > 20) {
    return Response.json({ error: "level must be an integer from 1 through 20" }, { status: 400 });
  }

  if (typeof abilities !== "object" || abilities === null) {
    return Response.json({ error: "abilities is required" }, { status: 400 });
  }
  const abilityScores = abilities as Record<string, unknown>;
  for (const key of ABILITY_KEYS) {
    if (!isAbilityScore(abilityScores[key])) {
      return Response.json({ error: `abilities.${key} must be an integer from 1 through 30` }, { status: 400 });
    }
  }

  if (typeof armor !== "object" || armor === null) {
    return Response.json({ error: "armor is required" }, { status: 400 });
  }
  const { base, shield, dex_cap: dexCap } = armor as Record<string, unknown>;
  if (!isInteger(base)) {
    return Response.json({ error: "armor.base must be an integer" }, { status: 400 });
  }
  if (typeof shield !== "boolean") {
    return Response.json({ error: "armor.shield must be a boolean" }, { status: 400 });
  }
  if (!isInteger(dexCap)) {
    return Response.json({ error: "armor.dex_cap must be an integer" }, { status: 400 });
  }

  const modifiers = Object.fromEntries(
    ABILITY_KEYS.map((key) => [key, abilityModifier(abilityScores[key] as number)])
  ) as Record<(typeof ABILITY_KEYS)[number], number>;

  const proficiency_bonus = proficiencyBonus(level);
  const hp_max = level * (6 + modifiers.con);
  const shieldBonus = shield ? 2 : 0;
  const armor_class = base + Math.min(modifiers.dex, dexCap) + shieldBonus;

  return Response.json({
    level,
    proficiency_bonus,
    hp_max,
    armor_class,
    modifiers,
  });
}
