import { abilityModifier, proficiencyBonus } from "../rules.js";
import { parseJsonBody } from "../../http.js";

const ABILITY_KEYS = ["str", "dex", "con", "int", "wis", "cha"] as const;
type AbilityKey = (typeof ABILITY_KEYS)[number];

export async function POST(request: Request) {
  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { level, abilities, armor } = (body ?? {}) as {
    level?: unknown;
    abilities?: unknown;
    armor?: unknown;
  };

  if (typeof level !== "number" || !Number.isInteger(level) || level < 1 || level > 20) {
    return Response.json({ error: "level must be an integer from 1 through 20" }, { status: 400 });
  }

  if (typeof abilities !== "object" || abilities === null || Array.isArray(abilities)) {
    return Response.json({ error: "abilities must be an object" }, { status: 400 });
  }

  const abilityScores = abilities as Record<string, unknown>;
  const modifiers: Record<AbilityKey, number> = {} as Record<AbilityKey, number>;
  for (const key of ABILITY_KEYS) {
    const score = abilityScores[key];
    if (typeof score !== "number" || !Number.isInteger(score) || score < 1 || score > 30) {
      return Response.json(
        { error: `abilities.${key} must be an integer from 1 through 30` },
        { status: 400 },
      );
    }
    modifiers[key] = abilityModifier(score);
  }

  if (typeof armor !== "object" || armor === null || Array.isArray(armor)) {
    return Response.json({ error: "armor must be an object" }, { status: 400 });
  }

  const { base, shield, dex_cap: dexCap } = armor as {
    base?: unknown;
    shield?: unknown;
    dex_cap?: unknown;
  };

  if (typeof base !== "number") {
    return Response.json({ error: "armor.base must be a number" }, { status: 400 });
  }
  if (typeof shield !== "boolean") {
    return Response.json({ error: "armor.shield must be a boolean" }, { status: 400 });
  }
  if (typeof dexCap !== "number") {
    return Response.json({ error: "armor.dex_cap must be a number" }, { status: 400 });
  }

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
