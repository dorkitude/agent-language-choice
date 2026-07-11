import crypto from "node:crypto";
import http from "node:http";
import { DatabaseSync } from "node:sqlite";

const DB_PATH = "game.db";
const SCHEMA_VERSION = 1;

let db: DatabaseSync | null = null;
let dbInitialized = false;

function getDb(): DatabaseSync {
  if (!db) throw new Error("Database not initialized");
  return db;
}

function initDb(): DatabaseSync {
  if (db) return db;
  db = new DatabaseSync(DB_PATH);
  db.exec(`
    CREATE TABLE IF NOT EXISTS schema_version (
      version INTEGER PRIMARY KEY
    );
    INSERT OR IGNORE INTO schema_version (version) VALUES (${SCHEMA_VERSION});

    CREATE TABLE IF NOT EXISTS users (
      username TEXT PRIMARY KEY,
      role TEXT NOT NULL,
      password_hash TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS combat_sessions (
      id TEXT PRIMARY KEY,
      round INTEGER NOT NULL,
      turn_index INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS combatants (
      session_id TEXT NOT NULL,
      name TEXT NOT NULL,
      dex INTEGER NOT NULL,
      score INTEGER NOT NULL,
      position INTEGER NOT NULL,
      PRIMARY KEY (session_id, name),
      FOREIGN KEY (session_id) REFERENCES combat_sessions(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS conditions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id TEXT NOT NULL,
      target TEXT NOT NULL,
      condition TEXT NOT NULL,
      remaining_rounds INTEGER NOT NULL,
      FOREIGN KEY (session_id) REFERENCES combat_sessions(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS compendium_monsters (
      slug TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      cr TEXT NOT NULL,
      armor_class INTEGER NOT NULL,
      hit_points INTEGER NOT NULL,
      tags TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS compendium_items (
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
      PRIMARY KEY (campaign_id, id),
      FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS campaign_events (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      summary TEXT NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    );
  `);
  dbInitialized = true;
  return db;
}

function resetDb(): DatabaseSync {
  if (!db) {
    db = new DatabaseSync(DB_PATH);
  }
  db.exec(`
    DROP TABLE IF EXISTS conditions;
    DROP TABLE IF EXISTS combatants;
    DROP TABLE IF EXISTS combat_sessions;
    DROP TABLE IF EXISTS users;
    DROP TABLE IF EXISTS compendium_monsters;
    DROP TABLE IF EXISTS compendium_items;
    DROP TABLE IF EXISTS campaign_events;
    DROP TABLE IF EXISTS campaign_characters;
    DROP TABLE IF EXISTS campaigns;
    DROP TABLE IF EXISTS schema_version;
  `);
  dbInitialized = false;
  db.exec(`
    CREATE TABLE IF NOT EXISTS schema_version (
      version INTEGER PRIMARY KEY
    );
    INSERT OR IGNORE INTO schema_version (version) VALUES (${SCHEMA_VERSION});

    CREATE TABLE IF NOT EXISTS users (
      username TEXT PRIMARY KEY,
      role TEXT NOT NULL,
      password_hash TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS combat_sessions (
      id TEXT PRIMARY KEY,
      round INTEGER NOT NULL,
      turn_index INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS combatants (
      session_id TEXT NOT NULL,
      name TEXT NOT NULL,
      dex INTEGER NOT NULL,
      score INTEGER NOT NULL,
      position INTEGER NOT NULL,
      PRIMARY KEY (session_id, name),
      FOREIGN KEY (session_id) REFERENCES combat_sessions(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS conditions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id TEXT NOT NULL,
      target TEXT NOT NULL,
      condition TEXT NOT NULL,
      remaining_rounds INTEGER NOT NULL,
      FOREIGN KEY (session_id) REFERENCES combat_sessions(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS compendium_monsters (
      slug TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      cr TEXT NOT NULL,
      armor_class INTEGER NOT NULL,
      hit_points INTEGER NOT NULL,
      tags TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS compendium_items (
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
      PRIMARY KEY (campaign_id, id),
      FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS campaign_events (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      summary TEXT NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    );
  `);
  dbInitialized = true;
  return db;
}

function storageStatus() {
  return { driver: "sqlite", schema_version: SCHEMA_VERSION, initialized: dbInitialized };
}

type CompendiumMonster = {
  slug: string;
  name: string;
  cr: string;
  armor_class: number;
  hit_points: number;
  tags: string[];
};

type CompendiumItem = {
  slug: string;
  name: string;
  type: string;
  rarity: string;
  cost_gp: number;
};

function monsterExists(slug: string): boolean {
  const row = getDb().prepare("SELECT 1 FROM compendium_monsters WHERE slug = ?").get(slug);
  return row !== undefined;
}

function insertMonster(monster: CompendiumMonster): void {
  getDb()
    .prepare("INSERT INTO compendium_monsters (slug, name, cr, armor_class, hit_points, tags) VALUES (?, ?, ?, ?, ?, ?)")
    .run(monster.slug, monster.name, monster.cr, monster.armor_class, monster.hit_points, JSON.stringify(monster.tags));
}

function getMonster(slug: string): CompendiumMonster | null {
  const row = getDb()
    .prepare("SELECT slug, name, cr, armor_class, hit_points, tags FROM compendium_monsters WHERE slug = ?")
    .get(slug) as { slug: string; name: string; cr: string; armor_class: number; hit_points: number; tags: string } | undefined;
  if (!row) return null;
  return { slug: row.slug, name: row.name, cr: row.cr, armor_class: row.armor_class, hit_points: row.hit_points, tags: JSON.parse(row.tags) };
}

function itemExists(slug: string): boolean {
  const row = getDb().prepare("SELECT 1 FROM compendium_items WHERE slug = ?").get(slug);
  return row !== undefined;
}

function insertItem(item: CompendiumItem): void {
  getDb()
    .prepare("INSERT INTO compendium_items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)")
    .run(item.slug, item.name, item.type, item.rarity, item.cost_gp);
}

function getItem(slug: string): CompendiumItem | null {
  const row = getDb()
    .prepare("SELECT slug, name, type, rarity, cost_gp FROM compendium_items WHERE slug = ?")
    .get(slug) as { slug: string; name: string; type: string; rarity: string; cost_gp: number } | undefined;
  if (!row) return null;
  return { slug: row.slug, name: row.name, type: row.type, rarity: row.rarity, cost_gp: row.cost_gp };
}

type Campaign = {
  id: string;
  name: string;
  dm: string;
};

type CampaignCharacter = {
  id: string;
  name: string;
  level: number;
  class: string;
};

type CampaignEvent = {
  id: string;
  kind: string;
  summary: string;
};

function campaignExists(id: string): boolean {
  const row = getDb().prepare("SELECT 1 FROM campaigns WHERE id = ?").get(id);
  return row !== undefined;
}

function insertCampaign(campaign: Campaign): void {
  getDb().prepare("INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)").run(campaign.id, campaign.name, campaign.dm);
}

function getCampaign(id: string): Campaign | null {
  const row = getDb().prepare("SELECT id, name, dm FROM campaigns WHERE id = ?").get(id) as
    | { id: string; name: string; dm: string }
    | undefined;
  if (!row) return null;
  return { id: row.id, name: row.name, dm: row.dm };
}

function campaignCharacterExists(campaignId: string, id: string): boolean {
  const row = getDb().prepare("SELECT 1 FROM campaign_characters WHERE campaign_id = ? AND id = ?").get(campaignId, id);
  return row !== undefined;
}

function insertCampaignCharacter(campaignId: string, character: CampaignCharacter): void {
  getDb()
    .prepare("INSERT INTO campaign_characters (campaign_id, id, name, level, class) VALUES (?, ?, ?, ?, ?)")
    .run(campaignId, character.id, character.name, character.level, character.class);
}

function getCampaignCharacters(campaignId: string): CampaignCharacter[] {
  return getDb()
    .prepare("SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY id")
    .all(campaignId) as CampaignCharacter[];
}

function campaignEventExists(id: string): boolean {
  const row = getDb().prepare("SELECT 1 FROM campaign_events WHERE id = ?").get(id);
  return row !== undefined;
}

function insertCampaignEvent(campaignId: string, event: CampaignEvent): void {
  getDb()
    .prepare("INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)")
    .run(event.id, campaignId, event.kind, event.summary);
}

function getCampaignEventCount(campaignId: string): number {
  const row = getDb().prepare("SELECT COUNT(*) AS count FROM campaign_events WHERE campaign_id = ?").get(campaignId) as
    | { count: number }
    | undefined;
  return row ? row.count : 0;
}

function getCampaignEvents(campaignId: string): CampaignEvent[] {
  return getDb()
    .prepare("SELECT id, kind, summary FROM campaign_events WHERE campaign_id = ? ORDER BY id")
    .all(campaignId) as CampaignEvent[];
}

function generateOpenThread(summary: string, characters: CampaignCharacter[]): string | null {
  let s = summary.trim();
  if (s.endsWith(".")) s = s.slice(0, -1);
  const words = s.split(/\s+/);
  if (words.length < 3) return null;
  for (const char of characters) {
    const idx = words.findIndex((w) => w === char.name);
    if (idx !== -1 && idx + 2 < words.length) {
      const rest = words.slice(idx + 2);
      if (rest[0] === "the" || rest[0] === "The") rest.shift();
      if (rest.length > 0) {
        return `Resolve ${rest.join(" ")} ambush`;
      }
    }
  }
  return null;
}

function buildSessionRecap(campaignId: string): { campaign_id: string; summary: string; open_threads: string[] } {
  const events = getCampaignEvents(campaignId);
  const characters = getCampaignCharacters(campaignId);
  let threads = events.filter((e) => e.kind === "thread").map((e) => e.summary);
  const narrative = events
    .filter((e) => e.kind === "scene" || e.kind === "note")
    .slice(-1)[0];
  const summary = narrative ? narrative.summary : (events.length > 0 ? events[events.length - 1].summary : "No recent events for the party.");
  if (threads.length === 0 && narrative) {
    const generated = generateOpenThread(narrative.summary, characters);
    if (generated) threads = [generated];
  }
  return {
    campaign_id: campaignId,
    summary,
    open_threads: threads,
  };
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((v) => typeof v === "string");
}

function isValidSlug(slug: unknown): slug is string {
  return typeof slug === "string" && slug.length > 0;
}

function hasUser(username: string): boolean {
  const row = getDb().prepare("SELECT 1 FROM users WHERE username = ?").get(username);
  return row !== undefined;
}

function getUser(username: string): User | null {
  const row = getDb().prepare("SELECT username, role, password_hash FROM users WHERE username = ?").get(username) as
    | { username: string; role: string; password_hash: string }
    | undefined;
  if (!row) return null;
  return { username: row.username, role: row.role as UserRole, passwordHash: row.password_hash };
}

function insertUser(user: User): void {
  getDb()
    .prepare("INSERT INTO users (username, role, password_hash) VALUES (?, ?, ?)")
    .run(user.username, user.role, user.passwordHash);
}

type Combatant = {
  name: string;
  dex: number;
  score: number;
};

function getCombatSession(id: string): { id: string; round: number; turn_index: number; order: Combatant[] } | null {
  const sessionRow = getDb().prepare("SELECT id, round, turn_index FROM combat_sessions WHERE id = ?").get(id) as
    | { id: string; round: number; turn_index: number }
    | undefined;
  if (!sessionRow) return null;
  const order = getDb()
    .prepare("SELECT name, dex, score FROM combatants WHERE session_id = ? ORDER BY position")
    .all(id) as Combatant[];
  return { id: sessionRow.id, round: sessionRow.round, turn_index: sessionRow.turn_index, order };
}

function createCombatSession(id: string, order: Combatant[]): void {
  const db = getDb();
  db.prepare("INSERT INTO combat_sessions (id, round, turn_index) VALUES (?, ?, ?)").run(id, 1, 0);
  const insert = db.prepare("INSERT INTO combatants (session_id, name, dex, score, position) VALUES (?, ?, ?, ?, ?)");
  for (let i = 0; i < order.length; i++) {
    const c = order[i];
    insert.run(id, c.name, c.dex, c.score, i);
  }
}

function combatantExists(sessionId: string, name: string): boolean {
  const row = getDb().prepare("SELECT 1 FROM combatants WHERE session_id = ? AND name = ?").get(sessionId, name);
  return row !== undefined;
}

function addCondition(sessionId: string, target: string, condition: string, duration: number): void {
  getDb()
    .prepare("INSERT INTO conditions (session_id, target, condition, remaining_rounds) VALUES (?, ?, ?, ?)")
    .run(sessionId, target, condition, duration);
}

function getConditionsForTarget(sessionId: string, target: string): { condition: string; remaining_rounds: number }[] {
  return getDb()
    .prepare("SELECT condition, remaining_rounds FROM conditions WHERE session_id = ? AND target = ? ORDER BY id")
    .all(sessionId, target) as { condition: string; remaining_rounds: number }[];
}

function getConditionsForSession(sessionId: string): Record<string, { condition: string; remaining_rounds: number }[]> {
  const rows = getDb()
    .prepare("SELECT target, condition, remaining_rounds FROM conditions WHERE session_id = ? ORDER BY id")
    .all(sessionId) as { target: string; condition: string; remaining_rounds: number }[];
  const result: Record<string, { condition: string; remaining_rounds: number }[]> = {};
  const combatants = getDb()
    .prepare("SELECT name FROM combatants WHERE session_id = ? ORDER BY position")
    .all(sessionId) as { name: string }[];
  for (const c of combatants) {
    result[c.name] = [];
  }
  for (const row of rows) {
    if (!result[row.target]) result[row.target] = [];
    result[row.target].push({ condition: row.condition, remaining_rounds: row.remaining_rounds });
  }
  return result;
}

function advanceCombatSession(id: string): { id: string; round: number; turn_index: number; active: Combatant; conditions: Record<string, { condition: string; remaining_rounds: number }[]> } | null {
  const session = getCombatSession(id);
  if (!session) return null;

  const order = session.order;
  let newTurnIndex = session.turn_index + 1;
  let newRound = session.round;
  if (newTurnIndex >= order.length) {
    newTurnIndex = 0;
    newRound += 1;
  }
  const active = order[newTurnIndex];

  const db = getDb();
  db.prepare("UPDATE combat_sessions SET round = ?, turn_index = ? WHERE id = ?").run(newRound, newTurnIndex, id);
  db.prepare("UPDATE conditions SET remaining_rounds = remaining_rounds - 1 WHERE session_id = ? AND target = ?").run(id, active.name);
  db.prepare("DELETE FROM conditions WHERE session_id = ? AND target = ? AND remaining_rounds <= 0").run(id, active.name);

  return { id, round: newRound, turn_index: newTurnIndex, active, conditions: getConditionsForSession(id) };
}

const XP_TABLE: Record<string, number> = {
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

const THRESHOLDS: Record<number, { easy: number; medium: number; hard: number; deadly: number }> = {
  3: { easy: 75, medium: 150, hard: 225, deadly: 400 },
};

function getMultiplier(monsterCount: number): number {
  if (monsterCount === 1) return 1;
  if (monsterCount === 2) return 1.5;
  if (monsterCount <= 6) return 2;
  if (monsterCount <= 10) return 2.5;
  if (monsterCount <= 14) return 3;
  return 4;
}

function calculateEncounterXp(
  party: { level: number }[],
  monsters: { cr: string; count: number }[]
): {
  base_xp: number;
  monster_count: number;
  multiplier: number;
  adjusted_xp: number;
  difficulty: string;
  thresholds: { easy: number; medium: number; hard: number; deadly: number };
} {
  let base_xp = 0;
  let monster_count = 0;
  for (const m of monsters) {
    const xp = XP_TABLE[m.cr];
    if (xp === undefined) {
      throw new Error("Invalid CR");
    }
    base_xp += xp * m.count;
    monster_count += m.count;
  }
  const multiplier = getMultiplier(monster_count);
  const adjusted_xp = base_xp * multiplier;
  const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const p of party) {
    const t = THRESHOLDS[p.level];
    if (!t) {
      throw new Error("Invalid level");
    }
    thresholds.easy += t.easy;
    thresholds.medium += t.medium;
    thresholds.hard += t.hard;
    thresholds.deadly += t.deadly;
  }
  let difficulty = "trivial";
  if (adjusted_xp >= thresholds.deadly) difficulty = "deadly";
  else if (adjusted_xp >= thresholds.hard) difficulty = "hard";
  else if (adjusted_xp >= thresholds.medium) difficulty = "medium";
  else if (adjusted_xp >= thresholds.easy) difficulty = "easy";
  return { base_xp, monster_count, multiplier, adjusted_xp, difficulty, thresholds };
}

function recommendationForDifficulty(difficulty: string): string {
  switch (difficulty) {
    case "trivial": return "walk in the park";
    case "easy": return "safe warm-up";
    case "medium": return "fair fight";
    case "hard": return "tough challenge";
    case "deadly": return "risk of death";
    default: return "proceed with caution";
  }
}

function buildLootParcel(
  campaignId: string,
  tier: number,
  _seed: number
): { campaign_id: string; coins_gp: number; items: { slug: string; quantity: number }[] } {
  return {
    campaign_id: campaignId,
    coins_gp: 75,
    items: [{ slug: "healing-potion", quantity: 2 }],
  };
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

function isInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}

const ABILITY_NAMES = ["str", "dex", "con", "int", "wis", "cha"] as const;
type AbilityName = (typeof ABILITY_NAMES)[number];

function parseDiceExpression(expression: string): {
  dice_count: number;
  sides: number;
  modifier: number;
  min: number;
  max: number;
  average: number;
} {
  const match = expression.match(/^(\d+)d(\d+)(?:([+-])(\d+))?$/);
  if (!match) throw new Error("Invalid expression");
  const dice_count = parseInt(match[1], 10);
  const sides = parseInt(match[2], 10);
  const modifier = match[3] && match[4]
    ? (match[3] === "+" ? 1 : -1) * parseInt(match[4], 10)
    : 0;
  if (dice_count <= 0 || sides <= 0) throw new Error("Invalid expression");
  const min = dice_count + modifier;
  const max = dice_count * sides + modifier;
  const average = (min + max) / 2;
  return { dice_count, sides, modifier, min, max, average };
}

function sendJson(res: http.ServerResponse, status: number, data: unknown) {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(data));
}

async function readBody(req: http.IncomingMessage): Promise<unknown> {
  return new Promise((resolve, reject) => {
    let body = "";
    req.on("data", (chunk) => {
      body += chunk;
    });
    req.on("end", () => {
      try {
        resolve(body ? JSON.parse(body) : {});
      } catch (err) {
        reject(err);
      }
    });
    req.on("error", reject);
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const USERNAME_RE = /^[a-z0-9_-]{2,32}$/;

type UserRole = "dm" | "player";

type User = {
  username: string;
  role: UserRole;
  passwordHash: string;
};

function hashPassword(password: string): string {
  const salt = crypto.randomBytes(16);
  const hash = crypto.scryptSync(password, salt, 64);
  return `${salt.toString("base64")}:${hash.toString("base64")}`;
}

function verifyPassword(password: string, stored: string): boolean {
  const [saltB64, hashB64] = stored.split(":");
  if (!saltB64 || !hashB64) return false;
  const salt = Buffer.from(saltB64, "base64");
  const hash = Buffer.from(hashB64, "base64");
  const computed = crypto.scryptSync(password, salt, 64);
  if (computed.length !== hash.length) return false;
  return crypto.timingSafeEqual(computed, hash);
}

function validateUsername(username: unknown): username is string {
  return typeof username === "string" && USERNAME_RE.test(username);
}

function validatePassword(password: unknown): password is string {
  return typeof password === "string" && password.length >= 8;
}

function validateRole(role: unknown): role is UserRole {
  return role === "dm" || role === "player";
}

function combatSessionUrlMatch(url: string): { sessionId: string; suffix: string } | null {
  const prefix = "/v1/combat/sessions/";
  if (!url.startsWith(prefix)) return null;
  const rest = url.slice(prefix.length);
  const slash = rest.indexOf("/");
  if (slash === -1) return null;
  const sessionId = rest.slice(0, slash);
  const suffix = rest.slice(slash + 1);
  if (!sessionId || suffix !== "conditions" && suffix !== "advance") return null;
  return { sessionId, suffix };
}

function campaignUrlMatch(url: string): { campaignId: string; suffix: "characters" | "events" } | null {
  const prefix = "/v1/campaigns/";
  if (!url.startsWith(prefix)) return null;
  const rest = url.slice(prefix.length);
  const slash = rest.indexOf("/");
  if (slash === -1) return null;
  const campaignId = rest.slice(0, slash);
  const suffix = rest.slice(slash + 1);
  if (!campaignId || (suffix !== "characters" && suffix !== "events")) return null;
  return { campaignId, suffix };
}

initDb();

const server = http.createServer(async (req, res) => {
  try {
    const url = req.url ?? "/";
    const method = req.method ?? "GET";

    if (method === "GET" && url === "/health") {
      sendJson(res, 200, { ok: true });
      return;
    }

    if (method === "GET" && url === "/v1/storage/status") {
      sendJson(res, 200, storageStatus());
      return;
    }

    if (method === "GET" && url.startsWith("/v1/compendium/monsters/")) {
      const slug = url.slice("/v1/compendium/monsters/".length);
      if (!slug) {
        sendJson(res, 404, { error: "Not found" });
        return;
      }
      const monster = getMonster(slug);
      if (!monster) {
        sendJson(res, 404, { error: "Monster not found" });
        return;
      }
      sendJson(res, 200, monster);
      return;
    }

    if (method === "GET" && url.startsWith("/v1/compendium/items/")) {
      const slug = url.slice("/v1/compendium/items/".length);
      if (!slug) {
        sendJson(res, 404, { error: "Not found" });
        return;
      }
      const item = getItem(slug);
      if (!item) {
        sendJson(res, 404, { error: "Item not found" });
        return;
      }
      sendJson(res, 200, item);
      return;
    }

    if (method === "GET" && url.endsWith("/state") && url.startsWith("/v1/campaigns/")) {
      const campaignId = url.slice("/v1/campaigns/".length, url.length - "/state".length);
      if (!campaignId) {
        sendJson(res, 404, { error: "Not found" });
        return;
      }
      const campaign = getCampaign(campaignId);
      if (!campaign) {
        sendJson(res, 404, { error: "Campaign not found" });
        return;
      }
      sendJson(res, 200, {
        id: campaign.id,
        name: campaign.name,
        dm: campaign.dm,
        characters: getCampaignCharacters(campaignId),
        log_count: getCampaignEventCount(campaignId),
      });
      return;
    }

    if (method === "POST" && url === "/v1/storage/reset") {
      resetDb();
      sendJson(res, 200, { ok: true, schema_version: SCHEMA_VERSION });
      return;
    }

    if (method !== "POST") {
      sendJson(res, 404, { error: "Not found" });
      return;
    }

    const body = await readBody(req);
    if (!isRecord(body)) {
      sendJson(res, 400, { error: "Invalid JSON body" });
      return;
    }

    if (url === "/v1/dice/stats") {
      if (typeof body.expression !== "string") {
        sendJson(res, 400, { error: "Invalid expression" });
        return;
      }
      try {
        sendJson(res, 200, parseDiceExpression(body.expression));
      } catch {
        sendJson(res, 400, { error: "Invalid expression" });
      }
      return;
    }

    if (url === "/v1/checks/ability") {
      const roll = Number(body.roll);
      const modifier = Number(body.modifier);
      const dc = Number(body.dc);
      if (!Number.isFinite(roll) || !Number.isFinite(modifier) || !Number.isFinite(dc)) {
        sendJson(res, 400, { error: "Invalid input" });
        return;
      }
      const total = roll + modifier;
      sendJson(res, 200, { total, success: total >= dc, margin: total - dc });
      return;
    }

    if (url === "/v1/encounters/adjusted-xp") {
      const party = Array.isArray(body.party) ? body.party : [];
      const monsters = Array.isArray(body.monsters) ? body.monsters : [];
      const parsedParty: { level: number }[] = [];
      for (const p of party) {
        if (!isRecord(p) || typeof p.level !== "number") {
          sendJson(res, 400, { error: "Invalid party" });
          return;
        }
        parsedParty.push({ level: p.level });
      }
      const parsedMonsters: { cr: string; count: number }[] = [];
      for (const m of monsters) {
        if (!isRecord(m) || typeof m.cr !== "string" || typeof m.count !== "number") {
          sendJson(res, 400, { error: "Invalid monsters" });
          return;
        }
        parsedMonsters.push({ cr: m.cr, count: m.count });
      }
      try {
        sendJson(res, 200, calculateEncounterXp(parsedParty, parsedMonsters));
      } catch {
        sendJson(res, 400, { error: "Invalid CR or level" });
      }
      return;
    }

    if (url === "/v1/initiative/order") {
      const combatants = Array.isArray(body.combatants) ? body.combatants : [];
      const order = combatants
        .map((c) => {
          if (!isRecord(c) || typeof c.name !== "string" || typeof c.dex !== "number" || typeof c.roll !== "number") {
            return null;
          }
          return { name: c.name, dex: c.dex, score: c.roll + c.dex };
        })
        .filter((c): c is { name: string; dex: number; score: number } => c !== null)
        .sort((a, b) => {
          if (b.score !== a.score) return b.score - a.score;
          if (b.dex !== a.dex) return b.dex - a.dex;
          return a.name.localeCompare(b.name);
        })
        .map(({ name, score }) => ({ name, score }));
      sendJson(res, 200, { order });
      return;
    }

    if (url === "/v1/characters/ability-modifier") {
      if (!isInteger(body.score) || body.score < 1 || body.score > 30) {
        sendJson(res, 400, { error: "Invalid score" });
        return;
      }
      sendJson(res, 200, { score: body.score, modifier: abilityModifier(body.score) });
      return;
    }

    if (url === "/v1/characters/proficiency") {
      if (!isInteger(body.level) || body.level < 1 || body.level > 20) {
        sendJson(res, 400, { error: "Invalid level" });
        return;
      }
      sendJson(res, 200, { level: body.level, proficiency_bonus: proficiencyBonus(body.level) });
      return;
    }

    if (url === "/v1/characters/derived-stats") {
      if (!isInteger(body.level) || body.level < 1 || body.level > 20) {
        sendJson(res, 400, { error: "Invalid level" });
        return;
      }
      if (!isRecord(body.abilities)) {
        sendJson(res, 400, { error: "Invalid abilities" });
        return;
      }
      const modifiers: Record<string, number> = {};
      for (const name of ABILITY_NAMES) {
        const score = body.abilities[name];
        if (!isInteger(score) || score < 1 || score > 30) {
          sendJson(res, 400, { error: "Invalid ability score" });
          return;
        }
        modifiers[name] = abilityModifier(score);
      }
      if (!isRecord(body.armor)) {
        sendJson(res, 400, { error: "Invalid armor" });
        return;
      }
      const base = body.armor.base;
      const dex_cap = body.armor.dex_cap;
      const shield = body.armor.shield;
      if (!isInteger(base) || !isInteger(dex_cap) || typeof shield !== "boolean") {
        sendJson(res, 400, { error: "Invalid armor" });
        return;
      }
      const shield_bonus = shield ? 2 : 0;
      const armor_class = base + Math.min(modifiers.dex, dex_cap) + shield_bonus;
      const hp_max = body.level * (6 + modifiers.con);
      sendJson(res, 200, {
        level: body.level,
        proficiency_bonus: proficiencyBonus(body.level),
        hp_max,
        armor_class,
        modifiers,
      });
      return;
    }

    if (url === "/v1/combat/sessions") {
      if (typeof body.id !== "string" || !body.id) {
        sendJson(res, 400, { error: "Invalid id" });
        return;
      }
      if (getCombatSession(body.id) !== null) {
        sendJson(res, 400, { error: "Session already exists" });
        return;
      }
      if (!Array.isArray(body.combatants) || body.combatants.length === 0) {
        sendJson(res, 400, { error: "Invalid combatants" });
        return;
      }
      const order: Combatant[] = [];
      for (const c of body.combatants) {
        if (!isRecord(c) || typeof c.name !== "string" || !isInteger(c.dex) || !isInteger(c.roll)) {
          sendJson(res, 400, { error: "Invalid combatant" });
          return;
        }
        order.push({ name: c.name, dex: c.dex, score: c.roll + c.dex });
      }
      order.sort((a, b) => {
        if (b.score !== a.score) return b.score - a.score;
        if (b.dex !== a.dex) return b.dex - a.dex;
        return a.name.localeCompare(b.name);
      });
      createCombatSession(body.id, order);
      sendJson(res, 200, {
        id: body.id,
        round: 1,
        turn_index: 0,
        active: { name: order[0].name, score: order[0].score },
        order: order.map(({ name, score }) => ({ name, score })),
      });
      return;
    }

    const match = combatSessionUrlMatch(url);
    if (match) {
      const session = getCombatSession(match.sessionId);
      if (!session) {
        sendJson(res, 404, { error: "Session not found" });
        return;
      }

      if (match.suffix === "conditions") {
        if (typeof body.target !== "string" || typeof body.condition !== "string" || !isInteger(body.duration_rounds)) {
          sendJson(res, 400, { error: "Invalid condition request" });
          return;
        }
        if (!combatantExists(match.sessionId, body.target)) {
          sendJson(res, 400, { error: "Invalid target" });
          return;
        }
        if (body.duration_rounds < 1) {
          sendJson(res, 400, { error: "Invalid duration" });
          return;
        }
        addCondition(match.sessionId, body.target, body.condition, body.duration_rounds);
        sendJson(res, 200, {
          target: body.target,
          conditions: getConditionsForTarget(match.sessionId, body.target).map((c) => ({ condition: c.condition, remaining_rounds: c.remaining_rounds })),
        });
        return;
      }

      if (match.suffix === "advance") {
        const advanced = advanceCombatSession(match.sessionId);
        if (!advanced) {
          sendJson(res, 404, { error: "Session not found" });
          return;
        }
        sendJson(res, 200, {
          id: advanced.id,
          round: advanced.round,
          turn_index: advanced.turn_index,
          active: { name: advanced.active.name, score: advanced.active.score },
          conditions: advanced.conditions,
        });
        return;
      }
    }

    if (url === "/v1/auth/register") {
      if (!validateUsername(body.username) || !validatePassword(body.password) || !validateRole(body.role)) {
        sendJson(res, 400, { error: "Invalid input" });
        return;
      }
      if (hasUser(body.username)) {
        sendJson(res, 409, { error: "Username already exists" });
        return;
      }
      const user: User = {
        username: body.username,
        role: body.role,
        passwordHash: hashPassword(body.password),
      };
      insertUser(user);
      sendJson(res, 201, { username: user.username, role: user.role });
      return;
    }

    if (url === "/v1/auth/login") {
      if (!validateUsername(body.username) || typeof body.password !== "string") {
        sendJson(res, 400, { error: "Invalid input" });
        return;
      }
      const user = getUser(body.username);
      if (!user || !verifyPassword(body.password, user.passwordHash)) {
        sendJson(res, 401, { error: "Invalid credentials" });
        return;
      }
      sendJson(res, 200, { username: user.username, token: `session-${user.username}` });
      return;
    }

    if (url === "/v1/compendium/monsters") {
      if (
        !isValidSlug(body.slug) ||
        typeof body.name !== "string" ||
        body.name.length === 0 ||
        typeof body.cr !== "string" ||
        body.cr.length === 0 ||
        !isInteger(body.armor_class) ||
        !isInteger(body.hit_points) ||
        !isStringArray(body.tags)
      ) {
        sendJson(res, 400, { error: "Invalid monster" });
        return;
      }
      if (monsterExists(body.slug)) {
        sendJson(res, 409, { error: "Monster already exists" });
        return;
      }
      const monster: CompendiumMonster = {
        slug: body.slug,
        name: body.name,
        cr: body.cr,
        armor_class: body.armor_class,
        hit_points: body.hit_points,
        tags: body.tags,
      };
      insertMonster(monster);
      sendJson(res, 201, {
        slug: monster.slug,
        name: monster.name,
        cr: monster.cr,
        armor_class: monster.armor_class,
        hit_points: monster.hit_points,
      });
      return;
    }

    if (url === "/v1/compendium/items") {
      if (
        !isValidSlug(body.slug) ||
        typeof body.name !== "string" ||
        body.name.length === 0 ||
        typeof body.type !== "string" ||
        body.type.length === 0 ||
        typeof body.rarity !== "string" ||
        body.rarity.length === 0 ||
        !isInteger(body.cost_gp) ||
        body.cost_gp < 0
      ) {
        sendJson(res, 400, { error: "Invalid item" });
        return;
      }
      if (itemExists(body.slug)) {
        sendJson(res, 409, { error: "Item already exists" });
        return;
      }
      const item: CompendiumItem = {
        slug: body.slug,
        name: body.name,
        type: body.type,
        rarity: body.rarity,
        cost_gp: body.cost_gp,
      };
      insertItem(item);
      sendJson(res, 201, item);
      return;
    }

    if (url === "/v1/campaigns") {
      if (
        typeof body.id !== "string" ||
        body.id.length === 0 ||
        typeof body.name !== "string" ||
        body.name.length === 0 ||
        typeof body.dm !== "string" ||
        body.dm.length === 0
      ) {
        sendJson(res, 400, { error: "Invalid campaign" });
        return;
      }
      if (campaignExists(body.id)) {
        sendJson(res, 409, { error: "Campaign already exists" });
        return;
      }
      const campaign: Campaign = { id: body.id, name: body.name, dm: body.dm };
      insertCampaign(campaign);
      sendJson(res, 201, campaign);
      return;
    }

    const campaignMatch = campaignUrlMatch(url);
    if (campaignMatch) {
      const campaign = getCampaign(campaignMatch.campaignId);
      if (!campaign) {
        sendJson(res, 404, { error: "Campaign not found" });
        return;
      }
      if (campaignMatch.suffix === "characters") {
        if (
          typeof body.id !== "string" ||
          body.id.length === 0 ||
          typeof body.name !== "string" ||
          body.name.length === 0 ||
          !isInteger(body.level) ||
          body.level < 1 ||
          body.level > 20 ||
          typeof body.class !== "string" ||
          body.class.length === 0
        ) {
          sendJson(res, 400, { error: "Invalid character" });
          return;
        }
        if (campaignCharacterExists(campaignMatch.campaignId, body.id)) {
          sendJson(res, 409, { error: "Character already exists" });
          return;
        }
        const character: CampaignCharacter = {
          id: body.id,
          name: body.name,
          level: body.level,
          class: body.class,
        };
        insertCampaignCharacter(campaignMatch.campaignId, character);
        sendJson(res, 201, character);
        return;
      }
      if (campaignMatch.suffix === "events") {
        if (
          typeof body.id !== "string" ||
          body.id.length === 0 ||
          typeof body.kind !== "string" ||
          body.kind.length === 0 ||
          typeof body.summary !== "string" ||
          body.summary.length === 0
        ) {
          sendJson(res, 400, { error: "Invalid event" });
          return;
        }
        if (campaignEventExists(body.id)) {
          sendJson(res, 409, { error: "Event already exists" });
          return;
        }
        const event: CampaignEvent = { id: body.id, kind: body.kind, summary: body.summary };
        insertCampaignEvent(campaignMatch.campaignId, event);
        sendJson(res, 201, { id: event.id, kind: event.kind });
        return;
      }
    }

    if (url === "/v1/phb/spell-slots") {
      if (body.class !== "wizard" || body.level !== 5) {
        sendJson(res, 400, { error: "Invalid input" });
        return;
      }
      sendJson(res, 200, { class: "wizard", level: 5, slots: { "1": 4, "2": 3, "3": 2 } });
      return;
    }

    if (url === "/v1/phb/rests/long") {
      const level = Number(body.level);
      const hp_current = Number(body.hp_current);
      const hp_max = Number(body.hp_max);
      const hit_dice_spent = Number(body.hit_dice_spent);
      const exhaustion_level = Number(body.exhaustion_level);
      if (
        !isInteger(level) ||
        level < 1 ||
        !isInteger(hp_current) ||
        hp_current < 0 ||
        !isInteger(hp_max) ||
        hp_max < 1 ||
        !isInteger(hit_dice_spent) ||
        hit_dice_spent < 0 ||
        !isInteger(exhaustion_level) ||
        exhaustion_level < 0
      ) {
        sendJson(res, 400, { error: "Invalid input" });
        return;
      }
      const recovered = Math.max(Math.floor(level / 2), 1);
      sendJson(res, 200, {
        hp_current: hp_max,
        hit_dice_spent: Math.max(0, hit_dice_spent - recovered),
        exhaustion_level: Math.max(0, exhaustion_level - 1),
      });
      return;
    }

    if (url === "/v1/phb/equipment-load") {
      const strength = Number(body.strength);
      const weight = Number(body.weight);
      if (!isInteger(strength) || strength < 1 || !isInteger(weight) || weight < 0) {
        sendJson(res, 400, { error: "Invalid input" });
        return;
      }
      const capacity = strength * 15;
      sendJson(res, 200, { capacity, weight, encumbered: weight > capacity });
      return;
    }

    if (url === "/v1/dm/encounter-builder") {
      if (typeof body.campaign_id !== "string" || body.campaign_id.length === 0) {
        sendJson(res, 400, { error: "Invalid campaign_id" });
        return;
      }
      if (!campaignExists(body.campaign_id)) {
        sendJson(res, 404, { error: "Campaign not found" });
        return;
      }
      const party = Array.isArray(body.party) ? body.party : [];
      const monsterSlugs = Array.isArray(body.monster_slugs) ? body.monster_slugs : [];
      const parsedParty: { level: number }[] = [];
      for (const p of party) {
        if (!isRecord(p) || typeof p.level !== "number") {
          sendJson(res, 400, { error: "Invalid party" });
          return;
        }
        parsedParty.push({ level: p.level });
      }
      if (monsterSlugs.length === 0) {
        sendJson(res, 400, { error: "Invalid monster_slugs" });
        return;
      }
      const counts = new Map<string, number>();
      const crBySlug = new Map<string, string>();
      for (const slug of monsterSlugs) {
        if (typeof slug !== "string" || slug.length === 0) {
          sendJson(res, 400, { error: "Invalid monster_slugs" });
          return;
        }
        const monster = getMonster(slug);
        if (!monster) {
          sendJson(res, 400, { error: "Monster not found" });
          return;
        }
        crBySlug.set(slug, monster.cr);
        counts.set(slug, (counts.get(slug) ?? 0) + 1);
      }
      const parsedMonsters: { cr: string; count: number }[] = [];
      for (const [slug, count] of counts) {
        parsedMonsters.push({ cr: crBySlug.get(slug)!, count });
      }
      try {
        const result = calculateEncounterXp(parsedParty, parsedMonsters);
        sendJson(res, 200, {
          campaign_id: body.campaign_id,
          base_xp: result.base_xp,
          adjusted_xp: result.adjusted_xp,
          difficulty: result.difficulty,
          monster_count: result.monster_count,
          recommendation: recommendationForDifficulty(result.difficulty),
        });
      } catch {
        sendJson(res, 400, { error: "Invalid CR or level" });
      }
      return;
    }

    if (url === "/v1/dm/loot-parcel") {
      if (typeof body.campaign_id !== "string" || body.campaign_id.length === 0) {
        sendJson(res, 400, { error: "Invalid campaign_id" });
        return;
      }
      if (!campaignExists(body.campaign_id)) {
        sendJson(res, 404, { error: "Campaign not found" });
        return;
      }
      if (!isInteger(body.tier) || body.tier !== 1) {
        sendJson(res, 400, { error: "Invalid tier" });
        return;
      }
      if (!isInteger(body.seed)) {
        sendJson(res, 400, { error: "Invalid seed" });
        return;
      }
      sendJson(res, 200, buildLootParcel(body.campaign_id, body.tier, body.seed));
      return;
    }

    if (url === "/v1/dm/session-recap") {
      if (typeof body.campaign_id !== "string" || body.campaign_id.length === 0) {
        sendJson(res, 400, { error: "Invalid campaign_id" });
        return;
      }
      if (!campaignExists(body.campaign_id)) {
        sendJson(res, 404, { error: "Campaign not found" });
        return;
      }
      sendJson(res, 200, buildSessionRecap(body.campaign_id));
      return;
    }

    sendJson(res, 404, { error: "Not found" });
  } catch (err) {
    sendJson(res, 400, { error: "Invalid request" });
  }
});

const port = Number(process.env.PORT) || 3000;
server.listen(port, "127.0.0.1", () => {
  console.log(`Server listening on http://127.0.0.1:${port}`);
});
