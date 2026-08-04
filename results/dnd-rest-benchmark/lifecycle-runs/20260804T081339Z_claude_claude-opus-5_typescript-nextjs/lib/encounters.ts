/**
 * Encounter XP math shared by the core `/v1/encounters/adjusted-xp` endpoint and
 * the DM-facing encounter builder, so both report identical numbers.
 */

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

/** Easy / medium / hard / deadly XP thresholds per character level. */
export const THRESHOLDS: Record<number, [number, number, number, number]> = {
  1: [25, 50, 75, 100],
  2: [50, 100, 150, 200],
  3: [75, 150, 225, 400],
  4: [125, 250, 375, 500],
  5: [250, 500, 750, 1100],
  6: [300, 600, 900, 1400],
  7: [350, 750, 1100, 1700],
  8: [450, 900, 1400, 2100],
  9: [550, 1100, 1600, 2400],
  10: [600, 1200, 1900, 2800],
  11: [800, 1600, 2400, 3600],
  12: [1000, 2000, 3000, 4500],
  13: [1100, 2200, 3400, 5100],
  14: [1250, 2500, 3800, 5700],
  15: [1400, 2800, 4300, 6400],
  16: [1600, 3200, 4800, 7200],
  17: [2000, 3900, 5900, 8800],
  18: [2100, 4200, 6300, 9500],
  19: [2400, 4900, 7300, 10900],
  20: [2800, 5700, 8500, 12700],
};

export type Thresholds = {
  easy: number;
  medium: number;
  hard: number;
  deadly: number;
};

export function emptyThresholds(): Thresholds {
  return { easy: 0, medium: 0, hard: 0, deadly: 0 };
}

/**
 * Fold one more party member into a running total: a party's thresholds are
 * the per-character thresholds added together, so a bigger party needs a
 * bigger encounter to reach the same difficulty band. Returns false, leaving
 * `thresholds` untouched, when the level is outside the 1-20 table.
 *
 * This is incremental rather than whole-party so callers can report a bad
 * level at the point they read it, interleaved with their other field checks.
 */
export function addLevelThresholds(thresholds: Thresholds, level: number): boolean {
  const row = THRESHOLDS[level];
  if (!row) return false;
  thresholds.easy += row[0];
  thresholds.medium += row[1];
  thresholds.hard += row[2];
  thresholds.deadly += row[3];
  return true;
}

/** Whole-party form; reports the first level that has no threshold row. */
export function sumThresholds(
  levels: number[],
): { thresholds: Thresholds } | { unsupportedLevel: number } {
  const thresholds = emptyThresholds();
  for (const level of levels) {
    if (!addLevelThresholds(thresholds, level)) return { unsupportedLevel: level };
  }
  return { thresholds };
}

/** Encounter multiplier: more monsters hit harder than their raw XP suggests. */
export function multiplierFor(monsterCount: number): number {
  if (monsterCount <= 1) return 1;
  if (monsterCount === 2) return 1.5;
  if (monsterCount <= 6) return 2;
  if (monsterCount <= 10) return 2.5;
  if (monsterCount <= 14) return 3;
  return 4;
}

/** Normalize a challenge rating to its table key, tolerating numeric input. */
export function crKey(raw: unknown): string | undefined {
  if (typeof raw === "string") {
    const key = raw.trim();
    return key in CR_XP ? key : undefined;
  }
  if (typeof raw === "number" && Number.isFinite(raw)) {
    if (Number.isInteger(raw)) return String(raw) in CR_XP ? String(raw) : undefined;
    if (raw === 0.125) return "1/8";
    if (raw === 0.25) return "1/4";
    if (raw === 0.5) return "1/2";
  }
  return undefined;
}

/** Highest band the adjusted XP reaches; below the easy threshold it is trivial. */
export function difficultyFor(adjustedXp: number, thresholds: Thresholds): string {
  if (adjustedXp >= thresholds.deadly) return "deadly";
  if (adjustedXp >= thresholds.hard) return "hard";
  if (adjustedXp >= thresholds.medium) return "medium";
  if (adjustedXp >= thresholds.easy) return "easy";
  return "trivial";
}
