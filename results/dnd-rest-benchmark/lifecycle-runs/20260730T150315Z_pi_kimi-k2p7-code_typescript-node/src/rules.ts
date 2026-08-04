import type { Combatant, ScoredCombatant } from './types.js';

export const CR_XP: Record<string, number> = {
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

export const LEVEL_3_THRESHOLDS = { easy: 75, medium: 150, hard: 225, deadly: 400 };

export const ENCOUNTER_THRESHOLDS: Record<number, { easy: number; medium: number; hard: number; deadly: number }> = {
  1: { easy: 25, medium: 50, hard: 75, deadly: 100 },
  2: { easy: 50, medium: 100, hard: 150, deadly: 200 },
  3: { easy: 75, medium: 150, hard: 225, deadly: 400 },
  4: { easy: 125, medium: 250, hard: 375, deadly: 500 },
  5: { easy: 250, medium: 500, hard: 750, deadly: 1100 },
  6: { easy: 300, medium: 600, hard: 900, deadly: 1400 },
  7: { easy: 350, medium: 750, hard: 1100, deadly: 1700 },
  8: { easy: 450, medium: 900, hard: 1400, deadly: 2100 },
  9: { easy: 500, medium: 1100, hard: 1700, deadly: 2600 },
  10: { easy: 600, medium: 1200, hard: 1900, deadly: 2800 },
  11: { easy: 800, medium: 1600, hard: 2400, deadly: 3600 },
  12: { easy: 1000, medium: 2000, hard: 3000, deadly: 4500 },
  13: { easy: 1100, medium: 2200, hard: 3400, deadly: 5100 },
  14: { easy: 1250, medium: 2500, hard: 3800, deadly: 5700 },
  15: { easy: 1400, medium: 2800, hard: 4300, deadly: 6400 },
  16: { easy: 1600, medium: 3200, hard: 4800, deadly: 7200 },
  17: { easy: 2000, medium: 3900, hard: 5900, deadly: 8800 },
  18: { easy: 2100, medium: 4200, hard: 6300, deadly: 9500 },
  19: { easy: 2400, medium: 4900, hard: 7300, deadly: 10900 },
  20: { easy: 2800, medium: 5700, hard: 8500, deadly: 12700 },
};

/** Parse a dice expression of the form `<count>d<sides>[+-<mod>]`. */
export function parseDiceExpression(expression: unknown): { diceCount: number; sides: number; modifier: number } | null {
  if (typeof expression !== 'string') return null;
  const match = expression.trim().match(/^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$/);
  if (!match) return null;
  const diceCount = Number(match[1]);
  const sides = Number(match[2]);
  const modifier = match[3] ? (match[3] === '+' ? 1 : -1) * Number(match[4]) : 0;
  if (diceCount <= 0 || sides <= 0) return null;
  return { diceCount, sides, modifier };
}

/** Standard D&D ability modifier: floor((score - 10) / 2). */
export function abilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

/** Standard 5e proficiency bonus by character level, capped at 6. */
export function proficiencyBonus(level: number): number {
  if (level <= 4) return 2;
  if (level <= 8) return 3;
  if (level <= 12) return 4;
  if (level <= 16) return 5;
  return 6;
}

const CLASS_HIT_DICE: Record<string, number> = {
  barbarian: 12,
  bard: 8,
  cleric: 8,
  druid: 8,
  fighter: 10,
  monk: 8,
  paladin: 10,
  ranger: 10,
  rogue: 8,
  sorcerer: 6,
  warlock: 8,
  wizard: 6,
};

const HIT_DIE_AVERAGE: Record<number, number> = {
  6: 4,
  8: 5,
  10: 6,
  12: 7,
};

/** Return the starting hit die for a valid class, or null for unknown classes. */
export function classHitDie(className: string): number | null {
  return CLASS_HIT_DICE[className.toLowerCase()] ?? null;
}

/** Return the fixed average roll for a known hit die size. */
export function averageHitDie(sides: number): number | null {
  return HIT_DIE_AVERAGE[sides] ?? null;
}

/** Encounter multiplier based on the number of enemy monsters. */
export function multiplierForMonsterCount(count: number): number {
  if (count === 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
  return 4;
}

export function difficultyFromAdjustedXP(
  adjusted: number,
  thresholds: { easy: number; medium: number; hard: number; deadly: number },
): string {
  if (adjusted >= thresholds.deadly) return 'deadly';
  if (adjusted >= thresholds.hard) return 'hard';
  if (adjusted >= thresholds.medium) return 'medium';
  if (adjusted >= thresholds.easy) return 'easy';
  return 'trivial';
}

export function recommendationForDifficulty(difficulty: string): string {
  switch (difficulty) {
    case 'trivial':
      return 'no challenge';
    case 'easy':
      return 'safe warm-up';
    case 'medium':
      return 'solid challenge';
    case 'hard':
      return 'tough fight';
    case 'deadly':
      return 'deadly threat';
    default:
      return 'unknown';
  }
}

/** Produces a fallback open-thread title from a recap summary. */
export function resolveTrailThread(summary: string, fallbackMonster: string): string {
  const match = summary.match(/the (\S+) trail/i);
  const monster = match ? match[1] : fallbackMonster;
  return `Resolve ${monster} trail ambush`;
}

/** Compute a deterministic initiative score from the raw roll and Dexterity. */
export function scoreCombatant(c: Combatant): ScoredCombatant {
  return { ...c, score: c.roll + c.dex };
}

/**
 * Sort combatants by initiative score descending, then Dexterity descending,
 * then name ascending for deterministic tie-breaking.
 */
export function sortCombatants(combatants: Combatant[]): ScoredCombatant[] {
  return combatants
    .map(scoreCombatant)
    .sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      if (b.dex !== a.dex) return b.dex - a.dex;
      return a.name.localeCompare(b.name);
    });
}
