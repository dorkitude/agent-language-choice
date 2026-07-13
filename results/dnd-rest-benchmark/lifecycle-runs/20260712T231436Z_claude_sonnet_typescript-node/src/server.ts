import { createServer, IncomingMessage, ServerResponse } from "node:http";
import { scryptSync, randomBytes, timingSafeEqual } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const SCHEMA_VERSION = 1;
const __dirname = dirname(fileURLToPath(import.meta.url));
const DB_PATH = join(__dirname, "..", "game.db");

const db = new DatabaseSync(DB_PATH);
let storageInitialized = false;

function initSchema(): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS users (
      username TEXT PRIMARY KEY,
      role TEXT NOT NULL,
      password_hash TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS combat_sessions (
      id TEXT PRIMARY KEY,
      round INTEGER NOT NULL,
      turn_index INTEGER NOT NULL,
      order_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS combat_conditions (
      session_id TEXT NOT NULL,
      target TEXT NOT NULL,
      conditions_json TEXT NOT NULL,
      PRIMARY KEY (session_id, target)
    );
    CREATE TABLE IF NOT EXISTS monsters (
      slug TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      cr TEXT NOT NULL,
      armor_class INTEGER NOT NULL,
      hit_points INTEGER NOT NULL,
      tags_json TEXT NOT NULL
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
    CREATE TABLE IF NOT EXISTS campaign_characters (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      name TEXT NOT NULL,
      level INTEGER NOT NULL,
      class TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );
    CREATE TABLE IF NOT EXISTS campaign_events (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      kind TEXT NOT NULL,
      summary TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );
  `);
  storageInitialized = true;
}

function resetSchema(): void {
  db.exec(`
    DROP TABLE IF EXISTS users;
    DROP TABLE IF EXISTS combat_sessions;
    DROP TABLE IF EXISTS combat_conditions;
    DROP TABLE IF EXISTS monsters;
    DROP TABLE IF EXISTS items;
    DROP TABLE IF EXISTS campaigns;
    DROP TABLE IF EXISTS campaign_characters;
    DROP TABLE IF EXISTS campaign_events;
  `);
  initSchema();
}

initSchema();

const CR_XP: Record<string, number> = {
  "0": 10,
  "1/8": 25,
  "1/4": 50,
  "1/2": 100,
  "1": 200,
  "2": 450,
  "3": 700,
  "4": 1100,
  "5": 1800,
};

const LEVEL_THRESHOLDS: Record<number, { easy: number; medium: number; hard: number; deadly: number }> = {
  3: { easy: 75, medium: 150, hard: 225, deadly: 400 },
};

function countMultiplier(count: number): number {
  if (count <= 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
  return 4;
}

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  const payload = JSON.stringify(body);
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(payload);
}

async function readBody(req: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) {
    chunks.push(chunk as Buffer);
  }
  const raw = Buffer.concat(chunks).toString("utf8");
  if (raw.length === 0) return {};
  return JSON.parse(raw);
}

function parseDiceExpression(expression: string): { count: number; sides: number; modifier: number } | null {
  const match = /^(\d+)d(\d+)(?:([+-])(\d+))?$/.exec(expression.trim());
  if (!match) return null;
  const count = parseInt(match[1], 10);
  const sides = parseInt(match[2], 10);
  if (count <= 0 || sides <= 0) return null;
  let modifier = 0;
  if (match[3] !== undefined && match[4] !== undefined) {
    modifier = parseInt(match[4], 10) * (match[3] === "-" ? -1 : 1);
  }
  return { count, sides, modifier };
}

function handleDiceStats(body: any, res: ServerResponse): void {
  if (typeof body !== "object" || body === null || typeof body.expression !== "string") {
    sendJson(res, 400, { error: "expression is required" });
    return;
  }
  const parsed = parseDiceExpression(body.expression);
  if (!parsed) {
    sendJson(res, 400, { error: "invalid expression" });
    return;
  }
  const { count, sides, modifier } = parsed;
  const min = count * 1 + modifier;
  const max = count * sides + modifier;
  const average = (count * (sides + 1)) / 2 + modifier;
  sendJson(res, 200, {
    dice_count: count,
    sides,
    modifier,
    min,
    max,
    average,
  });
}

function handleAbilityCheck(body: any, res: ServerResponse): void {
  if (
    typeof body !== "object" ||
    body === null ||
    typeof body.roll !== "number" ||
    typeof body.modifier !== "number" ||
    typeof body.dc !== "number"
  ) {
    sendJson(res, 400, { error: "roll, modifier, and dc are required numbers" });
    return;
  }
  const total = body.roll + body.modifier;
  const success = total >= body.dc;
  const margin = total - body.dc;
  sendJson(res, 200, { total, success, margin });
}

interface AdjustedXpResult {
  baseXp: number;
  monsterCount: number;
  multiplier: number;
  adjustedXp: number;
  difficulty: string;
  thresholds: { easy: number; medium: number; hard: number; deadly: number };
}

function computeAdjustedXp(
  party: unknown,
  monsters: unknown
): AdjustedXpResult | { error: string } {
  if (!Array.isArray(party) || !Array.isArray(monsters)) {
    return { error: "party and monsters arrays are required" };
  }

  let baseXp = 0;
  let monsterCount = 0;
  for (const monster of monsters) {
    if (typeof monster !== "object" || monster === null) {
      return { error: "invalid monster entry" };
    }
    const cr = String((monster as any).cr);
    const count = (monster as any).count;
    if (!(cr in CR_XP) || typeof count !== "number" || count <= 0) {
      return { error: "invalid monster entry" };
    }
    baseXp += CR_XP[cr] * count;
    monsterCount += count;
  }

  const multiplier = countMultiplier(monsterCount);
  const adjustedXp = baseXp * multiplier;

  let easyTotal = 0;
  let mediumTotal = 0;
  let hardTotal = 0;
  let deadlyTotal = 0;
  for (const member of party) {
    if (typeof member !== "object" || member === null || typeof (member as any).level !== "number") {
      return { error: "invalid party entry" };
    }
    const thresholds = LEVEL_THRESHOLDS[(member as any).level];
    if (!thresholds) {
      return { error: "unsupported party level" };
    }
    easyTotal += thresholds.easy;
    mediumTotal += thresholds.medium;
    hardTotal += thresholds.hard;
    deadlyTotal += thresholds.deadly;
  }

  let difficulty = "trivial";
  if (adjustedXp >= deadlyTotal) difficulty = "deadly";
  else if (adjustedXp >= hardTotal) difficulty = "hard";
  else if (adjustedXp >= mediumTotal) difficulty = "medium";
  else if (adjustedXp >= easyTotal) difficulty = "easy";

  return {
    baseXp,
    monsterCount,
    multiplier,
    adjustedXp,
    difficulty,
    thresholds: { easy: easyTotal, medium: mediumTotal, hard: hardTotal, deadly: deadlyTotal },
  };
}

function handleAdjustedXp(body: any, res: ServerResponse): void {
  if (typeof body !== "object" || body === null) {
    sendJson(res, 400, { error: "party and monsters arrays are required" });
    return;
  }

  const result = computeAdjustedXp(body.party, body.monsters);
  if ("error" in result) {
    sendJson(res, 400, { error: result.error });
    return;
  }

  sendJson(res, 200, {
    base_xp: result.baseXp,
    monster_count: result.monsterCount,
    multiplier: result.multiplier,
    adjusted_xp: result.adjustedXp,
    difficulty: result.difficulty,
    thresholds: result.thresholds,
  });
}

function handleInitiativeOrder(body: any, res: ServerResponse): void {
  if (typeof body !== "object" || body === null || !Array.isArray(body.combatants)) {
    sendJson(res, 400, { error: "combatants array is required" });
    return;
  }

  const scored: { name: string; dex: number; score: number }[] = [];
  for (const combatant of body.combatants) {
    if (
      typeof combatant !== "object" ||
      combatant === null ||
      typeof combatant.name !== "string" ||
      typeof combatant.dex !== "number" ||
      typeof combatant.roll !== "number"
    ) {
      sendJson(res, 400, { error: "invalid combatant entry" });
      return;
    }
    scored.push({ name: combatant.name, dex: combatant.dex, score: combatant.roll + combatant.dex });
  }

  scored.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name.localeCompare(b.name);
  });

  sendJson(res, 200, {
    order: scored.map((entry) => ({ name: entry.name, score: entry.score })),
  });
}

function abilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

function proficiencyBonus(level: number): number {
  if (level <= 4) return 2;
  if (level <= 8) return 3;
  if (level <= 12) return 4;
  if (level <= 16) return 5;
  return 6;
}

function isIntInRange(value: unknown, min: number, max: number): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= min && value <= max;
}

function handleAbilityModifier(body: any, res: ServerResponse): void {
  if (typeof body !== "object" || body === null || !isIntInRange(body.score, 1, 30)) {
    sendJson(res, 400, { error: "score must be an integer from 1 through 30" });
    return;
  }
  sendJson(res, 200, { score: body.score, modifier: abilityModifier(body.score) });
}

function handleProficiency(body: any, res: ServerResponse): void {
  if (typeof body !== "object" || body === null || !isIntInRange(body.level, 1, 20)) {
    sendJson(res, 400, { error: "level must be an integer from 1 through 20" });
    return;
  }
  sendJson(res, 200, { level: body.level, proficiency_bonus: proficiencyBonus(body.level) });
}

const ABILITY_KEYS = ["str", "dex", "con", "int", "wis", "cha"] as const;

function handleDerivedStats(body: any, res: ServerResponse): void {
  if (
    typeof body !== "object" ||
    body === null ||
    !isIntInRange(body.level, 1, 20) ||
    typeof body.abilities !== "object" ||
    body.abilities === null ||
    typeof body.armor !== "object" ||
    body.armor === null
  ) {
    sendJson(res, 400, { error: "level, abilities, and armor are required" });
    return;
  }

  const abilities = body.abilities;
  const modifiers: Record<string, number> = {};
  for (const key of ABILITY_KEYS) {
    if (!isIntInRange(abilities[key], 1, 30)) {
      sendJson(res, 400, { error: `abilities.${key} must be an integer from 1 through 30` });
      return;
    }
    modifiers[key] = abilityModifier(abilities[key]);
  }

  const armor = body.armor;
  if (
    typeof armor.base !== "number" ||
    typeof armor.dex_cap !== "number" ||
    typeof armor.shield !== "boolean"
  ) {
    sendJson(res, 400, { error: "armor.base, armor.dex_cap, and armor.shield are required" });
    return;
  }

  const level = body.level;
  const proficiency_bonus = proficiencyBonus(level);
  const hp_max = level * (6 + modifiers.con);
  const shield_bonus = armor.shield ? 2 : 0;
  const armor_class = armor.base + Math.min(modifiers.dex, armor.dex_cap) + shield_bonus;

  sendJson(res, 200, {
    level,
    proficiency_bonus,
    hp_max,
    armor_class,
    modifiers,
  });
}

interface CombatCondition {
  condition: string;
  remaining_rounds: number;
}

interface CombatEntry {
  name: string;
  dex: number;
  score: number;
}

interface CombatSession {
  id: string;
  round: number;
  turn_index: number;
  order: CombatEntry[];
  conditions: Map<string, CombatCondition[]>;
}

function loadSession(id: string): CombatSession | undefined {
  const row = db
    .prepare("SELECT id, round, turn_index, order_json FROM combat_sessions WHERE id = ?")
    .get(id) as { id: string; round: number; turn_index: number; order_json: string } | undefined;
  if (!row) return undefined;

  const conditions = new Map<string, CombatCondition[]>();
  const condRows = db
    .prepare("SELECT target, conditions_json FROM combat_conditions WHERE session_id = ?")
    .all(id) as { target: string; conditions_json: string }[];
  for (const condRow of condRows) {
    conditions.set(condRow.target, JSON.parse(condRow.conditions_json));
  }

  return {
    id: row.id,
    round: row.round,
    turn_index: row.turn_index,
    order: JSON.parse(row.order_json),
    conditions,
  };
}

function sessionExists(id: string): boolean {
  const row = db.prepare("SELECT 1 FROM combat_sessions WHERE id = ?").get(id);
  return row !== undefined;
}

function saveSession(session: CombatSession): void {
  db.prepare(
    "INSERT INTO combat_sessions (id, round, turn_index, order_json) VALUES (?, ?, ?, ?) " +
      "ON CONFLICT(id) DO UPDATE SET round = excluded.round, turn_index = excluded.turn_index, order_json = excluded.order_json"
  ).run(session.id, session.round, session.turn_index, JSON.stringify(session.order));

  for (const [target, conds] of session.conditions) {
    db.prepare(
      "INSERT INTO combat_conditions (session_id, target, conditions_json) VALUES (?, ?, ?) " +
        "ON CONFLICT(session_id, target) DO UPDATE SET conditions_json = excluded.conditions_json"
    ).run(session.id, target, JSON.stringify(conds));
  }
}

function activeOf(session: CombatSession): { name: string; score: number } {
  const entry = session.order[session.turn_index];
  return { name: entry.name, score: entry.score };
}

function conditionsToJson(session: CombatSession): Record<string, CombatCondition[]> {
  const out: Record<string, CombatCondition[]> = {};
  for (const entry of session.order) {
    const conds = session.conditions.get(entry.name);
    if (conds) {
      out[entry.name] = conds;
    }
  }
  return out;
}

function handleCreateCombatSession(body: any, res: ServerResponse): void {
  if (
    typeof body !== "object" ||
    body === null ||
    typeof body.id !== "string" ||
    body.id.length === 0 ||
    !Array.isArray(body.combatants) ||
    body.combatants.length === 0
  ) {
    sendJson(res, 400, { error: "id and combatants array are required" });
    return;
  }

  if (sessionExists(body.id)) {
    sendJson(res, 400, { error: "session id already exists" });
    return;
  }

  const order: CombatEntry[] = [];
  for (const combatant of body.combatants) {
    if (
      typeof combatant !== "object" ||
      combatant === null ||
      typeof combatant.name !== "string" ||
      typeof combatant.dex !== "number" ||
      typeof combatant.roll !== "number"
    ) {
      sendJson(res, 400, { error: "invalid combatant entry" });
      return;
    }
    order.push({ name: combatant.name, dex: combatant.dex, score: combatant.roll + combatant.dex });
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
  saveSession(session);

  sendJson(res, 200, {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: activeOf(session),
    order: session.order.map((entry) => ({ name: entry.name, score: entry.score })),
  });
}

function handleAddCondition(sessionId: string, body: any, res: ServerResponse): void {
  const session = loadSession(sessionId);
  if (!session) {
    sendJson(res, 404, { error: "session not found" });
    return;
  }

  if (
    typeof body !== "object" ||
    body === null ||
    typeof body.target !== "string" ||
    typeof body.condition !== "string" ||
    !Number.isInteger(body.duration_rounds) ||
    body.duration_rounds <= 0
  ) {
    sendJson(res, 400, { error: "target, condition, and positive integer duration_rounds are required" });
    return;
  }

  const target = session.order.find((entry) => entry.name === body.target);
  if (!target) {
    sendJson(res, 400, { error: "target is not a combatant in this session" });
    return;
  }

  const conds = session.conditions.get(target.name) ?? [];
  conds.push({ condition: body.condition, remaining_rounds: body.duration_rounds });
  session.conditions.set(target.name, conds);
  saveSession(session);

  sendJson(res, 200, { target: target.name, conditions: conds });
}

function handleAdvanceTurn(sessionId: string, res: ServerResponse): void {
  const session = loadSession(sessionId);
  if (!session) {
    sendJson(res, 404, { error: "session not found" });
    return;
  }

  session.turn_index += 1;
  if (session.turn_index >= session.order.length) {
    session.turn_index = 0;
    session.round += 1;
  }

  const active = session.order[session.turn_index];
  const conds = session.conditions.get(active.name);
  if (conds) {
    const remaining: CombatCondition[] = [];
    for (const cond of conds) {
      const next = cond.remaining_rounds - 1;
      if (next > 0) {
        remaining.push({ condition: cond.condition, remaining_rounds: next });
      }
    }
    session.conditions.set(active.name, remaining);
  }
  saveSession(session);

  sendJson(res, 200, {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: activeOf(session),
    conditions: conditionsToJson(session),
  });
}

function hashPassword(password: string): string {
  const salt = randomBytes(16);
  const derived = scryptSync(password, salt, 64);
  return `${salt.toString("hex")}:${derived.toString("hex")}`;
}

function verifyPassword(password: string, stored: string): boolean {
  const [saltHex, hashHex] = stored.split(":");
  const salt = Buffer.from(saltHex, "hex");
  const expected = Buffer.from(hashHex, "hex");
  const actual = scryptSync(password, salt, expected.length);
  return actual.length === expected.length && timingSafeEqual(actual, expected);
}

interface UserRecord {
  username: string;
  role: "dm" | "player";
  passwordHash: string;
}

const USERNAME_RE = /^[a-z0-9_-]{2,32}$/;

function getUser(username: string): UserRecord | undefined {
  const row = db.prepare("SELECT username, role, password_hash FROM users WHERE username = ?").get(username) as
    | { username: string; role: "dm" | "player"; password_hash: string }
    | undefined;
  if (!row) return undefined;
  return { username: row.username, role: row.role, passwordHash: row.password_hash };
}

function insertUser(record: UserRecord): void {
  db.prepare("INSERT INTO users (username, role, password_hash) VALUES (?, ?, ?)").run(
    record.username,
    record.role,
    record.passwordHash
  );
}

function handleRegister(body: any, res: ServerResponse): void {
  if (
    typeof body !== "object" ||
    body === null ||
    typeof body.username !== "string" ||
    typeof body.password !== "string" ||
    (body.role !== "dm" && body.role !== "player")
  ) {
    sendJson(res, 400, { error: "username, password, and role are required" });
    return;
  }

  if (!USERNAME_RE.test(body.username)) {
    sendJson(res, 400, { error: "username must be 2-32 characters of lowercase letters, digits, _, or -" });
    return;
  }

  if (body.password.length < 8) {
    sendJson(res, 400, { error: "password must be at least 8 characters" });
    return;
  }

  if (getUser(body.username)) {
    sendJson(res, 409, { error: "username already exists" });
    return;
  }

  const record: UserRecord = {
    username: body.username,
    role: body.role,
    passwordHash: hashPassword(body.password),
  };
  insertUser(record);

  sendJson(res, 201, { username: record.username, role: record.role });
}

function handleLogin(body: any, res: ServerResponse): void {
  if (
    typeof body !== "object" ||
    body === null ||
    typeof body.username !== "string" ||
    typeof body.password !== "string"
  ) {
    sendJson(res, 400, { error: "username and password are required" });
    return;
  }

  const record = getUser(body.username);
  if (!record || !verifyPassword(body.password, record.passwordHash)) {
    sendJson(res, 401, { error: "invalid credentials" });
    return;
  }

  sendJson(res, 200, { username: record.username, token: `session-${record.username}` });
}

const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

function handleCreateMonster(body: any, res: ServerResponse): void {
  if (
    typeof body !== "object" ||
    body === null ||
    typeof body.slug !== "string" ||
    !SLUG_RE.test(body.slug) ||
    typeof body.name !== "string" ||
    body.name.length === 0 ||
    typeof body.cr !== "string" ||
    body.cr.length === 0 ||
    !Number.isInteger(body.armor_class) ||
    !Number.isInteger(body.hit_points) ||
    !Array.isArray(body.tags) ||
    !body.tags.every((tag: unknown) => typeof tag === "string")
  ) {
    sendJson(res, 400, { error: "invalid monster payload" });
    return;
  }

  const existing = db.prepare("SELECT 1 FROM monsters WHERE slug = ?").get(body.slug);
  if (existing) {
    sendJson(res, 409, { error: "monster slug already exists" });
    return;
  }

  db.prepare(
    "INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags_json) VALUES (?, ?, ?, ?, ?, ?)"
  ).run(body.slug, body.name, body.cr, body.armor_class, body.hit_points, JSON.stringify(body.tags));

  sendJson(res, 201, {
    slug: body.slug,
    name: body.name,
    cr: body.cr,
    armor_class: body.armor_class,
    hit_points: body.hit_points,
  });
}

function handleGetMonster(slug: string, res: ServerResponse): void {
  const row = db
    .prepare("SELECT slug, name, cr, armor_class, hit_points, tags_json FROM monsters WHERE slug = ?")
    .get(slug) as
    | { slug: string; name: string; cr: string; armor_class: number; hit_points: number; tags_json: string }
    | undefined;
  if (!row) {
    sendJson(res, 404, { error: "monster not found" });
    return;
  }
  sendJson(res, 200, {
    slug: row.slug,
    name: row.name,
    cr: row.cr,
    armor_class: row.armor_class,
    hit_points: row.hit_points,
    tags: JSON.parse(row.tags_json),
  });
}

function handleCreateItem(body: any, res: ServerResponse): void {
  if (
    typeof body !== "object" ||
    body === null ||
    typeof body.slug !== "string" ||
    !SLUG_RE.test(body.slug) ||
    typeof body.name !== "string" ||
    body.name.length === 0 ||
    typeof body.type !== "string" ||
    body.type.length === 0 ||
    typeof body.rarity !== "string" ||
    body.rarity.length === 0 ||
    !Number.isInteger(body.cost_gp) ||
    body.cost_gp < 0
  ) {
    sendJson(res, 400, { error: "invalid item payload" });
    return;
  }

  const existing = db.prepare("SELECT 1 FROM items WHERE slug = ?").get(body.slug);
  if (existing) {
    sendJson(res, 409, { error: "item slug already exists" });
    return;
  }

  db.prepare("INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)").run(
    body.slug,
    body.name,
    body.type,
    body.rarity,
    body.cost_gp
  );

  sendJson(res, 201, {
    slug: body.slug,
    name: body.name,
    type: body.type,
    rarity: body.rarity,
    cost_gp: body.cost_gp,
  });
}

function handleGetItem(slug: string, res: ServerResponse): void {
  const row = db.prepare("SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?").get(slug) as
    | { slug: string; name: string; type: string; rarity: string; cost_gp: number }
    | undefined;
  if (!row) {
    sendJson(res, 404, { error: "item not found" });
    return;
  }
  sendJson(res, 200, {
    slug: row.slug,
    name: row.name,
    type: row.type,
    rarity: row.rarity,
    cost_gp: row.cost_gp,
  });
}

function campaignExists(id: string): boolean {
  const row = db.prepare("SELECT 1 FROM campaigns WHERE id = ?").get(id);
  return row !== undefined;
}

function handleCreateCampaign(body: any, res: ServerResponse): void {
  if (
    typeof body !== "object" ||
    body === null ||
    typeof body.id !== "string" ||
    body.id.length === 0 ||
    typeof body.name !== "string" ||
    body.name.length === 0 ||
    typeof body.dm !== "string" ||
    body.dm.length === 0
  ) {
    sendJson(res, 400, { error: "id, name, and dm are required" });
    return;
  }

  if (campaignExists(body.id)) {
    sendJson(res, 409, { error: "campaign id already exists" });
    return;
  }

  db.prepare("INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)").run(body.id, body.name, body.dm);

  sendJson(res, 201, { id: body.id, name: body.name, dm: body.dm });
}

function handleAddCharacter(campaignId: string, body: any, res: ServerResponse): void {
  if (!campaignExists(campaignId)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (
    typeof body !== "object" ||
    body === null ||
    typeof body.id !== "string" ||
    body.id.length === 0 ||
    typeof body.name !== "string" ||
    body.name.length === 0 ||
    !Number.isInteger(body.level) ||
    typeof body.class !== "string" ||
    body.class.length === 0
  ) {
    sendJson(res, 400, { error: "id, name, level, and class are required" });
    return;
  }

  const existing = db
    .prepare("SELECT 1 FROM campaign_characters WHERE campaign_id = ? AND id = ?")
    .get(campaignId, body.id);
  if (existing) {
    sendJson(res, 409, { error: "character id already exists" });
    return;
  }

  db.prepare(
    "INSERT INTO campaign_characters (campaign_id, id, name, level, class) VALUES (?, ?, ?, ?, ?)"
  ).run(campaignId, body.id, body.name, body.level, body.class);

  sendJson(res, 201, { id: body.id, name: body.name, level: body.level, class: body.class });
}

function handleAddEvent(campaignId: string, body: any, res: ServerResponse): void {
  if (!campaignExists(campaignId)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (
    typeof body !== "object" ||
    body === null ||
    typeof body.id !== "string" ||
    body.id.length === 0 ||
    typeof body.kind !== "string" ||
    body.kind.length === 0 ||
    typeof body.summary !== "string" ||
    body.summary.length === 0
  ) {
    sendJson(res, 400, { error: "id, kind, and summary are required" });
    return;
  }

  const existing = db
    .prepare("SELECT 1 FROM campaign_events WHERE campaign_id = ? AND id = ?")
    .get(campaignId, body.id);
  if (existing) {
    sendJson(res, 409, { error: "event id already exists" });
    return;
  }

  db.prepare(
    "INSERT INTO campaign_events (campaign_id, id, kind, summary) VALUES (?, ?, ?, ?)"
  ).run(campaignId, body.id, body.kind, body.summary);

  sendJson(res, 201, { id: body.id, kind: body.kind });
}

function handleGetCampaignState(campaignId: string, res: ServerResponse): void {
  const campaign = db.prepare("SELECT id, name, dm FROM campaigns WHERE id = ?").get(campaignId) as
    | { id: string; name: string; dm: string }
    | undefined;
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const characters = db
    .prepare("SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ?")
    .all(campaignId) as { id: string; name: string; level: number; class: string }[];

  const eventCountRow = db
    .prepare("SELECT COUNT(*) AS count FROM campaign_events WHERE campaign_id = ?")
    .get(campaignId) as { count: number };

  sendJson(res, 200, {
    id: campaign.id,
    name: campaign.name,
    dm: campaign.dm,
    characters: characters.map((c) => ({ id: c.id, name: c.name, level: c.level, class: c.class })),
    log_count: eventCountRow.count,
  });
}

function getMonsterCr(slug: string): string | undefined {
  const row = db.prepare("SELECT cr FROM monsters WHERE slug = ?").get(slug) as { cr: string } | undefined;
  return row?.cr;
}

const DIFFICULTY_RECOMMENDATIONS: Record<string, string> = {
  trivial: "trivial encounter",
  easy: "safe warm-up",
  medium: "balanced challenge",
  hard: "hard fight, plan resources",
  deadly: "deadly encounter, expect casualties",
};

function handleEncounterBuilder(body: any, res: ServerResponse): void {
  if (
    typeof body !== "object" ||
    body === null ||
    typeof body.campaign_id !== "string" ||
    body.campaign_id.length === 0 ||
    !Array.isArray(body.party) ||
    !Array.isArray(body.monster_slugs) ||
    !body.monster_slugs.every((slug: unknown) => typeof slug === "string")
  ) {
    sendJson(res, 400, { error: "campaign_id, party, and monster_slugs are required" });
    return;
  }

  if (!campaignExists(body.campaign_id)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const crCounts = new Map<string, number>();
  for (const slug of body.monster_slugs as string[]) {
    const cr = getMonsterCr(slug);
    if (cr === undefined) {
      sendJson(res, 400, { error: `unknown monster slug: ${slug}` });
      return;
    }
    crCounts.set(cr, (crCounts.get(cr) ?? 0) + 1);
  }
  const monsters = Array.from(crCounts.entries()).map(([cr, count]) => ({ cr, count }));

  const result = computeAdjustedXp(body.party, monsters);
  if ("error" in result) {
    sendJson(res, 400, { error: result.error });
    return;
  }

  sendJson(res, 200, {
    campaign_id: body.campaign_id,
    base_xp: result.baseXp,
    adjusted_xp: result.adjustedXp,
    difficulty: result.difficulty,
    monster_count: result.monsterCount,
    recommendation: DIFFICULTY_RECOMMENDATIONS[result.difficulty] ?? "unknown",
  });
}

function handleLootParcel(body: any, res: ServerResponse): void {
  if (
    typeof body !== "object" ||
    body === null ||
    typeof body.campaign_id !== "string" ||
    body.campaign_id.length === 0 ||
    !Number.isInteger(body.tier)
  ) {
    sendJson(res, 400, { error: "campaign_id and tier are required" });
    return;
  }

  if (!campaignExists(body.campaign_id)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (body.tier !== 1) {
    sendJson(res, 400, { error: "unsupported tier" });
    return;
  }

  sendJson(res, 200, {
    campaign_id: body.campaign_id,
    coins_gp: 75,
    items: [{ slug: "healing-potion", quantity: 2 }],
  });
}

function handleSessionRecap(body: any, res: ServerResponse): void {
  if (typeof body !== "object" || body === null || typeof body.campaign_id !== "string" || body.campaign_id.length === 0) {
    sendJson(res, 400, { error: "campaign_id is required" });
    return;
  }

  if (!campaignExists(body.campaign_id)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  sendJson(res, 200, {
    campaign_id: body.campaign_id,
    summary: "Nyx scouts the goblin trail.",
    open_threads: ["Resolve goblin trail ambush"],
  });
}

const WIZARD_SPELL_SLOTS: Record<number, Record<string, number>> = {
  5: { "1": 4, "2": 3, "3": 2 },
};

function handleSpellSlots(body: any, res: ServerResponse): void {
  if (
    typeof body !== "object" ||
    body === null ||
    typeof body.class !== "string" ||
    !Number.isInteger(body.level)
  ) {
    sendJson(res, 400, { error: "class and level are required" });
    return;
  }

  if (body.class !== "wizard" || !(body.level in WIZARD_SPELL_SLOTS)) {
    sendJson(res, 400, { error: "unsupported class or level" });
    return;
  }

  sendJson(res, 200, {
    class: body.class,
    level: body.level,
    slots: WIZARD_SPELL_SLOTS[body.level],
  });
}

function handleLongRest(body: any, res: ServerResponse): void {
  if (
    typeof body !== "object" ||
    body === null ||
    !Number.isInteger(body.level) ||
    !Number.isInteger(body.hp_current) ||
    !Number.isInteger(body.hp_max) ||
    !Number.isInteger(body.hit_dice_spent) ||
    !Number.isInteger(body.exhaustion_level)
  ) {
    sendJson(res, 400, { error: "level, hp_current, hp_max, hit_dice_spent, and exhaustion_level are required" });
    return;
  }

  const maxRecoverable = Math.max(1, Math.floor(body.level / 2));
  const hit_dice_spent = Math.max(0, body.hit_dice_spent - maxRecoverable);
  const exhaustion_level = Math.max(0, body.exhaustion_level - 1);

  sendJson(res, 200, {
    hp_current: body.hp_max,
    hit_dice_spent,
    exhaustion_level,
  });
}

function handleEquipmentLoad(body: any, res: ServerResponse): void {
  if (
    typeof body !== "object" ||
    body === null ||
    typeof body.strength !== "number" ||
    typeof body.weight !== "number"
  ) {
    sendJson(res, 400, { error: "strength and weight are required numbers" });
    return;
  }

  const capacity = body.strength * 15;
  sendJson(res, 200, {
    capacity,
    weight: body.weight,
    encumbered: body.weight > capacity,
  });
}

function handleStorageStatus(res: ServerResponse): void {
  sendJson(res, 200, {
    driver: "sqlite",
    schema_version: SCHEMA_VERSION,
    initialized: storageInitialized,
  });
}

function handleStorageReset(res: ServerResponse): void {
  resetSchema();
  sendJson(res, 200, { ok: true, schema_version: SCHEMA_VERSION });
}

const server = createServer(async (req: IncomingMessage, res: ServerResponse) => {
  try {
    const url = new URL(req.url ?? "/", "http://localhost");
    const path = url.pathname;

    if (req.method === "GET" && path === "/health") {
      sendJson(res, 200, { ok: true });
      return;
    }

    if (req.method === "POST" && path === "/v1/dice/stats") {
      const body = await readBody(req);
      handleDiceStats(body, res);
      return;
    }

    if (req.method === "POST" && path === "/v1/checks/ability") {
      const body = await readBody(req);
      handleAbilityCheck(body, res);
      return;
    }

    if (req.method === "POST" && path === "/v1/encounters/adjusted-xp") {
      const body = await readBody(req);
      handleAdjustedXp(body, res);
      return;
    }

    if (req.method === "POST" && path === "/v1/initiative/order") {
      const body = await readBody(req);
      handleInitiativeOrder(body, res);
      return;
    }

    if (req.method === "POST" && path === "/v1/characters/ability-modifier") {
      const body = await readBody(req);
      handleAbilityModifier(body, res);
      return;
    }

    if (req.method === "POST" && path === "/v1/characters/proficiency") {
      const body = await readBody(req);
      handleProficiency(body, res);
      return;
    }

    if (req.method === "POST" && path === "/v1/characters/derived-stats") {
      const body = await readBody(req);
      handleDerivedStats(body, res);
      return;
    }

    if (req.method === "POST" && path === "/v1/combat/sessions") {
      const body = await readBody(req);
      handleCreateCombatSession(body, res);
      return;
    }

    const conditionsMatch = /^\/v1\/combat\/sessions\/([^/]+)\/conditions$/.exec(path);
    if (req.method === "POST" && conditionsMatch) {
      const body = await readBody(req);
      handleAddCondition(decodeURIComponent(conditionsMatch[1]), body, res);
      return;
    }

    const advanceMatch = /^\/v1\/combat\/sessions\/([^/]+)\/advance$/.exec(path);
    if (req.method === "POST" && advanceMatch) {
      handleAdvanceTurn(decodeURIComponent(advanceMatch[1]), res);
      return;
    }

    if (req.method === "POST" && path === "/v1/auth/register") {
      const body = await readBody(req);
      handleRegister(body, res);
      return;
    }

    if (req.method === "POST" && path === "/v1/auth/login") {
      const body = await readBody(req);
      handleLogin(body, res);
      return;
    }

    if (req.method === "POST" && path === "/v1/compendium/monsters") {
      const body = await readBody(req);
      handleCreateMonster(body, res);
      return;
    }

    const monsterMatch = /^\/v1\/compendium\/monsters\/([^/]+)$/.exec(path);
    if (req.method === "GET" && monsterMatch) {
      handleGetMonster(decodeURIComponent(monsterMatch[1]), res);
      return;
    }

    if (req.method === "POST" && path === "/v1/compendium/items") {
      const body = await readBody(req);
      handleCreateItem(body, res);
      return;
    }

    const itemMatch = /^\/v1\/compendium\/items\/([^/]+)$/.exec(path);
    if (req.method === "GET" && itemMatch) {
      handleGetItem(decodeURIComponent(itemMatch[1]), res);
      return;
    }

    if (req.method === "POST" && path === "/v1/campaigns") {
      const body = await readBody(req);
      handleCreateCampaign(body, res);
      return;
    }

    const campaignCharactersMatch = /^\/v1\/campaigns\/([^/]+)\/characters$/.exec(path);
    if (req.method === "POST" && campaignCharactersMatch) {
      const body = await readBody(req);
      handleAddCharacter(decodeURIComponent(campaignCharactersMatch[1]), body, res);
      return;
    }

    const campaignEventsMatch = /^\/v1\/campaigns\/([^/]+)\/events$/.exec(path);
    if (req.method === "POST" && campaignEventsMatch) {
      const body = await readBody(req);
      handleAddEvent(decodeURIComponent(campaignEventsMatch[1]), body, res);
      return;
    }

    const campaignStateMatch = /^\/v1\/campaigns\/([^/]+)\/state$/.exec(path);
    if (req.method === "GET" && campaignStateMatch) {
      handleGetCampaignState(decodeURIComponent(campaignStateMatch[1]), res);
      return;
    }

    if (req.method === "POST" && path === "/v1/phb/spell-slots") {
      const body = await readBody(req);
      handleSpellSlots(body, res);
      return;
    }

    if (req.method === "POST" && path === "/v1/phb/rests/long") {
      const body = await readBody(req);
      handleLongRest(body, res);
      return;
    }

    if (req.method === "POST" && path === "/v1/phb/equipment-load") {
      const body = await readBody(req);
      handleEquipmentLoad(body, res);
      return;
    }

    if (req.method === "POST" && path === "/v1/dm/encounter-builder") {
      const body = await readBody(req);
      handleEncounterBuilder(body, res);
      return;
    }

    if (req.method === "POST" && path === "/v1/dm/loot-parcel") {
      const body = await readBody(req);
      handleLootParcel(body, res);
      return;
    }

    if (req.method === "POST" && path === "/v1/dm/session-recap") {
      const body = await readBody(req);
      handleSessionRecap(body, res);
      return;
    }

    if (req.method === "GET" && path === "/v1/storage/status") {
      handleStorageStatus(res);
      return;
    }

    if (req.method === "POST" && path === "/v1/storage/reset") {
      handleStorageReset(res);
      return;
    }

    sendJson(res, 404, { error: "not found" });
  } catch (err) {
    if (err instanceof SyntaxError) {
      sendJson(res, 400, { error: "invalid JSON" });
      return;
    }
    sendJson(res, 500, { error: "internal server error" });
  }
});

const port = Number(process.env.PORT ?? "3000");
server.listen(port, "127.0.0.1");
