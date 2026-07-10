import type { IncomingMessage, ServerResponse } from 'node:http';

// ---------------------------------------------------------------------------
// D&D REST engine — connect-style middleware mounted on the Vite dev server.
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

const THRESHOLDS_BY_LEVEL: Record<number, LevelThresholds> = {
  3: { easy: 75, medium: 150, hard: 225, deadly: 400 },
};

function multiplierFor(count: number): number {
  if (count <= 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
  return 4;
}

// --- helpers ---------------------------------------------------------------

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
    req.on('data', (c: Buffer) => chunks.push(c));
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}

async function parseJsonBody(req: IncomingMessage): Promise<Record<string, unknown> | null> {
  const raw = await readBody(req);
  if (raw.length === 0) return null;
  try {
    const parsed = JSON.parse(raw);
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return null;
    }
    return parsed as Record<string, unknown>;
  } catch {
    return null;
  }
}

function asNumber(value: unknown, fallback = 0): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && /^-?\d+(\.\d+)?$/.test(value.trim())) {
    return Number(value.trim());
  }
  return fallback;
}

// --- endpoint handlers -----------------------------------------------------

interface ParsedDice {
  count: number;
  sides: number;
  modifier: number;
}

function parseExpression(expr: string): ParsedDice | null {
  const m = /^(\d+)d(\d+)(?:([+-])(\d+))?$/.exec(expr);
  if (!m) return null;
  const count = parseInt(m[1]!, 10);
  const sides = parseInt(m[2]!, 10);
  if (count <= 0 || sides <= 0) return null;
  let modifier = 0;
  if (m[3] && m[4]) {
    modifier = parseInt(m[4], 10);
    if (m[3] === '-') modifier = -modifier;
  }
  return { count, sides, modifier };
}

async function handleDiceStats(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const body = await parseJsonBody(req);
  if (!body) {
    sendJson(res, 400, { error: 'invalid_json' });
    return;
  }
  const expr = body.expression;
  if (typeof expr !== 'string') {
    sendJson(res, 400, { error: 'invalid_expression' });
    return;
  }
  const parsed = parseExpression(expr.trim());
  if (!parsed) {
    sendJson(res, 400, { error: 'invalid_expression' });
    return;
  }
  const { count, sides, modifier } = parsed;
  const min = count + modifier;
  const max = count * sides + modifier;
  const average = (min + max) / 2;
  sendJson(res, 200, {
    dice_count: count,
    sides,
    modifier,
    min,
    max,
    average,
  });
}

async function handleAbilityCheck(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const body = await parseJsonBody(req);
  if (!body) {
    sendJson(res, 400, { error: 'invalid_json' });
    return;
  }
  const roll = asNumber(body.roll);
  const modifier = asNumber(body.modifier);
  const dc = asNumber(body.dc);
  const total = roll + modifier;
  const success = total >= dc;
  const margin = total - dc;
  sendJson(res, 200, { total, success, margin });
}

async function handleAdjustedXp(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const body = await parseJsonBody(req);
  if (!body) {
    sendJson(res, 400, { error: 'invalid_json' });
    return;
  }
  const party = Array.isArray(body.party) ? body.party : [];
  const monsters = Array.isArray(body.monsters) ? body.monsters : [];

  let baseXp = 0;
  let monsterCount = 0;
  for (const mon of monsters) {
    const cr = mon && typeof mon === 'object' ? String((mon as Record<string, unknown>).cr) : '';
    const count = asNumber((mon as Record<string, unknown> | null)?.count);
    const xp = XP_BY_CR[cr];
    if (xp === undefined) {
      sendJson(res, 400, { error: 'unknown_cr', cr });
      return;
    }
    baseXp += xp * count;
    monsterCount += count;
  }

  const multiplier = multiplierFor(monsterCount);
  const adjustedXp = baseXp * multiplier;

  let easy = 0;
  let medium = 0;
  let hard = 0;
  let deadly = 0;
  for (const member of party) {
    const level = asNumber((member as Record<string, unknown> | null)?.level);
    const t = THRESHOLDS_BY_LEVEL[level];
    if (!t) {
      sendJson(res, 400, { error: 'unknown_level', level });
      return;
    }
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
}

async function handleInitiativeOrder(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const body = await parseJsonBody(req);
  if (!body) {
    sendJson(res, 400, { error: 'invalid_json' });
    return;
  }
  const combatants = Array.isArray(body.combatants) ? body.combatants : [];

  const scored = combatants.map((c) => {
    const obj = (c && typeof c === 'object' ? c : {}) as Record<string, unknown>;
    const name = typeof obj.name === 'string' ? obj.name : String(obj.name ?? '');
    const dex = asNumber(obj.dex);
    const roll = asNumber(obj.roll);
    return { name, dex, roll, score: roll + dex };
  });

  scored.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score; // score descending
    if (b.dex !== a.dex) return b.dex - a.dex; // dex descending
    return a.name < b.name ? -1 : a.name > b.name ? 1 : 0; // name ascending
  });

  const order = scored.map((c) => ({ name: c.name, score: c.score }));
  sendJson(res, 200, { order });
}

// --- character rules ------------------------------------------------------

const ABILITY_KEYS = ['str', 'dex', 'con', 'int', 'wis', 'cha'] as const;

function abilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

function proficiencyBonus(level: number): number {
  return 2 + Math.floor((level - 1) / 4);
}

function asInteger(value: unknown): number | null {
  if (typeof value === 'number' && Number.isInteger(value)) return value;
  return null;
}

function asFiniteNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  return null;
}

async function handleAbilityModifier(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const body = await parseJsonBody(req);
  if (!body) {
    sendJson(res, 400, { error: 'invalid_json' });
    return;
  }
  const score = asInteger(body.score);
  if (score === null || score < 1 || score > 30) {
    sendJson(res, 400, { error: 'invalid_score' });
    return;
  }
  sendJson(res, 200, { score, modifier: abilityModifier(score) });
}

async function handleProficiency(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const body = await parseJsonBody(req);
  if (!body) {
    sendJson(res, 400, { error: 'invalid_json' });
    return;
  }
  const level = asInteger(body.level);
  if (level === null || level < 1 || level > 20) {
    sendJson(res, 400, { error: 'invalid_level' });
    return;
  }
  sendJson(res, 200, { level, proficiency_bonus: proficiencyBonus(level) });
}

async function handleDerivedStats(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const body = await parseJsonBody(req);
  if (!body) {
    sendJson(res, 400, { error: 'invalid_json' });
    return;
  }
  const level = asInteger(body.level);
  if (level === null || level < 1 || level > 20) {
    sendJson(res, 400, { error: 'invalid_level' });
    return;
  }

  const abilitiesSrc = body.abilities;
  if (!abilitiesSrc || typeof abilitiesSrc !== 'object' || Array.isArray(abilitiesSrc)) {
    sendJson(res, 400, { error: 'invalid_abilities' });
    return;
  }
  const abilitiesObj = abilitiesSrc as Record<string, unknown>;
  const modifiers: Record<string, number> = {};
  for (const key of ABILITY_KEYS) {
    const score = asInteger(abilitiesObj[key]);
    if (score === null || score < 1 || score > 30) {
      sendJson(res, 400, { error: 'invalid_ability', ability: key });
      return;
    }
    modifiers[key] = abilityModifier(score);
  }

  const armorSrc = body.armor;
  if (!armorSrc || typeof armorSrc !== 'object' || Array.isArray(armorSrc)) {
    sendJson(res, 400, { error: 'invalid_armor' });
    return;
  }
  const armorObj = armorSrc as Record<string, unknown>;
  const base = asFiniteNumber(armorObj.base);
  if (base === null) {
    sendJson(res, 400, { error: 'invalid_armor_base' });
    return;
  }
  const dexCap = asFiniteNumber(armorObj.dex_cap);
  if (dexCap === null) {
    sendJson(res, 400, { error: 'invalid_armor_dex_cap' });
    return;
  }
  const shieldBonus = armorObj.shield === true ? 2 : 0;

  const dexMod = modifiers['dex']!;
  const conMod = modifiers['con']!;
  const hpMax = level * (6 + conMod);
  const armorClass = base + Math.min(dexMod, dexCap) + shieldBonus;

  sendJson(res, 200, {
    level,
    proficiency_bonus: proficiencyBonus(level),
    hp_max: hpMax,
    armor_class: armorClass,
    modifiers,
  });
}

// --- combat sessions (stateful, in-memory) --------------------------------

interface Combatant {
  name: string;
  dex: number;
  roll: number;
  score: number;
}

interface ConditionEntry {
  condition: string;
  remaining_rounds: number;
}

interface CombatSession {
  id: string;
  round: number;
  turn_index: number;
  order: Combatant[];
  conditions: Map<string, ConditionEntry[]>;
}

const sessions: Map<string, CombatSession> = new Map();

function sortInitiative(order: Combatant[]): void {
  order.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score; // score descending
    if (b.dex !== a.dex) return b.dex - a.dex; // dex descending
    return a.name < b.name ? -1 : a.name > b.name ? 1 : 0; // name ascending
  });
}

async function handleCreateCombatSession(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const body = await parseJsonBody(req);
  if (!body) {
    sendJson(res, 400, { error: 'invalid_json' });
    return;
  }
  const id = body.id;
  if (typeof id !== 'string' || id.length === 0) {
    sendJson(res, 400, { error: 'invalid_id' });
    return;
  }
  const combatantsIn = body.combatants;
  if (!Array.isArray(combatantsIn) || combatantsIn.length === 0) {
    sendJson(res, 400, { error: 'invalid_combatants' });
    return;
  }
  const order: Combatant[] = [];
  for (const c of combatantsIn) {
    const obj = (c && typeof c === 'object' ? c : {}) as Record<string, unknown>;
    const name = obj.name;
    if (typeof name !== 'string' || name.length === 0) {
      sendJson(res, 400, { error: 'invalid_combatant' });
      return;
    }
    const dex = asNumber(obj.dex);
    const roll = asNumber(obj.roll);
    order.push({ name, dex, roll, score: roll + dex });
  }
  sortInitiative(order);
  const session: CombatSession = {
    id,
    round: 1,
    turn_index: 0,
    order,
    conditions: new Map(),
  };
  sessions.set(id, session);
  sendJson(res, 200, {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: { name: order[0]!.name, score: order[0]!.score },
    order: order.map((c) => ({ name: c.name, score: c.score })),
  });
}

async function handleAddCondition(
  req: IncomingMessage,
  res: ServerResponse,
  params: Record<string, string>,
): Promise<void> {
  const session = sessions.get(params.id);
  if (!session) {
    sendJson(res, 404, { error: 'unknown_session' });
    return;
  }
  const body = await parseJsonBody(req);
  if (!body) {
    sendJson(res, 400, { error: 'invalid_json' });
    return;
  }
  const target = body.target;
  if (typeof target !== 'string') {
    sendJson(res, 400, { error: 'invalid_target' });
    return;
  }
  if (!session.order.some((c) => c.name === target)) {
    sendJson(res, 400, { error: 'unknown_target' });
    return;
  }
  const condition = body.condition;
  if (typeof condition !== 'string') {
    sendJson(res, 400, { error: 'invalid_condition' });
    return;
  }
  const duration = asInteger(body.duration_rounds);
  if (duration === null || duration <= 0) {
    sendJson(res, 400, { error: 'invalid_duration' });
    return;
  }
  const list = session.conditions.get(target) ?? [];
  list.push({ condition, remaining_rounds: duration });
  session.conditions.set(target, list);
  sendJson(res, 200, {
    target,
    conditions: list.map((c) => ({ condition: c.condition, remaining_rounds: c.remaining_rounds })),
  });
}

async function handleAdvanceTurn(
  req: IncomingMessage,
  res: ServerResponse,
  params: Record<string, string>,
): Promise<void> {
  const session = sessions.get(params.id);
  if (!session) {
    sendJson(res, 404, { error: 'unknown_session' });
    return;
  }
  // Advance takes no payload; drain any body so the connection stays clean.
  await readBody(req).catch(() => undefined);
  const order = session.order;
  const prevIndex = session.turn_index;
  const nextIndex = (prevIndex + 1) % order.length;
  if (prevIndex === order.length - 1) {
    session.round += 1;
  }
  session.turn_index = nextIndex;
  const active = order[nextIndex]!;
  // At the start of the new active combatant's turn, tick down their conditions.
  const activeConds = session.conditions.get(active.name);
  if (activeConds) {
    for (const c of activeConds) c.remaining_rounds -= 1;
    session.conditions.set(
      active.name,
      activeConds.filter((c) => c.remaining_rounds > 0),
    );
  }
  // A combatant that has (or ever had) a condition tracked in the session
  // is always represented in the response — even after every condition on
  // them has expired and been removed, so callers can see the empty list.
  const conditionsResp: Record<string, { condition: string; remaining_rounds: number }[]> = {};
  for (const c of order) {
    const list = session.conditions.get(c.name);
    if (list) {
      conditionsResp[c.name] = list.map((x) => ({
        condition: x.condition,
        remaining_rounds: x.remaining_rounds,
      }));
    }
  }
  sendJson(res, 200, {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: { name: active.name, score: active.score },
    conditions: conditionsResp,
  });
}

// --- router ----------------------------------------------------------------

type AsyncHandler = (req: IncomingMessage, res: ServerResponse) => Promise<void>;
type DynamicHandler = (
  req: IncomingMessage,
  res: ServerResponse,
  params: Record<string, string>,
) => Promise<void>;

interface DynamicRoute {
  pattern: RegExp;
  handler: DynamicHandler;
}

const POST_ROUTES: Record<string, AsyncHandler> = {
  '/v1/dice/stats': handleDiceStats,
  '/v1/checks/ability': handleAbilityCheck,
  '/v1/encounters/adjusted-xp': handleAdjustedXp,
  '/v1/initiative/order': handleInitiativeOrder,
  '/v1/characters/ability-modifier': handleAbilityModifier,
  '/v1/characters/proficiency': handleProficiency,
  '/v1/characters/derived-stats': handleDerivedStats,
  '/v1/combat/sessions': handleCreateCombatSession,
};

const DYNAMIC_POST_ROUTES: DynamicRoute[] = [
  { pattern: /^\/v1\/combat\/sessions\/([^/]+)\/conditions$/, handler: handleAddCondition },
  { pattern: /^\/v1\/combat\/sessions\/([^/]+)\/advance$/, handler: handleAdvanceTurn },
];

type NextFunction = (err?: unknown) => void;

export function apiMiddleware(
  req: IncomingMessage,
  res: ServerResponse,
  next: NextFunction,
): void {
  const url = (req.url ?? '').split('?')[0] ?? '';
  const method = req.method ?? '';

  if (url === '/health' && method === 'GET') {
    sendJson(res, 200, { ok: true });
    return;
  }

  if (url.startsWith('/v1/')) {
    if (method === 'POST') {
      const handler = POST_ROUTES[url];
      if (handler) {
        Promise.resolve(handler(req, res)).catch(() => {
          if (!res.headersSent) sendJson(res, 500, { error: 'server_error' });
        });
        return;
      }
      for (const route of DYNAMIC_POST_ROUTES) {
        const m = route.pattern.exec(url);
        if (m) {
          const params: Record<string, string> = { id: decodeURIComponent(m[1] ?? '') };
          Promise.resolve(route.handler(req, res, params)).catch(() => {
            if (!res.headersSent) sendJson(res, 500, { error: 'server_error' });
          });
          return;
        }
      }
    }
    sendJson(res, 404, { error: 'not_found' });
    return;
  }

  // Everything else (static assets, HMR, index.html) is handled by Vite.
  next();
}
