// Rules-as-data: D&D 5e encounter-building math shared by the /v1/encounters
// and /v1/dm/encounter-builder routes.
//
// LEVEL_THRESHOLDS and CR_XP intentionally only cover the small slice of the
// rules (party level 3, monster CRs up to 5) that this API supports; a level
// or CR outside that range is reported to the caller as "unsupported"
// rather than guessed at.

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

export const LEVEL_THRESHOLDS: Record<number, { easy: number; medium: number; hard: number; deadly: number }> = {
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

export function abilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

export function proficiencyBonus(level: number): number {
  if (level <= 4) return 2;
  if (level <= 8) return 3;
  if (level <= 12) return 4;
  if (level <= 16) return 5;
  return 6;
}

// Deterministic initiative ordering shared by /v1/initiative/order and
// combat-session creation: highest score first, dex breaks ties, and name
// (alphabetical) breaks any remaining tie so the order is fully stable.
export function compareInitiative(a: { score: number; dex: number; name: string }, b: { score: number; dex: number; name: string }): number {
  if (b.score !== a.score) return b.score - a.score;
  if (b.dex !== a.dex) return b.dex - a.dex;
  return a.name.localeCompare(b.name);
}

export interface DifficultyThresholds {
  easy: number;
  medium: number;
  hard: number;
  deadly: number;
}

export interface EncounterDifficulty {
  multiplier: number;
  adjustedXp: number;
  difficulty: "trivial" | "easy" | "medium" | "hard" | "deadly";
  thresholds: DifficultyThresholds;
}

export type EncounterDifficultyResult =
  | { ok: true; value: EncounterDifficulty }
  | { ok: false; error: "unsupported party level" };

/**
 * Applies the monster-count multiplier to `baseXp` and compares the result
 * against the summed per-member thresholds for `party` to derive a
 * difficulty tier. Shared by the adjusted-XP and encounter-builder
 * endpoints, which differ only in how they arrive at `baseXp`/`monsterCount`.
 */
export function computeEncounterDifficulty(
  baseXp: number,
  monsterCount: number,
  party: { level: number }[],
): EncounterDifficultyResult {
  const multiplier = multiplierFor(monsterCount);
  const adjustedXp = baseXp * multiplier;

  const thresholds: DifficultyThresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const member of party) {
    const levelThresholds = LEVEL_THRESHOLDS[member.level];
    if (!levelThresholds) {
      return { ok: false, error: "unsupported party level" };
    }
    thresholds.easy += levelThresholds.easy;
    thresholds.medium += levelThresholds.medium;
    thresholds.hard += levelThresholds.hard;
    thresholds.deadly += levelThresholds.deadly;
  }

  let difficulty: EncounterDifficulty["difficulty"] = "trivial";
  if (adjustedXp >= thresholds.deadly) difficulty = "deadly";
  else if (adjustedXp >= thresholds.hard) difficulty = "hard";
  else if (adjustedXp >= thresholds.medium) difficulty = "medium";
  else if (adjustedXp >= thresholds.easy) difficulty = "easy";

  return { ok: true, value: { multiplier, adjustedXp, difficulty, thresholds } };
}
