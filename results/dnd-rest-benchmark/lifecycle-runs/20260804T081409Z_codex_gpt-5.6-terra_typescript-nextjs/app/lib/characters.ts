export const ABILITY_NAMES = ["str", "dex", "con", "int", "wis", "cha"] as const;

export type AbilityName = (typeof ABILITY_NAMES)[number];

export function isAbilityScore(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 1 && value <= 30;
}

export function isCharacterLevel(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 1 && value <= 20;
}

export function abilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

export function proficiencyBonus(level: number): number {
  return Math.floor((level - 1) / 4) + 2;
}
