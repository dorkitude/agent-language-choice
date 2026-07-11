import { isRecord } from "../../api.js";

export const ABILITY_KEYS = ["str", "dex", "con", "int", "wis", "cha"] as const;

export type AbilityKey = (typeof ABILITY_KEYS)[number];

export type AbilityScores = Record<AbilityKey, number>;

export function isIntegerInRange(value: unknown, min: number, max: number): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= min && value <= max;
}

export function abilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

export function proficiencyBonus(level: number): number {
  return 2 + Math.floor((level - 1) / 4);
}

export function parseAbilityScores(value: unknown): AbilityScores | undefined {
  if (!isRecord(value)) {
    return undefined;
  }

  const scores: Partial<AbilityScores> = {};
  for (const key of ABILITY_KEYS) {
    const score = value[key];
    if (!isIntegerInRange(score, 1, 30)) {
      return undefined;
    }
    scores[key] = score;
  }

  return scores as AbilityScores;
}
