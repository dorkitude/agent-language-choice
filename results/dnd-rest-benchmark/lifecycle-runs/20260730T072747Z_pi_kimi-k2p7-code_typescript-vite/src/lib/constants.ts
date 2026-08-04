// Deterministic reference data used by the D&D rules engine.

// Challenge rating → base XP budget. Only these CRs are supported by
// encounter math endpoints; an unknown CR is rejected with 400.
export const XP_TABLE: Record<string, number> = {
  '0': 10,
  '1/8': 25,
  '1/4': 50,
  '1/2': 100,
  '1': 200,
  '2': 450,
  '3': 700,
  '4': 1100,
  '5': 1800,
};

// Per-character thresholds used by the encounter difficulty calculator.
// These intentionally mirror the level-3 party thresholds from the original
// implementation; they are applied regardless of actual character level.
export const LEVEL3_THRESHOLDS = {
  easy: 75,
  medium: 150,
  hard: 225,
  deadly: 400,
} as const;

// Difficulty labels and a short DM-facing recommendation for each.
export const DIFFICULTY_RECOMMENDATION: Record<string, string> = {
  trivial: 'no challenge',
  easy: 'safe warm-up',
  medium: 'standard challenge',
  hard: 'risky fight',
  deadly: 'deadly encounter',
};

// SQLite file and schema metadata.
export const DB_PATH = 'game.db';
export const SCHEMA_VERSION = 1;
