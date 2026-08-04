/** Character math: ability modifiers, proficiency bonus, and derived combat stats. */

import type { ApiResult, JsonValue } from '../types.ts';
import { isValidIntInRange } from '../validation.ts';

const PROFICIENCY_TABLE: [number, number][] = [
  [4, 2],
  [8, 3],
  [12, 4],
  [16, 5],
  [20, 6],
];

export function abilityModifierValue(score: number): number {
  return Math.floor((score - 10) / 2);
}

export function proficiencyBonusValue(level: number): number {
  for (const [maxLevel, bonus] of PROFICIENCY_TABLE) {
    if (level <= maxLevel) return bonus;
  }
  return PROFICIENCY_TABLE[PROFICIENCY_TABLE.length - 1][1];
}

export function abilityModifier(body: JsonValue): ApiResult {
  const score = body.score;
  if (!isValidIntInRange(score, 1, 30)) {
    return { status: 400, body: { error: 'score must be an integer from 1 through 30' } };
  }
  return { status: 200, body: { score, modifier: abilityModifierValue(score) } };
}

export function proficiencyBonus(body: JsonValue): ApiResult {
  const level = body.level;
  if (!isValidIntInRange(level, 1, 20)) {
    return { status: 400, body: { error: 'level must be an integer from 1 through 20' } };
  }
  return { status: 200, body: { level, proficiency_bonus: proficiencyBonusValue(level) } };
}

const ABILITY_KEYS = ['str', 'dex', 'con', 'int', 'wis', 'cha'] as const;

export function derivedStats(body: JsonValue): ApiResult {
  const level = body.level;
  if (!isValidIntInRange(level, 1, 20)) {
    return { status: 400, body: { error: 'level must be an integer from 1 through 20' } };
  }

  const abilities = body.abilities;
  if (typeof abilities !== 'object' || abilities === null || Array.isArray(abilities)) {
    return { status: 400, body: { error: 'abilities must be an object' } };
  }
  const abilitiesObj = abilities as JsonValue;

  const modifiers: Record<string, number> = {};
  for (const key of ABILITY_KEYS) {
    const score = abilitiesObj[key];
    if (!isValidIntInRange(score, 1, 30)) {
      return { status: 400, body: { error: `abilities.${key} must be an integer from 1 through 30` } };
    }
    modifiers[key] = abilityModifierValue(score);
  }

  const armor = body.armor;
  if (typeof armor !== 'object' || armor === null || Array.isArray(armor)) {
    return { status: 400, body: { error: 'armor must be an object' } };
  }
  const armorObj = armor as JsonValue;

  const base = armorObj.base;
  if (typeof base !== 'number' || !Number.isFinite(base)) {
    return { status: 400, body: { error: 'armor.base must be a number' } };
  }

  const shield = armorObj.shield;
  if (typeof shield !== 'boolean') {
    return { status: 400, body: { error: 'armor.shield must be a boolean' } };
  }

  const dexCap = armorObj.dex_cap;
  if (typeof dexCap !== 'number' || !Number.isFinite(dexCap)) {
    return { status: 400, body: { error: 'armor.dex_cap must be a number' } };
  }

  const proficiencyBonusVal = proficiencyBonusValue(level);
  const hpMax = level * (6 + modifiers.con);
  const shieldBonus = shield ? 2 : 0;
  const armorClass = base + Math.min(modifiers.dex, dexCap) + shieldBonus;

  return {
    status: 200,
    body: {
      level,
      proficiency_bonus: proficiencyBonusVal,
      hp_max: hpMax,
      armor_class: armorClass,
      modifiers,
    },
  };
}
