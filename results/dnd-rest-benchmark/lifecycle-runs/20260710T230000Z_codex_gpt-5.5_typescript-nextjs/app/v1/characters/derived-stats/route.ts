import { badRequest, isRecord, json, readJson } from "../../../api.js";
import { ABILITY_KEYS, abilityModifier, isIntegerInRange, parseAbilityScores, proficiencyBonus } from "../rules.js";

export async function POST(request: Request) {
  const body = await readJson(request);
  if (!isRecord(body) || !isIntegerInRange(body.level, 1, 20)) {
    return badRequest();
  }

  const abilities = parseAbilityScores(body.abilities);
  if (abilities === undefined || !isRecord(body.armor)) {
    return badRequest();
  }

  const armor = body.armor;
  if (
    typeof armor.base !== "number" ||
    !Number.isSafeInteger(armor.base) ||
    typeof armor.shield !== "boolean" ||
    typeof armor.dex_cap !== "number" ||
    !Number.isSafeInteger(armor.dex_cap)
  ) {
    return badRequest();
  }

  const modifiers = Object.fromEntries(ABILITY_KEYS.map((key) => [key, abilityModifier(abilities[key])]));
  const conModifier = modifiers.con;
  const dexModifier = modifiers.dex;
  const shieldBonus = armor.shield ? 2 : 0;

  return json({
    level: body.level,
    proficiency_bonus: proficiencyBonus(body.level),
    hp_max: body.level * (6 + conModifier),
    armor_class: armor.base + Math.min(dexModifier, armor.dex_cap) + shieldBonus,
    modifiers,
  });
}
