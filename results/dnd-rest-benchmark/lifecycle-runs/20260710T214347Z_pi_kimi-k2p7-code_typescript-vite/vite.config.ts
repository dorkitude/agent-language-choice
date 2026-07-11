import { defineConfig } from 'vite';
import type { Connect, ViteDevServer } from 'vite';
import type { ServerResponse } from 'http';

const XP_TABLE: Record<string, number> = {
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

const THRESHOLDS = {
  3: { easy: 75, medium: 150, hard: 225, deadly: 400 },
};

function sendJson(res: ServerResponse, status: number, data: unknown) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json');
  res.end(JSON.stringify(data));
}

function computeAbilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

function computeProficiencyBonus(level: number): number {
  return Math.floor((level - 1) / 4) + 2;
}

const ABILITY_NAMES = ['str', 'dex', 'con', 'int', 'wis', 'cha'] as const;
type AbilityName = (typeof ABILITY_NAMES)[number];

type AbilityMap = Record<AbilityName, number>;

function parseBody(req: Connect.IncomingMessage): Promise<unknown> {
  return new Promise((resolve, reject) => {
    let body = '';
    req.setEncoding('utf8');
    req.on('data', (chunk: string) => {
      body += chunk;
    });
    req.on('end', () => {
      if (!body) return resolve({});
      try {
        resolve(JSON.parse(body));
      } catch (err) {
        reject(err);
      }
    });
    req.on('error', reject);
  });
}

function parseDiceExpression(expression: string) {
  const match = /^([1-9]\d*)d([1-9]\d*)(?:\+([0-9]+)|-([0-9]+))?$/.exec(expression);
  if (!match) return null;
  const diceCount = parseInt(match[1], 10);
  const sides = parseInt(match[2], 10);
  const modifier = match[3] ? parseInt(match[3], 10) : match[4] ? -parseInt(match[4], 10) : 0;
  return { diceCount, sides, modifier };
}

function getMonsterMultiplier(monsterCount: number): number {
  if (monsterCount === 1) return 1;
  if (monsterCount === 2) return 1.5;
  if (monsterCount <= 6) return 2;
  if (monsterCount <= 10) return 2.5;
  if (monsterCount <= 14) return 3;
  return 4;
}

function dndApiMiddleware() {
  return {
    name: 'dnd-api',
    configureServer(server: ViteDevServer) {
      server.middlewares.use('/health', async (req, res, next) => {
        if (req.method !== 'GET') return next();
        sendJson(res, 200, { ok: true });
      });

      server.middlewares.use('/v1/dice/stats', async (req, res, next) => {
        if (req.method !== 'POST') return next();
        try {
          const body = (await parseBody(req)) as { expression?: string };
          const parsed = parseDiceExpression(body.expression ?? '');
          if (!parsed) return sendJson(res, 400, { error: 'invalid expression' });
          const { diceCount, sides, modifier } = parsed;
          const min = diceCount + modifier;
          const max = diceCount * sides + modifier;
          const average = (min + max) / 2;
          sendJson(res, 200, {
            dice_count: diceCount,
            sides,
            modifier,
            min,
            max,
            average,
          });
        } catch {
          sendJson(res, 400, { error: 'invalid json' });
        }
      });

      server.middlewares.use('/v1/checks/ability', async (req, res, next) => {
        if (req.method !== 'POST') return next();
        try {
          const body = (await parseBody(req)) as { roll?: number; modifier?: number; dc?: number };
          const roll = Number(body.roll);
          const modifier = Number(body.modifier);
          const dc = Number(body.dc);
          if ([roll, modifier, dc].some((n) => !Number.isFinite(n))) {
            return sendJson(res, 400, { error: 'invalid numbers' });
          }
          const total = roll + modifier;
          sendJson(res, 200, { total, success: total >= dc, margin: total - dc });
        } catch {
          sendJson(res, 400, { error: 'invalid json' });
        }
      });

      server.middlewares.use('/v1/encounters/adjusted-xp', async (req, res, next) => {
        if (req.method !== 'POST') return next();
        try {
          const body = (await parseBody(req)) as {
            party?: Array<{ level?: number }>;
            monsters?: Array<{ cr?: string; count?: number }>;
          };
          const party = (body.party ?? []).filter((m) => m.level === 3);
          const monsters = (body.monsters ?? []).filter((m) => m.cr && m.count && XP_TABLE[m.cr]);
          const baseXp = monsters.reduce((sum, m) => sum + XP_TABLE[m.cr!] * m.count!, 0);
          const monsterCount = monsters.reduce((sum, m) => sum + m.count!, 0);
          const multiplier = getMonsterMultiplier(monsterCount);
          const adjustedXp = baseXp * multiplier;
          const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
          party.forEach(() => {
            thresholds.easy += THRESHOLDS[3].easy;
            thresholds.medium += THRESHOLDS[3].medium;
            thresholds.hard += THRESHOLDS[3].hard;
            thresholds.deadly += THRESHOLDS[3].deadly;
          });
          let difficulty = 'trivial';
          if (adjustedXp >= thresholds.deadly) difficulty = 'deadly';
          else if (adjustedXp >= thresholds.hard) difficulty = 'hard';
          else if (adjustedXp >= thresholds.medium) difficulty = 'medium';
          else if (adjustedXp >= thresholds.easy) difficulty = 'easy';
          sendJson(res, 200, {
            base_xp: baseXp,
            monster_count: monsterCount,
            multiplier,
            adjusted_xp: adjustedXp,
            difficulty,
            thresholds,
          });
        } catch {
          sendJson(res, 400, { error: 'invalid json' });
        }
      });

      server.middlewares.use('/v1/initiative/order', async (req, res, next) => {
        if (req.method !== 'POST') return next();
        try {
          const body = (await parseBody(req)) as {
            combatants?: Array<{ name?: string; dex?: number; roll?: number }>;
          };
          const combatants = (body.combatants ?? []).filter(
            (c) => typeof c.name === 'string' && Number.isFinite(Number(c.dex)) && Number.isFinite(Number(c.roll))
          );
          const order = combatants
            .map((c) => ({ name: c.name!, score: c.roll! + c.dex!, dex: c.dex! }))
            .sort((a, b) => {
              if (b.score !== a.score) return b.score - a.score;
              if (b.dex !== a.dex) return b.dex - a.dex;
              return a.name.localeCompare(b.name);
            });
          sendJson(res, 200, { order });
        } catch {
          sendJson(res, 400, { error: 'invalid json' });
        }
      });

      server.middlewares.use('/v1/characters/ability-modifier', async (req, res, next) => {
        if (req.method !== 'POST') return next();
        try {
          const body = (await parseBody(req)) as { score?: unknown };
          const score = Number(body.score);
          if (!Number.isInteger(score) || score < 1 || score > 30) {
            return sendJson(res, 400, { error: 'invalid score' });
          }
          sendJson(res, 200, { score, modifier: computeAbilityModifier(score) });
        } catch {
          sendJson(res, 400, { error: 'invalid json' });
        }
      });

      server.middlewares.use('/v1/characters/proficiency', async (req, res, next) => {
        if (req.method !== 'POST') return next();
        try {
          const body = (await parseBody(req)) as { level?: unknown };
          const level = Number(body.level);
          if (!Number.isInteger(level) || level < 1 || level > 20) {
            return sendJson(res, 400, { error: 'invalid level' });
          }
          sendJson(res, 200, { level, proficiency_bonus: computeProficiencyBonus(level) });
        } catch {
          sendJson(res, 400, { error: 'invalid json' });
        }
      });

      server.middlewares.use('/v1/characters/derived-stats', async (req, res, next) => {
        if (req.method !== 'POST') return next();
        try {
          const body = (await parseBody(req)) as {
            level?: unknown;
            abilities?: Partial<Record<AbilityName, unknown>>;
            armor?: { base?: unknown; shield?: unknown; dex_cap?: unknown };
          };

          const level = Number(body.level);
          if (!Number.isInteger(level) || level < 1 || level > 20) {
            return sendJson(res, 400, { error: 'invalid level' });
          }

          const abilities = body.abilities ?? {};
          for (const name of ABILITY_NAMES) {
            const value = Number(abilities[name]);
            if (!Number.isInteger(value) || value < 1 || value > 30) {
              return sendJson(res, 400, { error: 'invalid abilities' });
            }
          }

          const armor = body.armor ?? { base: undefined, shield: undefined, dex_cap: undefined };
          const base = Number(armor.base);
          const dexCap = Number(armor.dex_cap);
          const shield = Boolean(armor.shield);
          if (!Number.isInteger(base) || !Number.isInteger(dexCap)) {
            return sendJson(res, 400, { error: 'invalid armor' });
          }

          const modifiers: AbilityMap = {
            str: computeAbilityModifier(Number(abilities.str)),
            dex: computeAbilityModifier(Number(abilities.dex)),
            con: computeAbilityModifier(Number(abilities.con)),
            int: computeAbilityModifier(Number(abilities.int)),
            wis: computeAbilityModifier(Number(abilities.wis)),
            cha: computeAbilityModifier(Number(abilities.cha)),
          };

          const proficiencyBonus = computeProficiencyBonus(level);
          const hpMax = level * (6 + modifiers.con);
          const shieldBonus = shield ? 2 : 0;
          const armorClass = base + Math.min(modifiers.dex, dexCap) + shieldBonus;

          sendJson(res, 200, {
            level,
            proficiency_bonus: proficiencyBonus,
            hp_max: hpMax,
            armor_class: armorClass,
            modifiers,
          });
        } catch {
          sendJson(res, 400, { error: 'invalid json' });
        }
      });

      const sessions = new Map<string, CombatSession>();

      type CombatSession = {
        id: string;
        round: number;
        turn_index: number;
        order: Array<{ name: string; score: number; dex: number }>;
        conditions: Map<string, Array<{ condition: string; remaining_rounds: number }>>;
      };

      function getSessionConditions(session: CombatSession): Record<string, Array<{ condition: string; remaining_rounds: number }>> {
        const conditions: Record<string, Array<{ condition: string; remaining_rounds: number }>> = {};
        for (const [name, list] of session.conditions.entries()) {
          if (list.length > 0) conditions[name] = list;
        }
        return conditions;
      }

      server.middlewares.use(async (req, res, next) => {
        if (req.method !== 'POST') return next();

        const url = new URL(req.url!, 'http://localhost');
        const pathname = url.pathname;

        if (pathname === '/v1/combat/sessions') {
          try {
            const body = (await parseBody(req)) as { id?: unknown; combatants?: unknown };
            if (typeof body.id !== 'string' || !body.id) {
              return sendJson(res, 400, { error: 'invalid session id' });
            }
            if (sessions.has(body.id)) {
              return sendJson(res, 400, { error: 'session already exists' });
            }
            if (!Array.isArray(body.combatants) || body.combatants.length === 0) {
              return sendJson(res, 400, { error: 'invalid combatants' });
            }
            const order: Array<{ name: string; score: number; dex: number }> = [];
            for (const c of body.combatants) {
              if (!c || typeof c !== 'object') {
                return sendJson(res, 400, { error: 'invalid combatants' });
              }
              const raw = c as { name?: unknown; dex?: unknown; roll?: unknown };
              if (typeof raw.name !== 'string' || !raw.name) {
                return sendJson(res, 400, { error: 'invalid combatant name' });
              }
              const dex = Number(raw.dex);
              const roll = Number(raw.roll);
              if (!Number.isInteger(dex) || !Number.isInteger(roll)) {
                return sendJson(res, 400, { error: 'invalid combatant scores' });
              }
              order.push({ name: raw.name, score: roll + dex, dex });
            }
            order.sort((a, b) => {
              if (b.score !== a.score) return b.score - a.score;
              if (b.dex !== a.dex) return b.dex - a.dex;
              return a.name.localeCompare(b.name);
            });

            const session: CombatSession = {
              id: body.id,
              round: 1,
              turn_index: 0,
              order,
              conditions: new Map(),
            };
            for (const c of order) {
              session.conditions.set(c.name, []);
            }
            sessions.set(body.id, session);

            sendJson(res, 200, {
              id: session.id,
              round: session.round,
              turn_index: session.turn_index,
              active: { name: session.order[0].name, score: session.order[0].score },
              order: session.order.map((c) => ({ name: c.name, score: c.score })),
            });
          } catch {
            sendJson(res, 400, { error: 'invalid json' });
          }
          return;
        }

        const match = /^\/v1\/combat\/sessions\/([^/]+)\/(conditions|advance)$/.exec(pathname);
        if (!match) return next();

        const sessionId = decodeURIComponent(match[1]);
        const session = sessions.get(sessionId);
        if (!session) {
          return sendJson(res, 404, { error: 'session not found' });
        }

        if (match[2] === 'conditions') {
          try {
            const body = (await parseBody(req)) as { target?: unknown; condition?: unknown; duration_rounds?: unknown };
            if (typeof body.target !== 'string' || !session.conditions.has(body.target)) {
              return sendJson(res, 400, { error: 'invalid target' });
            }
            if (typeof body.condition !== 'string' || !body.condition) {
              return sendJson(res, 400, { error: 'invalid condition' });
            }
            const duration = Number(body.duration_rounds);
            if (!Number.isInteger(duration) || duration <= 0) {
              return sendJson(res, 400, { error: 'invalid duration' });
            }
            const list = session.conditions.get(body.target)!;
            list.push({ condition: body.condition, remaining_rounds: duration });
            sendJson(res, 200, {
              target: body.target,
              conditions: list.map((cond) => ({ condition: cond.condition, remaining_rounds: cond.remaining_rounds })),
            });
          } catch {
            sendJson(res, 400, { error: 'invalid json' });
          }
          return;
        }

        // advance
        const nextIndex = session.turn_index + 1;
        if (nextIndex >= session.order.length) {
          session.turn_index = 0;
          session.round += 1;
        } else {
          session.turn_index = nextIndex;
        }

        const active = session.order[session.turn_index];
        const activeConditions = session.conditions.get(active.name);
        if (activeConditions) {
          for (const cond of activeConditions) {
            cond.remaining_rounds -= 1;
          }
          const remaining = activeConditions.filter((cond) => cond.remaining_rounds > 0);
          session.conditions.set(active.name, remaining);
        }

        sendJson(res, 200, {
          id: session.id,
          round: session.round,
          turn_index: session.turn_index,
          active: { name: active.name, score: active.score },
          conditions: getSessionConditions(session),
        });
      });
    },
  };
}

export default defineConfig({
  plugins: [dndApiMiddleware()],
});
