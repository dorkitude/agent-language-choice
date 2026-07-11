import { DatabaseSync, type SQLOutputValue } from "node:sqlite";
import path from "node:path";

// Durable storage driver metadata. The benchmark stages report this back via
// `GET /v1/storage/status`.
export const DRIVER = "sqlite";
export const SCHEMA_VERSION = 1;

// Resolve the database file relative to the process working directory. The
// harness starts `./run.sh` with the project directory as cwd, so this places
// `game.db` in the project directory as the spec requests.
const DB_PATH = path.resolve(process.cwd(), "game.db");

export interface MonsterRecord {
  slug: string;
  name: string;
  cr: string;
  armor_class: number;
  hit_points: number;
  tags: string[];
}

export interface ItemRecord {
  slug: string;
  name: string;
  type: string;
  rarity: string;
  cost_gp: number;
}

export interface CampaignRecord {
  id: string;
  name: string;
  dm: string;
}

export interface CampaignCharacterRecord {
  id: string;
  name: string;
  level: number;
  class: string;
}

export interface CampaignEventRecord {
  id: string;
  kind: string;
  summary: string;
}

export interface UserRecord {
  username: string;
  role: string;
  // Stored as `scrypt$<saltHex>$<hashHex>`. Isolated behind hashPassword /
  // verifyPassword in the server so a production-grade KDF can replace it
  // without touching call sites. The plain password is never persisted.
  passwordHash: string;
}

export interface Combatant {
  name: string;
  dex: number;
  score: number;
}

export interface ConditionEntry {
  condition: string;
  remaining_rounds: number;
}

export interface CombatSession {
  id: string;
  order: Combatant[];
  round: number;
  turn_index: number;
  // Preserves every combatant that has ever had a condition, even once all of
  // their conditions have expired (empty array). This mirrors the prior
  // in-memory semantics where the map key was retained.
  conditions: Map<string, ConditionEntry[]>;
}

let db: DatabaseSync;
let initialized = false;

function asString(v: SQLOutputValue): string {
  return typeof v === "string" ? v : String(v);
}

function asNumber(v: SQLOutputValue): number {
  if (typeof v === "number") return v;
  if (typeof v === "bigint") return Number(v);
  return Number(v);
}

/** Create all tables if they do not already exist and pin the schema version. */
function initSchema(): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS schema_meta (
      key   TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS users (
      username      TEXT PRIMARY KEY,
      role          TEXT NOT NULL,
      password_hash TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS combat_sessions (
      id         TEXT PRIMARY KEY,
      round      INTEGER NOT NULL,
      turn_index INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS combatants (
      session_id TEXT NOT NULL,
      name       TEXT NOT NULL,
      dex        INTEGER NOT NULL,
      score      INTEGER NOT NULL,
      position   INTEGER NOT NULL,
      PRIMARY KEY (session_id, name),
      FOREIGN KEY (session_id) REFERENCES combat_sessions(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS condition_targets (
      session_id TEXT NOT NULL,
      target     TEXT NOT NULL,
      PRIMARY KEY (session_id, target),
      FOREIGN KEY (session_id) REFERENCES combat_sessions(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS conditions (
      id               INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id       TEXT NOT NULL,
      target           TEXT NOT NULL,
      condition        TEXT NOT NULL,
      remaining_rounds INTEGER NOT NULL,
      position         INTEGER NOT NULL,
      FOREIGN KEY (session_id) REFERENCES combat_sessions(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS monsters (
      slug        TEXT PRIMARY KEY,
      name        TEXT NOT NULL,
      cr          TEXT NOT NULL,
      armor_class INTEGER NOT NULL,
      hit_points  INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS monster_tags (
      slug     TEXT NOT NULL,
      tag      TEXT NOT NULL,
      position INTEGER NOT NULL,
      PRIMARY KEY (slug, tag),
      FOREIGN KEY (slug) REFERENCES monsters(slug) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS items (
      slug    TEXT PRIMARY KEY,
      name    TEXT NOT NULL,
      type    TEXT NOT NULL,
      rarity  TEXT NOT NULL,
      cost_gp INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS campaigns (
      id   TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      dm   TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS campaign_characters (
      campaign_id TEXT NOT NULL,
      id          TEXT NOT NULL,
      name        TEXT NOT NULL,
      level       INTEGER NOT NULL,
      class       TEXT NOT NULL,
      position    INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, id),
      FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS campaign_events (
      campaign_id TEXT NOT NULL,
      id          TEXT NOT NULL,
      kind        TEXT NOT NULL,
      summary     TEXT NOT NULL,
      position    INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, id),
      FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    );
  `);
  db.prepare(
    "INSERT INTO schema_meta (key, value) VALUES ('schema_version', ?1) " +
      "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
  ).run(String(SCHEMA_VERSION));
}

/** Open the database and initialize the schema. Idempotent across restarts. */
export function initStorage(): void {
  db = new DatabaseSync(DB_PATH);
  db.exec("PRAGMA foreign_keys = ON");
  initSchema();
  initialized = true;
}

export function isInitialized(): boolean {
  return initialized;
}

/**
 * Clear all benchmark-created durable data and recreate the schema. Process
 * health is preserved (the connection stays open). Children are dropped before
 * parents so foreign-key enforcement stays satisfied.
 */
export function resetStorage(): void {
  db.exec(`
    DROP TABLE IF EXISTS campaign_events;
    DROP TABLE IF EXISTS campaign_characters;
    DROP TABLE IF EXISTS campaigns;
    DROP TABLE IF EXISTS monster_tags;
    DROP TABLE IF EXISTS monsters;
    DROP TABLE IF EXISTS items;
    DROP TABLE IF EXISTS conditions;
    DROP TABLE IF EXISTS condition_targets;
    DROP TABLE IF EXISTS combatants;
    DROP TABLE IF EXISTS combat_sessions;
    DROP TABLE IF EXISTS users;
  `);
  initSchema();
  initialized = true;
}

// --- users -----------------------------------------------------------------

export function userExists(username: string): boolean {
  return db.prepare("SELECT 1 FROM users WHERE username = ?1").get(username) !== undefined;
}

export function insertUser(rec: UserRecord): void {
  db.prepare(
    "INSERT INTO users (username, role, password_hash) VALUES (?1, ?2, ?3)",
  ).run(rec.username, rec.role, rec.passwordHash);
}

export function getUser(username: string): UserRecord | undefined {
  const row = db.prepare(
    "SELECT username, role, password_hash AS passwordHash FROM users WHERE username = ?1",
  ).get(username);
  if (!row) return undefined;
  const r = row as Record<string, SQLOutputValue>;
  return {
    username: asString(r.username),
    role: asString(r.role),
    passwordHash: asString(r.passwordHash),
  };
}

// --- compendium: monsters --------------------------------------------------

export function monsterExists(slug: string): boolean {
  return db.prepare("SELECT 1 FROM monsters WHERE slug = ?1").get(slug) !== undefined;
}

export function insertMonster(m: MonsterRecord): void {
  db.prepare(
    "INSERT INTO monsters (slug, name, cr, armor_class, hit_points) VALUES (?1, ?2, ?3, ?4, ?5)",
  ).run(m.slug, m.name, m.cr, m.armor_class, m.hit_points);
  const stmt = db.prepare(
    "INSERT INTO monster_tags (slug, tag, position) VALUES (?1, ?2, ?3)",
  );
  m.tags.forEach((tag, i) => stmt.run(m.slug, tag, i));
}

export function getMonster(slug: string): MonsterRecord | undefined {
  const row = db.prepare(
    "SELECT slug, name, cr, armor_class, hit_points FROM monsters WHERE slug = ?1",
  ).get(slug);
  if (!row) return undefined;
  const r = row as Record<string, SQLOutputValue>;
  const tagRows = db.prepare(
    "SELECT tag FROM monster_tags WHERE slug = ?1 ORDER BY position",
  ).all(slug) as Record<string, SQLOutputValue>[];
  return {
    slug: asString(r.slug),
    name: asString(r.name),
    cr: asString(r.cr),
    armor_class: asNumber(r.armor_class),
    hit_points: asNumber(r.hit_points),
    tags: tagRows.map((tr) => asString(tr.tag)),
  };
}

// --- compendium: items -----------------------------------------------------

export function itemExists(slug: string): boolean {
  return db.prepare("SELECT 1 FROM items WHERE slug = ?1").get(slug) !== undefined;
}

export function insertItem(it: ItemRecord): void {
  db.prepare(
    "INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?1, ?2, ?3, ?4, ?5)",
  ).run(it.slug, it.name, it.type, it.rarity, it.cost_gp);
}

export function getItem(slug: string): ItemRecord | undefined {
  const row = db.prepare(
    "SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?1",
  ).get(slug);
  if (!row) return undefined;
  const r = row as Record<string, SQLOutputValue>;
  return {
    slug: asString(r.slug),
    name: asString(r.name),
    type: asString(r.type),
    rarity: asString(r.rarity),
    cost_gp: asNumber(r.cost_gp),
  };
}

// --- combat sessions -------------------------------------------------------

export function combatSessionExists(id: string): boolean {
  return db.prepare("SELECT 1 FROM combat_sessions WHERE id = ?1").get(id) !== undefined;
}

export function createCombatSession(id: string, combatants: Combatant[]): void {
  db.prepare(
    "INSERT INTO combat_sessions (id, round, turn_index) VALUES (?1, 1, 0)",
  ).run(id);
  const stmt = db.prepare(
    "INSERT INTO combatants (session_id, name, dex, score, position) VALUES (?1, ?2, ?3, ?4, ?5)",
  );
  combatants.forEach((c, i) => stmt.run(id, c.name, c.dex, c.score, i));
}

export function loadCombatSession(id: string): CombatSession | undefined {
  const row = db.prepare(
    "SELECT id, round, turn_index FROM combat_sessions WHERE id = ?1",
  ).get(id);
  if (!row) return undefined;
  const r = row as Record<string, SQLOutputValue>;

  const combatantRows = db.prepare(
    "SELECT name, dex, score FROM combatants WHERE session_id = ?1 ORDER BY position",
  ).all(id) as Record<string, SQLOutputValue>[];
  const order: Combatant[] = combatantRows.map((cr) => ({
    name: asString(cr.name),
    dex: asNumber(cr.dex),
    score: asNumber(cr.score),
  }));

  // Targets are ordered by insertion order (implicit rowid) so the snapshot
  // key order matches the original in-memory Map iteration order.
  const targetRows = db.prepare(
    "SELECT target FROM condition_targets WHERE session_id = ?1 ORDER BY rowid",
  ).all(id) as Record<string, SQLOutputValue>[];
  const conditions = new Map<string, ConditionEntry[]>();
  for (const tr of targetRows) {
    const target = asString(tr.target);
    const condRows = db.prepare(
      "SELECT condition, remaining_rounds AS remaining_rounds FROM conditions " +
        "WHERE session_id = ?1 AND target = ?2 ORDER BY position, id",
    ).all(id, target) as Record<string, SQLOutputValue>[];
    conditions.set(
      target,
      condRows.map((cr) => ({
        condition: asString(cr.condition),
        remaining_rounds: asNumber(cr.remaining_rounds),
      })),
    );
  }

  return {
    id: asString(r.id),
    order,
    round: asNumber(r.round),
    turn_index: asNumber(r.turn_index),
    conditions,
  };
}

export function saveCombatSessionMeta(
  id: string,
  round: number,
  turn_index: number,
): void {
  db.prepare(
    "UPDATE combat_sessions SET round = ?1, turn_index = ?2 WHERE id = ?3",
  ).run(round, turn_index, id);
}

/** Record that a target has ever carried a condition (idempotent). */
export function markConditionTarget(id: string, target: string): void {
  db.prepare(
    "INSERT OR IGNORE INTO condition_targets (session_id, target) VALUES (?1, ?2)",
  ).run(id, target);
}

/** Append a condition to a target's active list, preserving insertion order. */
export function appendCombatCondition(
  id: string,
  target: string,
  condition: string,
  duration_rounds: number,
): void {
  markConditionTarget(id, target);
  const maxRow = db.prepare(
    "SELECT COALESCE(MAX(position), -1) AS pos FROM conditions WHERE session_id = ?1 AND target = ?2",
  ).get(id, target) as Record<string, SQLOutputValue> | undefined;
  const nextPos = asNumber(maxRow?.pos ?? -1) + 1;
  db.prepare(
    "INSERT INTO conditions (session_id, target, condition, remaining_rounds, position) " +
      "VALUES (?1, ?2, ?3, ?4, ?5)",
  ).run(id, target, condition, duration_rounds, nextPos);
}

/** Replace a target's active conditions with the given list (in order). */
export function setCombatConditions(
  id: string,
  target: string,
  entries: ConditionEntry[],
): void {
  markConditionTarget(id, target);
  db.prepare("DELETE FROM conditions WHERE session_id = ?1 AND target = ?2").run(
    id,
    target,
  );
  const stmt = db.prepare(
    "INSERT INTO conditions (session_id, target, condition, remaining_rounds, position) " +
      "VALUES (?1, ?2, ?3, ?4, ?5)",
  );
  entries.forEach((c, i) =>
    stmt.run(id, target, c.condition, c.remaining_rounds, i),
  );
}

// --- campaign state -------------------------------------------------------

export function campaignExists(id: string): boolean {
  return db.prepare("SELECT 1 FROM campaigns WHERE id = ?1").get(id) !== undefined;
}

export function insertCampaign(rec: CampaignRecord): void {
  db.prepare(
    "INSERT INTO campaigns (id, name, dm) VALUES (?1, ?2, ?3)",
  ).run(rec.id, rec.name, rec.dm);
}

export function getCampaign(id: string): CampaignRecord | undefined {
  const row = db.prepare(
    "SELECT id, name, dm FROM campaigns WHERE id = ?1",
  ).get(id);
  if (!row) return undefined;
  const r = row as Record<string, SQLOutputValue>;
  return {
    id: asString(r.id),
    name: asString(r.name),
    dm: asString(r.dm),
  };
}

export function campaignCharacterExists(
  campaignId: string,
  charId: string,
): boolean {
  return (
    db
      .prepare(
        "SELECT 1 FROM campaign_characters WHERE campaign_id = ?1 AND id = ?2",
      )
      .get(campaignId, charId) !== undefined
  );
}

export function insertCampaignCharacter(
  campaignId: string,
  rec: CampaignCharacterRecord,
): void {
  const maxRow = db.prepare(
    "SELECT COALESCE(MAX(position), -1) AS pos FROM campaign_characters WHERE campaign_id = ?1",
  ).get(campaignId) as Record<string, SQLOutputValue> | undefined;
  const pos = asNumber(maxRow?.pos ?? -1) + 1;
  db.prepare(
    "INSERT INTO campaign_characters (campaign_id, id, name, level, class, position) " +
      "VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
  ).run(campaignId, rec.id, rec.name, rec.level, rec.class, pos);
}

export function getCampaignCharacters(
  campaignId: string,
): CampaignCharacterRecord[] {
  const rows = db.prepare(
    "SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ?1 ORDER BY position",
  ).all(campaignId) as Record<string, SQLOutputValue>[];
  return rows.map((r) => ({
    id: asString(r.id),
    name: asString(r.name),
    level: asNumber(r.level),
    class: asString(r.class),
  }));
}

export function campaignEventExists(
  campaignId: string,
  evtId: string,
): boolean {
  return (
    db
      .prepare(
        "SELECT 1 FROM campaign_events WHERE campaign_id = ?1 AND id = ?2",
      )
      .get(campaignId, evtId) !== undefined
  );
}

export function insertCampaignEvent(
  campaignId: string,
  rec: CampaignEventRecord,
): void {
  const maxRow = db.prepare(
    "SELECT COALESCE(MAX(position), -1) AS pos FROM campaign_events WHERE campaign_id = ?1",
  ).get(campaignId) as Record<string, SQLOutputValue> | undefined;
  const pos = asNumber(maxRow?.pos ?? -1) + 1;
  db.prepare(
    "INSERT INTO campaign_events (campaign_id, id, kind, summary, position) " +
      "VALUES (?1, ?2, ?3, ?4, ?5)",
  ).run(campaignId, rec.id, rec.kind, rec.summary, pos);
}

export function getCampaignEventCount(campaignId: string): number {
  const row = db.prepare(
    "SELECT COUNT(*) AS n FROM campaign_events WHERE campaign_id = ?1",
  ).get(campaignId) as Record<string, SQLOutputValue>;
  return asNumber(row.n);
}

/** Return a campaign's events in insertion order (earliest first). */
export function getCampaignEvents(
  campaignId: string,
): CampaignEventRecord[] {
  const rows = db.prepare(
    "SELECT id, kind, summary FROM campaign_events WHERE campaign_id = ?1 ORDER BY position",
  ).all(campaignId) as Record<string, SQLOutputValue>[];
  return rows.map((r) => ({
    id: asString(r.id),
    kind: asString(r.kind),
    summary: asString(r.summary),
  }));
}
