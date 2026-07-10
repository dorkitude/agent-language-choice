import { defineConfig } from 'vite';
import type { Connect, ViteDevServer } from 'vite';

type ApiHandler = (body: any) => any;

function parseBody(req: Connect.IncomingMessage): Promise<any> {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', (chunk) => {
      data += chunk;
    });
    req.on('end', () => {
      if (!data) return resolve({});
      try {
        resolve(JSON.parse(data));
      } catch {
        reject(new Error('Invalid JSON'));
      }
    });
  });
}

function sendJson(res: any, status: number, body: any) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json');
  res.end(JSON.stringify(body));
}

function route(
  server: ViteDevServer,
  path: string,
  method: string,
  handler: ApiHandler,
) {
  server.middlewares.use(path, async (req, res, next) => {
    if (req.method !== method) return next();
    try {
      const body = await parseBody(req);
      const result = handler(body);
      sendJson(res, 200, result);
    } catch (err) {
      sendJson(res, 400, { error: err instanceof Error ? err.message : String(err) });
    }
  });
}

function parseDiceStats(body: any) {
  const expression = String(body.expression ?? '');
  const match = /^(\d+)d(\d+)([+-]\d+)?$/.exec(expression);
  if (!match) throw new Error('Invalid expression');
  const diceCount = parseInt(match[1], 10);
  const sides = parseInt(match[2], 10);
  const modifier = match[3] ? parseInt(match[3], 10) : 0;
  if (diceCount <= 0 || sides <= 0) throw new Error('Invalid expression');
  const min = diceCount + modifier;
  const max = diceCount * sides + modifier;
  const average = (diceCount * (1 + sides)) / 2 + modifier;
  return { dice_count: diceCount, sides, modifier, min, max, average };
}

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

function getMultiplier(count: number): number {
  if (count === 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
  return 4;
}

function computeAdjustedXp(body: any) {
  const party = body.party;
  const monsters = body.monsters;
  if (!Array.isArray(party) || !Array.isArray(monsters)) throw new Error('Invalid request');

  let baseXp = 0;
  let monsterCount = 0;
  for (const m of monsters) {
    const xp = CR_XP[m.cr];
    if (xp === undefined) throw new Error('Unsupported CR');
    const count = m.count;
    baseXp += xp * count;
    monsterCount += count;
  }

  const multiplier = getMultiplier(monsterCount);
  const adjustedXp = baseXp * multiplier;

  const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const p of party) {
    const t = LEVEL_THRESHOLDS[p.level];
    if (!t) throw new Error('Unsupported level');
    thresholds.easy += t.easy;
    thresholds.medium += t.medium;
    thresholds.hard += t.hard;
    thresholds.deadly += t.deadly;
  }

  let difficulty = 'trivial';
  if (adjustedXp >= thresholds.deadly) difficulty = 'deadly';
  else if (adjustedXp >= thresholds.hard) difficulty = 'hard';
  else if (adjustedXp >= thresholds.medium) difficulty = 'medium';
  else if (adjustedXp >= thresholds.easy) difficulty = 'easy';

  return {
    base_xp: baseXp,
    monster_count: monsterCount,
    multiplier,
    adjusted_xp: adjustedXp,
    difficulty,
    thresholds,
  };
}

function computeInitiative(body: any) {
  const combatants = body.combatants;
  if (!Array.isArray(combatants)) throw new Error('Invalid request');
  const order = combatants
    .map((c: any) => ({ name: c.name, score: c.roll + c.dex, dex: c.dex }))
    .sort((a: any, b: any) => {
      if (b.score !== a.score) return b.score - a.score;
      if (b.dex !== a.dex) return b.dex - a.dex;
      return a.name.localeCompare(b.name);
    })
    .map((c: any) => ({ name: c.name, score: c.score }));
  return { order };
}

function abilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

function parseScore(score: any): number {
  if (!Number.isInteger(score) || score < 1 || score > 30) {
    throw new Error('Invalid score');
  }
  return score;
}

function computeAbilityModifier(body: any) {
  const score = parseScore(body.score);
  return { score, modifier: abilityModifier(score) };
}

function parseLevel(level: any): number {
  if (!Number.isInteger(level) || level < 1 || level > 20) {
    throw new Error('Invalid level');
  }
  return level;
}

function proficiencyBonus(level: number): number {
  return Math.floor((level - 1) / 4) + 2;
}

function computeProficiency(body: any) {
  const level = parseLevel(body.level);
  return { level, proficiency_bonus: proficiencyBonus(level) };
}

const ABILITY_NAMES = ['str', 'dex', 'con', 'int', 'wis', 'cha'] as const;
type AbilityName = (typeof ABILITY_NAMES)[number];

function computeDerivedStats(body: any) {
  const level = parseLevel(body.level);

  const abilities = body.abilities;
  if (!abilities || typeof abilities !== 'object') throw new Error('Invalid abilities');
  const modifiers: Record<AbilityName, number> = { str: 0, dex: 0, con: 0, int: 0, wis: 0, cha: 0 };
  for (const name of ABILITY_NAMES) {
    modifiers[name] = abilityModifier(parseScore(abilities[name]));
  }

  const armor = body.armor;
  if (!armor || typeof armor !== 'object') throw new Error('Invalid armor');
  const base = typeof armor.base === 'number' ? armor.base : parseInt(armor.base, 10);
  if (!Number.isFinite(base)) throw new Error('Invalid armor base');
  const dexCap = typeof armor.dex_cap === 'number' ? armor.dex_cap : parseInt(armor.dex_cap, 10);
  if (!Number.isFinite(dexCap) || dexCap < 0) throw new Error('Invalid armor dex_cap');
  const shieldBonus = armor.shield === true ? 2 : 0;
  const armorClass = base + Math.min(modifiers.dex, dexCap) + shieldBonus;

  const hpMax = level * (6 + modifiers.con);

  return {
    level,
    proficiency_bonus: proficiencyBonus(level),
    hp_max: hpMax,
    armor_class: armorClass,
    modifiers,
  };
}

type CombatCondition = { condition: string; remaining_rounds: number };

type Combatant = {
  name: string;
  score: number;
  dex: number;
  conditions: CombatCondition[];
};

type CombatSession = {
  id: string;
  round: number;
  turn_index: number;
  combatants: Combatant[];
};

const combatSessions = new Map<string, CombatSession>();

function createCombatSession(body: any): any {
  const id = body.id;
  if (typeof id !== 'string' || !id) throw new Error('Invalid id');
  if (combatSessions.has(id)) throw new Error('Session already exists');

  const combatantsInput = body.combatants;
  if (!Array.isArray(combatantsInput) || combatantsInput.length === 0) {
    throw new Error('Invalid combatants');
  }

  const seenNames = new Set<string>();
  const combatants: Combatant[] = combatantsInput.map((c: any) => {
    const name = String(c.name ?? '');
    const dex = c.dex;
    const roll = c.roll;
    if (!name || !Number.isInteger(dex) || !Number.isInteger(roll)) {
      throw new Error('Invalid combatant');
    }
    if (seenNames.has(name)) throw new Error('Duplicate combatant name');
    seenNames.add(name);
    return { name, score: roll + dex, dex, conditions: [] };
  });

  combatants.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name.localeCompare(b.name);
  });

  const session: CombatSession = { id, round: 1, turn_index: 0, combatants };
  combatSessions.set(id, session);
  return formatCombatSession(session);
}

function formatCombatSession(session: CombatSession): any {
  const active = session.combatants[session.turn_index];
  return {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: { name: active.name, score: active.score },
    order: session.combatants.map((c) => ({ name: c.name, score: c.score })),
  };
}

function formatCombatConditions(session: CombatSession): any {
  const conditions: Record<string, { condition: string; remaining_rounds: number }[]> = {};
  for (const c of session.combatants) {
    conditions[c.name] = c.conditions.map((cond) => ({
      condition: cond.condition,
      remaining_rounds: cond.remaining_rounds,
    }));
  }
  return conditions;
}

function addCombatCondition(session: CombatSession, body: any): any {
  const target = String(body.target ?? '');
  const condition = String(body.condition ?? '');
  const duration = body.duration_rounds;
  if (!target || !condition || !Number.isInteger(duration) || duration <= 0) {
    throw new Error('Invalid request');
  }

  const combatant = session.combatants.find((c) => c.name === target);
  if (!combatant) throw new Error('Unknown target');

  combatant.conditions.push({ condition, remaining_rounds: duration });
  return {
    target,
    conditions: combatant.conditions.map((c) => ({
      condition: c.condition,
      remaining_rounds: c.remaining_rounds,
    })),
  };
}

function advanceCombatTurn(session: CombatSession): any {
  session.turn_index += 1;
  if (session.turn_index >= session.combatants.length) {
    session.turn_index = 0;
    session.round += 1;
  }

  const active = session.combatants[session.turn_index];
  active.conditions = active.conditions
    .map((c) => ({ condition: c.condition, remaining_rounds: c.remaining_rounds - 1 }))
    .filter((c) => c.remaining_rounds > 0);

  return {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: { name: active.name, score: active.score },
    conditions: formatCombatConditions(session),
  };
}

function combatRoutes(server: ViteDevServer) {
  server.middlewares.use('/', async (req, res, next) => {
    if (req.method !== 'POST') return next();
    const url = (req.url ?? '').replace(/\?.*$/, '');

    if (url === '/v1/combat/sessions' || url === '/v1/combat/sessions/') {
      try {
        const body = await parseBody(req);
        const result = createCombatSession(body);
        sendJson(res, 200, result);
      } catch (err) {
        sendJson(res, 400, { error: err instanceof Error ? err.message : String(err) });
      }
      return;
    }

    const match = /^\/v1\/combat\/sessions\/([^/]+)\/(conditions|advance)$/.exec(url);
    if (!match) return next();

    const id = decodeURIComponent(match[1]);
    const action = match[2];
    const session = combatSessions.get(id);
    if (!session) {
      sendJson(res, 404, { error: 'Session not found' });
      return;
    }

    try {
      const body = await parseBody(req);
      const result = action === 'conditions'
        ? addCombatCondition(session, body)
        : advanceCombatTurn(session);
      sendJson(res, 200, result);
    } catch (err) {
      sendJson(res, 400, { error: err instanceof Error ? err.message : String(err) });
    }
  });
}

function dndApi() {
  return {
    name: 'dnd-api',
    configureServer(server: ViteDevServer) {
      route(server, '/health', 'GET', () => ({ ok: true }));
      route(server, '/v1/dice/stats', 'POST', parseDiceStats);
      route(server, '/v1/checks/ability', 'POST', (body: any) => {
        const total = body.roll + body.modifier;
        return { total, success: total >= body.dc, margin: total - body.dc };
      });
      route(server, '/v1/encounters/adjusted-xp', 'POST', computeAdjustedXp);
      route(server, '/v1/initiative/order', 'POST', computeInitiative);
      route(server, '/v1/characters/ability-modifier', 'POST', computeAbilityModifier);
      route(server, '/v1/characters/proficiency', 'POST', computeProficiency);
      route(server, '/v1/characters/derived-stats', 'POST', computeDerivedStats);
      combatRoutes(server);
    },
  };
}

export default defineConfig({
  plugins: [dndApi()],
});
