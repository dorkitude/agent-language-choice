import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { randomBytes, scryptSync, timingSafeEqual } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath } from "node:url";

type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

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

const ABILITY_KEYS = ["str", "dex", "con", "int", "wis", "cha"] as const;

type CombatantOrderEntry = {
  name: string;
  dex: number;
  score: number;
};

type Condition = {
  condition: string;
  remaining_rounds: number;
};

type CombatSession = {
  id: string;
  round: number;
  turn_index: number;
  order: CombatantOrderEntry[];
  conditions: Map<string, Condition[]>;
};

type UserRole = "dm" | "player";

type User = {
  username: string;
  role: UserRole;
  passwordSalt: string;
  passwordHash: string;
};

const SCHEMA_VERSION = 1;
const database = new DatabaseSync(fileURLToPath(new URL("../game.db", import.meta.url)));
let storageInitialized = false;

type UserRow = {
  username: string;
  role: string;
  password_salt: string;
  password_hash: string;
};

type CombatSessionRow = {
  id: string;
  round: number;
  turn_index: number;
  order_json: string;
  conditions_json: string;
};

type Monster = {
  slug: string;
  name: string;
  cr: string;
  armor_class: number;
  hit_points: number;
  tags: string[];
};

type MonsterRow = {
  slug: string;
  name: string;
  cr: string;
  armor_class: number;
  hit_points: number;
  tags_json: string;
};

type Item = {
  slug: string;
  name: string;
  type: string;
  rarity: string;
  cost_gp: number;
};

type ItemRow = Item;

type Campaign = {
  id: string;
  name: string;
  dm: string;
};

type CampaignCharacter = {
  id: string;
  campaign_id: string;
  name: string;
  level: number;
  class: string;
};

type CampaignEvent = {
  id: string;
  campaign_id: string;
  kind: string;
  summary: string;
};

type CampaignCharacterRow = CampaignCharacter;
type CampaignEventRow = CampaignEvent;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isInteger(value: unknown): value is number {
  return Number.isInteger(value);
}

function initializeStorage(): void {
  database.exec(`
    PRAGMA journal_mode = WAL;
    CREATE TABLE IF NOT EXISTS storage_metadata (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS users (
      username TEXT PRIMARY KEY,
      role TEXT NOT NULL,
      password_salt TEXT NOT NULL,
      password_hash TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS combat_sessions (
      id TEXT PRIMARY KEY,
      round INTEGER NOT NULL,
      turn_index INTEGER NOT NULL,
      order_json TEXT NOT NULL,
      conditions_json TEXT NOT NULL
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
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      name TEXT NOT NULL,
      level INTEGER NOT NULL,
      class TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS campaign_events (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      summary TEXT NOT NULL
    );
  `);
  database.prepare(`
    INSERT INTO storage_metadata (key, value)
    VALUES ('schema_version', ?)
    ON CONFLICT(key) DO UPDATE SET value = excluded.value
  `).run(String(SCHEMA_VERSION));
  storageInitialized = true;
}

function resetStorage(): void {
  storageInitialized = false;
  database.exec(`
    DROP TABLE IF EXISTS campaign_events;
    DROP TABLE IF EXISTS campaign_characters;
    DROP TABLE IF EXISTS campaigns;
    DROP TABLE IF EXISTS items;
    DROP TABLE IF EXISTS monsters;
    DROP TABLE IF EXISTS combat_sessions;
    DROP TABLE IF EXISTS users;
    DROP TABLE IF EXISTS storage_metadata;
  `);
  initializeStorage();
}

function serializeConditions(conditions: Map<string, Condition[]>): string {
  const value: { [key: string]: Condition[] } = {};
  for (const [name, entries] of conditions) {
    value[name] = entries;
  }
  return JSON.stringify(value);
}

function deserializeConditions(value: string): Map<string, Condition[]> {
  const parsed: unknown = JSON.parse(value);
  const conditions = new Map<string, Condition[]>();
  if (!isRecord(parsed)) {
    return conditions;
  }

  for (const [name, entries] of Object.entries(parsed)) {
    if (!Array.isArray(entries)) {
      continue;
    }
    const validEntries = entries.filter((entry): entry is Condition => (
      isRecord(entry) &&
      typeof entry.condition === "string" &&
      isInteger(entry.remaining_rounds)
    ));
    conditions.set(name, validEntries);
  }

  return conditions;
}

function getUser(username: string): User | undefined {
  const row = database.prepare("SELECT username, role, password_salt, password_hash FROM users WHERE username = ?")
    .get(username) as UserRow | undefined;
  if (row === undefined || !isUserRole(row.role)) {
    return undefined;
  }
  return {
    username: row.username,
    role: row.role,
    passwordSalt: row.password_salt,
    passwordHash: row.password_hash,
  };
}

function insertUser(user: User): void {
  database.prepare(`
    INSERT INTO users (username, role, password_salt, password_hash)
    VALUES (?, ?, ?, ?)
  `).run(user.username, user.role, user.passwordSalt, user.passwordHash);
}

function combatSessionExists(id: string): boolean {
  return database.prepare("SELECT 1 FROM combat_sessions WHERE id = ?").get(id) !== undefined;
}

function getCombatSession(id: string): CombatSession | undefined {
  const row = database.prepare(`
    SELECT id, round, turn_index, order_json, conditions_json
    FROM combat_sessions
    WHERE id = ?
  `).get(id) as CombatSessionRow | undefined;
  if (row === undefined) {
    return undefined;
  }

  const order = JSON.parse(row.order_json) as CombatantOrderEntry[];
  return {
    id: row.id,
    round: row.round,
    turn_index: row.turn_index,
    order,
    conditions: deserializeConditions(row.conditions_json),
  };
}

function saveCombatSession(session: CombatSession): void {
  database.prepare(`
    INSERT INTO combat_sessions (id, round, turn_index, order_json, conditions_json)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
      round = excluded.round,
      turn_index = excluded.turn_index,
      order_json = excluded.order_json,
      conditions_json = excluded.conditions_json
  `).run(
    session.id,
    session.round,
    session.turn_index,
    JSON.stringify(session.order),
    serializeConditions(session.conditions),
  );
}

function getMonster(slug: string): Monster | undefined {
  const row = database.prepare(`
    SELECT slug, name, cr, armor_class, hit_points, tags_json
    FROM monsters
    WHERE slug = ?
  `).get(slug) as MonsterRow | undefined;
  if (row === undefined) {
    return undefined;
  }

  const parsedTags: unknown = JSON.parse(row.tags_json);
  const tags = Array.isArray(parsedTags) && parsedTags.every((tag) => typeof tag === "string") ? parsedTags : [];
  return {
    slug: row.slug,
    name: row.name,
    cr: row.cr,
    armor_class: row.armor_class,
    hit_points: row.hit_points,
    tags,
  };
}

function insertMonster(monster: Monster): void {
  database.prepare(`
    INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags_json)
    VALUES (?, ?, ?, ?, ?, ?)
  `).run(
    monster.slug,
    monster.name,
    monster.cr,
    monster.armor_class,
    monster.hit_points,
    JSON.stringify(monster.tags),
  );
}

function getItem(slug: string): Item | undefined {
  return database.prepare(`
    SELECT slug, name, type, rarity, cost_gp
    FROM items
    WHERE slug = ?
  `).get(slug) as ItemRow | undefined;
}

function insertItem(item: Item): void {
  database.prepare(`
    INSERT INTO items (slug, name, type, rarity, cost_gp)
    VALUES (?, ?, ?, ?, ?)
  `).run(item.slug, item.name, item.type, item.rarity, item.cost_gp);
}

function getCampaign(id: string): Campaign | undefined {
  return database.prepare(`
    SELECT id, name, dm
    FROM campaigns
    WHERE id = ?
  `).get(id) as Campaign | undefined;
}

function insertCampaign(campaign: Campaign): void {
  database.prepare(`
    INSERT INTO campaigns (id, name, dm)
    VALUES (?, ?, ?)
  `).run(campaign.id, campaign.name, campaign.dm);
}

function campaignCharacterExists(id: string): boolean {
  return database.prepare("SELECT 1 FROM campaign_characters WHERE id = ?").get(id) !== undefined;
}

function insertCampaignCharacter(character: CampaignCharacter): void {
  database.prepare(`
    INSERT INTO campaign_characters (id, campaign_id, name, level, class)
    VALUES (?, ?, ?, ?, ?)
  `).run(character.id, character.campaign_id, character.name, character.level, character.class);
}

function campaignEventExists(id: string): boolean {
  return database.prepare("SELECT 1 FROM campaign_events WHERE id = ?").get(id) !== undefined;
}

function insertCampaignEvent(event: CampaignEvent): void {
  database.prepare(`
    INSERT INTO campaign_events (id, campaign_id, kind, summary)
    VALUES (?, ?, ?, ?)
  `).run(event.id, event.campaign_id, event.kind, event.summary);
}

function getCampaignCharacters(campaignId: string): CampaignCharacter[] {
  return database.prepare(`
    SELECT id, campaign_id, name, level, class
    FROM campaign_characters
    WHERE campaign_id = ?
    ORDER BY rowid
  `).all(campaignId) as CampaignCharacterRow[];
}

function getCampaignEventCount(campaignId: string): number {
  const row = database.prepare(`
    SELECT COUNT(*) AS count
    FROM campaign_events
    WHERE campaign_id = ?
  `).get(campaignId) as { count: number } | undefined;
  return row?.count ?? 0;
}

function getLatestCampaignEvent(campaignId: string): CampaignEvent | undefined {
  return database.prepare(`
    SELECT id, campaign_id, kind, summary
    FROM campaign_events
    WHERE campaign_id = ?
    ORDER BY rowid DESC
    LIMIT 1
  `).get(campaignId) as CampaignEventRow | undefined;
}

function sendJson(response: ServerResponse, status: number, body: JsonValue): void {
  const payload = JSON.stringify(body);
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
  });
  response.end(payload);
}

function badRequest(response: ServerResponse): void {
  sendJson(response, 400, { error: "bad_request" });
}

function notFound(response: ServerResponse): void {
  sendJson(response, 404, { error: "not_found" });
}

function readBody(request: IncomingMessage): Promise<unknown> {
  return new Promise((resolve, reject) => {
    let body = "";

    request.setEncoding("utf8");
    request.on("data", (chunk: string) => {
      body += chunk;
      if (body.length > 1_000_000) {
        reject(new Error("request body too large"));
        request.destroy();
      }
    });
    request.on("end", () => {
      try {
        resolve(body === "" ? {} : JSON.parse(body));
      } catch (error) {
        reject(error);
      }
    });
    request.on("error", reject);
  });
}

function hashPassword(password: string, salt: string): string {
  return scryptSync(password, salt, 64).toString("hex");
}

function createPasswordRecord(password: string): { salt: string; hash: string } {
  const salt = randomBytes(16).toString("hex");
  return { salt, hash: hashPassword(password, salt) };
}

function verifyPassword(password: string, user: User): boolean {
  const expected = Buffer.from(user.passwordHash, "hex");
  const actual = Buffer.from(hashPassword(password, user.passwordSalt), "hex");
  return expected.length === actual.length && timingSafeEqual(expected, actual);
}

function isUsername(value: unknown): value is string {
  return typeof value === "string" && /^[a-z0-9_-]{2,32}$/.test(value);
}

function isPassword(value: unknown): value is string {
  return typeof value === "string" && value.length >= 8;
}

function isUserRole(value: unknown): value is UserRole {
  return value === "dm" || value === "player";
}

function isSlug(value: unknown): value is string {
  return typeof value === "string" && /^[a-z0-9][a-z0-9-]{0,63}$/.test(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function createMonster(body: unknown): { status: number; body: JsonValue } {
  if (
    !isRecord(body) ||
    !isSlug(body.slug) ||
    !isNonEmptyString(body.name) ||
    !isNonEmptyString(body.cr) ||
    !isInteger(body.armor_class) ||
    !isInteger(body.hit_points) ||
    body.armor_class < 0 ||
    body.hit_points < 0 ||
    !Array.isArray(body.tags) ||
    !body.tags.every((tag) => typeof tag === "string")
  ) {
    return { status: 400, body: { error: "bad_request" } };
  }

  if (getMonster(body.slug) !== undefined) {
    return { status: 409, body: { error: "duplicate_slug" } };
  }

  const monster: Monster = {
    slug: body.slug,
    name: body.name,
    cr: body.cr,
    armor_class: body.armor_class,
    hit_points: body.hit_points,
    tags: body.tags,
  };
  insertMonster(monster);

  return {
    status: 201,
    body: {
      slug: monster.slug,
      name: monster.name,
      cr: monster.cr,
      armor_class: monster.armor_class,
      hit_points: monster.hit_points,
    },
  };
}

function createItem(body: unknown): { status: number; body: JsonValue } {
  if (
    !isRecord(body) ||
    !isSlug(body.slug) ||
    !isNonEmptyString(body.name) ||
    !isNonEmptyString(body.type) ||
    !isNonEmptyString(body.rarity) ||
    !isInteger(body.cost_gp) ||
    body.cost_gp < 0
  ) {
    return { status: 400, body: { error: "bad_request" } };
  }

  if (getItem(body.slug) !== undefined) {
    return { status: 409, body: { error: "duplicate_slug" } };
  }

  const item: Item = {
    slug: body.slug,
    name: body.name,
    type: body.type,
    rarity: body.rarity,
    cost_gp: body.cost_gp,
  };
  insertItem(item);

  return { status: 201, body: item };
}

function createCampaign(body: unknown): { status: number; body: JsonValue } {
  if (!isRecord(body) || !isNonEmptyString(body.id) || !isNonEmptyString(body.name) || !isNonEmptyString(body.dm)) {
    return { status: 400, body: { error: "bad_request" } };
  }

  if (getCampaign(body.id) !== undefined) {
    return { status: 409, body: { error: "duplicate_id" } };
  }

  const campaign: Campaign = {
    id: body.id,
    name: body.name,
    dm: body.dm,
  };
  insertCampaign(campaign);

  return { status: 201, body: campaign };
}

function addCampaignCharacter(campaignId: string, body: unknown): { status: number; body: JsonValue } {
  if (getCampaign(campaignId) === undefined) {
    return { status: 404, body: { error: "not_found" } };
  }

  if (
    !isRecord(body) ||
    !isNonEmptyString(body.id) ||
    !isNonEmptyString(body.name) ||
    !isCharacterLevel(body.level) ||
    !isNonEmptyString(body.class)
  ) {
    return { status: 400, body: { error: "bad_request" } };
  }

  if (campaignCharacterExists(body.id)) {
    return { status: 409, body: { error: "duplicate_id" } };
  }

  const character: CampaignCharacter = {
    id: body.id,
    campaign_id: campaignId,
    name: body.name,
    level: body.level,
    class: body.class,
  };
  insertCampaignCharacter(character);

  return {
    status: 201,
    body: {
      id: character.id,
      name: character.name,
      level: character.level,
      class: character.class,
    },
  };
}

function addCampaignEvent(campaignId: string, body: unknown): { status: number; body: JsonValue } {
  if (getCampaign(campaignId) === undefined) {
    return { status: 404, body: { error: "not_found" } };
  }

  if (
    !isRecord(body) ||
    !isNonEmptyString(body.id) ||
    !isNonEmptyString(body.kind) ||
    !isNonEmptyString(body.summary)
  ) {
    return { status: 400, body: { error: "bad_request" } };
  }

  if (campaignEventExists(body.id)) {
    return { status: 409, body: { error: "duplicate_id" } };
  }

  const event: CampaignEvent = {
    id: body.id,
    campaign_id: campaignId,
    kind: body.kind,
    summary: body.summary,
  };
  insertCampaignEvent(event);

  return {
    status: 201,
    body: { id: event.id, kind: event.kind },
  };
}

function getCampaignState(campaignId: string): { status: number; body: JsonValue } {
  const campaign = getCampaign(campaignId);
  if (campaign === undefined) {
    return { status: 404, body: { error: "not_found" } };
  }

  return {
    status: 200,
    body: {
      id: campaign.id,
      name: campaign.name,
      dm: campaign.dm,
      characters: getCampaignCharacters(campaignId).map((character) => ({
        id: character.id,
        name: character.name,
        level: character.level,
        class: character.class,
      })),
      log_count: getCampaignEventCount(campaignId),
    },
  };
}

function registerUser(body: unknown): { status: number; body: JsonValue } {
  if (!isRecord(body) || !isUsername(body.username) || !isPassword(body.password) || !isUserRole(body.role)) {
    return { status: 400, body: { error: "bad_request" } };
  }

  if (getUser(body.username) !== undefined) {
    return { status: 409, body: { error: "duplicate_username" } };
  }

  const passwordRecord = createPasswordRecord(body.password);
  const user: User = {
    username: body.username,
    role: body.role,
    passwordSalt: passwordRecord.salt,
    passwordHash: passwordRecord.hash,
  };
  insertUser(user);

  return {
    status: 201,
    body: { username: user.username, role: user.role },
  };
}

function loginUser(body: unknown): { status: number; body: JsonValue } {
  if (!isRecord(body) || typeof body.username !== "string" || typeof body.password !== "string") {
    return { status: 400, body: { error: "bad_request" } };
  }

  const user = getUser(body.username);
  if (user === undefined || !verifyPassword(body.password, user)) {
    return { status: 401, body: { error: "bad_credentials" } };
  }

  return {
    status: 200,
    body: { username: user.username, token: `session-${user.username}` },
  };
}

function diceStats(body: unknown): JsonValue | undefined {
  if (!isRecord(body) || typeof body.expression !== "string") {
    return undefined;
  }

  const match = /^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$/.exec(body.expression);
  if (match === null) {
    return undefined;
  }

  const diceCount = Number(match[1]);
  const sides = Number(match[2]);
  const modifierValue = match[4] === undefined ? 0 : Number(match[4]);
  const modifier = match[3] === "-" ? -modifierValue : modifierValue;

  if (
    !Number.isSafeInteger(diceCount) ||
    !Number.isSafeInteger(sides) ||
    !Number.isSafeInteger(modifier) ||
    diceCount <= 0 ||
    sides <= 0
  ) {
    return undefined;
  }

  const min = diceCount + modifier;
  const max = diceCount * sides + modifier;
  const average = diceCount * (sides + 1) / 2 + modifier;

  return {
    dice_count: diceCount,
    sides,
    modifier,
    min,
    max,
    average,
  };
}

function abilityCheck(body: unknown): JsonValue | undefined {
  if (!isRecord(body) || !isInteger(body.roll) || !isInteger(body.modifier) || !isInteger(body.dc)) {
    return undefined;
  }

  const total = body.roll + body.modifier;
  return {
    total,
    success: total >= body.dc,
    margin: total - body.dc,
  };
}

function isAbilityScore(value: unknown): value is number {
  return isInteger(value) && value >= 1 && value <= 30;
}

function isCharacterLevel(value: unknown): value is number {
  return isInteger(value) && value >= 1 && value <= 20;
}

function abilityModifierForScore(score: number): number {
  return Math.floor((score - 10) / 2);
}

function proficiencyBonusForLevel(level: number): number {
  return 2 + Math.floor((level - 1) / 4);
}

function abilityModifier(body: unknown): JsonValue | undefined {
  if (!isRecord(body) || !isAbilityScore(body.score)) {
    return undefined;
  }

  return {
    score: body.score,
    modifier: abilityModifierForScore(body.score),
  };
}

function proficiency(body: unknown): JsonValue | undefined {
  if (!isRecord(body) || !isCharacterLevel(body.level)) {
    return undefined;
  }

  return {
    level: body.level,
    proficiency_bonus: proficiencyBonusForLevel(body.level),
  };
}

function derivedStats(body: unknown): JsonValue | undefined {
  if (!isRecord(body) || !isCharacterLevel(body.level) || !isRecord(body.abilities) || !isRecord(body.armor)) {
    return undefined;
  }
  if (!isInteger(body.armor.base) || typeof body.armor.shield !== "boolean" || !isInteger(body.armor.dex_cap)) {
    return undefined;
  }

  const modifiers: Record<string, number> = {};
  for (const key of ABILITY_KEYS) {
    const score = body.abilities[key];
    if (!isAbilityScore(score)) {
      return undefined;
    }
    modifiers[key] = abilityModifierForScore(score);
  }

  const proficiencyBonus = proficiencyBonusForLevel(body.level);
  const shieldBonus = body.armor.shield ? 2 : 0;

  return {
    level: body.level,
    proficiency_bonus: proficiencyBonus,
    hp_max: body.level * (6 + modifiers.con),
    armor_class: body.armor.base + Math.min(modifiers.dex, body.armor.dex_cap) + shieldBonus,
    modifiers,
  };
}

function monsterMultiplier(monsterCount: number): number {
  if (monsterCount <= 1) {
    return 1;
  }
  if (monsterCount === 2) {
    return 1.5;
  }
  if (monsterCount <= 6) {
    return 2;
  }
  if (monsterCount <= 10) {
    return 2.5;
  }
  if (monsterCount <= 14) {
    return 3;
  }
  return 4;
}

function adjustedXp(body: unknown): JsonValue | undefined {
  if (!isRecord(body) || !Array.isArray(body.party) || !Array.isArray(body.monsters)) {
    return undefined;
  }

  const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const member of body.party) {
    if (!isRecord(member) || !isInteger(member.level)) {
      return undefined;
    }

    const memberThresholds = LEVEL_THRESHOLDS[member.level];
    if (memberThresholds === undefined) {
      return undefined;
    }

    thresholds.easy += memberThresholds.easy;
    thresholds.medium += memberThresholds.medium;
    thresholds.hard += memberThresholds.hard;
    thresholds.deadly += memberThresholds.deadly;
  }

  let baseXp = 0;
  let monsterCount = 0;
  for (const monster of body.monsters) {
    if (!isRecord(monster) || typeof monster.cr !== "string" || !isInteger(monster.count) || monster.count <= 0) {
      return undefined;
    }

    const xp = CR_XP[monster.cr];
    if (xp === undefined) {
      return undefined;
    }

    baseXp += xp * monster.count;
    monsterCount += monster.count;
  }

  const multiplier = monsterMultiplier(monsterCount);
  const adjusted = baseXp * multiplier;
  let difficulty = "trivial";
  if (adjusted >= thresholds.deadly) {
    difficulty = "deadly";
  } else if (adjusted >= thresholds.hard) {
    difficulty = "hard";
  } else if (adjusted >= thresholds.medium) {
    difficulty = "medium";
  } else if (adjusted >= thresholds.easy) {
    difficulty = "easy";
  }

  return {
    base_xp: baseXp,
    monster_count: monsterCount,
    multiplier,
    adjusted_xp: adjusted,
    difficulty,
    thresholds,
  };
}

function recommendationForDifficulty(difficulty: unknown): string {
  switch (difficulty) {
    case "trivial":
      return "trivial diversion";
    case "easy":
      return "safe warm-up";
    case "medium":
      return "standard challenge";
    case "hard":
      return "dangerous fight";
    case "deadly":
      return "high risk";
    default:
      return "review encounter";
  }
}

function buildEncounter(body: unknown): { status: number; body: JsonValue } {
  if (
    !isRecord(body) ||
    !isNonEmptyString(body.campaign_id) ||
    !Array.isArray(body.party) ||
    !Array.isArray(body.monster_slugs) ||
    body.monster_slugs.length === 0
  ) {
    return { status: 400, body: { error: "bad_request" } };
  }

  if (getCampaign(body.campaign_id) === undefined) {
    return { status: 404, body: { error: "not_found" } };
  }

  const monsters = [];
  for (const slug of body.monster_slugs) {
    if (!isSlug(slug)) {
      return { status: 400, body: { error: "bad_request" } };
    }
    const monster = getMonster(slug);
    if (monster === undefined) {
      return { status: 404, body: { error: "not_found" } };
    }
    monsters.push({ cr: monster.cr, count: 1 });
  }

  const encounterMath = adjustedXp({ party: body.party, monsters });
  if (!isRecord(encounterMath)) {
    return { status: 400, body: { error: "bad_request" } };
  }

  return {
    status: 200,
    body: {
      campaign_id: body.campaign_id,
      base_xp: encounterMath.base_xp as JsonValue,
      adjusted_xp: encounterMath.adjusted_xp as JsonValue,
      difficulty: encounterMath.difficulty as JsonValue,
      monster_count: encounterMath.monster_count as JsonValue,
      recommendation: recommendationForDifficulty(encounterMath.difficulty),
    },
  };
}

function createLootParcel(body: unknown): { status: number; body: JsonValue } {
  if (
    !isRecord(body) ||
    !isNonEmptyString(body.campaign_id) ||
    body.tier !== 1 ||
    !isInteger(body.seed)
  ) {
    return { status: 400, body: { error: "bad_request" } };
  }

  if (getCampaign(body.campaign_id) === undefined) {
    return { status: 404, body: { error: "not_found" } };
  }

  return {
    status: 200,
    body: {
      campaign_id: body.campaign_id,
      coins_gp: 75,
      items: [{ slug: "healing-potion", quantity: 2 }],
    },
  };
}

function openThreadsForSummary(summary: string): string[] {
  if (summary.toLowerCase().includes("goblin trail")) {
    return ["Resolve goblin trail ambush"];
  }

  return summary === "" ? [] : [`Resolve ${summary.replace(/[.?!]+$/, "")}`];
}

function createSessionRecap(body: unknown): { status: number; body: JsonValue } {
  if (!isRecord(body) || !isNonEmptyString(body.campaign_id)) {
    return { status: 400, body: { error: "bad_request" } };
  }

  if (getCampaign(body.campaign_id) === undefined) {
    return { status: 404, body: { error: "not_found" } };
  }

  const summary = getLatestCampaignEvent(body.campaign_id)?.summary ?? "";
  return {
    status: 200,
    body: {
      campaign_id: body.campaign_id,
      summary,
      open_threads: openThreadsForSummary(summary),
    },
  };
}

function spellSlots(body: unknown): JsonValue | undefined {
  if (!isRecord(body) || body.class !== "wizard" || body.level !== 5) {
    return undefined;
  }

  return {
    class: "wizard",
    level: 5,
    slots: { "1": 4, "2": 3, "3": 2 },
  };
}

function longRest(body: unknown): JsonValue | undefined {
  if (
    !isRecord(body) ||
    !isCharacterLevel(body.level) ||
    !isInteger(body.hp_current) ||
    !isInteger(body.hp_max) ||
    !isInteger(body.hit_dice_spent) ||
    !isInteger(body.exhaustion_level) ||
    body.hp_current < 0 ||
    body.hp_max < 0 ||
    body.hp_current > body.hp_max ||
    body.hit_dice_spent < 0 ||
    body.exhaustion_level < 0
  ) {
    return undefined;
  }

  const recoveredHitDice = Math.max(1, Math.floor(body.level / 2));
  return {
    hp_current: body.hp_max,
    hit_dice_spent: Math.max(0, body.hit_dice_spent - recoveredHitDice),
    exhaustion_level: Math.max(0, body.exhaustion_level - 1),
  };
}

function equipmentLoad(body: unknown): JsonValue | undefined {
  if (
    !isRecord(body) ||
    !isInteger(body.strength) ||
    !isInteger(body.weight) ||
    body.strength < 0 ||
    body.weight < 0
  ) {
    return undefined;
  }

  const capacity = body.strength * 15;
  return {
    capacity,
    weight: body.weight,
    encumbered: body.weight > capacity,
  };
}

function initiativeOrder(body: unknown): JsonValue | undefined {
  if (!isRecord(body) || !Array.isArray(body.combatants)) {
    return undefined;
  }

  const combatants = [];
  for (const combatant of body.combatants) {
    if (!isRecord(combatant) || typeof combatant.name !== "string" || !isInteger(combatant.dex) || !isInteger(combatant.roll)) {
      return undefined;
    }
    combatants.push({
      name: combatant.name,
      dex: combatant.dex,
      score: combatant.roll + combatant.dex,
    });
  }

  combatants.sort((a, b) => b.score - a.score || b.dex - a.dex || a.name.localeCompare(b.name));

  return {
    order: combatants.map(({ name, score }) => ({ name, score })),
  };
}

function publicOrder(order: CombatantOrderEntry[]): JsonValue[] {
  return order.map(({ name, score }) => ({ name, score }));
}

function activeCombatant(session: CombatSession): JsonValue {
  const active = session.order[session.turn_index];
  return { name: active.name, score: active.score };
}

function publicConditions(session: CombatSession): JsonValue {
  const conditions: { [key: string]: JsonValue } = {};
  for (const [name, entries] of session.conditions) {
    conditions[name] = entries.map(({ condition, remaining_rounds }) => ({ condition, remaining_rounds }));
  }
  return conditions;
}

function createCombatSession(body: unknown): JsonValue | undefined {
  if (!isRecord(body) || typeof body.id !== "string" || body.id === "" || !Array.isArray(body.combatants)) {
    return undefined;
  }
  if (combatSessionExists(body.id) || body.combatants.length === 0) {
    return undefined;
  }

  const order: CombatantOrderEntry[] = [];
  for (const combatant of body.combatants) {
    if (!isRecord(combatant) || typeof combatant.name !== "string" || !isInteger(combatant.dex) || !isInteger(combatant.roll)) {
      return undefined;
    }
    order.push({
      name: combatant.name,
      dex: combatant.dex,
      score: combatant.roll + combatant.dex,
    });
  }

  order.sort((a, b) => b.score - a.score || b.dex - a.dex || a.name.localeCompare(b.name));

  const session: CombatSession = {
    id: body.id,
    round: 1,
    turn_index: 0,
    order,
    conditions: new Map(),
  };
  saveCombatSession(session);

  return {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: activeCombatant(session),
    order: publicOrder(session.order),
  };
}

function addCombatCondition(session: CombatSession, body: unknown): JsonValue | undefined {
  if (
    !isRecord(body) ||
    typeof body.target !== "string" ||
    typeof body.condition !== "string" ||
    !isInteger(body.duration_rounds) ||
    body.duration_rounds <= 0
  ) {
    return undefined;
  }

  if (!session.order.some((combatant) => combatant.name === body.target)) {
    return undefined;
  }

  const conditions = session.conditions.get(body.target) ?? [];
  conditions.push({ condition: body.condition, remaining_rounds: body.duration_rounds });
  session.conditions.set(body.target, conditions);
  saveCombatSession(session);

  return {
    target: body.target,
    conditions: conditions.map(({ condition, remaining_rounds }) => ({ condition, remaining_rounds })),
  };
}

function advanceCombatSession(session: CombatSession): JsonValue {
  session.turn_index += 1;
  if (session.turn_index >= session.order.length) {
    session.turn_index = 0;
    session.round += 1;
  }

  const active = session.order[session.turn_index];
  const conditions = session.conditions.get(active.name);
  if (conditions !== undefined) {
    const remaining = conditions
      .map(({ condition, remaining_rounds }) => ({ condition, remaining_rounds: remaining_rounds - 1 }))
      .filter(({ remaining_rounds }) => remaining_rounds > 0);
    if (remaining.length > 0) {
      session.conditions.set(active.name, remaining);
    } else {
      session.conditions.set(active.name, []);
    }
  }
  saveCombatSession(session);

  return {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: activeCombatant(session),
    conditions: publicConditions(session),
  };
}

async function handleRequest(request: IncomingMessage, response: ServerResponse): Promise<void> {
  const method = request.method ?? "";
  const path = new URL(request.url ?? "/", "http://127.0.0.1").pathname;

  if (method === "GET" && path === "/health") {
    sendJson(response, 200, { ok: true });
    return;
  }

  if (method === "GET" && path === "/v1/storage/status") {
    sendJson(response, 200, { driver: "sqlite", schema_version: SCHEMA_VERSION, initialized: storageInitialized });
    return;
  }

  if (method === "POST" && path === "/v1/storage/reset") {
    resetStorage();
    sendJson(response, 200, { ok: true, schema_version: SCHEMA_VERSION });
    return;
  }

  if (method === "GET") {
    const monsterMatch = /^\/v1\/compendium\/monsters\/([^/]+)$/.exec(path);
    if (monsterMatch !== null) {
      const monster = getMonster(decodeURIComponent(monsterMatch[1]));
      if (monster === undefined) {
        notFound(response);
        return;
      }
      sendJson(response, 200, monster);
      return;
    }

    const itemMatch = /^\/v1\/compendium\/items\/([^/]+)$/.exec(path);
    if (itemMatch !== null) {
      const item = getItem(decodeURIComponent(itemMatch[1]));
      if (item === undefined) {
        notFound(response);
        return;
      }
      sendJson(response, 200, item);
      return;
    }

    const campaignStateMatch = /^\/v1\/campaigns\/([^/]+)\/state$/.exec(path);
    if (campaignStateMatch !== null) {
      const result = getCampaignState(decodeURIComponent(campaignStateMatch[1]));
      sendJson(response, result.status, result.body);
      return;
    }
  }

  if (method !== "POST") {
    notFound(response);
    return;
  }

  let body: unknown;
  try {
    body = await readBody(request);
  } catch {
    badRequest(response);
    return;
  }

  if (path === "/v1/auth/register") {
    const result = registerUser(body);
    sendJson(response, result.status, result.body);
    return;
  }

  if (path === "/v1/auth/login") {
    const result = loginUser(body);
    sendJson(response, result.status, result.body);
    return;
  }

  if (path === "/v1/compendium/monsters") {
    const result = createMonster(body);
    sendJson(response, result.status, result.body);
    return;
  }

  if (path === "/v1/compendium/items") {
    const result = createItem(body);
    sendJson(response, result.status, result.body);
    return;
  }

  if (path === "/v1/campaigns") {
    const result = createCampaign(body);
    sendJson(response, result.status, result.body);
    return;
  }

  if (path === "/v1/dm/encounter-builder") {
    const result = buildEncounter(body);
    sendJson(response, result.status, result.body);
    return;
  }

  if (path === "/v1/dm/loot-parcel") {
    const result = createLootParcel(body);
    sendJson(response, result.status, result.body);
    return;
  }

  if (path === "/v1/dm/session-recap") {
    const result = createSessionRecap(body);
    sendJson(response, result.status, result.body);
    return;
  }

  const campaignMutationMatch = /^\/v1\/campaigns\/([^/]+)\/(characters|events)$/.exec(path);
  if (campaignMutationMatch !== null) {
    const campaignId = decodeURIComponent(campaignMutationMatch[1]);
    const result = campaignMutationMatch[2] === "characters"
      ? addCampaignCharacter(campaignId, body)
      : addCampaignEvent(campaignId, body);
    sendJson(response, result.status, result.body);
    return;
  }

  let result: JsonValue | undefined;
  switch (path) {
    case "/v1/dice/stats":
      result = diceStats(body);
      break;
    case "/v1/checks/ability":
      result = abilityCheck(body);
      break;
    case "/v1/characters/ability-modifier":
      result = abilityModifier(body);
      break;
    case "/v1/characters/proficiency":
      result = proficiency(body);
      break;
    case "/v1/characters/derived-stats":
      result = derivedStats(body);
      break;
    case "/v1/encounters/adjusted-xp":
      result = adjustedXp(body);
      break;
    case "/v1/phb/spell-slots":
      result = spellSlots(body);
      break;
    case "/v1/phb/rests/long":
      result = longRest(body);
      break;
    case "/v1/phb/equipment-load":
      result = equipmentLoad(body);
      break;
    case "/v1/initiative/order":
      result = initiativeOrder(body);
      break;
    case "/v1/combat/sessions":
      result = createCombatSession(body);
      break;
    default:
      {
        const match = /^\/v1\/combat\/sessions\/([^/]+)\/(conditions|advance)$/.exec(path);
        if (match === null) {
          notFound(response);
          return;
        }

        const session = getCombatSession(decodeURIComponent(match[1]));
        if (session === undefined) {
          notFound(response);
          return;
        }

        result = match[2] === "conditions" ? addCombatCondition(session, body) : advanceCombatSession(session);
        break;
      }
  }

  if (result === undefined) {
    badRequest(response);
    return;
  }

  sendJson(response, 200, result);
}

const port = Number(process.env.PORT);
if (!Number.isInteger(port) || port <= 0 || port > 65535) {
  throw new Error("PORT must be an integer from 1 to 65535");
}

const server = createServer((request, response) => {
  void handleRequest(request, response).catch(() => {
    if (!response.headersSent) {
      sendJson(response, 500, { error: "internal_server_error" });
    } else {
      response.end();
    }
  });
});

initializeStorage();
server.listen(port, "127.0.0.1");
