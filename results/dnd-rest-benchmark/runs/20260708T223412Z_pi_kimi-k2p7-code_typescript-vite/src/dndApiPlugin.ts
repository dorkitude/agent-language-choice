import type { Plugin } from 'vite';

type Request = any;
type Response = any;
type Next = () => void;

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

const LEVEL_3_THRESHOLDS = { easy: 75, medium: 150, hard: 225, deadly: 400 };

function sendJson(res: Response, status: number, body: unknown): void {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json');
  res.end(JSON.stringify(body));
}

function readBody(req: Request): Promise<string> {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', (chunk: string | Buffer) => {
      data += chunk.toString();
    });
    req.on('end', () => resolve(data));
    req.on('error', reject);
  });
}

function monsterMultiplier(count: number): number {
  if (count === 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
  return 4;
}

function parseDice(expression: string) {
  const m = /^([1-9]\d*)d([1-9]\d*)([+-]\d+)?$/.exec(expression.trim());
  if (!m) return null;
  const count = parseInt(m[1], 10);
  const sides = parseInt(m[2], 10);
  const modifier = m[3] ? parseInt(m[3], 10) : 0;
  const min = count + modifier;
  const max = count * sides + modifier;
  const average = (min + max) / 2;
  return { dice_count: count, sides, modifier, min, max, average };
}

function isFiniteNumber(n: unknown): n is number {
  return typeof n === 'number' && Number.isFinite(n);
}

export function dndApiPlugin(): Plugin {
  return {
    name: 'dnd-api',
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        try {
          const url = req.url ?? '';

          if (req.method === 'GET' && url === '/health') {
            sendJson(res, 200, { ok: true });
            return;
          }

          if (req.method !== 'POST') {
            next();
            return;
          }

          if (
            url !== '/v1/dice/stats' &&
            url !== '/v1/checks/ability' &&
            url !== '/v1/encounters/adjusted-xp' &&
            url !== '/v1/initiative/order'
          ) {
            next();
            return;
          }

          let body: unknown;
          try {
            body = JSON.parse(await readBody(req));
          } catch {
            sendJson(res, 400, { error: 'invalid json' });
            return;
          }

          switch (url) {
            case '/v1/dice/stats': {
              const expr = String((body as any).expression ?? '');
              const result = parseDice(expr);
              if (!result) {
                sendJson(res, 400, { error: 'invalid expression' });
                return;
              }
              sendJson(res, 200, result);
              return;
            }

            case '/v1/checks/ability': {
              const b = body as any;
              const roll = Number(b.roll);
              const modifier = Number(b.modifier);
              const dc = Number(b.dc);
              if (!isFiniteNumber(roll) || !isFiniteNumber(modifier) || !isFiniteNumber(dc)) {
                sendJson(res, 400, { error: 'bad input' });
                return;
              }
              const total = roll + modifier;
              sendJson(res, 200, {
                total,
                success: total >= dc,
                margin: total - dc,
              });
              return;
            }

            case '/v1/encounters/adjusted-xp': {
              const b = body as any;
              const party = Array.isArray(b.party) ? b.party : [];
              const monsters = Array.isArray(b.monsters) ? b.monsters : [];

              const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
              for (const p of party) {
                const level = Number(p.level);
                if (level !== 3) {
                  sendJson(res, 400, { error: 'unsupported level' });
                  return;
                }
                thresholds.easy += LEVEL_3_THRESHOLDS.easy;
                thresholds.medium += LEVEL_3_THRESHOLDS.medium;
                thresholds.hard += LEVEL_3_THRESHOLDS.hard;
                thresholds.deadly += LEVEL_3_THRESHOLDS.deadly;
              }

              let baseXp = 0;
              let monsterCount = 0;
              for (const m of monsters) {
                const cr = String(m.cr ?? '');
                const count = Number(m.count);
                if (!(cr in CR_XP)) {
                  sendJson(res, 400, { error: 'unsupported cr' });
                  return;
                }
                if (!Number.isInteger(count) || count <= 0) {
                  sendJson(res, 400, { error: 'bad count' });
                  return;
                }
                baseXp += CR_XP[cr] * count;
                monsterCount += count;
              }

              const mult = monsterCount > 0 ? monsterMultiplier(monsterCount) : 1;
              const adjustedXp = baseXp * mult;

              let difficulty = 'trivial';
              if (adjustedXp >= thresholds.deadly) difficulty = 'deadly';
              else if (adjustedXp >= thresholds.hard) difficulty = 'hard';
              else if (adjustedXp >= thresholds.medium) difficulty = 'medium';
              else if (adjustedXp >= thresholds.easy) difficulty = 'easy';

              sendJson(res, 200, {
                base_xp: baseXp,
                monster_count: monsterCount,
                multiplier: mult,
                adjusted_xp: adjustedXp,
                difficulty,
                thresholds,
              });
              return;
            }

            case '/v1/initiative/order': {
              const b = body as any;
              const combatants = Array.isArray(b.combatants) ? b.combatants : [];
              const entries = [];
              for (const c of combatants) {
                const name = c.name;
                const dex = Number(c.dex);
                const roll = Number(c.roll);
                if (typeof name !== 'string' || !isFiniteNumber(dex) || !isFiniteNumber(roll)) {
                  sendJson(res, 400, { error: 'bad combatant' });
                  return;
                }
                entries.push({ name, dex, score: roll + dex });
              }
              entries.sort((a, b) => {
                if (b.score !== a.score) return b.score - a.score;
                if (b.dex !== a.dex) return b.dex - a.dex;
                return a.name.localeCompare(b.name);
              });
              sendJson(res, 200, {
                order: entries.map(({ name, score }) => ({ name, score })),
              });
              return;
            }

            default:
              next();
              return;
          }
        } catch {
          sendJson(res, 500, { error: 'server error' });
        }
      });
    },
  };
}
