import {
  ABILITIES,
  abilityModifier,
  proficiencyBonus,
  validateArmor,
  validateLevel,
  validateScore,
  type Ability,
} from "../../../lib/dnd.js";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const level = validateLevel(body.level);

    const rawAbilities = body.abilities;
    if (typeof rawAbilities !== "object" || rawAbilities === null) {
      throw new Error("abilities must be an object");
    }
    const abilities = rawAbilities as Record<string, unknown>;
    const modifiers: Record<Ability, number> = {
      str: 0,
      dex: 0,
      con: 0,
      int: 0,
      wis: 0,
      cha: 0,
    };
    for (const ability of ABILITIES) {
      const score = validateScore(abilities[ability]);
      modifiers[ability] = abilityModifier(score);
    }

    const armor = validateArmor(body.armor);
    const shieldBonus = armor.shield ? 2 : 0;
    const armorClass =
      armor.base + Math.min(modifiers.dex, armor.dex_cap) + shieldBonus;
    const hpMax = level * (6 + modifiers.con);

    return Response.json({
      level,
      proficiency_bonus: proficiencyBonus(level),
      hp_max: hpMax,
      armor_class: armorClass,
      modifiers,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "invalid request";
    return Response.json({ error: message }, { status: 400 });
  }
}
