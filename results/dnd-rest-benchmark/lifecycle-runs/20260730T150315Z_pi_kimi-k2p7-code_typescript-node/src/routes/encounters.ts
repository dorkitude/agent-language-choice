import { ServerResponse } from 'node:http';
import { sendJSON } from '../http-utils.js';
import {
  CR_XP,
  LEVEL_3_THRESHOLDS,
  difficultyFromAdjustedXP,
  multiplierForMonsterCount,
} from '../rules.js';

export function handleAdjustedXP(res: ServerResponse, _params: unknown, body: unknown): void {
  const { party, monsters } = body as {
    party?: Array<{ level?: unknown }>;
    monsters?: Array<{ cr?: unknown; count?: unknown }>;
  };
  if (!Array.isArray(party) || !Array.isArray(monsters)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  let baseXP = 0;
  let monsterCount = 0;
  for (const m of monsters) {
    if (
      typeof m !== 'object' ||
      m == null ||
      typeof m.cr !== 'string' ||
      typeof m.count !== 'number' ||
      !Number.isInteger(m.count) ||
      m.count <= 0
    ) {
      sendJSON(res, 400, { error: 'invalid input' });
      return;
    }
    const xp = CR_XP[m.cr];
    if (xp === undefined) {
      sendJSON(res, 400, { error: 'unsupported cr' });
      return;
    }
    baseXP += xp * m.count;
    monsterCount += m.count;
  }

  const multiplier = multiplierForMonsterCount(monsterCount);
  const adjustedXP = baseXP * multiplier;

  const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const p of party) {
    if (typeof p !== 'object' || p == null || p.level !== 3) {
      sendJSON(res, 400, { error: 'unsupported level' });
      return;
    }
    thresholds.easy += LEVEL_3_THRESHOLDS.easy;
    thresholds.medium += LEVEL_3_THRESHOLDS.medium;
    thresholds.hard += LEVEL_3_THRESHOLDS.hard;
    thresholds.deadly += LEVEL_3_THRESHOLDS.deadly;
  }

  const difficulty = difficultyFromAdjustedXP(adjustedXP, thresholds);
  sendJSON(res, 200, {
    base_xp: baseXP,
    monster_count: monsterCount,
    multiplier,
    adjusted_xp: adjustedXP,
    difficulty,
    thresholds,
  });
}
