import { ABILITIES, abilityModifier, proficiencyBonus } from "../../../../lib/characters";
import { badRequest, json, readObject } from "../../../../lib/http";
import {
  asInteger,
  asIntegerInRange,
  isObject,
} from "../../../../lib/validation";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  const body = await readObject(request);
  if (!body) return badRequest("body must be a JSON object");

  const level = asIntegerInRange(body.level, 1, 20);
  if (level === undefined) {
    return badRequest("level must be an integer from 1 through 20");
  }

  // All six abilities are required; a missing one is as invalid as a bad one.
  if (!isObject(body.abilities)) {
    return badRequest("abilities must be a JSON object");
  }
  const abilities = body.abilities;

  const modifiers: Record<string, number> = {};
  for (const key of ABILITIES) {
    const score = asIntegerInRange(abilities[key], 1, 30);
    if (score === undefined) {
      return badRequest(`abilities.${key} must be an integer from 1 through 30`);
    }
    modifiers[key] = abilityModifier(score);
  }

  // `armor` is optional and so is every field inside it: an absent object is
  // unarmored (AC 10, no dex cap, no shield).
  const armor = body.armor === undefined ? {} : body.armor;
  if (!isObject(armor)) return badRequest("armor must be a JSON object");

  const base = armor.base === undefined ? 10 : asInteger(armor.base);
  if (base === undefined) return badRequest("armor.base must be an integer");

  const dexCapRaw = armor.dex_cap;
  let dexCap = Number.POSITIVE_INFINITY;
  if (dexCapRaw !== undefined && dexCapRaw !== null) {
    const parsed = asInteger(dexCapRaw);
    if (parsed === undefined) return badRequest("armor.dex_cap must be an integer");
    dexCap = parsed;
  }

  const shieldRaw = armor.shield;
  if (shieldRaw !== undefined && typeof shieldRaw !== "boolean") {
    return badRequest("armor.shield must be a boolean");
  }
  const shieldBonus = shieldRaw === true ? 2 : 0;

  const hpMax = level * (6 + modifiers.con);
  const armorClass = base + Math.min(modifiers.dex, dexCap) + shieldBonus;

  return json({
    level,
    proficiency_bonus: proficiencyBonus(level),
    hp_max: hpMax,
    armor_class: armorClass,
    modifiers,
  });
}
