// Core D&D REST engine logic. Pure functions plus a small dispatcher so the
// same handlers can be mounted on Vite dev-server middleware.

export interface ApiResult {
  status: number;
  body: unknown;
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

// Level -> [easy, medium, hard, deadly] per-character thresholds.
const LEVEL_THRESHOLDS: Record<number, [number, number, number, number]> = {
  3: [75, 150, 225, 400],
};

function bad(message: string): ApiResult {
  return { status: 400, body: { error: message } };
}

function isInteger(n: unknown): n is number {
  return typeof n === 'number' && Number.isInteger(n);
}

export function diceStats(body: any): ApiResult {
  if (!body || typeof body.expression !== 'string') {
    return bad('expression must be a string');
  }
  const match = /^(\d+)d(\d+)([+-]\d+)?$/.exec(body.expression.trim());
  if (!match) return bad('invalid dice expression');

  const count = parseInt(match[1], 10);
  const sides = parseInt(match[2], 10);
  const modifier = match[3] ? parseInt(match[3], 10) : 0;

  if (count <= 0 || sides <= 0) return bad('count and sides must be positive');

  const min = count * 1 + modifier;
  const max = count * sides + modifier;
  const average = (min + max) / 2;

  return {
    status: 200,
    body: {
      dice_count: count,
      sides,
      modifier,
      min,
      max,
      average,
    },
  };
}

export function abilityCheck(body: any): ApiResult {
  if (!body || !isInteger(body.roll) || !isInteger(body.modifier) || !isInteger(body.dc)) {
    return bad('roll, modifier, and dc must be integers');
  }
  const total = body.roll + body.modifier;
  return {
    status: 200,
    body: {
      total,
      success: total >= body.dc,
      margin: total - body.dc,
    },
  };
}

function countMultiplier(monsterCount: number): number {
  if (monsterCount <= 1) return 1;
  if (monsterCount === 2) return 1.5;
  if (monsterCount <= 6) return 2;
  if (monsterCount <= 10) return 2.5;
  if (monsterCount <= 14) return 3;
  return 4;
}

export function adjustedXp(body: any): ApiResult {
  if (!body || !Array.isArray(body.party) || !Array.isArray(body.monsters)) {
    return bad('party and monsters must be arrays');
  }

  const thresholdTotals = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const member of body.party) {
    if (!member || !isInteger(member.level)) return bad('party member level must be an integer');
    const row = LEVEL_THRESHOLDS[member.level];
    if (!row) return bad(`unsupported party level: ${member.level}`);
    thresholdTotals.easy += row[0];
    thresholdTotals.medium += row[1];
    thresholdTotals.hard += row[2];
    thresholdTotals.deadly += row[3];
  }

  let baseXp = 0;
  let monsterCount = 0;
  for (const m of body.monsters) {
    if (!m || typeof m.cr !== 'string' || !isInteger(m.count)) {
      return bad('monster cr must be a string and count an integer');
    }
    const xp = CR_XP[m.cr];
    if (xp === undefined) return bad(`unsupported cr: ${m.cr}`);
    if (m.count < 0) return bad('monster count must be non-negative');
    baseXp += xp * m.count;
    monsterCount += m.count;
  }

  const multiplier = countMultiplier(monsterCount);
  const adjusted = baseXp * multiplier;

  let difficulty = 'trivial';
  if (adjusted >= thresholdTotals.deadly) difficulty = 'deadly';
  else if (adjusted >= thresholdTotals.hard) difficulty = 'hard';
  else if (adjusted >= thresholdTotals.medium) difficulty = 'medium';
  else if (adjusted >= thresholdTotals.easy) difficulty = 'easy';

  return {
    status: 200,
    body: {
      base_xp: baseXp,
      monster_count: monsterCount,
      multiplier,
      adjusted_xp: adjusted,
      difficulty,
      thresholds: thresholdTotals,
    },
  };
}

export function initiativeOrder(body: any): ApiResult {
  if (!body || !Array.isArray(body.combatants)) {
    return bad('combatants must be an array');
  }
  const combatants = body.combatants.map((c: any) => {
    if (!c || typeof c.name !== 'string' || !isInteger(c.dex) || !isInteger(c.roll)) {
      return null;
    }
    return { name: c.name, dex: c.dex, score: c.roll + c.dex };
  });
  if (combatants.some((c: any) => c === null)) {
    return bad('each combatant needs name (string), dex (int), roll (int)');
  }

  combatants.sort((a: any, b: any) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
  });

  return {
    status: 200,
    body: {
      order: combatants.map((c: any) => ({ name: c.name, score: c.score })),
    },
  };
}

function abilityModifierValue(score: number): number {
  return Math.floor((score - 10) / 2);
}

function proficiencyBonusValue(level: number): number {
  return Math.floor((level - 1) / 4) + 2;
}

export function abilityModifier(body: any): ApiResult {
  if (!body || !isInteger(body.score) || body.score < 1 || body.score > 30) {
    return bad('score must be an integer from 1 to 30');
  }
  return {
    status: 200,
    body: { score: body.score, modifier: abilityModifierValue(body.score) },
  };
}

export function proficiency(body: any): ApiResult {
  if (!body || !isInteger(body.level) || body.level < 1 || body.level > 20) {
    return bad('level must be an integer from 1 to 20');
  }
  return {
    status: 200,
    body: { level: body.level, proficiency_bonus: proficiencyBonusValue(body.level) },
  };
}

const ABILITY_KEYS = ['str', 'dex', 'con', 'int', 'wis', 'cha'] as const;

export function derivedStats(body: any): ApiResult {
  if (!body || !isInteger(body.level) || body.level < 1 || body.level > 20) {
    return bad('level must be an integer from 1 to 20');
  }
  const abilities = body.abilities;
  if (!abilities || typeof abilities !== 'object') {
    return bad('abilities must be an object');
  }
  const modifiers: Record<string, number> = {};
  for (const key of ABILITY_KEYS) {
    const score = abilities[key];
    if (!isInteger(score) || score < 1 || score > 30) {
      return bad(`ability ${key} must be an integer from 1 to 30`);
    }
    modifiers[key] = abilityModifierValue(score);
  }

  const armor = body.armor;
  if (!armor || typeof armor !== 'object') {
    return bad('armor must be an object');
  }
  if (!isInteger(armor.base)) return bad('armor.base must be an integer');
  if (typeof armor.shield !== 'boolean') return bad('armor.shield must be a boolean');
  if (!isInteger(armor.dex_cap)) return bad('armor.dex_cap must be an integer');

  const proficiencyBonus = proficiencyBonusValue(body.level);
  const hpMax = body.level * (6 + modifiers.con);
  const shieldBonus = armor.shield ? 2 : 0;
  const armorClass = armor.base + Math.min(modifiers.dex, armor.dex_cap) + shieldBonus;

  return {
    status: 200,
    body: {
      level: body.level,
      proficiency_bonus: proficiencyBonus,
      hp_max: hpMax,
      armor_class: armorClass,
      modifiers,
    },
  };
}

// --- Stateful combat (Maintenance Stage 2) ----------------------------------

interface ConditionState {
  condition: string;
  remaining_rounds: number;
}

interface CombatantState {
  name: string;
  dex: number;
  score: number;
}

interface CombatSession {
  id: string;
  order: CombatantState[];
  round: number;
  turn_index: number;
  conditions: Map<string, ConditionState[]>;
}

// In-memory session store; lives for the process lifetime only.
const sessions = new Map<string, CombatSession>();

function notFound(message: string): ApiResult {
  return { status: 404, body: { error: message } };
}

function activeView(session: CombatSession): { name: string; score: number } {
  const c = session.order[session.turn_index];
  return { name: c.name, score: c.score };
}

function conditionsView(session: CombatSession): Record<string, ConditionState[]> {
  const out: Record<string, ConditionState[]> = {};
  for (const c of session.order) {
    const list = session.conditions.get(c.name);
    // Once a combatant has had a condition tracked, keep its key present even
    // after all conditions expire (the map entry becomes an empty array).
    if (list) {
      out[c.name] = list.map((x) => ({ ...x }));
    }
  }
  return out;
}

export function createCombatSession(body: any): ApiResult {
  if (!body || typeof body.id !== 'string' || body.id.length === 0) {
    return bad('id must be a non-empty string');
  }
  if (!Array.isArray(body.combatants) || body.combatants.length === 0) {
    return bad('combatants must be a non-empty array');
  }
  if (sessions.has(body.id)) {
    return bad(`session id already exists: ${body.id}`);
  }

  const combatants: CombatantState[] = [];
  for (const c of body.combatants) {
    if (!c || typeof c.name !== 'string' || !isInteger(c.dex) || !isInteger(c.roll)) {
      return bad('each combatant needs name (string), dex (int), roll (int)');
    }
    combatants.push({ name: c.name, dex: c.dex, score: c.roll + c.dex });
  }

  combatants.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
  });

  const session: CombatSession = {
    id: body.id,
    order: combatants,
    round: 1,
    turn_index: 0,
    conditions: new Map(),
  };
  sessions.set(session.id, session);

  return {
    status: 200,
    body: {
      id: session.id,
      round: session.round,
      turn_index: session.turn_index,
      active: activeView(session),
      order: session.order.map((c) => ({ name: c.name, score: c.score })),
    },
  };
}

export function addCondition(id: string, body: any): ApiResult {
  const session = sessions.get(id);
  if (!session) return notFound(`unknown session: ${id}`);

  if (!body || typeof body.target !== 'string') {
    return bad('target must be a string');
  }
  if (typeof body.condition !== 'string' || body.condition.length === 0) {
    return bad('condition must be a non-empty string');
  }
  if (!isInteger(body.duration_rounds) || body.duration_rounds <= 0) {
    return bad('duration_rounds must be a positive integer');
  }
  if (!session.order.some((c) => c.name === body.target)) {
    return bad(`unknown combatant: ${body.target}`);
  }

  const list = session.conditions.get(body.target) ?? [];
  list.push({ condition: body.condition, remaining_rounds: body.duration_rounds });
  session.conditions.set(body.target, list);

  return {
    status: 200,
    body: {
      target: body.target,
      conditions: list.map((x) => ({ ...x })),
    },
  };
}

export function advanceTurn(id: string): ApiResult {
  const session = sessions.get(id);
  if (!session) return notFound(`unknown session: ${id}`);

  session.turn_index += 1;
  if (session.turn_index >= session.order.length) {
    session.turn_index = 0;
    session.round += 1;
  }

  // Start of the newly active combatant's turn: decrement its conditions.
  const active = session.order[session.turn_index];
  const list = session.conditions.get(active.name);
  if (list) {
    const remaining = list
      .map((c) => ({ condition: c.condition, remaining_rounds: c.remaining_rounds - 1 }))
      .filter((c) => c.remaining_rounds > 0);
    // Keep the map entry (as an empty array) so the combatant still appears in
    // the conditions view after its last condition expires.
    session.conditions.set(active.name, remaining);
  }

  return {
    status: 200,
    body: {
      id: session.id,
      round: session.round,
      turn_index: session.turn_index,
      active: activeView(session),
      conditions: conditionsView(session),
    },
  };
}

// --- Routing ----------------------------------------------------------------

export interface Route {
  method: string;
  path: string;
  handler: (body: any) => ApiResult;
}

export const routes: Route[] = [
  { method: 'POST', path: '/v1/dice/stats', handler: diceStats },
  { method: 'POST', path: '/v1/checks/ability', handler: abilityCheck },
  { method: 'POST', path: '/v1/encounters/adjusted-xp', handler: adjustedXp },
  { method: 'POST', path: '/v1/initiative/order', handler: initiativeOrder },
  { method: 'POST', path: '/v1/characters/ability-modifier', handler: abilityModifier },
  { method: 'POST', path: '/v1/characters/proficiency', handler: proficiency },
  { method: 'POST', path: '/v1/characters/derived-stats', handler: derivedStats },
];

// Dispatch a request to the matching handler. Returns null when no route
// matches so the caller can fall through to Vite's own middleware.
export function dispatch(method: string, url: string, body: any): ApiResult | null {
  const staticRoute = routes.find((r) => r.method === method && r.path === url);
  if (staticRoute) return staticRoute.handler(body);

  if (method === 'POST' && url === '/v1/combat/sessions') {
    return createCombatSession(body);
  }

  const condMatch = /^\/v1\/combat\/sessions\/([^/]+)\/conditions$/.exec(url);
  if (condMatch && method === 'POST') {
    return addCondition(decodeURIComponent(condMatch[1]), body);
  }

  const advMatch = /^\/v1\/combat\/sessions\/([^/]+)\/advance$/.exec(url);
  if (advMatch && method === 'POST') {
    return advanceTurn(decodeURIComponent(advMatch[1]));
  }

  return null;
}
