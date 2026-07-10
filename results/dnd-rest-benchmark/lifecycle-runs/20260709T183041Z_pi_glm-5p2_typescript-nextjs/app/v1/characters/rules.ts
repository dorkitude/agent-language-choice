// Shared D&D 5e character rules used by the character endpoints.

export const ABILITY_SCORE_MIN = 1;
export const ABILITY_SCORE_MAX = 30;
export const LEVEL_MIN = 1;
export const LEVEL_MAX = 20;

export const ABILITIES = ['str', 'dex', 'con', 'int', 'wis', 'cha'] as const;

export function isInt(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value);
}

// modifier = floor((score - 10) / 2); floors negative halves correctly.
export function abilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

// proficiency bonus: levels 1-4 -> 2, 5-8 -> 3, 9-12 -> 4, 13-16 -> 5, 17-20 -> 6.
export function proficiencyBonus(level: number): number {
  return 2 + Math.floor((level - 1) / 4);
}

export function isValidScore(value: unknown): value is number {
  return isInt(value) && value >= ABILITY_SCORE_MIN && value <= ABILITY_SCORE_MAX;
}

export function isValidLevel(value: unknown): value is number {
  return isInt(value) && value >= LEVEL_MIN && value <= LEVEL_MAX;
}
