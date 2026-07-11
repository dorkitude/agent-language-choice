export const ABILITIES = ["str", "dex", "con", "int", "wis", "cha"] as const;
export type Ability = (typeof ABILITIES)[number];

export function abilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

export function proficiencyBonus(level: number): number {
  return 2 + Math.floor((level - 1) / 4);
}

export function validateScore(value: unknown): number {
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value < 1 ||
    value > 30
  ) {
    throw new Error("score must be an integer from 1 to 30");
  }
  return value;
}

export function validateLevel(value: unknown): number {
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value < 1 ||
    value > 20
  ) {
    throw new Error("level must be an integer from 1 to 20");
  }
  return value;
}

export interface Armor {
  base: number;
  shield: boolean;
  dex_cap: number;
}

export function validateArmor(value: unknown): Armor {
  if (typeof value !== "object" || value === null) {
    throw new Error("armor must be an object");
  }
  const armor = value as Record<string, unknown>;
  if (typeof armor.base !== "number" || !Number.isInteger(armor.base)) {
    throw new Error("armor.base must be an integer");
  }
  if (typeof armor.shield !== "boolean") {
    throw new Error("armor.shield must be a boolean");
  }
  if (typeof armor.dex_cap !== "number" || !Number.isInteger(armor.dex_cap)) {
    throw new Error("armor.dex_cap must be an integer");
  }
  return { base: armor.base, shield: armor.shield, dex_cap: armor.dex_cap };
}
