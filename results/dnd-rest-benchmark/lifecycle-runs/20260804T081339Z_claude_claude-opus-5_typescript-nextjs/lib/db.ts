/**
 * SQLite persistence. Every durable module (`users`, `combat`, `compendium`,
 * `campaigns`) goes through `database()` for its connection; nothing else
 * opens a handle or owns schema.
 */
import { DatabaseSync } from "node:sqlite";
import path from "node:path";

export const DRIVER = "sqlite";
export const SCHEMA_VERSION = 1;

const DB_PATH = process.env.DND_DB_PATH ?? path.join(process.cwd(), "game.db");

/**
 * Every table this application owns, parents before children. `initSchema`
 * creates them in this order and `resetSchema` drops them in reverse, so the
 * foreign keys from `campaign_characters`/`campaign_events` to `campaigns` are
 * never left dangling.
 */
const TABLES = [
  "meta",
  "users",
  "combat_sessions",
  "monsters",
  "items",
  "campaigns",
  "campaign_characters",
  "campaign_events",
] as const;

/**
 * One connection per process. It hangs off globalThis so the dev server's
 * module reloading does not open a second handle on the same file.
 */
const db: DatabaseSync = ((globalThis as Record<string, unknown>).__dndDb ??=
  openDatabase()) as DatabaseSync;

function openDatabase(): DatabaseSync {
  const handle = new DatabaseSync(DB_PATH);
  handle.exec("PRAGMA journal_mode = WAL");
  handle.exec("PRAGMA foreign_keys = ON");
  return handle;
}

/** Create every table if it is missing. Safe to call repeatedly. */
export function initSchema(): void {
  db.exec(`
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
    CREATE TABLE IF NOT EXISTS combat_sessions (
      id TEXT PRIMARY KEY,
      round INTEGER NOT NULL,
      turn_index INTEGER NOT NULL,
      order_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS monsters (
      slug TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      cr_json TEXT NOT NULL,
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
      campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
      id TEXT NOT NULL,
      name TEXT NOT NULL,
      level INTEGER NOT NULL,
      class TEXT NOT NULL,
      seq INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );
    CREATE TABLE IF NOT EXISTS campaign_events (
      campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
      id TEXT NOT NULL,
      kind TEXT NOT NULL,
      summary TEXT NOT NULL,
      seq INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );
  `);
  db.prepare("INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)").run(
    String(SCHEMA_VERSION),
  );
}

/** Drop every table and rebuild the schema from scratch. Backs `POST /v1/storage/reset`. */
export function resetSchema(): void {
  const drops = [...TABLES].reverse().map((table) => `DROP TABLE IF EXISTS ${table};`);
  db.exec(drops.join("\n"));
  initSchema();
}

/** True once every table exists and the schema version is recorded. */
export function isInitialized(): boolean {
  const placeholders = TABLES.map(() => "?").join(", ");
  const row = db
    .prepare(
      `SELECT COUNT(*) AS present FROM sqlite_master
       WHERE type = 'table' AND name IN (${placeholders})`,
    )
    .get(...TABLES) as { present: number } | undefined;
  if (!row || Number(row.present) !== TABLES.length) return false;

  const version = db
    .prepare("SELECT value FROM meta WHERE key = 'schema_version'")
    .get() as { value: string } | undefined;
  return version?.value === String(SCHEMA_VERSION);
}

/**
 * The connection every query should use. It re-creates the schema when it has
 * gone missing, so a request that lands between `resetSchema`'s drop and its
 * rebuild — or on a database file deleted out from under the process — still
 * sees the tables it expects.
 */
export function database(): DatabaseSync {
  if (!isInitialized()) initSchema();
  return db;
}

// Guarantee the schema exists as soon as this module is imported. `GET
// /v1/storage/status` reads `isInitialized()` without going through
// `database()`, so it must already be true on the first request; the
// `instrumentation.ts` startup hook covers the same ground for a cold server.
initSchema();
