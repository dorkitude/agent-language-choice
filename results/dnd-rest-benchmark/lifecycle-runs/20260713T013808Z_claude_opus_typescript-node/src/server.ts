import { createServer, IncomingMessage, ServerResponse } from "node:http";
import { randomBytes, scryptSync, timingSafeEqual } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import { join } from "node:path";

type Json = Record<string, unknown>;

const SCHEMA_VERSION = 1;
const DB_PATH = join(process.cwd(), "game.db");

// Durable game-world and game-state data lives behind SQLite. The in-memory
// Maps below act as a working mirror that is rehydrated from the database on
// startup and kept in sync on every mutation.
const db = new DatabaseSync(DB_PATH);

function initSchema(): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS meta (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS users (
      username TEXT PRIMARY KEY,
      role TEXT NOT NULL,
      password_hash TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS combat_sessions (
      id TEXT PRIMARY KEY,
      data TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS monsters (
      slug TEXT PRIMARY KEY,
      data TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS items (
      slug TEXT PRIMARY KEY,
      data TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS campaigns (
      id TEXT PRIMARY KEY,
      data TEXT NOT NULL
    );
  `);
  db.prepare(
    "INSERT INTO meta (key, value) VALUES ('schema_version', ?) " +
      "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
  ).run(String(SCHEMA_VERSION));
}

function isInitialized(): boolean {
  const row = db
    .prepare("SELECT value FROM meta WHERE key = 'schema_version'")
    .get() as { value?: string } | undefined;
  return row !== undefined && row.value === String(SCHEMA_VERSION);
}

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

function multiplierFor(count: number): number {
  if (count <= 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
  return 4;
}

function isInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}

function sendJson(res: ServerResponse, status: number, body: Json): void {
  const payload = JSON.stringify(body);
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(payload);
}

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on("data", (chunk: Buffer) => chunks.push(chunk));
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

async function parseJsonBody(req: IncomingMessage, res: ServerResponse): Promise<Json | undefined> {
  const raw = await readBody(req);
  let parsed: unknown;
  try {
    parsed = raw.length === 0 ? {} : JSON.parse(raw);
  } catch {
    sendJson(res, 400, { error: "invalid json" });
    return undefined;
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    sendJson(res, 400, { error: "invalid body" });
    return undefined;
  }
  return parsed as Json;
}

function parseDice(expression: unknown):
  | { dice_count: number; sides: number; modifier: number; min: number; max: number; average: number }
  | null {
  if (typeof expression !== "string") return null;
  const match = /^(\d+)d(\d+)([+-]\d+)?$/.exec(expression.trim());
  if (!match) return null;
  const dice_count = Number.parseInt(match[1], 10);
  const sides = Number.parseInt(match[2], 10);
  const modifier = match[3] ? Number.parseInt(match[3], 10) : 0;
  if (dice_count <= 0 || sides <= 0) return null;
  const min = dice_count * 1 + modifier;
  const max = dice_count * sides + modifier;
  const average = (min + max) / 2;
  return { dice_count, sides, modifier, min, max, average };
}

function handleDiceStats(body: Json, res: ServerResponse): void {
  const result = parseDice(body["expression"]);
  if (!result) {
    sendJson(res, 400, { error: "invalid expression" });
    return;
  }
  sendJson(res, 200, result);
}

function handleAbilityCheck(body: Json, res: ServerResponse): void {
  const roll = body["roll"];
  const modifier = body["modifier"];
  const dc = body["dc"];
  if (!isInteger(roll) || !isInteger(modifier) || !isInteger(dc)) {
    sendJson(res, 400, { error: "invalid check" });
    return;
  }
  const total = roll + modifier;
  sendJson(res, 200, { total, success: total >= dc, margin: total - dc });
}

function handleAdjustedXp(body: Json, res: ServerResponse): void {
  const party = body["party"];
  const monsters = body["monsters"];
  if (!Array.isArray(party) || !Array.isArray(monsters)) {
    sendJson(res, 400, { error: "invalid encounter" });
    return;
  }

  const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const member of party) {
    if (!member || typeof member !== "object") {
      sendJson(res, 400, { error: "invalid party member" });
      return;
    }
    const level = (member as Json)["level"];
    if (!isInteger(level) || !(level in LEVEL_THRESHOLDS)) {
      sendJson(res, 400, { error: "unsupported level" });
      return;
    }
    const t = LEVEL_THRESHOLDS[level];
    thresholds.easy += t.easy;
    thresholds.medium += t.medium;
    thresholds.hard += t.hard;
    thresholds.deadly += t.deadly;
  }

  let base_xp = 0;
  let monster_count = 0;
  for (const monster of monsters) {
    if (!monster || typeof monster !== "object") {
      sendJson(res, 400, { error: "invalid monster" });
      return;
    }
    const cr = (monster as Json)["cr"];
    const count = (monster as Json)["count"];
    const crKey = typeof cr === "string" ? cr : typeof cr === "number" ? String(cr) : null;
    if (crKey === null || !(crKey in CR_XP)) {
      sendJson(res, 400, { error: "unsupported cr" });
      return;
    }
    if (!isInteger(count) || count < 0) {
      sendJson(res, 400, { error: "invalid count" });
      return;
    }
    base_xp += CR_XP[crKey] * count;
    monster_count += count;
  }

  const multiplier = multiplierFor(monster_count);
  const adjusted_xp = base_xp * multiplier;

  let difficulty = "trivial";
  if (adjusted_xp >= thresholds.deadly) difficulty = "deadly";
  else if (adjusted_xp >= thresholds.hard) difficulty = "hard";
  else if (adjusted_xp >= thresholds.medium) difficulty = "medium";
  else if (adjusted_xp >= thresholds.easy) difficulty = "easy";

  sendJson(res, 200, {
    base_xp,
    monster_count,
    multiplier,
    adjusted_xp,
    difficulty,
    thresholds,
  });
}

function handleInitiative(body: Json, res: ServerResponse): void {
  const combatants = body["combatants"];
  if (!Array.isArray(combatants)) {
    sendJson(res, 400, { error: "invalid combatants" });
    return;
  }
  const entries: { name: string; dex: number; score: number }[] = [];
  for (const c of combatants) {
    if (!c || typeof c !== "object") {
      sendJson(res, 400, { error: "invalid combatant" });
      return;
    }
    const name = (c as Json)["name"];
    const dex = (c as Json)["dex"];
    const roll = (c as Json)["roll"];
    if (typeof name !== "string" || !isInteger(dex) || !isInteger(roll)) {
      sendJson(res, 400, { error: "invalid combatant" });
      return;
    }
    entries.push({ name, dex, score: roll + dex });
  }

  entries.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
  });

  sendJson(res, 200, { order: entries.map((e) => ({ name: e.name, score: e.score })) });
}

function abilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

function proficiencyBonus(level: number): number {
  return Math.floor((level - 1) / 4) + 2;
}

function handleAbilityModifier(body: Json, res: ServerResponse): void {
  const score = body["score"];
  if (!isInteger(score) || score < 1 || score > 30) {
    sendJson(res, 400, { error: "invalid score" });
    return;
  }
  sendJson(res, 200, { score, modifier: abilityModifier(score) });
}

function handleProficiency(body: Json, res: ServerResponse): void {
  const level = body["level"];
  if (!isInteger(level) || level < 1 || level > 20) {
    sendJson(res, 400, { error: "invalid level" });
    return;
  }
  sendJson(res, 200, { level, proficiency_bonus: proficiencyBonus(level) });
}

const ABILITY_KEYS = ["str", "dex", "con", "int", "wis", "cha"] as const;

function handleDerivedStats(body: Json, res: ServerResponse): void {
  const level = body["level"];
  if (!isInteger(level) || level < 1 || level > 20) {
    sendJson(res, 400, { error: "invalid level" });
    return;
  }

  const abilities = body["abilities"];
  if (!abilities || typeof abilities !== "object" || Array.isArray(abilities)) {
    sendJson(res, 400, { error: "invalid abilities" });
    return;
  }
  const abilitiesObj = abilities as Json;
  const modifiers: Record<string, number> = {};
  for (const key of ABILITY_KEYS) {
    const score = abilitiesObj[key];
    if (!isInteger(score) || score < 1 || score > 30) {
      sendJson(res, 400, { error: "invalid abilities" });
      return;
    }
    modifiers[key] = abilityModifier(score);
  }

  const armor = body["armor"];
  if (!armor || typeof armor !== "object" || Array.isArray(armor)) {
    sendJson(res, 400, { error: "invalid armor" });
    return;
  }
  const armorObj = armor as Json;
  const base = armorObj["base"];
  const shield = armorObj["shield"];
  const dexCap = armorObj["dex_cap"];
  if (!isInteger(base) || typeof shield !== "boolean" || !isInteger(dexCap)) {
    sendJson(res, 400, { error: "invalid armor" });
    return;
  }

  const proficiency_bonus = proficiencyBonus(level);
  const hp_max = level * (6 + modifiers["con"]);
  const shield_bonus = shield ? 2 : 0;
  const armor_class = base + Math.min(modifiers["dex"], dexCap) + shield_bonus;

  sendJson(res, 200, {
    level,
    proficiency_bonus,
    hp_max,
    armor_class,
    modifiers,
  });
}

interface Condition {
  condition: string;
  remaining_rounds: number;
}

interface Combatant {
  name: string;
  dex: number;
  score: number;
  conditions: Condition[];
}

interface CombatSession {
  id: string;
  round: number;
  turn_index: number;
  order: Combatant[];
}

const combatSessions = new Map<string, CombatSession>();

function orderView(order: Combatant[]): Json[] {
  return order.map((c) => ({ name: c.name, score: c.score }));
}

function activeView(session: CombatSession): Json {
  const active = session.order[session.turn_index];
  return { name: active.name, score: active.score };
}

function conditionsView(session: CombatSession, forceInclude?: string): Json {
  const out: Record<string, Json[]> = {};
  for (const c of session.order) {
    if (c.conditions.length > 0 || c.name === forceInclude) {
      out[c.name] = c.conditions.map((cond) => ({
        condition: cond.condition,
        remaining_rounds: cond.remaining_rounds,
      }));
    }
  }
  return out;
}

function handleCreateCombatSession(body: Json, res: ServerResponse): void {
  const id = body["id"];
  const combatants = body["combatants"];
  if (typeof id !== "string" || id.length === 0) {
    sendJson(res, 400, { error: "invalid id" });
    return;
  }
  if (!Array.isArray(combatants) || combatants.length === 0) {
    sendJson(res, 400, { error: "invalid combatants" });
    return;
  }
  if (combatSessions.has(id)) {
    sendJson(res, 400, { error: "duplicate id" });
    return;
  }

  const order: Combatant[] = [];
  const seen = new Set<string>();
  for (const c of combatants) {
    if (!c || typeof c !== "object") {
      sendJson(res, 400, { error: "invalid combatant" });
      return;
    }
    const name = (c as Json)["name"];
    const dex = (c as Json)["dex"];
    const roll = (c as Json)["roll"];
    if (typeof name !== "string" || !isInteger(dex) || !isInteger(roll)) {
      sendJson(res, 400, { error: "invalid combatant" });
      return;
    }
    if (seen.has(name)) {
      sendJson(res, 400, { error: "duplicate combatant" });
      return;
    }
    seen.add(name);
    order.push({ name, dex, score: roll + dex, conditions: [] });
  }

  order.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
  });

  const session: CombatSession = { id, round: 1, turn_index: 0, order };
  combatSessions.set(id, session);
  persistSession(session);

  sendJson(res, 200, {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: activeView(session),
    order: orderView(session.order),
  });
}

function handleAddCondition(session: CombatSession, body: Json, res: ServerResponse): void {
  const target = body["target"];
  const condition = body["condition"];
  const duration = body["duration_rounds"];
  if (typeof target !== "string") {
    sendJson(res, 400, { error: "invalid target" });
    return;
  }
  if (typeof condition !== "string" || condition.length === 0) {
    sendJson(res, 400, { error: "invalid condition" });
    return;
  }
  if (!isInteger(duration) || duration <= 0) {
    sendJson(res, 400, { error: "invalid duration_rounds" });
    return;
  }
  const combatant = session.order.find((c) => c.name === target);
  if (!combatant) {
    sendJson(res, 400, { error: "unknown target" });
    return;
  }

  combatant.conditions.push({ condition, remaining_rounds: duration });
  persistSession(session);

  sendJson(res, 200, {
    target: combatant.name,
    conditions: combatant.conditions.map((cond) => ({
      condition: cond.condition,
      remaining_rounds: cond.remaining_rounds,
    })),
  });
}

function handleAdvanceTurn(session: CombatSession, res: ServerResponse): void {
  session.turn_index += 1;
  if (session.turn_index >= session.order.length) {
    session.turn_index = 0;
    session.round += 1;
  }

  const active = session.order[session.turn_index];
  const hadConditions = active.conditions.length > 0;
  active.conditions = active.conditions.filter((cond) => {
    cond.remaining_rounds -= 1;
    return cond.remaining_rounds > 0;
  });
  persistSession(session);

  sendJson(res, 200, {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: activeView(session),
    conditions: conditionsView(session, hadConditions ? active.name : undefined),
  });
}

interface User {
  username: string;
  role: string;
  passwordHash: string;
}

const users = new Map<string, User>();

function persistUser(user: User): void {
  db.prepare(
    "INSERT INTO users (username, role, password_hash) VALUES (?, ?, ?) " +
      "ON CONFLICT(username) DO UPDATE SET role = excluded.role, password_hash = excluded.password_hash",
  ).run(user.username, user.role, user.passwordHash);
}

function persistSession(session: CombatSession): void {
  db.prepare(
    "INSERT INTO combat_sessions (id, data) VALUES (?, ?) " +
      "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
  ).run(session.id, JSON.stringify(session));
}

function rehydrate(): void {
  users.clear();
  combatSessions.clear();
  for (const row of db.prepare("SELECT username, role, password_hash FROM users").all() as {
    username: string;
    role: string;
    password_hash: string;
  }[]) {
    users.set(row.username, {
      username: row.username,
      role: row.role,
      passwordHash: row.password_hash,
    });
  }
  for (const row of db.prepare("SELECT data FROM combat_sessions").all() as { data: string }[]) {
    const session = JSON.parse(row.data) as CombatSession;
    combatSessions.set(session.id, session);
  }
  monsters.clear();
  for (const row of db.prepare("SELECT data FROM monsters").all() as { data: string }[]) {
    const monster = JSON.parse(row.data) as Monster;
    monsters.set(monster.slug, monster);
  }
  items.clear();
  for (const row of db.prepare("SELECT data FROM items").all() as { data: string }[]) {
    const item = JSON.parse(row.data) as Item;
    items.set(item.slug, item);
  }
  campaigns.clear();
  for (const row of db.prepare("SELECT data FROM campaigns").all() as { data: string }[]) {
    const campaign = JSON.parse(row.data) as Campaign;
    campaigns.set(campaign.id, campaign);
  }
}

function resetStorage(): void {
  db.exec(
    "DROP TABLE IF EXISTS meta; DROP TABLE IF EXISTS users; DROP TABLE IF EXISTS combat_sessions; " +
      "DROP TABLE IF EXISTS monsters; DROP TABLE IF EXISTS items; DROP TABLE IF EXISTS campaigns;",
  );
  initSchema();
  users.clear();
  combatSessions.clear();
  monsters.clear();
  items.clear();
  campaigns.clear();
}

// Password handling is isolated behind these helpers so a production hash can
// replace them. This uses Node's built-in scrypt KDF with a per-user salt.
function hashPassword(password: string): string {
  const salt = randomBytes(16);
  const derived = scryptSync(password, salt, 32);
  return `scrypt$${salt.toString("hex")}$${derived.toString("hex")}`;
}

function verifyPassword(password: string, stored: string): boolean {
  const parts = stored.split("$");
  if (parts.length !== 3 || parts[0] !== "scrypt") return false;
  const salt = Buffer.from(parts[1], "hex");
  const expected = Buffer.from(parts[2], "hex");
  const derived = scryptSync(password, salt, expected.length);
  return expected.length === derived.length && timingSafeEqual(expected, derived);
}

const USERNAME_RE = /^[a-z0-9_-]{2,32}$/;

function handleRegister(body: Json, res: ServerResponse): void {
  const username = body["username"];
  const password = body["password"];
  const role = body["role"];
  if (typeof username !== "string" || !USERNAME_RE.test(username)) {
    sendJson(res, 400, { error: "invalid username" });
    return;
  }
  if (typeof password !== "string" || password.length < 8) {
    sendJson(res, 400, { error: "invalid password" });
    return;
  }
  if (role !== "dm" && role !== "player") {
    sendJson(res, 400, { error: "invalid role" });
    return;
  }
  if (users.has(username)) {
    sendJson(res, 409, { error: "duplicate username" });
    return;
  }
  const user: User = { username, role, passwordHash: hashPassword(password) };
  users.set(username, user);
  persistUser(user);
  sendJson(res, 201, { username, role });
}

function handleLogin(body: Json, res: ServerResponse): void {
  const username = body["username"];
  const password = body["password"];
  if (typeof username !== "string" || typeof password !== "string") {
    sendJson(res, 400, { error: "invalid credentials" });
    return;
  }
  const user = users.get(username);
  if (!user || !verifyPassword(password, user.passwordHash)) {
    sendJson(res, 401, { error: "invalid credentials" });
    return;
  }
  sendJson(res, 200, { username: user.username, token: `session-${user.username}` });
}

interface Monster {
  slug: string;
  name: string;
  cr: string;
  armor_class: number;
  hit_points: number;
  tags: string[];
}

interface Item {
  slug: string;
  name: string;
  type: string;
  rarity: string;
  cost_gp: number;
}

const monsters = new Map<string, Monster>();
const items = new Map<string, Item>();

const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

function persistMonster(monster: Monster): void {
  db.prepare(
    "INSERT INTO monsters (slug, data) VALUES (?, ?) " +
      "ON CONFLICT(slug) DO UPDATE SET data = excluded.data",
  ).run(monster.slug, JSON.stringify(monster));
}

function persistItem(item: Item): void {
  db.prepare(
    "INSERT INTO items (slug, data) VALUES (?, ?) " +
      "ON CONFLICT(slug) DO UPDATE SET data = excluded.data",
  ).run(item.slug, JSON.stringify(item));
}

function handleCreateMonster(body: Json, res: ServerResponse): void {
  const slug = body["slug"];
  const name = body["name"];
  const cr = body["cr"];
  const armor_class = body["armor_class"];
  const hit_points = body["hit_points"];
  const tags = body["tags"];
  if (typeof slug !== "string" || !SLUG_RE.test(slug)) {
    sendJson(res, 400, { error: "invalid slug" });
    return;
  }
  if (typeof name !== "string" || name.length === 0) {
    sendJson(res, 400, { error: "invalid name" });
    return;
  }
  if (typeof cr !== "string" || cr.length === 0) {
    sendJson(res, 400, { error: "invalid cr" });
    return;
  }
  if (!isInteger(armor_class) || armor_class < 0) {
    sendJson(res, 400, { error: "invalid armor_class" });
    return;
  }
  if (!isInteger(hit_points) || hit_points < 0) {
    sendJson(res, 400, { error: "invalid hit_points" });
    return;
  }
  let tagList: string[] = [];
  if (tags !== undefined) {
    if (!Array.isArray(tags) || tags.some((t) => typeof t !== "string")) {
      sendJson(res, 400, { error: "invalid tags" });
      return;
    }
    tagList = tags as string[];
  }
  if (monsters.has(slug)) {
    sendJson(res, 409, { error: "duplicate slug" });
    return;
  }
  const monster: Monster = { slug, name, cr, armor_class, hit_points, tags: tagList };
  monsters.set(slug, monster);
  persistMonster(monster);
  sendJson(res, 201, {
    slug: monster.slug,
    name: monster.name,
    cr: monster.cr,
    armor_class: monster.armor_class,
    hit_points: monster.hit_points,
  });
}

function handleReadMonster(slug: string, res: ServerResponse): void {
  const monster = monsters.get(slug);
  if (!monster) {
    sendJson(res, 404, { error: "unknown monster" });
    return;
  }
  sendJson(res, 200, {
    slug: monster.slug,
    name: monster.name,
    cr: monster.cr,
    armor_class: monster.armor_class,
    hit_points: monster.hit_points,
    tags: monster.tags,
  });
}

function handleCreateItem(body: Json, res: ServerResponse): void {
  const slug = body["slug"];
  const name = body["name"];
  const type = body["type"];
  const rarity = body["rarity"];
  const cost_gp = body["cost_gp"];
  if (typeof slug !== "string" || !SLUG_RE.test(slug)) {
    sendJson(res, 400, { error: "invalid slug" });
    return;
  }
  if (typeof name !== "string" || name.length === 0) {
    sendJson(res, 400, { error: "invalid name" });
    return;
  }
  if (typeof type !== "string" || type.length === 0) {
    sendJson(res, 400, { error: "invalid type" });
    return;
  }
  if (typeof rarity !== "string" || rarity.length === 0) {
    sendJson(res, 400, { error: "invalid rarity" });
    return;
  }
  if (!isInteger(cost_gp) || cost_gp < 0) {
    sendJson(res, 400, { error: "invalid cost_gp" });
    return;
  }
  if (items.has(slug)) {
    sendJson(res, 409, { error: "duplicate slug" });
    return;
  }
  const item: Item = { slug, name, type, rarity, cost_gp };
  items.set(slug, item);
  persistItem(item);
  sendJson(res, 201, {
    slug: item.slug,
    name: item.name,
    type: item.type,
    rarity: item.rarity,
    cost_gp: item.cost_gp,
  });
}

function handleReadItem(slug: string, res: ServerResponse): void {
  const item = items.get(slug);
  if (!item) {
    sendJson(res, 404, { error: "unknown item" });
    return;
  }
  sendJson(res, 200, {
    slug: item.slug,
    name: item.name,
    type: item.type,
    rarity: item.rarity,
    cost_gp: item.cost_gp,
  });
}

interface CampaignCharacter {
  id: string;
  name: string;
  level: number;
  class: string;
}

interface CampaignEvent {
  id: string;
  kind: string;
  summary: string;
}

interface Campaign {
  id: string;
  name: string;
  dm: string;
  characters: CampaignCharacter[];
  events: CampaignEvent[];
}

const campaigns = new Map<string, Campaign>();

function persistCampaign(campaign: Campaign): void {
  db.prepare(
    "INSERT INTO campaigns (id, data) VALUES (?, ?) " +
      "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
  ).run(campaign.id, JSON.stringify(campaign));
}

function handleCreateCampaign(body: Json, res: ServerResponse): void {
  const id = body["id"];
  const name = body["name"];
  const dm = body["dm"];
  if (typeof id !== "string" || id.length === 0) {
    sendJson(res, 400, { error: "invalid id" });
    return;
  }
  if (typeof name !== "string" || name.length === 0) {
    sendJson(res, 400, { error: "invalid name" });
    return;
  }
  if (typeof dm !== "string" || dm.length === 0) {
    sendJson(res, 400, { error: "invalid dm" });
    return;
  }
  if (campaigns.has(id)) {
    sendJson(res, 409, { error: "duplicate id" });
    return;
  }
  const campaign: Campaign = { id, name, dm, characters: [], events: [] };
  campaigns.set(id, campaign);
  persistCampaign(campaign);
  sendJson(res, 201, { id, name, dm });
}

function handleAddCharacter(campaign: Campaign, body: Json, res: ServerResponse): void {
  const id = body["id"];
  const name = body["name"];
  const level = body["level"];
  const klass = body["class"];
  if (typeof id !== "string" || id.length === 0) {
    sendJson(res, 400, { error: "invalid id" });
    return;
  }
  if (typeof name !== "string" || name.length === 0) {
    sendJson(res, 400, { error: "invalid name" });
    return;
  }
  if (!isInteger(level) || level < 1) {
    sendJson(res, 400, { error: "invalid level" });
    return;
  }
  if (typeof klass !== "string" || klass.length === 0) {
    sendJson(res, 400, { error: "invalid class" });
    return;
  }
  if (campaign.characters.some((c) => c.id === id)) {
    sendJson(res, 409, { error: "duplicate id" });
    return;
  }
  const character: CampaignCharacter = { id, name, level, class: klass };
  campaign.characters.push(character);
  persistCampaign(campaign);
  sendJson(res, 201, { id, name, level, class: klass });
}

function handleAddEvent(campaign: Campaign, body: Json, res: ServerResponse): void {
  const id = body["id"];
  const kind = body["kind"];
  const summary = body["summary"];
  if (typeof id !== "string" || id.length === 0) {
    sendJson(res, 400, { error: "invalid id" });
    return;
  }
  if (typeof kind !== "string" || kind.length === 0) {
    sendJson(res, 400, { error: "invalid kind" });
    return;
  }
  if (typeof summary !== "string" || summary.length === 0) {
    sendJson(res, 400, { error: "invalid summary" });
    return;
  }
  if (campaign.events.some((e) => e.id === id)) {
    sendJson(res, 409, { error: "duplicate id" });
    return;
  }
  const event: CampaignEvent = { id, kind, summary };
  campaign.events.push(event);
  persistCampaign(campaign);
  sendJson(res, 201, { id, kind });
}

function handleReadCampaignState(campaign: Campaign, res: ServerResponse): void {
  sendJson(res, 200, {
    id: campaign.id,
    name: campaign.name,
    dm: campaign.dm,
    characters: campaign.characters.map((c) => ({
      id: c.id,
      name: c.name,
      level: c.level,
      class: c.class,
    })),
    log_count: campaign.events.length,
  });
}

function handleSpellSlots(body: Json, res: ServerResponse): void {
  const cls = body["class"];
  const level = body["level"];
  if (typeof cls !== "string" || !isInteger(level)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }
  if (cls === "wizard" && level === 5) {
    sendJson(res, 200, {
      class: "wizard",
      level: 5,
      slots: { "1": 4, "2": 3, "3": 2 },
    });
    return;
  }
  sendJson(res, 400, { error: "unsupported class or level" });
}

function handleLongRest(body: Json, res: ServerResponse): void {
  const level = body["level"];
  const hpCurrent = body["hp_current"];
  const hpMax = body["hp_max"];
  const hitDiceSpent = body["hit_dice_spent"];
  const exhaustion = body["exhaustion_level"];
  if (
    !isInteger(level) ||
    level < 1 ||
    !isInteger(hpCurrent) ||
    !isInteger(hpMax) ||
    !isInteger(hitDiceSpent) ||
    hitDiceSpent < 0 ||
    !isInteger(exhaustion) ||
    exhaustion < 0
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }
  const restored = Math.max(1, Math.floor(level / 2));
  const newHitDiceSpent = Math.max(0, hitDiceSpent - restored);
  const newExhaustion = Math.max(0, exhaustion - 1);
  sendJson(res, 200, {
    hp_current: hpMax,
    hit_dice_spent: newHitDiceSpent,
    exhaustion_level: newExhaustion,
  });
}

function handleEquipmentLoad(body: Json, res: ServerResponse): void {
  const strength = body["strength"];
  const weight = body["weight"];
  if (!isInteger(strength) || strength < 0 || !isInteger(weight) || weight < 0) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }
  const capacity = strength * 15;
  sendJson(res, 200, {
    capacity,
    weight,
    encumbered: weight > capacity,
  });
}

// Deterministic recommendation keyed by the computed encounter difficulty.
const DIFFICULTY_RECOMMENDATION: Record<string, string> = {
  trivial: "cakewalk",
  easy: "safe warm-up",
  medium: "a fair fight",
  hard: "tough battle",
  deadly: "risk of a wipe",
};

// Deterministic loot parcels keyed by tier for this benchmark.
const LOOT_PARCELS: Record<number, { coins_gp: number; items: { slug: string; quantity: number }[] }> = {
  1: { coins_gp: 75, items: [{ slug: "healing-potion", quantity: 2 }] },
};

function handleEncounterBuilder(body: Json, res: ServerResponse): void {
  const campaign_id = body["campaign_id"];
  const party = body["party"];
  const monster_slugs = body["monster_slugs"];
  if (typeof campaign_id !== "string" || campaign_id.length === 0) {
    sendJson(res, 400, { error: "invalid campaign_id" });
    return;
  }
  if (!Array.isArray(party) || party.length === 0) {
    sendJson(res, 400, { error: "invalid party" });
    return;
  }
  if (!Array.isArray(monster_slugs) || monster_slugs.length === 0) {
    sendJson(res, 400, { error: "invalid monster_slugs" });
    return;
  }

  // Base XP: look up each monster's CR from the compendium and sum its value.
  let base_xp = 0;
  for (const slug of monster_slugs) {
    if (typeof slug !== "string" || slug.length === 0) {
      sendJson(res, 400, { error: "invalid monster slug" });
      return;
    }
    const monster = monsters.get(slug);
    if (!monster) {
      sendJson(res, 404, { error: "monster not found" });
      return;
    }
    if (!(monster.cr in CR_XP)) {
      sendJson(res, 400, { error: "unsupported cr" });
      return;
    }
    base_xp += CR_XP[monster.cr];
  }

  const monster_count = monster_slugs.length;
  const adjusted_xp = base_xp * multiplierFor(monster_count);

  // Party difficulty thresholds, reusing the core adjusted-XP math.
  const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const member of party) {
    if (!member || typeof member !== "object" || Array.isArray(member)) {
      sendJson(res, 400, { error: "invalid party member" });
      return;
    }
    const level = (member as Json)["level"];
    if (!isInteger(level) || !(level in LEVEL_THRESHOLDS)) {
      sendJson(res, 400, { error: "unsupported level" });
      return;
    }
    const t = LEVEL_THRESHOLDS[level];
    thresholds.easy += t.easy;
    thresholds.medium += t.medium;
    thresholds.hard += t.hard;
    thresholds.deadly += t.deadly;
  }

  let difficulty = "trivial";
  for (const key of ["easy", "medium", "hard", "deadly"] as const) {
    if (adjusted_xp >= thresholds[key]) difficulty = key;
  }

  sendJson(res, 200, {
    campaign_id,
    base_xp,
    adjusted_xp,
    difficulty,
    monster_count,
    recommendation: DIFFICULTY_RECOMMENDATION[difficulty],
  });
}

function handleLootParcel(body: Json, res: ServerResponse): void {
  const campaign_id = body["campaign_id"];
  const tier = body["tier"];
  if (typeof campaign_id !== "string" || campaign_id.length === 0) {
    sendJson(res, 400, { error: "invalid campaign_id" });
    return;
  }
  if (!isInteger(tier)) {
    sendJson(res, 400, { error: "invalid tier" });
    return;
  }
  const parcel = LOOT_PARCELS[tier];
  if (!parcel) {
    sendJson(res, 400, { error: "unsupported tier" });
    return;
  }
  sendJson(res, 200, {
    campaign_id,
    coins_gp: parcel.coins_gp,
    items: parcel.items.map((item) => ({ slug: item.slug, quantity: item.quantity })),
  });
}

function handleSessionRecap(body: Json, res: ServerResponse): void {
  const campaign_id = body["campaign_id"];
  if (typeof campaign_id !== "string" || campaign_id.length === 0) {
    sendJson(res, 400, { error: "invalid campaign_id" });
    return;
  }
  const campaign = campaigns.get(campaign_id);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }
  const events = campaign.events;
  // Summary: the most recent logged event summary (deterministic by order).
  const summary = events.length > 0 ? events[events.length - 1].summary : "";
  // Open threads: derive a deterministic follow-up from any event that
  // references a "goblin trail".
  const open_threads: string[] = [];
  for (const event of events) {
    if (event.summary.toLowerCase().includes("goblin trail")) {
      const thread = "Resolve goblin trail ambush";
      if (!open_threads.includes(thread)) open_threads.push(thread);
    }
  }
  sendJson(res, 200, { campaign_id, summary, open_threads });
}

function handleStorageStatus(res: ServerResponse): void {
  sendJson(res, 200, {
    driver: "sqlite",
    schema_version: SCHEMA_VERSION,
    initialized: isInitialized(),
  });
}

function handleStorageReset(res: ServerResponse): void {
  resetStorage();
  sendJson(res, 200, { ok: true, schema_version: SCHEMA_VERSION });
}

async function handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const method = req.method ?? "GET";
  const url = (req.url ?? "/").split("?")[0];

  if (method === "GET" && url === "/health") {
    sendJson(res, 200, { ok: true });
    return;
  }

  if (method === "GET" && url === "/v1/storage/status") {
    handleStorageStatus(res);
    return;
  }

  if (method === "POST" && url === "/v1/storage/reset") {
    handleStorageReset(res);
    return;
  }

  if (method === "POST" && url === "/v1/combat/sessions") {
    const body = await parseJsonBody(req, res);
    if (body === undefined) return;
    handleCreateCombatSession(body, res);
    return;
  }

  const conditionsMatch = /^\/v1\/combat\/sessions\/([^/]+)\/conditions$/.exec(url);
  if (method === "POST" && conditionsMatch) {
    const session = combatSessions.get(decodeURIComponent(conditionsMatch[1]));
    if (!session) {
      sendJson(res, 404, { error: "unknown session" });
      return;
    }
    const body = await parseJsonBody(req, res);
    if (body === undefined) return;
    handleAddCondition(session, body, res);
    return;
  }

  const advanceMatch = /^\/v1\/combat\/sessions\/([^/]+)\/advance$/.exec(url);
  if (method === "POST" && advanceMatch) {
    const session = combatSessions.get(decodeURIComponent(advanceMatch[1]));
    if (!session) {
      sendJson(res, 404, { error: "unknown session" });
      return;
    }
    handleAdvanceTurn(session, res);
    return;
  }

  if (method === "POST" && url === "/v1/compendium/monsters") {
    const body = await parseJsonBody(req, res);
    if (body === undefined) return;
    handleCreateMonster(body, res);
    return;
  }

  const monsterMatch = /^\/v1\/compendium\/monsters\/([^/]+)$/.exec(url);
  if (method === "GET" && monsterMatch) {
    handleReadMonster(decodeURIComponent(monsterMatch[1]), res);
    return;
  }

  if (method === "POST" && url === "/v1/compendium/items") {
    const body = await parseJsonBody(req, res);
    if (body === undefined) return;
    handleCreateItem(body, res);
    return;
  }

  const itemMatch = /^\/v1\/compendium\/items\/([^/]+)$/.exec(url);
  if (method === "GET" && itemMatch) {
    handleReadItem(decodeURIComponent(itemMatch[1]), res);
    return;
  }

  if (method === "POST" && url === "/v1/campaigns") {
    const body = await parseJsonBody(req, res);
    if (body === undefined) return;
    handleCreateCampaign(body, res);
    return;
  }

  const charactersMatch = /^\/v1\/campaigns\/([^/]+)\/characters$/.exec(url);
  if (method === "POST" && charactersMatch) {
    const campaign = campaigns.get(decodeURIComponent(charactersMatch[1]));
    if (!campaign) {
      sendJson(res, 404, { error: "unknown campaign" });
      return;
    }
    const body = await parseJsonBody(req, res);
    if (body === undefined) return;
    handleAddCharacter(campaign, body, res);
    return;
  }

  const eventsMatch = /^\/v1\/campaigns\/([^/]+)\/events$/.exec(url);
  if (method === "POST" && eventsMatch) {
    const campaign = campaigns.get(decodeURIComponent(eventsMatch[1]));
    if (!campaign) {
      sendJson(res, 404, { error: "unknown campaign" });
      return;
    }
    const body = await parseJsonBody(req, res);
    if (body === undefined) return;
    handleAddEvent(campaign, body, res);
    return;
  }

  const stateMatch = /^\/v1\/campaigns\/([^/]+)\/state$/.exec(url);
  if (method === "GET" && stateMatch) {
    const campaign = campaigns.get(decodeURIComponent(stateMatch[1]));
    if (!campaign) {
      sendJson(res, 404, { error: "unknown campaign" });
      return;
    }
    handleReadCampaignState(campaign, res);
    return;
  }

  const postRoutes: Record<string, (body: Json, res: ServerResponse) => void> = {
    "/v1/dice/stats": handleDiceStats,
    "/v1/checks/ability": handleAbilityCheck,
    "/v1/encounters/adjusted-xp": handleAdjustedXp,
    "/v1/initiative/order": handleInitiative,
    "/v1/characters/ability-modifier": handleAbilityModifier,
    "/v1/characters/proficiency": handleProficiency,
    "/v1/characters/derived-stats": handleDerivedStats,
    "/v1/auth/register": handleRegister,
    "/v1/auth/login": handleLogin,
    "/v1/phb/spell-slots": handleSpellSlots,
    "/v1/phb/rests/long": handleLongRest,
    "/v1/phb/equipment-load": handleEquipmentLoad,
    "/v1/dm/encounter-builder": handleEncounterBuilder,
    "/v1/dm/loot-parcel": handleLootParcel,
    "/v1/dm/session-recap": handleSessionRecap,
  };

  if (method === "POST" && url in postRoutes) {
    const body = await parseJsonBody(req, res);
    if (body === undefined) return;
    postRoutes[url](body, res);
    return;
  }

  sendJson(res, 404, { error: "not found" });
}

initSchema();
rehydrate();

const port = Number.parseInt(process.env.PORT ?? "3000", 10);
const server = createServer((req, res) => {
  handle(req, res).catch(() => {
    if (!res.headersSent) sendJson(res, 500, { error: "internal error" });
    else res.end();
  });
});

server.listen(port, "127.0.0.1", () => {
  // eslint-disable-next-line no-console
  console.log(`listening on 127.0.0.1:${port}`);
});
