/** Encounter difficulty math (DMG-style adjusted XP), shared by the DM tools module. */

import type { ApiResult, JsonValue } from '../types.ts';

const CR_XP: Record<string, number> = {
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

// Only level-3 party thresholds are supported; unsupported levels are rejected explicitly.
const LEVEL_THRESHOLDS: Record<number, { easy: number; medium: number; hard: number; deadly: number }> = {
  3: { easy: 75, medium: 150, hard: 225, deadly: 400 },
};

function countMultiplier(count: number): number {
  if (count <= 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
  return 4;
}

export function adjustedXp(body: JsonValue): ApiResult {
  const party = body.party;
  const monsters = body.monsters;
  if (!Array.isArray(party) || !Array.isArray(monsters)) {
    return { status: 400, body: { error: 'party and monsters must be arrays' } };
  }

  let baseXp = 0;
  let monsterCount = 0;
  for (const m of monsters) {
    const cr = String((m as JsonValue).cr);
    const count = Number((m as JsonValue).count);
    if (!(cr in CR_XP) || !Number.isFinite(count)) {
      return { status: 400, body: { error: 'invalid monster entry' } };
    }
    baseXp += CR_XP[cr] * count;
    monsterCount += count;
  }

  const multiplier = countMultiplier(monsterCount);
  const adjustedXpValue = baseXp * multiplier;

  const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const p of party) {
    const level = Number((p as JsonValue).level);
    const t = LEVEL_THRESHOLDS[level];
    if (!t) {
      return { status: 400, body: { error: 'unsupported party level' } };
    }
    thresholds.easy += t.easy;
    thresholds.medium += t.medium;
    thresholds.hard += t.hard;
    thresholds.deadly += t.deadly;
  }

  let difficulty = 'trivial';
  if (adjustedXpValue >= thresholds.deadly) difficulty = 'deadly';
  else if (adjustedXpValue >= thresholds.hard) difficulty = 'hard';
  else if (adjustedXpValue >= thresholds.medium) difficulty = 'medium';
  else if (adjustedXpValue >= thresholds.easy) difficulty = 'easy';

  return {
    status: 200,
    body: {
      base_xp: baseXp,
      monster_count: monsterCount,
      multiplier,
      adjusted_xp: adjustedXpValue,
      difficulty,
      thresholds,
    },
  };
}
