export function isInt(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}

export function abilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

export function proficiencyBonus(level: number): number {
  return 2 + Math.floor((level - 1) / 4);
}
