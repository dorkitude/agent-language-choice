import { sendJson, parseJsonBody } from '../lib/http.js';
import { CR_XP, LEVEL_THRESHOLDS, countMultiplier, difficultyForXp } from '../lib/rules.js';

export function registerEncounterRoutes(router) {
  router.post('/v1/encounters/adjusted-xp', async (req, res) => {
    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const party = body.data && body.data.party;
    const monsters = body.data && body.data.monsters;
    if (!Array.isArray(party) || !Array.isArray(monsters)) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    let baseXp = 0;
    let monsterCount = 0;
    for (const m of monsters) {
      const xp = CR_XP[String(m.cr)];
      if (xp === undefined || typeof m.count !== 'number') {
        sendJson(res, 400, { error: 'unsupported challenge rating' });
        return;
      }
      baseXp += xp * m.count;
      monsterCount += m.count;
    }

    const multiplier = countMultiplier(monsterCount);
    const adjustedXp = baseXp * multiplier;

    const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
    for (const member of party) {
      const t = LEVEL_THRESHOLDS[member.level];
      if (!t) {
        sendJson(res, 400, { error: 'unsupported party level' });
        return;
      }
      thresholds.easy += t.easy;
      thresholds.medium += t.medium;
      thresholds.hard += t.hard;
      thresholds.deadly += t.deadly;
    }

    sendJson(res, 200, {
      base_xp: baseXp,
      monster_count: monsterCount,
      multiplier,
      adjusted_xp: adjustedXp,
      difficulty: difficultyForXp(adjustedXp, thresholds),
      thresholds,
    });
  });

  router.post('/v1/initiative/order', async (req, res) => {
    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const combatants = body.data && body.data.combatants;
    if (!Array.isArray(combatants)) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    const scored = combatants.map((c) => ({
      name: c.name,
      dex: c.dex,
      score: c.roll + c.dex,
    }));
    scored.sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      if (b.dex !== a.dex) return b.dex - a.dex;
      return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
    });
    sendJson(res, 200, {
      order: scored.map((c) => ({ name: c.name, score: c.score })),
    });
  });
}
