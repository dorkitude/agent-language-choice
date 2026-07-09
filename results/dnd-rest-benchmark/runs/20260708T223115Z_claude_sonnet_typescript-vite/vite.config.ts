import type { Connect, Plugin } from 'vite';
import type { IncomingMessage, ServerResponse } from 'node:http';

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

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', (chunk) => {
      data += chunk;
    });
    req.on('end', () => resolve(data));
    req.on('error', reject);
  });
}

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  const payload = JSON.stringify(body);
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json');
  res.end(payload);
}

function parseDiceExpression(expression: unknown): { count: number; sides: number; modifier: number } | null {
  if (typeof expression !== 'string') return null;
  const match = /^(\d+)d(\d+)([+-]\d+)?$/.exec(expression.trim());
  if (!match) return null;
  const count = parseInt(match[1], 10);
  const sides = parseInt(match[2], 10);
  const modifier = match[3] ? parseInt(match[3], 10) : 0;
  if (count <= 0 || sides <= 0) return null;
  return { count, sides, modifier };
}

function diceStatsHandler(body: any, res: ServerResponse): void {
  const parsed = parseDiceExpression(body?.expression);
  if (!parsed) {
    sendJson(res, 400, { error: 'invalid expression' });
    return;
  }
  const { count, sides, modifier } = parsed;
  const min = count * 1 + modifier;
  const max = count * sides + modifier;
  const average = (count * (1 + sides)) / 2 + modifier;
  sendJson(res, 200, {
    dice_count: count,
    sides,
    modifier,
    min,
    max,
    average,
  });
}

function abilityCheckHandler(body: any, res: ServerResponse): void {
  const roll = Number(body?.roll);
  const modifier = Number(body?.modifier);
  const dc = Number(body?.dc);
  if (!Number.isFinite(roll) || !Number.isFinite(modifier) || !Number.isFinite(dc)) {
    sendJson(res, 400, { error: 'invalid request' });
    return;
  }
  const total = roll + modifier;
  const success = total >= dc;
  const margin = total - dc;
  sendJson(res, 200, { total, success, margin });
}

function adjustedXpHandler(body: any, res: ServerResponse): void {
  const party = body?.party;
  const monsters = body?.monsters;
  if (!Array.isArray(party) || !Array.isArray(monsters)) {
    sendJson(res, 400, { error: 'invalid request' });
    return;
  }

  let baseXp = 0;
  let monsterCount = 0;
  for (const m of monsters) {
    const cr = String(m?.cr);
    const count = Number(m?.count);
    const xp = CR_XP[cr];
    if (xp === undefined || !Number.isFinite(count)) {
      sendJson(res, 400, { error: 'unsupported cr' });
      return;
    }
    baseXp += xp * count;
    monsterCount += count;
  }

  const multiplier = countMultiplier(monsterCount);
  const adjustedXp = baseXp * multiplier;

  const totals = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const member of party) {
    const level = Number(member?.level);
    const thresholds = LEVEL_THRESHOLDS[level];
    if (!thresholds) {
      sendJson(res, 400, { error: 'unsupported level' });
      return;
    }
    totals.easy += thresholds.easy;
    totals.medium += thresholds.medium;
    totals.hard += thresholds.hard;
    totals.deadly += thresholds.deadly;
  }

  let difficulty = 'trivial';
  if (adjustedXp >= totals.deadly) difficulty = 'deadly';
  else if (adjustedXp >= totals.hard) difficulty = 'hard';
  else if (adjustedXp >= totals.medium) difficulty = 'medium';
  else if (adjustedXp >= totals.easy) difficulty = 'easy';

  sendJson(res, 200, {
    base_xp: baseXp,
    monster_count: monsterCount,
    multiplier,
    adjusted_xp: adjustedXp,
    difficulty,
    thresholds: totals,
  });
}

function initiativeOrderHandler(body: any, res: ServerResponse): void {
  const combatants = body?.combatants;
  if (!Array.isArray(combatants)) {
    sendJson(res, 400, { error: 'invalid request' });
    return;
  }

  const scored = combatants.map((c: any) => {
    const dex = Number(c?.dex);
    const roll = Number(c?.roll);
    return { name: String(c?.name), dex, score: roll + dex };
  });

  scored.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
  });

  sendJson(res, 200, {
    order: scored.map((c) => ({ name: c.name, score: c.score })),
  });
}

function apiMiddleware(): Connect.NextHandleFunction {
  return (req, res, next) => {
    const url = req.url ?? '';
    const method = req.method ?? 'GET';

    if (method === 'GET' && url === '/health') {
      sendJson(res, 200, { ok: true });
      return;
    }

    const postRoutes: Record<string, (body: any, res: ServerResponse) => void> = {
      '/v1/dice/stats': diceStatsHandler,
      '/v1/checks/ability': abilityCheckHandler,
      '/v1/encounters/adjusted-xp': adjustedXpHandler,
      '/v1/initiative/order': initiativeOrderHandler,
    };

    const handler = postRoutes[url];
    if (method === 'POST' && handler) {
      readBody(req)
        .then((raw) => {
          let parsed: any;
          try {
            parsed = raw ? JSON.parse(raw) : {};
          } catch {
            sendJson(res, 400, { error: 'invalid json' });
            return;
          }
          handler(parsed, res);
        })
        .catch(() => {
          sendJson(res, 500, { error: 'internal error' });
        });
      return;
    }

    next();
  };
}

function ddRestApiPlugin(): Plugin {
  return {
    name: 'dnd-rest-api',
    configureServer(server) {
      server.middlewares.use(apiMiddleware());
    },
    configurePreviewServer(server) {
      server.middlewares.use(apiMiddleware());
    },
  };
}

export default {
  plugins: [ddRestApiPlugin()],
};
