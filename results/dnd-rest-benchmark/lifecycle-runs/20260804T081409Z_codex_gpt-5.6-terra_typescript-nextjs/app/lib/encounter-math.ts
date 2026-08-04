export const XP_BY_CR: Record<string, number> = {
  "0": 10, "1/8": 25, "1/4": 50, "1/2": 100, "1": 200,
  "2": 450, "3": 700, "4": 1100, "5": 1800,
};

export const LEVEL_THREE = { easy: 75, medium: 150, hard: 225, deadly: 400 };

export function encounterMultiplier(count: number) {
  if (count === 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
  return 4;
}

export function encounterDifficulty(adjustedXp: number, thresholds: typeof LEVEL_THREE) {
  return adjustedXp >= thresholds.deadly ? "deadly" : adjustedXp >= thresholds.hard ? "hard" :
    adjustedXp >= thresholds.medium ? "medium" : adjustedXp >= thresholds.easy ? "easy" : "trivial";
}
