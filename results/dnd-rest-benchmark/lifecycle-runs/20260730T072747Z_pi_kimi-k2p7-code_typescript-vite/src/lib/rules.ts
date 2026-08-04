// Pure game-rule calculations. These functions are deterministic and have no
// side effects, making them easy to unit test without a database.

import { DIFFICULTY_RECOMMENDATION, LEVEL3_THRESHOLDS, XP_TABLE } from './constants.js';

export function abilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

export function proficiencyBonus(level: number): number {
  return Math.floor((level - 1) / 4) + 2;
}

export function multiplier(monsterCount: number): number {
  if (monsterCount === 1) return 1;
  if (monsterCount === 2) return 1.5;
  if (monsterCount <= 6) return 2;
  if (monsterCount <= 10) return 2.5;
  if (monsterCount <= 14) return 3;
  return 4;
}

export type DiceExpression = {
  dice_count: number;
  sides: number;
  modifier: number;
};

export function parseDiceExpression(expression: unknown): DiceExpression | null {
  if (typeof expression !== 'string') return null;
  const match = expression.match(/^(\d+)d(\d+)([+-]\d+)?$/);
  if (!match) return null;
  const count = parseInt(match[1], 10);
  const sides = parseInt(match[2], 10);
  const modifier = match[3] ? parseInt(match[3], 10) : 0;
  if (count <= 0 || sides <= 0) return null;
  return { dice_count: count, sides, modifier };
}

export function diceStats(expression: DiceExpression) {
  const min = expression.dice_count + expression.modifier;
  const max = expression.dice_count * expression.sides + expression.modifier;
  return {
    dice_count: expression.dice_count,
    sides: expression.sides,
    modifier: expression.modifier,
    min,
    max,
    average: (min + max) / 2,
  };
}

export type InitiativeCombatant = {
  name: string;
  dex: number;
  roll: number;
};

export type InitiativeEntry = { name: string; score: number };

export function sortInitiative(combatants: InitiativeCombatant[]): InitiativeEntry[] {
  return combatants
    .map((c) => ({ name: c.name, score: c.roll + c.dex, dex: c.dex }))
    .sort((a, b) => {
      const scoreDiff = b.score - a.score;
      if (scoreDiff !== 0) return scoreDiff;
      const dexDiff = b.dex - a.dex;
      if (dexDiff !== 0) return dexDiff;
      return a.name.localeCompare(b.name);
    })
    .map(({ name, score }) => ({ name, score }));
}

export type EncounterMonster = { cr: string; count: number };

export type EncounterResult = {
  base_xp: number;
  monster_count: number;
  multiplier: number;
  adjusted_xp: number;
  difficulty: string;
  thresholds: { easy: number; medium: number; hard: number; deadly: number };
};

export function calculateEncounter(
  monsters: EncounterMonster[],
  partySize: number,
): EncounterResult | { error: string } {
  let baseXp = 0;
  let monsterCount = 0;
  for (const m of monsters) {
    if (!m || typeof m.cr !== 'string' || typeof m.count !== 'number' || m.count <= 0 || !(m.cr in XP_TABLE)) {
      return { error: 'invalid monster' };
    }
    baseXp += XP_TABLE[m.cr] * m.count;
    monsterCount += m.count;
  }

  const mult = multiplier(monsterCount);
  const adjusted = baseXp * mult;

  const thresholds = {
    easy: LEVEL3_THRESHOLDS.easy * partySize,
    medium: LEVEL3_THRESHOLDS.medium * partySize,
    hard: LEVEL3_THRESHOLDS.hard * partySize,
    deadly: LEVEL3_THRESHOLDS.deadly * partySize,
  };

  let difficulty = 'trivial';
  if (adjusted >= thresholds.deadly) difficulty = 'deadly';
  else if (adjusted >= thresholds.hard) difficulty = 'hard';
  else if (adjusted >= thresholds.medium) difficulty = 'medium';
  else if (adjusted >= thresholds.easy) difficulty = 'easy';

  return {
    base_xp: baseXp,
    monster_count: monsterCount,
    multiplier: mult,
    adjusted_xp: adjusted,
    difficulty,
    thresholds,
  };
}

export function difficultyLabel(adjustedXp: number, partySize: number): string {
  const thresholds = {
    easy: LEVEL3_THRESHOLDS.easy * partySize,
    medium: LEVEL3_THRESHOLDS.medium * partySize,
    hard: LEVEL3_THRESHOLDS.hard * partySize,
    deadly: LEVEL3_THRESHOLDS.deadly * partySize,
  };
  if (adjustedXp >= thresholds.deadly) return 'deadly';
  if (adjustedXp >= thresholds.hard) return 'hard';
  if (adjustedXp >= thresholds.medium) return 'medium';
  if (adjustedXp >= thresholds.easy) return 'easy';
  return 'trivial';
}

export function recommendationFor(difficulty: string): string {
  return DIFFICULTY_RECOMMENDATION[difficulty] ?? 'unknown difficulty';
}
