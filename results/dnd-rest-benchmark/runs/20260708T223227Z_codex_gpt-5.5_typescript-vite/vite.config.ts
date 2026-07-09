import { defineConfig, type Plugin } from 'vite';
import type { IncomingMessage, ServerResponse } from 'node:http';

type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

const monsterXp: Record<string, number> = {
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

const levelThresholds: Record<number, { easy: number; medium: number; hard: number; deadly: number }> = {
  3: { easy: 75, medium: 150, hard: 225, deadly: 400 },
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isInteger(value: unknown): value is number {
  return Number.isInteger(value);
}

function sendJson(res: ServerResponse, status: number, body: JsonValue): void {
  res.statusCode = status;
  res.setHeader('content-type', 'application/json');
  res.end(JSON.stringify(body));
}

function badRequest(res: ServerResponse): void {
  sendJson(res, 400, { error: 'bad_request' });
}

function readJson(req: IncomingMessage): Promise<unknown> {
  return new Promise((resolve, reject) => {
    let data = '';

    req.setEncoding('utf8');
    req.on('data', (chunk: string) => {
      data += chunk;
    });
    req.on('end', () => {
      try {
        resolve(JSON.parse(data));
      } catch (error) {
        reject(error);
      }
    });
    req.on('error', reject);
  });
}

function monsterMultiplier(count: number): number {
  if (count <= 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
  return 4;
}

function dndRestPlugin(): Plugin {
  return {
    name: 'dnd-rest-api',
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        const url = new URL(req.url ?? '/', 'http://127.0.0.1');
        const path = url.pathname;

        if (req.method === 'GET' && path === '/health') {
          sendJson(res, 200, { ok: true });
          return;
        }

        if (req.method !== 'POST') {
          next();
          return;
        }

        if (
          path !== '/v1/dice/stats' &&
          path !== '/v1/checks/ability' &&
          path !== '/v1/encounters/adjusted-xp' &&
          path !== '/v1/initiative/order'
        ) {
          next();
          return;
        }

        let body: unknown;
        try {
          body = await readJson(req);
        } catch {
          badRequest(res);
          return;
        }

        if (path === '/v1/dice/stats') {
          if (!isRecord(body) || typeof body.expression !== 'string') {
            badRequest(res);
            return;
          }

          const match = /^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$/.exec(body.expression);
          if (match === null) {
            badRequest(res);
            return;
          }

          const diceCount = Number(match[1]);
          const sides = Number(match[2]);
          const modifier = match[4] === undefined ? 0 : Number(match[4]) * (match[3] === '-' ? -1 : 1);

          if (!Number.isSafeInteger(diceCount) || !Number.isSafeInteger(sides) || diceCount <= 0 || sides <= 0) {
            badRequest(res);
            return;
          }

          sendJson(res, 200, {
            dice_count: diceCount,
            sides,
            modifier,
            min: diceCount + modifier,
            max: diceCount * sides + modifier,
            average: diceCount * (sides + 1) / 2 + modifier,
          });
          return;
        }

        if (path === '/v1/checks/ability') {
          if (!isRecord(body) || !isInteger(body.roll) || !isInteger(body.modifier) || !isInteger(body.dc)) {
            badRequest(res);
            return;
          }

          const total = body.roll + body.modifier;
          sendJson(res, 200, {
            total,
            success: total >= body.dc,
            margin: total - body.dc,
          });
          return;
        }

        if (path === '/v1/encounters/adjusted-xp') {
          if (!isRecord(body) || !Array.isArray(body.party) || !Array.isArray(body.monsters)) {
            badRequest(res);
            return;
          }

          const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
          for (const member of body.party) {
            if (!isRecord(member) || !isInteger(member.level) || levelThresholds[member.level] === undefined) {
              badRequest(res);
              return;
            }

            const memberThresholds = levelThresholds[member.level];
            thresholds.easy += memberThresholds.easy;
            thresholds.medium += memberThresholds.medium;
            thresholds.hard += memberThresholds.hard;
            thresholds.deadly += memberThresholds.deadly;
          }

          let baseXp = 0;
          let monsterCount = 0;
          for (const monster of body.monsters) {
            if (
              !isRecord(monster) ||
              typeof monster.cr !== 'string' ||
              !isInteger(monster.count) ||
              monster.count < 0 ||
              monsterXp[monster.cr] === undefined
            ) {
              badRequest(res);
              return;
            }

            baseXp += monsterXp[monster.cr] * monster.count;
            monsterCount += monster.count;
          }

          const multiplier = monsterMultiplier(monsterCount);
          const adjustedXp = baseXp * multiplier;
          let difficulty = 'trivial';
          if (adjustedXp >= thresholds.easy) difficulty = 'easy';
          if (adjustedXp >= thresholds.medium) difficulty = 'medium';
          if (adjustedXp >= thresholds.hard) difficulty = 'hard';
          if (adjustedXp >= thresholds.deadly) difficulty = 'deadly';

          sendJson(res, 200, {
            base_xp: baseXp,
            monster_count: monsterCount,
            multiplier,
            adjusted_xp: adjustedXp,
            difficulty,
            thresholds,
          });
          return;
        }

        if (path === '/v1/initiative/order') {
          if (!isRecord(body) || !Array.isArray(body.combatants)) {
            badRequest(res);
            return;
          }

          const combatants = body.combatants.map((combatant) => {
            if (
              !isRecord(combatant) ||
              typeof combatant.name !== 'string' ||
              !isInteger(combatant.dex) ||
              !isInteger(combatant.roll)
            ) {
              return null;
            }

            return {
              name: combatant.name,
              dex: combatant.dex,
              score: combatant.roll + combatant.dex,
            };
          });

          if (combatants.some((combatant) => combatant === null)) {
            badRequest(res);
            return;
          }

          const order = combatants
            .filter((combatant): combatant is { name: string; dex: number; score: number } => combatant !== null)
            .sort((a, b) => b.score - a.score || b.dex - a.dex || a.name.localeCompare(b.name))
            .map(({ name, score }) => ({ name, score }));

          sendJson(res, 200, { order });
        }
      });
    },
  };
}

export default defineConfig({
  plugins: [dndRestPlugin()],
});
