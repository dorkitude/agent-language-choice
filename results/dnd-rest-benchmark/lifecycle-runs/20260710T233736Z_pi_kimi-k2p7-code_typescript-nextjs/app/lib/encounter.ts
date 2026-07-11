export const CR_XP: Record<string, number> = {
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

export const LEVEL_3_THRESHOLDS = {
  easy: 75,
  medium: 150,
  hard: 225,
  deadly: 400,
};

export function multiplierForCount(count: number): number {
  if (count === 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
  return 4;
}

export interface EncounterResult {
  base_xp: number;
  monster_count: number;
  multiplier: number;
  adjusted_xp: number;
  difficulty: string;
  thresholds: {
    easy: number;
    medium: number;
    hard: number;
    deadly: number;
  };
}

export function calculateEncounter(
  party: Array<{ level: number }>,
  monsters: Array<{ cr: string; count: number }>
): EncounterResult {
  const baseXp = monsters.reduce((sum, m) => {
    return sum + (CR_XP[m.cr] ?? 0) * (m.count ?? 0);
  }, 0);

  const monsterCount = monsters.reduce((sum, m) => sum + (m.count ?? 0), 0);
  const multiplier = multiplierForCount(monsterCount);
  const adjustedXp = baseXp * multiplier;

  const thresholds = {
    easy: LEVEL_3_THRESHOLDS.easy * party.length,
    medium: LEVEL_3_THRESHOLDS.medium * party.length,
    hard: LEVEL_3_THRESHOLDS.hard * party.length,
    deadly: LEVEL_3_THRESHOLDS.deadly * party.length,
  };

  let difficulty: string;
  if (adjustedXp >= thresholds.deadly) difficulty = "deadly";
  else if (adjustedXp >= thresholds.hard) difficulty = "hard";
  else if (adjustedXp >= thresholds.medium) difficulty = "medium";
  else if (adjustedXp >= thresholds.easy) difficulty = "easy";
  else difficulty = "trivial";

  return {
    base_xp: baseXp,
    monster_count: monsterCount,
    multiplier,
    adjusted_xp: adjustedXp,
    difficulty,
    thresholds,
  };
}
