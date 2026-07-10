import http from 'node:http';

// --- Dice expression parsing ---
// Grammar: <count>d<sides>[+<modifier>|-<modifier>]
// count and sides must be positive (no leading zeros allowed); modifier optional.
const DICE_RE = /^([1-9]\d*)d([1-9]\d*)(?:([+-])(\d+))?$/;

// --- Encounter tables ---
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

// --- Character rules ---
const ABILITY_NAMES = ['str', 'dex', 'con', 'int', 'wis', 'cha'] as const;

function isValidScore(score: unknown): score is number {
  return typeof score === 'number' && Number.isInteger(score) && score >= 1 && score <= 30;
}

function isValidLevel(level: unknown): level is number {
  return typeof level === 'number' && Number.isInteger(level) && level >= 1 && level <= 20;
}

// modifier = floor((score - 10) / 2); floors negative halves correctly.
function abilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

// 1-4 -> 2, 5-8 -> 3, 9-12 -> 4, 13-16 -> 5, 17-20 -> 6.
function proficiencyBonus(level: number): number {
  return 2 + Math.floor((level - 1) / 4);
}

// --- HTTP helpers ---
function sendJson(res: http.ServerResponse, status: number, obj: unknown): void {
  const body = JSON.stringify(obj);
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(body),
  });
  res.end(body);
}

function readJsonBody(req: http.IncomingMessage): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on('data', (chunk: Buffer) => chunks.push(chunk));
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8');
      if (raw.length === 0) {
        reject(new Error('empty body'));
        return;
      }
      try {
        resolve(JSON.parse(raw));
      } catch (e) {
        reject(e);
      }
    });
    req.on('error', reject);
  });
}

function drainBody(req: http.IncomingMessage): Promise<void> {
  return new Promise((resolve) => {
    req.on('data', () => {});
    req.on('end', () => resolve());
    req.on('error', () => resolve());
  });
}

function asRecord(body: unknown): Record<string, unknown> | null {
  if (typeof body !== 'object' || body === null) return null;
  return body as Record<string, unknown>;
}

// --- Endpoint handlers ---
function diceStats(res: http.ServerResponse, body: unknown): void {
  const rec = asRecord(body);
  if (!rec) return sendJson(res, 400, { error: 'invalid expression' });
  const expression = rec.expression;
  if (typeof expression !== 'string') {
    return sendJson(res, 400, { error: 'invalid expression' });
  }
  const m = expression.match(DICE_RE);
  if (!m) return sendJson(res, 400, { error: 'invalid expression' });

  const dice_count = parseInt(m[1] as string, 10);
  const sides = parseInt(m[2] as string, 10);
  const sign = m[3] ?? '+';
  let modifier = parseInt(m[4] ?? '0', 10);
  if (sign === '-') modifier = -modifier;

  const min = dice_count + modifier;
  const max = dice_count * sides + modifier;
  const average = (min + max) / 2;

  return sendJson(res, 200, { dice_count, sides, modifier, min, max, average });
}

function abilityCheck(res: http.ServerResponse, body: unknown): void {
  const rec = asRecord(body);
  if (!rec) return sendJson(res, 400, { error: 'invalid input' });
  const { roll, modifier, dc } = rec;
  if (
    typeof roll !== 'number' || !Number.isFinite(roll) ||
    typeof modifier !== 'number' || !Number.isFinite(modifier) ||
    typeof dc !== 'number' || !Number.isFinite(dc)
  ) {
    return sendJson(res, 400, { error: 'invalid input' });
  }
  const total = roll + modifier;
  const success = total >= dc;
  const margin = total - dc;
  return sendJson(res, 200, { total, success, margin });
}

function adjustedXp(res: http.ServerResponse, body: unknown): void {
  const rec = asRecord(body);
  if (!rec) return sendJson(res, 400, { error: 'invalid input' });
  const party = Array.isArray(rec.party) ? rec.party : [];
  const monsters = Array.isArray(rec.monsters) ? rec.monsters : [];

  let base_xp = 0;
  let monster_count = 0;
  for (const monster of monsters) {
    const mo = asRecord(monster);
    if (!mo) return sendJson(res, 400, { error: 'invalid monster' });
    const cr = mo.cr;
    const count = mo.count;
    if (typeof cr !== 'string' || !(cr in XP_TABLE)) {
      return sendJson(res, 400, { error: 'invalid cr' });
    }
    if (typeof count !== 'number' || !Number.isInteger(count) || count < 1) {
      return sendJson(res, 400, { error: 'invalid count' });
    }
    base_xp += XP_TABLE[cr] * count;
    monster_count += count;
  }

  const multiplier = multiplierFor(monster_count);
  const adjusted_xp = base_xp * multiplier;

  const thresholds: LevelThresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const member of party) {
    const po = asRecord(member);
    if (!po) continue;
    const level = po.level;
    if (typeof level === 'number') {
      const t = THRESHOLDS_BY_LEVEL[level];
      if (t) {
        thresholds.easy += t.easy;
        thresholds.medium += t.medium;
        thresholds.hard += t.hard;
        thresholds.deadly += t.deadly;
      }
    }
  }

  let difficulty: string;
  if (adjusted_xp >= thresholds.deadly) difficulty = 'deadly';
  else if (adjusted_xp >= thresholds.hard) difficulty = 'hard';
  else if (adjusted_xp >= thresholds.medium) difficulty = 'medium';
  else if (adjusted_xp >= thresholds.easy) difficulty = 'easy';
  else difficulty = 'trivial';

  return sendJson(res, 200, {
    base_xp,
    monster_count,
    multiplier,
    adjusted_xp,
    difficulty,
    thresholds,
  });
}

function initiative(res: http.ServerResponse, body: unknown): void {
  const rec = asRecord(body);
  if (!rec) return sendJson(res, 400, { error: 'invalid combatants' });
  const combatants = rec.combatants;
  if (!Array.isArray(combatants)) {
    return sendJson(res, 400, { error: 'invalid combatants' });
  }

  const scored: { name: string; dex: number; score: number }[] = [];
  for (const c of combatants) {
    const co = asRecord(c);
    if (!co) return sendJson(res, 400, { error: 'invalid combatant' });
    const { name, dex, roll } = co;
    if (
      typeof name !== 'string' ||
      typeof dex !== 'number' || !Number.isFinite(dex) ||
      typeof roll !== 'number' || !Number.isFinite(roll)
    ) {
      return sendJson(res, 400, { error: 'invalid combatant' });
    }
    scored.push({ name, dex, score: roll + dex });
  }

  // Sort: score desc, then dex desc, then name asc.
  scored.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
  });

  return sendJson(res, 200, {
    order: scored.map((c) => ({ name: c.name, score: c.score })),
  });
}

function abilityModifierEndpoint(res: http.ServerResponse, body: unknown): void {
  const rec = asRecord(body);
  if (!rec) return sendJson(res, 400, { error: 'invalid input' });
  const { score } = rec;
  if (!isValidScore(score)) {
    return sendJson(res, 400, { error: 'invalid score' });
  }
  return sendJson(res, 200, { score, modifier: abilityModifier(score) });
}

function proficiencyEndpoint(res: http.ServerResponse, body: unknown): void {
  const rec = asRecord(body);
  if (!rec) return sendJson(res, 400, { error: 'invalid input' });
  const { level } = rec;
  if (!isValidLevel(level)) {
    return sendJson(res, 400, { error: 'invalid level' });
  }
  return sendJson(res, 200, { level, proficiency_bonus: proficiencyBonus(level) });
}

function derivedStatsEndpoint(res: http.ServerResponse, body: unknown): void {
  const rec = asRecord(body);
  if (!rec) return sendJson(res, 400, { error: 'invalid input' });
  const { level, abilities, armor } = rec;
  if (!isValidLevel(level)) {
    return sendJson(res, 400, { error: 'invalid level' });
  }
  const ab = asRecord(abilities);
  if (!ab) return sendJson(res, 400, { error: 'invalid abilities' });
  const ar = asRecord(armor);
  if (!ar) return sendJson(res, 400, { error: 'invalid armor' });

  const modifiers: Record<string, number> = {};
  for (const name of ABILITY_NAMES) {
    const val = ab[name];
    if (!isValidScore(val)) {
      return sendJson(res, 400, { error: `invalid ${name}` });
    }
    modifiers[name] = abilityModifier(val);
  }

  const { base, shield, dex_cap } = ar;
  if (typeof base !== 'number' || !Number.isFinite(base)) {
    return sendJson(res, 400, { error: 'invalid armor base' });
  }
  if (typeof shield !== 'boolean') {
    return sendJson(res, 400, { error: 'invalid armor shield' });
  }
  if (typeof dex_cap !== 'number' || !Number.isFinite(dex_cap)) {
    return sendJson(res, 400, { error: 'invalid armor dex_cap' });
  }

  const proficiency_bonus = proficiencyBonus(level);
  const hp_max = level * (6 + modifiers.con);
  const shield_bonus = shield ? 2 : 0;
  const armor_class = base + Math.min(modifiers.dex, dex_cap) + shield_bonus;

  return sendJson(res, 200, {
    level,
    proficiency_bonus,
    hp_max,
    armor_class,
    modifiers,
  });
}

// --- Combat session state ---
interface Combatant {
  name: string;
  dex: number;
  score: number;
}

interface Condition {
  condition: string;
  remaining_rounds: number;
}

interface CombatSession {
  id: string;
  order: Combatant[];
  round: number;
  turn_index: number;
  conditions: Map<string, Condition[]>;
}

const sessions: Map<string, CombatSession> = new Map();

function createCombatSession(res: http.ServerResponse, body: unknown): void {
  const rec = asRecord(body);
  if (!rec) return sendJson(res, 400, { error: 'invalid input' });
  const { id, combatants } = rec;
  if (typeof id !== 'string' || id.length === 0) {
    return sendJson(res, 400, { error: 'invalid id' });
  }
  if (!Array.isArray(combatants) || combatants.length === 0) {
    return sendJson(res, 400, { error: 'invalid combatants' });
  }
  const order: Combatant[] = [];
  for (const c of combatants) {
    const co = asRecord(c);
    if (!co) return sendJson(res, 400, { error: 'invalid combatant' });
    const { name, dex, roll } = co;
    if (
      typeof name !== 'string' || name.length === 0 ||
      typeof dex !== 'number' || !Number.isFinite(dex) ||
      typeof roll !== 'number' || !Number.isFinite(roll)
    ) {
      return sendJson(res, 400, { error: 'invalid combatant' });
    }
    order.push({ name, dex, score: roll + dex });
  }
  // Sort: score desc, then dex desc, then name asc.
  order.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
  });
  const session: CombatSession = {
    id,
    order,
    round: 1,
    turn_index: 0,
    conditions: new Map(),
  };
  sessions.set(id, session);
  const active = order[0];
  return sendJson(res, 200, {
    id,
    round: 1,
    turn_index: 0,
    active: { name: active.name, score: active.score },
    order: order.map((c) => ({ name: c.name, score: c.score })),
  });
}

function addCondition(res: http.ServerResponse, sessionId: string, body: unknown): void {
  const session = sessions.get(sessionId);
  if (!session) return sendJson(res, 404, { error: 'session not found' });
  const rec = asRecord(body);
  if (!rec) return sendJson(res, 400, { error: 'invalid input' });
  const { target, condition, duration_rounds } = rec;
  if (typeof target !== 'string') {
    return sendJson(res, 400, { error: 'invalid target' });
  }
  const combatant = session.order.find((c) => c.name === target);
  if (!combatant) return sendJson(res, 400, { error: 'invalid target' });
  if (typeof condition !== 'string') {
    return sendJson(res, 400, { error: 'invalid condition' });
  }
  if (
    typeof duration_rounds !== 'number' ||
    !Number.isInteger(duration_rounds) ||
    duration_rounds < 1
  ) {
    return sendJson(res, 400, { error: 'invalid duration_rounds' });
  }
  let list = session.conditions.get(target);
  if (!list) {
    list = [];
    session.conditions.set(target, list);
  }
  list.push({ condition, remaining_rounds: duration_rounds });
  return sendJson(res, 200, {
    target,
    conditions: list.map((c) => ({ condition: c.condition, remaining_rounds: c.remaining_rounds })),
  });
}

function advanceTurn(res: http.ServerResponse, sessionId: string): void {
  const session = sessions.get(sessionId);
  if (!session) return sendJson(res, 404, { error: 'session not found' });
  let nextIndex = session.turn_index + 1;
  if (nextIndex >= session.order.length) {
    nextIndex = 0;
    session.round += 1;
  }
  session.turn_index = nextIndex;
  const active = session.order[nextIndex];
  // At the start of the active combatant's turn, decrement their conditions.
  // Remove individual conditions that reach 0, but keep the combatant's entry
  // (with an empty list) so callers can see the target still has no conditions.
  const list = session.conditions.get(active.name);
  if (list) {
    for (const cond of list) {
      cond.remaining_rounds -= 1;
    }
    const filtered = list.filter((c) => c.remaining_rounds > 0);
    session.conditions.set(active.name, filtered);
  }
  const conditionsResp: Record<string, { condition: string; remaining_rounds: number }[]> = {};
  for (const [name, conds] of session.conditions) {
    conditionsResp[name] = conds.map((c) => ({ condition: c.condition, remaining_rounds: c.remaining_rounds }));
  }
  return sendJson(res, 200, {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: { name: active.name, score: active.score },
    conditions: conditionsResp,
  });
}

// --- Server ---
const server = http.createServer(async (req, res): Promise<void> => {
  const method = req.method ?? 'GET';
  const path = (req.url ?? '/').split('?')[0];
  const segments = path.split('/').filter((s) => s.length > 0);

  try {
    if (method === 'GET' && path === '/health') {
      return sendJson(res, 200, { ok: true });
    }
    if (method === 'POST' && path === '/v1/dice/stats') {
      const body = await readJsonBody(req);
      return diceStats(res, body);
    }
    if (method === 'POST' && path === '/v1/checks/ability') {
      const body = await readJsonBody(req);
      return abilityCheck(res, body);
    }
    if (method === 'POST' && path === '/v1/encounters/adjusted-xp') {
      const body = await readJsonBody(req);
      return adjustedXp(res, body);
    }
    if (method === 'POST' && path === '/v1/initiative/order') {
      const body = await readJsonBody(req);
      return initiative(res, body);
    }
    if (method === 'POST' && path === '/v1/characters/ability-modifier') {
      const body = await readJsonBody(req);
      return abilityModifierEndpoint(res, body);
    }
    if (method === 'POST' && path === '/v1/characters/proficiency') {
      const body = await readJsonBody(req);
      return proficiencyEndpoint(res, body);
    }
    if (method === 'POST' && path === '/v1/characters/derived-stats') {
      const body = await readJsonBody(req);
      return derivedStatsEndpoint(res, body);
    }
    if (method === 'POST' && segments.length === 3 &&
        segments[0] === 'v1' && segments[1] === 'combat' && segments[2] === 'sessions') {
      const body = await readJsonBody(req);
      return createCombatSession(res, body);
    }
    if (method === 'POST' && segments.length === 5 &&
        segments[0] === 'v1' && segments[1] === 'combat' && segments[2] === 'sessions' &&
        segments[4] === 'conditions') {
      const body = await readJsonBody(req);
      return addCondition(res, decodeURIComponent(segments[3]), body);
    }
    if (method === 'POST' && segments.length === 5 &&
        segments[0] === 'v1' && segments[1] === 'combat' && segments[2] === 'sessions' &&
        segments[4] === 'advance') {
      await drainBody(req);
      return advanceTurn(res, decodeURIComponent(segments[3]));
    }
    return sendJson(res, 404, { error: 'not found' });
  } catch {
    return sendJson(res, 400, { error: 'bad request' });
  }
});

const port = parseInt(process.env.PORT ?? '3000', 10);
server.listen(port, '127.0.0.1', () => {
  console.log(`listening on 127.0.0.1:${port}`);
});
