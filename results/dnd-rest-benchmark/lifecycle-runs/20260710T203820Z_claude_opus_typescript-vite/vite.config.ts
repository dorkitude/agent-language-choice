import type { Connect, Plugin, ViteDevServer } from 'vite';
import { defineConfig } from 'vite';
import type { IncomingMessage, ServerResponse } from 'node:http';
import { randomBytes, scryptSync, timingSafeEqual } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

// --- Domain data ---------------------------------------------------------

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

function encounterMultiplier(monsterCount: number): number {
  if (monsterCount <= 0) return 1;
  if (monsterCount === 1) return 1;
  if (monsterCount === 2) return 1.5;
  if (monsterCount <= 6) return 2;
  if (monsterCount <= 10) return 2.5;
  if (monsterCount <= 14) return 3;
  return 4;
}

// --- HTTP helpers --------------------------------------------------------

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  const payload = JSON.stringify(body);
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json');
  res.end(payload);
}

function readBody(req: IncomingMessage): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on('data', (c: Buffer) => chunks.push(c));
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8');
      if (raw.trim() === '') {
        resolve(undefined);
        return;
      }
      try {
        resolve(JSON.parse(raw));
      } catch {
        reject(new Error('invalid json'));
      }
    });
    req.on('error', reject);
  });
}

class BadRequest extends Error {}

function isFiniteInt(n: unknown): n is number {
  return typeof n === 'number' && Number.isFinite(n) && Number.isInteger(n);
}

// --- Handlers ------------------------------------------------------------

function diceStats(body: any) {
  if (!body || typeof body.expression !== 'string') {
    throw new BadRequest('expression required');
  }
  const m = /^(-?\d+)d(-?\d+)([+-]\d+)?$/.exec(body.expression.trim());
  if (!m) throw new BadRequest('invalid expression');
  const count = parseInt(m[1], 10);
  const sides = parseInt(m[2], 10);
  const modifier = m[3] !== undefined ? parseInt(m[3], 10) : 0;
  if (!(count > 0) || !(sides > 0)) throw new BadRequest('count and sides must be positive');
  const min = count * 1 + modifier;
  const max = count * sides + modifier;
  const average = (min + max) / 2;
  return { dice_count: count, sides, modifier, min, max, average };
}

function abilityCheck(body: any) {
  if (!body || !isFiniteInt(body.roll) || !isFiniteInt(body.modifier) || !isFiniteInt(body.dc)) {
    throw new BadRequest('roll, modifier, dc required');
  }
  const total = body.roll + body.modifier;
  return { total, success: total >= body.dc, margin: total - body.dc };
}

function adjustedXp(body: any) {
  if (!body || !Array.isArray(body.party) || !Array.isArray(body.monsters)) {
    throw new BadRequest('party and monsters required');
  }

  let baseXp = 0;
  let monsterCount = 0;
  for (const mon of body.monsters) {
    if (!mon || typeof mon !== 'object') throw new BadRequest('invalid monster');
    const cr = String(mon.cr);
    const xp = CR_XP[cr];
    if (xp === undefined) throw new BadRequest(`unsupported cr: ${cr}`);
    const c = mon.count;
    if (!isFiniteInt(c) || c < 0) throw new BadRequest('invalid monster count');
    baseXp += xp * c;
    monsterCount += c;
  }

  const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const member of body.party) {
    if (!member || !isFiniteInt(member.level)) throw new BadRequest('invalid party member');
    const t = LEVEL_THRESHOLDS[member.level];
    if (!t) throw new BadRequest(`unsupported level: ${member.level}`);
    thresholds.easy += t.easy;
    thresholds.medium += t.medium;
    thresholds.hard += t.hard;
    thresholds.deadly += t.deadly;
  }

  const multiplier = encounterMultiplier(monsterCount);
  const adjusted = baseXp * multiplier;

  let difficulty = 'trivial';
  if (adjusted >= thresholds.deadly) difficulty = 'deadly';
  else if (adjusted >= thresholds.hard) difficulty = 'hard';
  else if (adjusted >= thresholds.medium) difficulty = 'medium';
  else if (adjusted >= thresholds.easy) difficulty = 'easy';

  return {
    base_xp: baseXp,
    monster_count: monsterCount,
    multiplier,
    adjusted_xp: adjusted,
    difficulty,
    thresholds,
  };
}

function initiativeOrder(body: any) {
  if (!body || !Array.isArray(body.combatants)) {
    throw new BadRequest('combatants required');
  }
  const combatants = body.combatants.map((c: any) => {
    if (!c || typeof c.name !== 'string' || !isFiniteInt(c.dex) || !isFiniteInt(c.roll)) {
      throw new BadRequest('invalid combatant');
    }
    return { name: c.name, dex: c.dex, score: c.roll + c.dex };
  });
  combatants.sort((a: any, b: any) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
  });
  return { order: combatants.map((c: any) => ({ name: c.name, score: c.score })) };
}

function abilityModifierFor(score: number): number {
  return Math.floor((score - 10) / 2);
}

function proficiencyFor(level: number): number {
  return Math.floor((level - 1) / 4) + 2;
}

function abilityModifier(body: any) {
  if (!body || !isFiniteInt(body.score) || body.score < 1 || body.score > 30) {
    throw new BadRequest('score must be an integer from 1 to 30');
  }
  return { score: body.score, modifier: abilityModifierFor(body.score) };
}

function proficiency(body: any) {
  if (!body || !isFiniteInt(body.level) || body.level < 1 || body.level > 20) {
    throw new BadRequest('level must be an integer from 1 to 20');
  }
  return { level: body.level, proficiency_bonus: proficiencyFor(body.level) };
}

const ABILITY_KEYS = ['str', 'dex', 'con', 'int', 'wis', 'cha'] as const;

function derivedStats(body: any) {
  if (!body || !isFiniteInt(body.level) || body.level < 1 || body.level > 20) {
    throw new BadRequest('level must be an integer from 1 to 20');
  }
  if (!body.abilities || typeof body.abilities !== 'object') {
    throw new BadRequest('abilities required');
  }
  const modifiers: Record<string, number> = {};
  for (const key of ABILITY_KEYS) {
    const score = body.abilities[key];
    if (!isFiniteInt(score) || score < 1 || score > 30) {
      throw new BadRequest(`invalid ability score: ${key}`);
    }
    modifiers[key] = abilityModifierFor(score);
  }
  const armor = body.armor;
  if (!armor || typeof armor !== 'object') throw new BadRequest('armor required');
  if (!isFiniteInt(armor.base)) throw new BadRequest('armor.base required');
  if (!isFiniteInt(armor.dex_cap)) throw new BadRequest('armor.dex_cap required');
  if (typeof armor.shield !== 'boolean') throw new BadRequest('armor.shield required');

  const proficiencyBonus = proficiencyFor(body.level);
  const hpMax = body.level * (6 + modifiers.con);
  const shieldBonus = armor.shield ? 2 : 0;
  const armorClass = armor.base + Math.min(modifiers.dex, armor.dex_cap) + shieldBonus;

  return {
    level: body.level,
    proficiency_bonus: proficiencyBonus,
    hp_max: hpMax,
    armor_class: armorClass,
    modifiers,
  };
}

// --- Selected PHB rules --------------------------------------------------

const SPELL_SLOTS: Record<string, Record<number, Record<string, number>>> = {
  wizard: {
    5: { '1': 4, '2': 3, '3': 2 },
  },
};

function spellSlots(body: any) {
  if (!body || typeof body.class !== 'string' || !isFiniteInt(body.level)) {
    throw new BadRequest('class and level required');
  }
  const byLevel = SPELL_SLOTS[body.class];
  const slots = byLevel?.[body.level];
  if (!slots) throw new BadRequest('unsupported class/level');
  return { class: body.class, level: body.level, slots };
}

function longRest(body: any) {
  if (
    !body ||
    !isFiniteInt(body.level) ||
    !isFiniteInt(body.hp_current) ||
    !isFiniteInt(body.hp_max) ||
    !isFiniteInt(body.hit_dice_spent) ||
    !isFiniteInt(body.exhaustion_level)
  ) {
    throw new BadRequest('level, hp_current, hp_max, hit_dice_spent, exhaustion_level required');
  }
  if (body.level < 1) throw new BadRequest('invalid level');
  if (body.hit_dice_spent < 0) throw new BadRequest('invalid hit_dice_spent');
  if (body.exhaustion_level < 0) throw new BadRequest('invalid exhaustion_level');

  const recovered = Math.max(1, Math.floor(body.level / 2));
  const hitDiceSpent = Math.max(0, body.hit_dice_spent - recovered);
  const exhaustionLevel = Math.max(0, body.exhaustion_level - 1);

  return {
    hp_current: body.hp_max,
    hit_dice_spent: hitDiceSpent,
    exhaustion_level: exhaustionLevel,
  };
}

function equipmentLoad(body: any) {
  if (!body || !isFiniteInt(body.strength) || !isFiniteInt(body.weight)) {
    throw new BadRequest('strength and weight required');
  }
  if (body.strength < 1) throw new BadRequest('invalid strength');
  if (body.weight < 0) throw new BadRequest('invalid weight');
  const capacity = body.strength * 15;
  return { capacity, weight: body.weight, encumbered: body.weight > capacity };
}

// --- Combat sessions (stateful) -----------------------------------------

class NotFound extends Error {}

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

const COMBAT_SESSIONS = new Map<string, CombatSession>();

function sortInitiative(combatants: Combatant[]): Combatant[] {
  return [...combatants].sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
  });
}

function activeCombatant(session: CombatSession) {
  const c = session.order[session.turn_index];
  return { name: c.name, score: c.score };
}

function createCombatSession(body: any) {
  if (!body || typeof body.id !== 'string' || body.id === '') {
    throw new BadRequest('id required');
  }
  if (!Array.isArray(body.combatants) || body.combatants.length === 0) {
    throw new BadRequest('combatants required');
  }
  if (COMBAT_SESSIONS.has(body.id)) {
    throw new BadRequest('session id already exists');
  }
  const combatants: Combatant[] = body.combatants.map((c: any) => {
    if (!c || typeof c.name !== 'string' || !isFiniteInt(c.dex) || !isFiniteInt(c.roll)) {
      throw new BadRequest('invalid combatant');
    }
    return { name: c.name, dex: c.dex, score: c.roll + c.dex };
  });
  const order = sortInitiative(combatants);
  const session: CombatSession = {
    id: body.id,
    order,
    round: 1,
    turn_index: 0,
    conditions: new Map(),
  };
  COMBAT_SESSIONS.set(session.id, session);
  return {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: activeCombatant(session),
    order: order.map((c) => ({ name: c.name, score: c.score })),
  };
}

function addCondition(id: string, body: any) {
  const session = COMBAT_SESSIONS.get(id);
  if (!session) throw new NotFound('unknown session');
  if (!body || typeof body.target !== 'string') throw new BadRequest('target required');
  if (typeof body.condition !== 'string' || body.condition === '') {
    throw new BadRequest('condition required');
  }
  if (!isFiniteInt(body.duration_rounds) || body.duration_rounds <= 0) {
    throw new BadRequest('duration_rounds must be a positive integer');
  }
  if (!session.order.some((c) => c.name === body.target)) {
    throw new BadRequest('unknown target');
  }
  const list = session.conditions.get(body.target) ?? [];
  list.push({ condition: body.condition, remaining_rounds: body.duration_rounds });
  session.conditions.set(body.target, list);
  return {
    target: body.target,
    conditions: list.map((c) => ({ condition: c.condition, remaining_rounds: c.remaining_rounds })),
  };
}

function conditionsObject(session: CombatSession) {
  const out: Record<string, Condition[]> = {};
  for (const [name, list] of session.conditions) {
    out[name] = list.map((c) => ({ condition: c.condition, remaining_rounds: c.remaining_rounds }));
  }
  return out;
}

function advanceTurn(id: string) {
  const session = COMBAT_SESSIONS.get(id);
  if (!session) throw new NotFound('unknown session');

  session.turn_index += 1;
  if (session.turn_index >= session.order.length) {
    session.turn_index = 0;
    session.round += 1;
  }

  const active = session.order[session.turn_index];
  const list = session.conditions.get(active.name);
  if (list) {
    for (const c of list) c.remaining_rounds -= 1;
    const remaining = list.filter((c) => c.remaining_rounds > 0);
    session.conditions.set(active.name, remaining);
  }

  return {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: activeCombatant(session),
    conditions: conditionsObject(session),
  };
}

// --- Durable SQLite storage ---------------------------------------------

const SCHEMA_VERSION = 1;

const DB_PATH = join(dirname(fileURLToPath(import.meta.url)), 'game.db');

let db: DatabaseSync | undefined;

function createSchema(database: DatabaseSync): void {
  database.exec(`
    CREATE TABLE IF NOT EXISTS meta (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS users (
      username TEXT PRIMARY KEY,
      role TEXT NOT NULL,
      salt TEXT NOT NULL,
      hash TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS monsters (
      slug TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      cr TEXT NOT NULL,
      armor_class INTEGER NOT NULL,
      hit_points INTEGER NOT NULL,
      tags TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS items (
      slug TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      type TEXT NOT NULL,
      rarity TEXT NOT NULL,
      cost_gp INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS campaigns (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      dm TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS characters (
      seq INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      name TEXT NOT NULL,
      level INTEGER NOT NULL,
      class TEXT NOT NULL,
      UNIQUE (campaign_id, id)
    );
    CREATE TABLE IF NOT EXISTS events (
      seq INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      kind TEXT NOT NULL,
      summary TEXT NOT NULL,
      UNIQUE (campaign_id, id)
    );
  `);
  database.exec(
    `INSERT INTO meta (key, value) VALUES ('schema_version', '${SCHEMA_VERSION}')
     ON CONFLICT(key) DO UPDATE SET value = excluded.value;`,
  );
}

function getDb(): DatabaseSync {
  if (!db) {
    db = new DatabaseSync(DB_PATH);
    createSchema(db);
  }
  return db;
}

function storageInitialized(): boolean {
  const row = getDb()
    .prepare(`SELECT value FROM meta WHERE key = 'schema_version'`)
    .get() as { value?: string } | undefined;
  return row?.value === String(SCHEMA_VERSION);
}

function storageStatus() {
  return {
    driver: 'sqlite',
    schema_version: SCHEMA_VERSION,
    initialized: storageInitialized(),
  };
}

function resetStorage() {
  const database = getDb();
  database.exec(
    `DROP TABLE IF EXISTS events; DROP TABLE IF EXISTS characters; DROP TABLE IF EXISTS campaigns; DROP TABLE IF EXISTS items; DROP TABLE IF EXISTS monsters; DROP TABLE IF EXISTS users; DROP TABLE IF EXISTS meta;`,
  );
  createSchema(database);
  COMBAT_SESSIONS.clear();
  return { ok: true, schema_version: SCHEMA_VERSION };
}

// --- Users and password login (SQLite-backed) ---------------------------

class Unauthorized extends Error {}
class Conflict extends Error {}

interface User {
  username: string;
  role: 'dm' | 'player';
  salt: string;
  hash: string;
}

const USERS = {
  has(username: string): boolean {
    const row = getDb()
      .prepare(`SELECT 1 FROM users WHERE username = ?`)
      .get(username);
    return row !== undefined;
  },
  get(username: string): User | undefined {
    const row = getDb()
      .prepare(`SELECT username, role, salt, hash FROM users WHERE username = ?`)
      .get(username) as User | undefined;
    return row ?? undefined;
  },
  set(username: string, user: User): void {
    getDb()
      .prepare(
        `INSERT INTO users (username, role, salt, hash) VALUES (?, ?, ?, ?)
         ON CONFLICT(username) DO UPDATE SET role = excluded.role, salt = excluded.salt, hash = excluded.hash`,
      )
      .run(user.username, user.role, user.salt, user.hash);
  },
};

const USERNAME_RE = /^[a-z0-9_-]{2,32}$/;

// Password hashing isolated behind a small helper so a production hash can
// replace it. Uses Node's built-in scrypt with a per-user random salt.
function hashPassword(password: string, salt: string): string {
  return scryptSync(password, salt, 64).toString('hex');
}

function verifyPassword(password: string, salt: string, expected: string): boolean {
  const actual = hashPassword(password, salt);
  const a = Buffer.from(actual, 'hex');
  const b = Buffer.from(expected, 'hex');
  if (a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}

function registerUser(body: any) {
  if (!body || typeof body !== 'object') throw new BadRequest('body required');
  const { username, password, role } = body;
  if (typeof username !== 'string' || !USERNAME_RE.test(username)) {
    throw new BadRequest('invalid username');
  }
  if (typeof password !== 'string' || password.length < 8) {
    throw new BadRequest('invalid password');
  }
  if (role !== 'dm' && role !== 'player') {
    throw new BadRequest('invalid role');
  }
  if (USERS.has(username)) {
    throw new Conflict('username already exists');
  }
  const salt = randomBytes(16).toString('hex');
  const hash = hashPassword(password, salt);
  USERS.set(username, { username, role, salt, hash });
  return { username, role };
}

function loginUser(body: any) {
  if (!body || typeof body !== 'object') throw new BadRequest('body required');
  const { username, password } = body;
  if (typeof username !== 'string' || typeof password !== 'string') {
    throw new BadRequest('username and password required');
  }
  const user = USERS.get(username);
  if (!user || !verifyPassword(password, user.salt, user.hash)) {
    throw new Unauthorized('invalid credentials');
  }
  return { username: user.username, token: `session-${user.username}` };
}

// --- Compendium: monsters and items (SQLite-backed) ---------------------

const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

function validateSlug(slug: unknown): string {
  if (typeof slug !== 'string' || !SLUG_RE.test(slug)) {
    throw new BadRequest('invalid slug');
  }
  return slug;
}

function createMonster(body: any) {
  if (!body || typeof body !== 'object') throw new BadRequest('body required');
  const slug = validateSlug(body.slug);
  if (typeof body.name !== 'string' || body.name === '') {
    throw new BadRequest('invalid name');
  }
  if (typeof body.cr !== 'string' || body.cr === '') {
    throw new BadRequest('invalid cr');
  }
  if (!isFiniteInt(body.armor_class)) throw new BadRequest('invalid armor_class');
  if (!isFiniteInt(body.hit_points)) throw new BadRequest('invalid hit_points');
  let tags: string[] = [];
  if (body.tags !== undefined) {
    if (!Array.isArray(body.tags) || body.tags.some((t: unknown) => typeof t !== 'string')) {
      throw new BadRequest('invalid tags');
    }
    tags = body.tags;
  }
  const exists = getDb().prepare(`SELECT 1 FROM monsters WHERE slug = ?`).get(slug);
  if (exists !== undefined) throw new Conflict('monster slug already exists');
  getDb()
    .prepare(
      `INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags) VALUES (?, ?, ?, ?, ?, ?)`,
    )
    .run(slug, body.name, body.cr, body.armor_class, body.hit_points, JSON.stringify(tags));
  return {
    slug,
    name: body.name,
    cr: body.cr,
    armor_class: body.armor_class,
    hit_points: body.hit_points,
  };
}

function getMonster(slug: string) {
  const row = getDb()
    .prepare(`SELECT slug, name, cr, armor_class, hit_points, tags FROM monsters WHERE slug = ?`)
    .get(slug) as
    | { slug: string; name: string; cr: string; armor_class: number; hit_points: number; tags: string }
    | undefined;
  if (!row) throw new NotFound('unknown monster');
  return {
    slug: row.slug,
    name: row.name,
    cr: row.cr,
    armor_class: row.armor_class,
    hit_points: row.hit_points,
    tags: JSON.parse(row.tags) as string[],
  };
}

function createItem(body: any) {
  if (!body || typeof body !== 'object') throw new BadRequest('body required');
  const slug = validateSlug(body.slug);
  if (typeof body.name !== 'string' || body.name === '') {
    throw new BadRequest('invalid name');
  }
  if (typeof body.type !== 'string' || body.type === '') {
    throw new BadRequest('invalid type');
  }
  if (typeof body.rarity !== 'string' || body.rarity === '') {
    throw new BadRequest('invalid rarity');
  }
  if (!isFiniteInt(body.cost_gp)) throw new BadRequest('invalid cost_gp');
  const exists = getDb().prepare(`SELECT 1 FROM items WHERE slug = ?`).get(slug);
  if (exists !== undefined) throw new Conflict('item slug already exists');
  getDb()
    .prepare(`INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)`)
    .run(slug, body.name, body.type, body.rarity, body.cost_gp);
  return {
    slug,
    name: body.name,
    type: body.type,
    rarity: body.rarity,
    cost_gp: body.cost_gp,
  };
}

function getItem(slug: string) {
  const row = getDb()
    .prepare(`SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?`)
    .get(slug) as
    | { slug: string; name: string; type: string; rarity: string; cost_gp: number }
    | undefined;
  if (!row) throw new NotFound('unknown item');
  return row;
}

// --- Campaign state (SQLite-backed) -------------------------------------

function campaignExists(id: string): boolean {
  return getDb().prepare(`SELECT 1 FROM campaigns WHERE id = ?`).get(id) !== undefined;
}

function createCampaign(body: any) {
  if (!body || typeof body !== 'object') throw new BadRequest('body required');
  if (typeof body.id !== 'string' || body.id === '') throw new BadRequest('invalid id');
  if (typeof body.name !== 'string' || body.name === '') throw new BadRequest('invalid name');
  if (typeof body.dm !== 'string' || body.dm === '') throw new BadRequest('invalid dm');
  if (campaignExists(body.id)) throw new Conflict('campaign id already exists');
  getDb()
    .prepare(`INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)`)
    .run(body.id, body.name, body.dm);
  return { id: body.id, name: body.name, dm: body.dm };
}

function addCharacter(campaignId: string, body: any) {
  if (!campaignExists(campaignId)) throw new NotFound('unknown campaign');
  if (!body || typeof body !== 'object') throw new BadRequest('body required');
  if (typeof body.id !== 'string' || body.id === '') throw new BadRequest('invalid id');
  if (typeof body.name !== 'string' || body.name === '') throw new BadRequest('invalid name');
  if (!isFiniteInt(body.level)) throw new BadRequest('invalid level');
  if (typeof body.class !== 'string' || body.class === '') throw new BadRequest('invalid class');
  const exists = getDb()
    .prepare(`SELECT 1 FROM characters WHERE campaign_id = ? AND id = ?`)
    .get(campaignId, body.id);
  if (exists !== undefined) throw new Conflict('character id already exists');
  getDb()
    .prepare(
      `INSERT INTO characters (campaign_id, id, name, level, class) VALUES (?, ?, ?, ?, ?)`,
    )
    .run(campaignId, body.id, body.name, body.level, body.class);
  return { id: body.id, name: body.name, level: body.level, class: body.class };
}

function addEvent(campaignId: string, body: any) {
  if (!campaignExists(campaignId)) throw new NotFound('unknown campaign');
  if (!body || typeof body !== 'object') throw new BadRequest('body required');
  if (typeof body.id !== 'string' || body.id === '') throw new BadRequest('invalid id');
  if (typeof body.kind !== 'string' || body.kind === '') throw new BadRequest('invalid kind');
  if (typeof body.summary !== 'string' || body.summary === '') throw new BadRequest('invalid summary');
  const exists = getDb()
    .prepare(`SELECT 1 FROM events WHERE campaign_id = ? AND id = ?`)
    .get(campaignId, body.id);
  if (exists !== undefined) throw new Conflict('event id already exists');
  getDb()
    .prepare(`INSERT INTO events (campaign_id, id, kind, summary) VALUES (?, ?, ?, ?)`)
    .run(campaignId, body.id, body.kind, body.summary);
  return { id: body.id, kind: body.kind };
}

function campaignState(campaignId: string) {
  const campaign = getDb()
    .prepare(`SELECT id, name, dm FROM campaigns WHERE id = ?`)
    .get(campaignId) as { id: string; name: string; dm: string } | undefined;
  if (!campaign) throw new NotFound('unknown campaign');
  const characters = getDb()
    .prepare(
      `SELECT id, name, level, class FROM characters WHERE campaign_id = ? ORDER BY seq ASC`,
    )
    .all(campaignId) as { id: string; name: string; level: number; class: string }[];
  const logRow = getDb()
    .prepare(`SELECT COUNT(*) AS n FROM events WHERE campaign_id = ?`)
    .get(campaignId) as { n: number };
  return {
    id: campaign.id,
    name: campaign.name,
    dm: campaign.dm,
    characters,
    log_count: logRow.n,
  };
}

// --- DM tools (compendium + campaign state) -----------------------------

const ENCOUNTER_RECOMMENDATION: Record<string, string> = {
  trivial: 'cakewalk',
  easy: 'safe warm-up',
  medium: 'a fair fight',
  hard: 'tough fight',
  deadly: 'deadly encounter',
};

function encounterBuilder(body: any) {
  if (!body || typeof body !== 'object') throw new BadRequest('body required');
  if (typeof body.campaign_id !== 'string' || body.campaign_id === '') {
    throw new BadRequest('invalid campaign_id');
  }
  if (!Array.isArray(body.party) || body.party.length === 0) {
    throw new BadRequest('party required');
  }
  if (!Array.isArray(body.monster_slugs) || body.monster_slugs.length === 0) {
    throw new BadRequest('monster_slugs required');
  }

  let baseXp = 0;
  for (const slug of body.monster_slugs) {
    const monster = getMonster(validateSlug(slug));
    const xp = CR_XP[monster.cr];
    if (xp === undefined) throw new BadRequest(`unsupported cr: ${monster.cr}`);
    baseXp += xp;
  }
  const monsterCount = body.monster_slugs.length;

  const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const member of body.party) {
    if (!member || !isFiniteInt(member.level)) throw new BadRequest('invalid party member');
    const t = LEVEL_THRESHOLDS[member.level];
    if (!t) throw new BadRequest(`unsupported level: ${member.level}`);
    thresholds.easy += t.easy;
    thresholds.medium += t.medium;
    thresholds.hard += t.hard;
    thresholds.deadly += t.deadly;
  }

  const multiplier = encounterMultiplier(monsterCount);
  const adjusted = baseXp * multiplier;

  let difficulty = 'trivial';
  if (adjusted >= thresholds.deadly) difficulty = 'deadly';
  else if (adjusted >= thresholds.hard) difficulty = 'hard';
  else if (adjusted >= thresholds.medium) difficulty = 'medium';
  else if (adjusted >= thresholds.easy) difficulty = 'easy';

  return {
    campaign_id: body.campaign_id,
    base_xp: baseXp,
    adjusted_xp: adjusted,
    difficulty,
    monster_count: monsterCount,
    recommendation: ENCOUNTER_RECOMMENDATION[difficulty],
  };
}

const LOOT_TIERS: Record<number, { coins_gp: number; items: { slug: string; quantity: number }[] }> = {
  1: { coins_gp: 75, items: [{ slug: 'healing-potion', quantity: 2 }] },
};

function lootParcel(body: any) {
  if (!body || typeof body !== 'object') throw new BadRequest('body required');
  if (typeof body.campaign_id !== 'string' || body.campaign_id === '') {
    throw new BadRequest('invalid campaign_id');
  }
  if (!isFiniteInt(body.tier)) throw new BadRequest('invalid tier');
  const parcel = LOOT_TIERS[body.tier];
  if (!parcel) throw new BadRequest('unsupported tier');
  return {
    campaign_id: body.campaign_id,
    coins_gp: parcel.coins_gp,
    items: parcel.items.map((i) => ({ slug: i.slug, quantity: i.quantity })),
  };
}

function sessionRecap(body: any) {
  if (!body || typeof body !== 'object') throw new BadRequest('body required');
  if (typeof body.campaign_id !== 'string' || body.campaign_id === '') {
    throw new BadRequest('invalid campaign_id');
  }
  if (!campaignExists(body.campaign_id)) throw new NotFound('unknown campaign');

  const events = getDb()
    .prepare(`SELECT summary FROM events WHERE campaign_id = ? ORDER BY seq DESC`)
    .all(body.campaign_id) as { summary: string }[];

  const summary = events.length > 0 ? events[0].summary : 'No events recorded yet.';

  // Derive an open thread from the most recent event that names a locale via a
  // trailing "the <place>." clause: "Nyx scouts the goblin trail." -> "goblin trail".
  const openThreads: string[] = [];
  for (const evt of events) {
    const m = /\bthe\s+(.+?)\.?\s*$/i.exec(evt.summary);
    if (m) {
      openThreads.push(`Resolve ${m[1]} ambush`);
      break;
    }
  }

  return {
    campaign_id: body.campaign_id,
    summary,
    open_threads: openThreads,
  };
}

// --- Middleware plugin ---------------------------------------------------

type Handler = (body: unknown) => unknown;

const ROUTES: Record<string, Handler> = {
  'POST /v1/dice/stats': diceStats,
  'POST /v1/checks/ability': abilityCheck,
  'POST /v1/encounters/adjusted-xp': adjustedXp,
  'POST /v1/initiative/order': initiativeOrder,
  'POST /v1/characters/ability-modifier': abilityModifier,
  'POST /v1/characters/proficiency': proficiency,
  'POST /v1/characters/derived-stats': derivedStats,
  'POST /v1/combat/sessions': createCombatSession,
  'POST /v1/auth/register': registerUser,
  'POST /v1/auth/login': loginUser,
  'POST /v1/storage/reset': () => resetStorage(),
  'POST /v1/compendium/monsters': createMonster,
  'POST /v1/compendium/items': createItem,
  'POST /v1/campaigns': createCampaign,
  'POST /v1/phb/spell-slots': spellSlots,
  'POST /v1/phb/rests/long': longRest,
  'POST /v1/phb/equipment-load': equipmentLoad,
  'POST /v1/dm/encounter-builder': encounterBuilder,
  'POST /v1/dm/loot-parcel': lootParcel,
  'POST /v1/dm/session-recap': sessionRecap,
};

const GET_ROUTES: Record<string, () => unknown> = {
  '/v1/storage/status': () => storageStatus(),
};

function apiPlugin(): Plugin {
  const middleware: Connect.NextHandleFunction = async (req, res, next) => {
    const method = (req.method ?? 'GET').toUpperCase();
    const url = (req.url ?? '').split('?')[0].replace(/\/+$/, '') || '/';

    if (method === 'GET' && url === '/health') {
      sendJson(res, 200, { ok: true });
      return;
    }

    if (method === 'GET' && GET_ROUTES[url]) {
      try {
        sendJson(res, 200, GET_ROUTES[url]());
      } catch {
        sendJson(res, 500, { error: 'internal error' });
      }
      return;
    }

    // Compendium read routes (with path parameters).
    if (method === 'GET') {
      const mon = /^\/v1\/compendium\/monsters\/([^/]+)$/.exec(url);
      const item = /^\/v1\/compendium\/items\/([^/]+)$/.exec(url);
      if (mon || item) {
        try {
          const result = mon
            ? getMonster(decodeURIComponent(mon[1]))
            : getItem(decodeURIComponent(item![1]));
          sendJson(res, 200, result);
        } catch (err) {
          if (err instanceof NotFound) {
            sendJson(res, 404, { error: (err as Error).message });
          } else if (err instanceof BadRequest) {
            sendJson(res, 400, { error: (err as Error).message });
          } else {
            sendJson(res, 500, { error: 'internal error' });
          }
        }
        return;
      }
    }

    // Campaign state read route (with path parameter).
    if (method === 'GET') {
      const state = /^\/v1\/campaigns\/([^/]+)\/state$/.exec(url);
      if (state) {
        try {
          sendJson(res, 200, campaignState(decodeURIComponent(state[1])));
        } catch (err) {
          if (err instanceof NotFound) {
            sendJson(res, 404, { error: (err as Error).message });
          } else if (err instanceof BadRequest) {
            sendJson(res, 400, { error: (err as Error).message });
          } else {
            sendJson(res, 500, { error: 'internal error' });
          }
        }
        return;
      }
    }

    // Combat session routes (with path parameters).
    let combat: (() => unknown) | undefined;
    if (method === 'POST' && url === '/v1/combat/sessions') {
      combat = undefined; // handled by exact-match ROUTES below
    } else if (method === 'POST') {
      const cond = /^\/v1\/combat\/sessions\/([^/]+)\/conditions$/.exec(url);
      const adv = /^\/v1\/combat\/sessions\/([^/]+)\/advance$/.exec(url);
      if (cond) {
        const id = decodeURIComponent(cond[1]);
        combat = async () => addCondition(id, await readBody(req));
      } else if (adv) {
        const id = decodeURIComponent(adv[1]);
        combat = () => advanceTurn(id);
      } else {
        const chars = /^\/v1\/campaigns\/([^/]+)\/characters$/.exec(url);
        const evts = /^\/v1\/campaigns\/([^/]+)\/events$/.exec(url);
        if (chars) {
          const id = decodeURIComponent(chars[1]);
          combat = async () => addCharacter(id, await readBody(req));
        } else if (evts) {
          const id = decodeURIComponent(evts[1]);
          combat = async () => addEvent(id, await readBody(req));
        }
      }
    }

    const handler = ROUTES[`${method} ${url}`];
    if (!handler && !combat) {
      next();
      return;
    }

    try {
      const result = combat ? await combat() : handler!(await readBody(req));
      const route = `${method} ${url}`;
      const CREATED_ROUTES = new Set([
        'POST /v1/auth/register',
        'POST /v1/compendium/monsters',
        'POST /v1/compendium/items',
        'POST /v1/campaigns',
      ]);
      const isCampaignCreate =
        method === 'POST' &&
        (/^\/v1\/campaigns\/[^/]+\/characters$/.test(url) ||
          /^\/v1\/campaigns\/[^/]+\/events$/.test(url));
      const successStatus =
        CREATED_ROUTES.has(route) || isCampaignCreate ? 201 : 200;
      sendJson(res, successStatus, result);
    } catch (err) {
      if (err instanceof NotFound) {
        sendJson(res, 404, { error: (err as Error).message });
      } else if (err instanceof Conflict) {
        sendJson(res, 409, { error: (err as Error).message });
      } else if (err instanceof Unauthorized) {
        sendJson(res, 401, { error: (err as Error).message });
      } else if (err instanceof BadRequest || (err as Error).message === 'invalid json') {
        sendJson(res, 400, { error: (err as Error).message });
      } else {
        sendJson(res, 500, { error: 'internal error' });
      }
    }
  };

  // Initialize durable storage (creates game.db + schema) on startup.
  getDb();

  return {
    name: 'dnd-rest-api',
    configureServer(server: ViteDevServer) {
      server.middlewares.use(middleware);
    },
    configurePreviewServer(server) {
      server.middlewares.use(middleware);
    },
  };
}

export default defineConfig({
  plugins: [apiPlugin()],
});
