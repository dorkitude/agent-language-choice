import { defineConfig, type Plugin } from 'vite';
import type { IncomingMessage, ServerResponse } from 'node:http';

// ---------------------------------------------------------------------------
// D&D REST API logic
// ---------------------------------------------------------------------------

const XP_BY_CR: Record<string, number> = {
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

interface LevelThresholds {
  easy: number;
  medium: number;
  hard: number;
  deadly: number;
}

// Standard D&D 5e encounter-difficulty XP thresholds per character.
// Level 3 matches the benchmark spec: 75 / 150 / 225 / 400.
const THRESHOLDS_BY_LEVEL: Record<number, LevelThresholds> = {
  1: { easy: 25, medium: 50, hard: 75, deadly: 100 },
  2: { easy: 50, medium: 100, hard: 150, deadly: 200 },
  3: { easy: 75, medium: 150, hard: 225, deadly: 400 },
  4: { easy: 125, medium: 250, hard: 375, deadly: 500 },
  5: { easy: 250, medium: 500, hard: 750, deadly: 1100 },
  6: { easy: 300, medium: 600, hard: 900, deadly: 1400 },
  7: { easy: 350, medium: 750, hard: 1100, deadly: 1700 },
  8: { easy: 450, medium: 900, hard: 1400, deadly: 2100 },
  9: { easy: 550, medium: 1100, hard: 1600, deadly: 2400 },
  10: { easy: 600, medium: 1200, hard: 1900, deadly: 2800 },
  11: { easy: 800, medium: 1600, hard: 2400, deadly: 3600 },
  12: { easy: 1000, medium: 2000, hard: 3000, deadly: 4500 },
  13: { easy: 1100, medium: 2200, hard: 3300, deadly: 5100 },
  14: { easy: 1250, medium: 2500, hard: 3700, deadly: 5400 },
  15: { easy: 1400, medium: 2800, hard: 4100, deadly: 6200 },
  16: { easy: 1600, medium: 3200, hard: 4800, deadly: 7200 },
  17: { easy: 2000, medium: 3900, hard: 5900, deadly: 8800 },
  18: { easy: 2100, medium: 4200, hard: 6300, deadly: 9500 },
  19: { easy: 2400, medium: 4700, hard: 7200, deadly: 10900 },
  20: { easy: 2800, medium: 5700, hard: 8500, deadly: 12700 },
};

function multiplierFor(monsterCount: number): number {
  if (monsterCount <= 1) return 1;
  if (monsterCount === 2) return 1.5;
  if (monsterCount <= 6) return 2;
  if (monsterCount <= 10) return 2.5;
  if (monsterCount <= 14) return 3;
  return 4;
}

interface DiceStats {
  dice_count: number;
  sides: number;
  modifier: number;
  min: number;
  max: number;
  average: number;
}

function parseDice(expression: string): DiceStats {
  const re = /^(\d+)d(\d+)(?:([+-])(\d+))?$/;
  const m = re.exec(expression);
  if (!m) throw new Error('invalid expression');
  const dice_count = parseInt(m[1] as string, 10);
  const sides = parseInt(m[2] as string, 10);
  let modifier = 0;
  if (m[3] !== undefined && m[4] !== undefined) {
    const val = parseInt(m[4], 10);
    modifier = m[3] === '-' ? -val : val;
  }
  if (dice_count <= 0 || sides <= 0) throw new Error('invalid expression');
  const min = dice_count * 1 + modifier;
  const max = dice_count * sides + modifier;
  const average = (min + max) / 2;
  return { dice_count, sides, modifier, min, max, average };
}

// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  const payload = JSON.stringify(body);
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Content-Length', Buffer.byteLength(payload).toString());
  res.end(payload);
}

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on('data', (chunk: Buffer) => chunks.push(chunk));
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}

function isFiniteNumber(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v);
}

// Returns true if the request was handled (response ended).
async function handleApi(
  req: IncomingMessage,
  res: ServerResponse,
  rawUrl: string,
): Promise<boolean> {
  const method = req.method ?? '';
  const path = rawUrl.split('?')[0];

  if (method === 'GET' && path === '/health') {
    sendJson(res, 200, { ok: true });
    return true;
  }

  if (method === 'POST' && path.startsWith('/v1/')) {
    let body: Record<string, unknown> = {};
    try {
      const raw = await readBody(req);
      if (raw.length > 0) {
        const parsed = JSON.parse(raw);
        if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
          sendJson(res, 400, { error: 'invalid body' });
          return true;
        }
        body = parsed as Record<string, unknown>;
      }
    } catch {
      sendJson(res, 400, { error: 'invalid json' });
      return true;
    }

    try {
      if (path === '/v1/dice/stats') {
        const expr = body['expression'];
        if (typeof expr !== 'string') {
          sendJson(res, 400, { error: 'invalid expression' });
          return true;
        }
        sendJson(res, 200, parseDice(expr));
        return true;
      }

      if (path === '/v1/checks/ability') {
        const roll = body['roll'];
        const dc = body['dc'];
        const modifierField = body['modifier'];
        if (!isFiniteNumber(roll) || !isFiniteNumber(dc)) {
          sendJson(res, 400, { error: 'invalid input' });
          return true;
        }
        const modifier = isFiniteNumber(modifierField) ? modifierField : 0;
        const total = roll + modifier;
        const success = total >= dc;
        const margin = total - dc;
        sendJson(res, 200, { total, success, margin });
        return true;
      }

      if (path === '/v1/encounters/adjusted-xp') {
        const party = body['party'];
        const monsters = body['monsters'];
        if (!Array.isArray(party) || !Array.isArray(monsters)) {
          sendJson(res, 400, { error: 'invalid input' });
          return true;
        }

        let baseXp = 0;
        let monsterCount = 0;
        for (const mon of monsters) {
          if (mon === null || typeof mon !== 'object') {
            sendJson(res, 400, { error: 'invalid monster' });
            return true;
          }
          const monRec = mon as Record<string, unknown>;
          const crRaw = monRec['cr'];
          const crKey =
            typeof crRaw === 'number' ? String(crRaw) : typeof crRaw === 'string' ? crRaw : null;
          if (crKey === null || !(crKey in XP_BY_CR)) {
            sendJson(res, 400, { error: 'invalid cr' });
            return true;
          }
          const count = monRec['count'];
          if (!isFiniteNumber(count) || !Number.isInteger(count) || count < 1) {
            sendJson(res, 400, { error: 'invalid count' });
            return true;
          }
          baseXp += XP_BY_CR[crKey] * count;
          monsterCount += count;
        }

        const multiplier = multiplierFor(monsterCount);
        const adjustedXp = baseXp * multiplier;

        let easy = 0;
        let medium = 0;
        let hard = 0;
        let deadly = 0;
        for (const p of party) {
          if (p === null || typeof p !== 'object') {
            sendJson(res, 400, { error: 'invalid party member' });
            return true;
          }
          const pRec = p as Record<string, unknown>;
          const lvl = pRec['level'];
          if (!isFiniteNumber(lvl) || !Number.isInteger(lvl) || !(lvl in THRESHOLDS_BY_LEVEL)) {
            sendJson(res, 400, { error: 'invalid level' });
            return true;
          }
          const t = THRESHOLDS_BY_LEVEL[lvl];
          easy += t.easy;
          medium += t.medium;
          hard += t.hard;
          deadly += t.deadly;
        }

        let difficulty: string;
        if (adjustedXp >= deadly) difficulty = 'deadly';
        else if (adjustedXp >= hard) difficulty = 'hard';
        else if (adjustedXp >= medium) difficulty = 'medium';
        else if (adjustedXp >= easy) difficulty = 'easy';
        else difficulty = 'trivial';

        sendJson(res, 200, {
          base_xp: baseXp,
          monster_count: monsterCount,
          multiplier,
          adjusted_xp: adjustedXp,
          difficulty,
          thresholds: { easy, medium, hard, deadly },
        });
        return true;
      }

      if (path === '/v1/initiative/order') {
        const combatants = body['combatants'];
        if (!Array.isArray(combatants)) {
          sendJson(res, 400, { error: 'invalid input' });
          return true;
        }
        interface ScoredCombatant {
          name: string;
          dex: number;
          roll: number;
          score: number;
        }
        const scored: ScoredCombatant[] = combatants.map((c) => {
          if (c === null || typeof c !== 'object') {
            throw new Error('invalid combatant');
          }
          const cRec = c as Record<string, unknown>;
          const name = cRec['name'];
          const dex = cRec['dex'];
          const roll = cRec['roll'];
          if (
            typeof name !== 'string' ||
            !isFiniteNumber(dex) ||
            !isFiniteNumber(roll)
          ) {
            throw new Error('invalid combatant');
          }
          return { name, dex, roll, score: roll + dex };
        });
        scored.sort((a, b) => {
          if (b.score !== a.score) return b.score - a.score;
          if (b.dex !== a.dex) return b.dex - a.dex;
          if (a.name < b.name) return -1;
          if (a.name > b.name) return 1;
          return 0;
        });
        sendJson(res, 200, {
          order: scored.map((c) => ({ name: c.name, score: c.score })),
        });
        return true;
      }

      // Unknown /v1/ route.
      sendJson(res, 404, { error: 'not found' });
      return true;
    } catch (e) {
      sendJson(res, 400, { error: e instanceof Error ? e.message : 'error' });
      return true;
    }
  }

  return false;
}

// ---------------------------------------------------------------------------
// Vite plugin
// ---------------------------------------------------------------------------

function dndRestApiPlugin(): Plugin {
  return {
    name: 'dnd-rest-api',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = req.url ?? '';
        handleApi(req, res, url)
          .then((handled) => {
            if (handled) return;
            next();
          })
          .catch((err) => {
            if (!res.headersSent) {
              sendJson(res, 500, { error: err instanceof Error ? err.message : 'error' });
            } else {
              next(err);
            }
          });
      });
    },
  };
}

export default defineConfig({
  plugins: [dndRestApiPlugin()],
  server: {
    host: '127.0.0.1',
  },
});
