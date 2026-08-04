import type { ServerResponse } from 'node:http';
import { sendError, sendJson } from '../http.js';
import { calculateEncounter } from '../rules.js';

export function handleAdjustedXp(body: unknown, res: ServerResponse): boolean {
  const b = body as any;
  if (!Array.isArray(b?.party) || !Array.isArray(b?.monsters)) {
    sendError(res, 400, 'invalid request');
    return true;
  }

  for (const p of b.party) {
    if (!p || typeof p.level !== 'number') {
      sendError(res, 400, 'invalid party member');
      return true;
    }
  }

  const result = calculateEncounter(b.monsters, b.party.length);
  if ('error' in result) {
    sendError(res, 400, result.error);
    return true;
  }

  sendJson(res, 200, {
    base_xp: result.base_xp,
    monster_count: result.monster_count,
    multiplier: result.multiplier,
    adjusted_xp: result.adjusted_xp,
    difficulty: result.difficulty,
    thresholds: result.thresholds,
  });
  return true;
}
