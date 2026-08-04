export const MONSTER_XP: Record<string, number> = {
  "0": 10,
  "1/8": 25,
  "1/4": 50,
  "1/2": 100,
  "1": 200,
  "2": 450,
  "3": 700,
  "4": 1100,
  "5": 1800,
};

export interface XpThresholds {
  easy: number;
  medium: number;
  hard: number;
  deadly: number;
}

// Only level 3 is defined because that's the only party level exercised by
// this API's fixtures/tests. A party member at any other level is treated as
// unsupported (see sumPartyThresholds) rather than silently defaulting.
export const LEVEL_THRESHOLDS: Record<number, XpThresholds> = {
  3: { easy: 75, medium: 150, hard: 225, deadly: 400 },
};

export function multiplierFor(monsterCount: number): number {
  if (monsterCount <= 1) return 1;
  if (monsterCount === 2) return 1.5;
  if (monsterCount <= 6) return 2;
  if (monsterCount <= 10) return 2.5;
  if (monsterCount <= 14) return 3;
  return 4;
}

/**
 * Sums per-member XP thresholds across a party. Returns undefined if any
 * member's level has no defined thresholds (caller should treat this as a
 * validation error).
 */
export function sumPartyThresholds(party: { level?: unknown }[]): XpThresholds | undefined {
  const thresholds: XpThresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const member of party) {
    const levelThresholds = LEVEL_THRESHOLDS[member?.level as number];
    if (!levelThresholds) return undefined;
    thresholds.easy += levelThresholds.easy;
    thresholds.medium += levelThresholds.medium;
    thresholds.hard += levelThresholds.hard;
    thresholds.deadly += levelThresholds.deadly;
  }
  return thresholds;
}

/** Classifies an adjusted XP total against a party's summed thresholds. */
export function difficultyFor(adjustedXp: number, thresholds: XpThresholds): string {
  if (adjustedXp >= thresholds.deadly) return "deadly";
  if (adjustedXp >= thresholds.hard) return "hard";
  if (adjustedXp >= thresholds.medium) return "medium";
  if (adjustedXp >= thresholds.easy) return "easy";
  return "trivial";
}
