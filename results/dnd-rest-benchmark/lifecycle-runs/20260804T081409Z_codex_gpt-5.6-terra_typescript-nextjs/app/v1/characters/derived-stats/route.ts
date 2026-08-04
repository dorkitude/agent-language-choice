import { NextResponse } from "next/server";
import {
  ABILITY_NAMES,
  abilityModifier,
  isAbilityScore,
  isCharacterLevel,
  proficiencyBonus,
} from "../../../lib/characters";
import { badRequest, isInteger, isRecord, jsonBody } from "../../../lib/http";

export async function POST(request: Request) {
  const body = await jsonBody(request);
  if (!isRecord(body) || !isCharacterLevel(body.level) || !isRecord(body.abilities) || !isRecord(body.armor)) {
    return badRequest();
  }

  const abilities = body.abilities;
  const armor = body.armor;
  if (!isInteger(armor.base) || typeof armor.shield !== "boolean" || !isInteger(armor.dex_cap)) {
    return badRequest();
  }

  const modifiers: Record<string, number> = {};
  for (const ability of ABILITY_NAMES) {
    if (!isAbilityScore(abilities[ability])) return badRequest();
    modifiers[ability] = abilityModifier(abilities[ability]);
  }

  return NextResponse.json({
    level: body.level,
    proficiency_bonus: proficiencyBonus(body.level),
    hp_max: body.level * (6 + modifiers.con),
    armor_class: armor.base + Math.min(modifiers.dex, armor.dex_cap) + (armor.shield ? 2 : 0),
    modifiers,
  });
}
