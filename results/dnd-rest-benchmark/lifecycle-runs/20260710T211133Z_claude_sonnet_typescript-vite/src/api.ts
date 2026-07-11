import type { IncomingMessage, ServerResponse } from 'node:http';
import type { Connect } from 'vite';
import { randomBytes, scryptSync, timingSafeEqual } from 'node:crypto';
import { getDb, resetDb, storageStatus, SCHEMA_VERSION } from './db.ts';

function readJsonBody(req: IncomingMessage): Promise<any> {
  return new Promise((resolve, reject) => {
    let raw = '';
    req.on('data', (chunk) => {
      raw += chunk;
    });
    req.on('end', () => {
      if (!raw) {
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

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  const payload = JSON.stringify(body);
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json');
  res.end(payload);
}

const DICE_EXPRESSION = /^(\d+)d(\d+)(?:([+-])(\d+))?$/;

function handleDiceStats(body: any, res: ServerResponse): void {
  const expression = body?.expression;
  if (typeof expression !== 'string') {
    sendJson(res, 400, { error: 'expression is required' });
    return;
  }
  const match = DICE_EXPRESSION.exec(expression.trim());
  if (!match) {
    sendJson(res, 400, { error: 'invalid expression' });
    return;
  }
  const diceCount = Number.parseInt(match[1], 10);
  const sides = Number.parseInt(match[2], 10);
  const sign = match[3] === '-' ? -1 : 1;
  const modifier = match[4] ? sign * Number.parseInt(match[4], 10) : 0;
  if (diceCount <= 0 || sides <= 0) {
    sendJson(res, 400, { error: 'count and sides must be positive' });
    return;
  }
  const min = diceCount * 1 + modifier;
  const max = diceCount * sides + modifier;
  const average = (diceCount * (sides + 1)) / 2 + modifier;
  sendJson(res, 200, {
    dice_count: diceCount,
    sides,
    modifier,
    min,
    max,
    average,
  });
}

function handleAbilityCheck(body: any, res: ServerResponse): void {
  const roll = Number(body?.roll);
  const modifier = Number(body?.modifier);
  const dc = Number(body?.dc);
  if (![roll, modifier, dc].every((n) => Number.isFinite(n))) {
    sendJson(res, 400, { error: 'roll, modifier, and dc must be numbers' });
    return;
  }
  const total = roll + modifier;
  const success = total >= dc;
  const margin = total - dc;
  sendJson(res, 200, { total, success, margin });
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

function multiplierForCount(count: number): number {
  if (count <= 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
  return 4;
}

function handleAdjustedXp(body: any, res: ServerResponse): void {
  const party = body?.party;
  const monsters = body?.monsters;
  if (!Array.isArray(party) || !Array.isArray(monsters)) {
    sendJson(res, 400, { error: 'party and monsters must be arrays' });
    return;
  }

  const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const member of party) {
    const level = Number(member?.level);
    const levelThresholds = LEVEL_THRESHOLDS[level];
    if (!Number.isFinite(level) || !levelThresholds) {
      sendJson(res, 400, { error: `unsupported party level: ${member?.level}` });
      return;
    }
    thresholds.easy += levelThresholds.easy;
    thresholds.medium += levelThresholds.medium;
    thresholds.hard += levelThresholds.hard;
    thresholds.deadly += levelThresholds.deadly;
  }

  let baseXp = 0;
  let monsterCount = 0;
  for (const monster of monsters) {
    const cr = String(monster?.cr);
    const count = Number(monster?.count);
    const xp = CR_XP[cr];
    if (xp === undefined || !Number.isFinite(count) || count <= 0) {
      sendJson(res, 400, { error: `unsupported monster: ${JSON.stringify(monster)}` });
      return;
    }
    baseXp += xp * count;
    monsterCount += count;
  }

  const multiplier = multiplierForCount(monsterCount);
  const adjustedXp = baseXp * multiplier;

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
}

function handleInitiativeOrder(body: any, res: ServerResponse): void {
  const combatants = body?.combatants;
  if (!Array.isArray(combatants)) {
    sendJson(res, 400, { error: 'combatants must be an array' });
    return;
  }

  const scored = combatants.map((c: any) => {
    const dex = Number(c?.dex);
    const roll = Number(c?.roll);
    const name = String(c?.name);
    return { name, dex, score: roll + dex };
  });

  scored.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name.localeCompare(b.name);
  });

  sendJson(res, 200, {
    order: scored.map(({ name, score }) => ({ name, score })),
  });
}

function abilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

function isIntegerInRange(value: unknown, min: number, max: number): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= min && value <= max;
}

function proficiencyBonus(level: number): number {
  return 2 + Math.floor((level - 1) / 4);
}

function handleAbilityModifier(body: any, res: ServerResponse): void {
  const score = body?.score;
  if (!isIntegerInRange(score, 1, 30)) {
    sendJson(res, 400, { error: 'score must be an integer from 1 through 30' });
    return;
  }
  sendJson(res, 200, { score, modifier: abilityModifier(score) });
}

function handleProficiency(body: any, res: ServerResponse): void {
  const level = body?.level;
  if (!isIntegerInRange(level, 1, 20)) {
    sendJson(res, 400, { error: 'level must be an integer from 1 through 20' });
    return;
  }
  sendJson(res, 200, { level, proficiency_bonus: proficiencyBonus(level) });
}

const ABILITY_KEYS = ['str', 'dex', 'con', 'int', 'wis', 'cha'] as const;

function handleDerivedStats(body: any, res: ServerResponse): void {
  const level = body?.level;
  if (!isIntegerInRange(level, 1, 20)) {
    sendJson(res, 400, { error: 'level must be an integer from 1 through 20' });
    return;
  }

  const abilities = body?.abilities;
  if (typeof abilities !== 'object' || abilities === null) {
    sendJson(res, 400, { error: 'abilities must be an object' });
    return;
  }
  const modifiers: Record<string, number> = {};
  for (const key of ABILITY_KEYS) {
    const score = abilities[key];
    if (!isIntegerInRange(score, 1, 30)) {
      sendJson(res, 400, { error: `abilities.${key} must be an integer from 1 through 30` });
      return;
    }
    modifiers[key] = abilityModifier(score);
  }

  const armor = body?.armor;
  if (typeof armor !== 'object' || armor === null) {
    sendJson(res, 400, { error: 'armor must be an object' });
    return;
  }
  const base = armor.base;
  if (typeof base !== 'number' || !Number.isFinite(base)) {
    sendJson(res, 400, { error: 'armor.base must be a number' });
    return;
  }
  const dexCap = armor.dex_cap;
  if (typeof dexCap !== 'number' || !Number.isFinite(dexCap)) {
    sendJson(res, 400, { error: 'armor.dex_cap must be a number' });
    return;
  }
  const shield = armor.shield === true;
  const shieldBonus = shield ? 2 : 0;

  const bonus = proficiencyBonus(level);
  const hpMax = level * (6 + modifiers.con);
  const armorClass = base + Math.min(modifiers.dex, dexCap) + shieldBonus;

  sendJson(res, 200, {
    level,
    proficiency_bonus: bonus,
    hp_max: hpMax,
    armor_class: armorClass,
    modifiers,
  });
}

const WIZARD_SPELL_SLOTS: Record<number, Record<string, number>> = {
  5: { '1': 4, '2': 3, '3': 2 },
};

function handleSpellSlots(body: any, res: ServerResponse): void {
  const characterClass = body?.class;
  const level = body?.level;

  if (typeof characterClass !== 'string' || characterClass.length === 0) {
    sendJson(res, 400, { error: 'class is required' });
    return;
  }
  if (!Number.isInteger(level) || level <= 0) {
    sendJson(res, 400, { error: 'level must be a positive integer' });
    return;
  }
  if (characterClass !== 'wizard' || !WIZARD_SPELL_SLOTS[level]) {
    sendJson(res, 400, { error: `unsupported class/level: ${characterClass} ${level}` });
    return;
  }

  sendJson(res, 200, { class: characterClass, level, slots: WIZARD_SPELL_SLOTS[level] });
}

function handleLongRest(body: any, res: ServerResponse): void {
  const level = body?.level;
  const hpMax = body?.hp_max;
  const hitDiceSpent = body?.hit_dice_spent;
  const exhaustionLevel = body?.exhaustion_level;

  if (!Number.isInteger(level) || level <= 0) {
    sendJson(res, 400, { error: 'level must be a positive integer' });
    return;
  }
  if (typeof body?.hp_current !== 'number' || !Number.isFinite(body.hp_current)) {
    sendJson(res, 400, { error: 'hp_current must be a number' });
    return;
  }
  if (!Number.isInteger(hpMax) || hpMax < 0) {
    sendJson(res, 400, { error: 'hp_max must be a non-negative integer' });
    return;
  }
  if (!Number.isInteger(hitDiceSpent) || hitDiceSpent < 0) {
    sendJson(res, 400, { error: 'hit_dice_spent must be a non-negative integer' });
    return;
  }
  if (!Number.isInteger(exhaustionLevel) || exhaustionLevel < 0) {
    sendJson(res, 400, { error: 'exhaustion_level must be a non-negative integer' });
    return;
  }

  const recoverable = Math.max(1, Math.floor(level / 2));
  const newHitDiceSpent = Math.max(0, hitDiceSpent - recoverable);
  const newExhaustion = Math.max(0, exhaustionLevel - 1);

  sendJson(res, 200, {
    hp_current: hpMax,
    hit_dice_spent: newHitDiceSpent,
    exhaustion_level: newExhaustion,
  });
}

function handleEquipmentLoad(body: any, res: ServerResponse): void {
  const strength = body?.strength;
  const weight = body?.weight;

  if (typeof strength !== 'number' || !Number.isFinite(strength)) {
    sendJson(res, 400, { error: 'strength must be a number' });
    return;
  }
  if (typeof weight !== 'number' || !Number.isFinite(weight)) {
    sendJson(res, 400, { error: 'weight must be a number' });
    return;
  }

  const capacity = strength * 15;
  const encumbered = weight > capacity;

  sendJson(res, 200, { capacity, weight, encumbered });
}

const ROUTES: Record<string, (body: any, res: ServerResponse) => void> = {
  '/v1/dice/stats': handleDiceStats,
  '/v1/checks/ability': handleAbilityCheck,
  '/v1/encounters/adjusted-xp': handleAdjustedXp,
  '/v1/initiative/order': handleInitiativeOrder,
  '/v1/characters/ability-modifier': handleAbilityModifier,
  '/v1/characters/proficiency': handleProficiency,
  '/v1/characters/derived-stats': handleDerivedStats,
  '/v1/auth/register': handleRegister,
  '/v1/auth/login': handleLogin,
  '/v1/compendium/monsters': handleCreateMonster,
  '/v1/compendium/items': handleCreateItem,
  '/v1/phb/spell-slots': handleSpellSlots,
  '/v1/phb/rests/long': handleLongRest,
  '/v1/phb/equipment-load': handleEquipmentLoad,
  '/v1/dm/encounter-builder': handleEncounterBuilder,
  '/v1/dm/loot-parcel': handleLootParcel,
  '/v1/dm/session-recap': handleSessionRecap,
};

interface Condition {
  condition: string;
  remaining_rounds: number;
}

interface CombatSession {
  id: string;
  round: number;
  turn_index: number;
  order: { name: string; dex: number; score: number }[];
  conditions: Record<string, Condition[]>;
}

const combatSessions = {
  get(id: string): CombatSession | undefined {
    const row = getDb().prepare('SELECT data FROM combat_sessions WHERE id = ?').get(id) as
      | { data: string }
      | undefined;
    return row ? (JSON.parse(row.data) as CombatSession) : undefined;
  },
  has(id: string): boolean {
    return this.get(id) !== undefined;
  },
  set(id: string, session: CombatSession): void {
    getDb()
      .prepare(
        'INSERT INTO combat_sessions (id, data) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data',
      )
      .run(id, JSON.stringify(session));
  },
};

function activeCombatant(session: CombatSession): { name: string; score: number } {
  const c = session.order[session.turn_index];
  return { name: c.name, score: c.score };
}

function handleCreateCombatSession(body: any, res: ServerResponse): void {
  const id = body?.id;
  const combatants = body?.combatants;
  if (typeof id !== 'string' || id.length === 0) {
    sendJson(res, 400, { error: 'id is required' });
    return;
  }
  if (combatSessions.has(id)) {
    sendJson(res, 400, { error: `session already exists: ${id}` });
    return;
  }
  if (!Array.isArray(combatants) || combatants.length === 0) {
    sendJson(res, 400, { error: 'combatants must be a non-empty array' });
    return;
  }

  const scored: { name: string; dex: number; score: number }[] = [];
  for (const c of combatants) {
    const name = c?.name;
    const dex = Number(c?.dex);
    const roll = Number(c?.roll);
    if (typeof name !== 'string' || !Number.isFinite(dex) || !Number.isFinite(roll)) {
      sendJson(res, 400, { error: 'each combatant needs name, dex, and roll' });
      return;
    }
    scored.push({ name, dex, score: roll + dex });
  }

  scored.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name.localeCompare(b.name);
  });

  const session: CombatSession = {
    id,
    round: 1,
    turn_index: 0,
    order: scored,
    conditions: {},
  };
  combatSessions.set(id, session);

  sendJson(res, 200, {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: activeCombatant(session),
    order: session.order.map(({ name, score }) => ({ name, score })),
  });
}

function handleAddCondition(sessionId: string, body: any, res: ServerResponse): void {
  const session = combatSessions.get(sessionId);
  if (!session) {
    sendJson(res, 404, { error: `unknown session: ${sessionId}` });
    return;
  }

  const target = body?.target;
  const condition = body?.condition;
  const durationRounds = body?.duration_rounds;

  if (typeof target !== 'string' || !session.order.some((c) => c.name === target)) {
    sendJson(res, 400, { error: 'target must name a combatant in the session' });
    return;
  }
  if (typeof condition !== 'string' || condition.length === 0) {
    sendJson(res, 400, { error: 'condition must be a non-empty string' });
    return;
  }
  if (!Number.isInteger(durationRounds) || durationRounds <= 0) {
    sendJson(res, 400, { error: 'duration_rounds must be a positive integer' });
    return;
  }

  const list = session.conditions[target] ?? [];
  list.push({ condition, remaining_rounds: durationRounds });
  session.conditions[target] = list;
  combatSessions.set(sessionId, session);

  sendJson(res, 200, { target, conditions: list });
}

function handleAdvanceTurn(sessionId: string, res: ServerResponse): void {
  const session = combatSessions.get(sessionId);
  if (!session) {
    sendJson(res, 404, { error: `unknown session: ${sessionId}` });
    return;
  }

  session.turn_index += 1;
  if (session.turn_index >= session.order.length) {
    session.turn_index = 0;
    session.round += 1;
  }

  const active = activeCombatant(session);
  const activeConditions = session.conditions[active.name];
  if (activeConditions) {
    const remaining: Condition[] = [];
    for (const cond of activeConditions) {
      const next = cond.remaining_rounds - 1;
      if (next > 0) {
        remaining.push({ condition: cond.condition, remaining_rounds: next });
      }
    }
    session.conditions[active.name] = remaining;
  }

  combatSessions.set(sessionId, session);

  sendJson(res, 200, {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active,
    conditions: session.conditions,
  });
}

const COMBAT_SESSION_CONDITIONS_RE = /^\/v1\/combat\/sessions\/([^/]+)\/conditions$/;
const COMBAT_SESSION_ADVANCE_RE = /^\/v1\/combat\/sessions\/([^/]+)\/advance$/;
const MONSTER_SLUG_RE = /^\/v1\/compendium\/monsters\/([^/]+)$/;
const ITEM_SLUG_RE = /^\/v1\/compendium\/items\/([^/]+)$/;
const CAMPAIGN_CHARACTERS_RE = /^\/v1\/campaigns\/([^/]+)\/characters$/;
const CAMPAIGN_EVENTS_RE = /^\/v1\/campaigns\/([^/]+)\/events$/;
const CAMPAIGN_STATE_RE = /^\/v1\/campaigns\/([^/]+)\/state$/;

const USERNAME_RE = /^[a-z0-9_-]{2,32}$/;

interface User {
  username: string;
  role: 'dm' | 'player';
  salt: string;
  hash: string;
}

const users = {
  get(username: string): User | undefined {
    const row = getDb().prepare('SELECT username, role, salt, hash FROM users WHERE username = ?').get(username) as
      | User
      | undefined;
    return row ?? undefined;
  },
  has(username: string): boolean {
    return this.get(username) !== undefined;
  },
  set(username: string, user: User): void {
    getDb()
      .prepare(
        'INSERT INTO users (username, role, salt, hash) VALUES (?, ?, ?, ?) ON CONFLICT(username) DO UPDATE SET role = excluded.role, salt = excluded.salt, hash = excluded.hash',
      )
      .run(user.username, user.role, user.salt, user.hash);
  },
};

function hashPassword(password: string, salt: string): string {
  return scryptSync(password, salt, 64).toString('hex');
}

function verifyPassword(password: string, salt: string, hash: string): boolean {
  const candidate = Buffer.from(hashPassword(password, salt), 'hex');
  const expected = Buffer.from(hash, 'hex');
  return candidate.length === expected.length && timingSafeEqual(candidate, expected);
}

function handleRegister(body: any, res: ServerResponse): void {
  const username = body?.username;
  const password = body?.password;
  const role = body?.role;

  if (typeof username !== 'string' || !USERNAME_RE.test(username)) {
    sendJson(res, 400, { error: 'username must be 2-32 characters of lowercase letters, digits, _, or -' });
    return;
  }
  if (typeof password !== 'string' || password.length < 8) {
    sendJson(res, 400, { error: 'password must be at least 8 characters' });
    return;
  }
  if (role !== 'dm' && role !== 'player') {
    sendJson(res, 400, { error: 'role must be dm or player' });
    return;
  }
  if (users.has(username)) {
    sendJson(res, 409, { error: `username already exists: ${username}` });
    return;
  }

  const salt = randomBytes(16).toString('hex');
  const hash = hashPassword(password, salt);
  users.set(username, { username, role, salt, hash });

  sendJson(res, 201, { username, role });
}

function handleLogin(body: any, res: ServerResponse): void {
  const username = body?.username;
  const password = body?.password;

  if (typeof username !== 'string' || typeof password !== 'string') {
    sendJson(res, 400, { error: 'username and password are required' });
    return;
  }

  const user = users.get(username);
  if (!user || !verifyPassword(password, user.salt, user.hash)) {
    sendJson(res, 401, { error: 'invalid credentials' });
    return;
  }

  sendJson(res, 200, { username: user.username, token: `session-${user.username}` });
}

const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

interface Monster {
  slug: string;
  name: string;
  cr: string;
  armor_class: number;
  hit_points: number;
  tags: string[];
}

const monsters = {
  get(slug: string): Monster | undefined {
    const row = getDb()
      .prepare('SELECT slug, name, cr, armor_class, hit_points, tags FROM monsters WHERE slug = ?')
      .get(slug) as
      | { slug: string; name: string; cr: string; armor_class: number; hit_points: number; tags: string }
      | undefined;
    if (!row) return undefined;
    return { ...row, tags: JSON.parse(row.tags) };
  },
  has(slug: string): boolean {
    return this.get(slug) !== undefined;
  },
  insert(monster: Monster): void {
    getDb()
      .prepare(
        'INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags) VALUES (?, ?, ?, ?, ?, ?)',
      )
      .run(
        monster.slug,
        monster.name,
        monster.cr,
        monster.armor_class,
        monster.hit_points,
        JSON.stringify(monster.tags),
      );
  },
};

interface Item {
  slug: string;
  name: string;
  type: string;
  rarity: string;
  cost_gp: number;
}

const items = {
  get(slug: string): Item | undefined {
    const row = getDb()
      .prepare('SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?')
      .get(slug) as Item | undefined;
    return row ?? undefined;
  },
  has(slug: string): boolean {
    return this.get(slug) !== undefined;
  },
  insert(item: Item): void {
    getDb()
      .prepare('INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)')
      .run(item.slug, item.name, item.type, item.rarity, item.cost_gp);
  },
};

function handleCreateMonster(body: any, res: ServerResponse): void {
  const slug = body?.slug;
  const name = body?.name;
  const cr = body?.cr;
  const armorClass = body?.armor_class;
  const hitPoints = body?.hit_points;
  const tags = body?.tags;

  if (typeof slug !== 'string' || !SLUG_RE.test(slug)) {
    sendJson(res, 400, { error: 'slug must be a lowercase, hyphenated string' });
    return;
  }
  if (typeof name !== 'string' || name.length === 0) {
    sendJson(res, 400, { error: 'name is required' });
    return;
  }
  if (typeof cr !== 'string' || cr.length === 0) {
    sendJson(res, 400, { error: 'cr is required' });
    return;
  }
  if (!Number.isInteger(armorClass) || armorClass < 0) {
    sendJson(res, 400, { error: 'armor_class must be a non-negative integer' });
    return;
  }
  if (!Number.isInteger(hitPoints) || hitPoints < 0) {
    sendJson(res, 400, { error: 'hit_points must be a non-negative integer' });
    return;
  }
  if (!Array.isArray(tags) || !tags.every((t) => typeof t === 'string')) {
    sendJson(res, 400, { error: 'tags must be an array of strings' });
    return;
  }
  if (monsters.has(slug)) {
    sendJson(res, 409, { error: `monster already exists: ${slug}` });
    return;
  }

  monsters.insert({ slug, name, cr, armor_class: armorClass, hit_points: hitPoints, tags });

  sendJson(res, 201, { slug, name, cr, armor_class: armorClass, hit_points: hitPoints });
}

function handleGetMonster(slug: string, res: ServerResponse): void {
  const monster = monsters.get(slug);
  if (!monster) {
    sendJson(res, 404, { error: `unknown monster: ${slug}` });
    return;
  }
  sendJson(res, 200, monster);
}

function handleCreateItem(body: any, res: ServerResponse): void {
  const slug = body?.slug;
  const name = body?.name;
  const type = body?.type;
  const rarity = body?.rarity;
  const costGp = body?.cost_gp;

  if (typeof slug !== 'string' || !SLUG_RE.test(slug)) {
    sendJson(res, 400, { error: 'slug must be a lowercase, hyphenated string' });
    return;
  }
  if (typeof name !== 'string' || name.length === 0) {
    sendJson(res, 400, { error: 'name is required' });
    return;
  }
  if (typeof type !== 'string' || type.length === 0) {
    sendJson(res, 400, { error: 'type is required' });
    return;
  }
  if (typeof rarity !== 'string' || rarity.length === 0) {
    sendJson(res, 400, { error: 'rarity is required' });
    return;
  }
  if (!Number.isInteger(costGp) || costGp < 0) {
    sendJson(res, 400, { error: 'cost_gp must be a non-negative integer' });
    return;
  }
  if (items.has(slug)) {
    sendJson(res, 409, { error: `item already exists: ${slug}` });
    return;
  }

  items.insert({ slug, name, type, rarity, cost_gp: costGp });

  sendJson(res, 201, { slug, name, type, rarity, cost_gp: costGp });
}

function handleGetItem(slug: string, res: ServerResponse): void {
  const item = items.get(slug);
  if (!item) {
    sendJson(res, 404, { error: `unknown item: ${slug}` });
    return;
  }
  sendJson(res, 200, item);
}

function handleStorageReset(res: ServerResponse): void {
  resetDb();
  sendJson(res, 200, { ok: true, schema_version: SCHEMA_VERSION });
}

interface Campaign {
  id: string;
  name: string;
  dm: string;
}

interface CampaignCharacter {
  id: string;
  campaign_id: string;
  name: string;
  level: number;
  class: string;
}

const campaigns = {
  get(id: string): Campaign | undefined {
    const row = getDb().prepare('SELECT id, name, dm FROM campaigns WHERE id = ?').get(id) as Campaign | undefined;
    return row ?? undefined;
  },
  has(id: string): boolean {
    return this.get(id) !== undefined;
  },
  insert(campaign: Campaign): void {
    getDb()
      .prepare('INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)')
      .run(campaign.id, campaign.name, campaign.dm);
  },
};

const campaignCharacters = {
  has(id: string): boolean {
    return (
      getDb().prepare('SELECT 1 FROM campaign_characters WHERE id = ?').get(id) !== undefined
    );
  },
  insert(character: CampaignCharacter): void {
    getDb()
      .prepare(
        'INSERT INTO campaign_characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)',
      )
      .run(character.id, character.campaign_id, character.name, character.level, character.class);
  },
  listByCampaign(campaignId: string): { id: string; name: string; level: number; class: string }[] {
    return getDb()
      .prepare('SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ?')
      .all(campaignId) as { id: string; name: string; level: number; class: string }[];
  },
};

const campaignEvents = {
  has(id: string): boolean {
    return getDb().prepare('SELECT 1 FROM campaign_events WHERE id = ?').get(id) !== undefined;
  },
  insert(event: { id: string; campaign_id: string; kind: string; summary: string }): void {
    getDb()
      .prepare('INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)')
      .run(event.id, event.campaign_id, event.kind, event.summary);
  },
  countByCampaign(campaignId: string): number {
    const row = getDb()
      .prepare('SELECT COUNT(*) as count FROM campaign_events WHERE campaign_id = ?')
      .get(campaignId) as { count: number };
    return row.count;
  },
  listSummariesNewestFirst(campaignId: string): string[] {
    const rows = getDb()
      .prepare('SELECT summary FROM campaign_events WHERE campaign_id = ? ORDER BY rowid DESC')
      .all(campaignId) as { summary: string }[];
    return rows.map((row) => row.summary);
  },
};

function handleCreateCampaign(body: any, res: ServerResponse): void {
  const id = body?.id;
  const name = body?.name;
  const dm = body?.dm;

  if (typeof id !== 'string' || id.length === 0) {
    sendJson(res, 400, { error: 'id is required' });
    return;
  }
  if (typeof name !== 'string' || name.length === 0) {
    sendJson(res, 400, { error: 'name is required' });
    return;
  }
  if (typeof dm !== 'string' || dm.length === 0) {
    sendJson(res, 400, { error: 'dm is required' });
    return;
  }
  if (campaigns.has(id)) {
    sendJson(res, 409, { error: `campaign already exists: ${id}` });
    return;
  }

  campaigns.insert({ id, name, dm });

  sendJson(res, 201, { id, name, dm });
}

function handleAddCharacter(campaignId: string, body: any, res: ServerResponse): void {
  if (!campaigns.has(campaignId)) {
    sendJson(res, 404, { error: `unknown campaign: ${campaignId}` });
    return;
  }

  const id = body?.id;
  const name = body?.name;
  const level = body?.level;
  const characterClass = body?.class;

  if (typeof id !== 'string' || id.length === 0) {
    sendJson(res, 400, { error: 'id is required' });
    return;
  }
  if (typeof name !== 'string' || name.length === 0) {
    sendJson(res, 400, { error: 'name is required' });
    return;
  }
  if (!Number.isInteger(level) || level <= 0) {
    sendJson(res, 400, { error: 'level must be a positive integer' });
    return;
  }
  if (typeof characterClass !== 'string' || characterClass.length === 0) {
    sendJson(res, 400, { error: 'class is required' });
    return;
  }
  if (campaignCharacters.has(id)) {
    sendJson(res, 409, { error: `character already exists: ${id}` });
    return;
  }

  campaignCharacters.insert({ id, campaign_id: campaignId, name, level, class: characterClass });

  sendJson(res, 201, { id, name, level, class: characterClass });
}

function handleAddEvent(campaignId: string, body: any, res: ServerResponse): void {
  if (!campaigns.has(campaignId)) {
    sendJson(res, 404, { error: `unknown campaign: ${campaignId}` });
    return;
  }

  const id = body?.id;
  const kind = body?.kind;
  const summary = body?.summary;

  if (typeof id !== 'string' || id.length === 0) {
    sendJson(res, 400, { error: 'id is required' });
    return;
  }
  if (typeof kind !== 'string' || kind.length === 0) {
    sendJson(res, 400, { error: 'kind is required' });
    return;
  }
  if (typeof summary !== 'string' || summary.length === 0) {
    sendJson(res, 400, { error: 'summary is required' });
    return;
  }
  if (campaignEvents.has(id)) {
    sendJson(res, 409, { error: `event already exists: ${id}` });
    return;
  }

  campaignEvents.insert({ id, campaign_id: campaignId, kind, summary });

  sendJson(res, 201, { id, kind });
}

function handleCampaignState(campaignId: string, res: ServerResponse): void {
  const campaign = campaigns.get(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: `unknown campaign: ${campaignId}` });
    return;
  }

  sendJson(res, 200, {
    id: campaign.id,
    name: campaign.name,
    dm: campaign.dm,
    characters: campaignCharacters.listByCampaign(campaignId),
    log_count: campaignEvents.countByCampaign(campaignId),
  });
}

const ENCOUNTER_RECOMMENDATION: Record<string, string> = {
  trivial: 'cakewalk',
  easy: 'safe warm-up',
  medium: 'a fair fight',
  hard: 'tough fight',
  deadly: 'deadly encounter',
};

function isFiniteInt(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && Number.isInteger(value);
}

function handleEncounterBuilder(body: any, res: ServerResponse): void {
  const campaignId = body?.campaign_id;
  const party = body?.party;
  const monsterSlugs = body?.monster_slugs;

  if (typeof campaignId !== 'string' || campaignId.length === 0) {
    sendJson(res, 400, { error: 'campaign_id is required' });
    return;
  }
  if (!Array.isArray(party) || party.length === 0) {
    sendJson(res, 400, { error: 'party must be a non-empty array' });
    return;
  }
  if (!Array.isArray(monsterSlugs) || monsterSlugs.length === 0) {
    sendJson(res, 400, { error: 'monster_slugs must be a non-empty array' });
    return;
  }

  let baseXp = 0;
  for (const slug of monsterSlugs) {
    if (typeof slug !== 'string' || !SLUG_RE.test(slug)) {
      sendJson(res, 400, { error: 'monster_slugs must be lowercase, hyphenated strings' });
      return;
    }
    const monster = monsters.get(slug);
    if (!monster) {
      sendJson(res, 404, { error: `unknown monster: ${slug}` });
      return;
    }
    const xp = CR_XP[monster.cr];
    if (xp === undefined) {
      sendJson(res, 400, { error: `unsupported cr: ${monster.cr}` });
      return;
    }
    baseXp += xp;
  }
  const monsterCount = monsterSlugs.length;

  const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const member of party) {
    const level = member?.level;
    const levelThresholds = LEVEL_THRESHOLDS[level];
    if (!isFiniteInt(level) || !levelThresholds) {
      sendJson(res, 400, { error: `unsupported party level: ${member?.level}` });
      return;
    }
    thresholds.easy += levelThresholds.easy;
    thresholds.medium += levelThresholds.medium;
    thresholds.hard += levelThresholds.hard;
    thresholds.deadly += levelThresholds.deadly;
  }

  const multiplier = multiplierForCount(monsterCount);
  const adjustedXp = baseXp * multiplier;

  let difficulty = 'trivial';
  if (adjustedXp >= thresholds.deadly) difficulty = 'deadly';
  else if (adjustedXp >= thresholds.hard) difficulty = 'hard';
  else if (adjustedXp >= thresholds.medium) difficulty = 'medium';
  else if (adjustedXp >= thresholds.easy) difficulty = 'easy';

  sendJson(res, 200, {
    campaign_id: campaignId,
    base_xp: baseXp,
    adjusted_xp: adjustedXp,
    difficulty,
    monster_count: monsterCount,
    recommendation: ENCOUNTER_RECOMMENDATION[difficulty],
  });
}

const LOOT_TIERS: Record<number, { coins_gp: number; items: { slug: string; quantity: number }[] }> = {
  1: { coins_gp: 75, items: [{ slug: 'healing-potion', quantity: 2 }] },
};

function handleLootParcel(body: any, res: ServerResponse): void {
  const campaignId = body?.campaign_id;
  const tier = body?.tier;

  if (typeof campaignId !== 'string' || campaignId.length === 0) {
    sendJson(res, 400, { error: 'campaign_id is required' });
    return;
  }
  if (!isFiniteInt(tier)) {
    sendJson(res, 400, { error: 'tier must be an integer' });
    return;
  }
  const parcel = LOOT_TIERS[tier];
  if (!parcel) {
    sendJson(res, 400, { error: `unsupported tier: ${tier}` });
    return;
  }

  sendJson(res, 200, {
    campaign_id: campaignId,
    coins_gp: parcel.coins_gp,
    items: parcel.items.map((item) => ({ slug: item.slug, quantity: item.quantity })),
  });
}

const OPEN_THREAD_RE = /\bthe\s+(.+?)\.?\s*$/i;

function handleSessionRecap(body: any, res: ServerResponse): void {
  const campaignId = body?.campaign_id;

  if (typeof campaignId !== 'string' || campaignId.length === 0) {
    sendJson(res, 400, { error: 'campaign_id is required' });
    return;
  }
  if (!campaigns.has(campaignId)) {
    sendJson(res, 404, { error: `unknown campaign: ${campaignId}` });
    return;
  }

  const summaries = campaignEvents.listSummariesNewestFirst(campaignId);
  const summary = summaries.length > 0 ? summaries[0] : 'No events recorded yet.';

  const openThreads: string[] = [];
  for (const eventSummary of summaries) {
    const match = OPEN_THREAD_RE.exec(eventSummary);
    if (match) {
      openThreads.push(`Resolve ${match[1]} ambush`);
      break;
    }
  }

  sendJson(res, 200, {
    campaign_id: campaignId,
    summary,
    open_threads: openThreads,
  });
}

export function ddApiMiddleware(): Connect.NextHandleFunction {
  return (req, res, next) => {
    const url = req.url ?? '';
    const path = url.split('?')[0];

    if (req.method === 'GET' && path === '/health') {
      sendJson(res, 200, { ok: true });
      return;
    }

    if (req.method === 'GET' && path === '/v1/storage/status') {
      sendJson(res, 200, storageStatus());
      return;
    }

    if (req.method === 'POST' && path === '/v1/storage/reset') {
      handleStorageReset(res);
      return;
    }

    if (req.method === 'POST' && path === '/v1/combat/sessions') {
      readJsonBody(req)
        .then((body) => handleCreateCombatSession(body, res))
        .catch(() => {
          sendJson(res, 400, { error: 'invalid json' });
        });
      return;
    }

    const conditionsMatch = COMBAT_SESSION_CONDITIONS_RE.exec(path);
    if (req.method === 'POST' && conditionsMatch) {
      readJsonBody(req)
        .then((body) => handleAddCondition(conditionsMatch[1], body, res))
        .catch(() => {
          sendJson(res, 400, { error: 'invalid json' });
        });
      return;
    }

    const advanceMatch = COMBAT_SESSION_ADVANCE_RE.exec(path);
    if (req.method === 'POST' && advanceMatch) {
      handleAdvanceTurn(advanceMatch[1], res);
      return;
    }

    const monsterSlugMatch = MONSTER_SLUG_RE.exec(path);
    if (req.method === 'GET' && monsterSlugMatch) {
      handleGetMonster(monsterSlugMatch[1], res);
      return;
    }

    const itemSlugMatch = ITEM_SLUG_RE.exec(path);
    if (req.method === 'GET' && itemSlugMatch) {
      handleGetItem(itemSlugMatch[1], res);
      return;
    }

    if (req.method === 'POST' && path === '/v1/campaigns') {
      readJsonBody(req)
        .then((body) => handleCreateCampaign(body, res))
        .catch(() => {
          sendJson(res, 400, { error: 'invalid json' });
        });
      return;
    }

    const campaignCharactersMatch = CAMPAIGN_CHARACTERS_RE.exec(path);
    if (req.method === 'POST' && campaignCharactersMatch) {
      readJsonBody(req)
        .then((body) => handleAddCharacter(campaignCharactersMatch[1], body, res))
        .catch(() => {
          sendJson(res, 400, { error: 'invalid json' });
        });
      return;
    }

    const campaignEventsMatch = CAMPAIGN_EVENTS_RE.exec(path);
    if (req.method === 'POST' && campaignEventsMatch) {
      readJsonBody(req)
        .then((body) => handleAddEvent(campaignEventsMatch[1], body, res))
        .catch(() => {
          sendJson(res, 400, { error: 'invalid json' });
        });
      return;
    }

    const campaignStateMatch = CAMPAIGN_STATE_RE.exec(path);
    if (req.method === 'GET' && campaignStateMatch) {
      handleCampaignState(campaignStateMatch[1], res);
      return;
    }

    const handler = ROUTES[path];
    if (req.method === 'POST' && handler) {
      readJsonBody(req)
        .then((body) => handler(body, res))
        .catch(() => {
          sendJson(res, 400, { error: 'invalid json' });
        });
      return;
    }

    next();
  };
}
