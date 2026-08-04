export const ABILITIES = ["str", "dex", "con", "int", "wis", "cha"] as const;

export type Ability = (typeof ABILITIES)[number];

/** floor((score - 10) / 2), flooring negative halves toward -inf. */
export function abilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

export function proficiencyBonus(level: number): number {
  return 2 + Math.floor((level - 1) / 4);
}
