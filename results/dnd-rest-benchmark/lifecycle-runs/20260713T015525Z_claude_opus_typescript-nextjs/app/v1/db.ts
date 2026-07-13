import { DatabaseSync } from "node:sqlite";
import path from "node:path";

export const SCHEMA_VERSION = 1;

type Cache = { db: DatabaseSync | null };

// Persist a single connection across dev-mode module reloads.
const g = globalThis as unknown as { __gameDb?: Cache };
if (!g.__gameDb) {
  g.__gameDb = { db: null };
}

function dbPath(): string {
  return path.join(process.cwd(), "game.db");
}

export function initSchema(db: DatabaseSync): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS meta (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS users (
      username TEXT PRIMARY KEY,
      role TEXT NOT NULL,
      hash TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sessions (
      id TEXT PRIMARY KEY,
      round INTEGER NOT NULL,
      turn_index INTEGER NOT NULL,
      order_json TEXT NOT NULL
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
      seq INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );
    CREATE TABLE IF NOT EXISTS campaign_events (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      kind TEXT NOT NULL,
      summary TEXT NOT NULL,
      seq INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );
  `);
  db.prepare(
    "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)"
  ).run(String(SCHEMA_VERSION));
}

export function getDb(): DatabaseSync {
  const cache = g.__gameDb!;
  if (cache.db) return cache.db;
  const db = new DatabaseSync(dbPath());
  db.exec("PRAGMA journal_mode = WAL;");
  initSchema(db);
  cache.db = db;
  return db;
}

export function isInitialized(db: DatabaseSync): boolean {
  const row = db
    .prepare("SELECT value FROM meta WHERE key = 'schema_version'")
    .get() as { value: string } | undefined;
  return !!row && row.value === String(SCHEMA_VERSION);
}

// Drop and recreate benchmark-created durable data.
export function resetStorage(): void {
  const db = getDb();
  db.exec(`
    DROP TABLE IF EXISTS users;
    DROP TABLE IF EXISTS sessions;
    DROP TABLE IF EXISTS monsters;
    DROP TABLE IF EXISTS items;
    DROP TABLE IF EXISTS campaigns;
    DROP TABLE IF EXISTS campaign_characters;
    DROP TABLE IF EXISTS campaign_events;
    DROP TABLE IF EXISTS meta;
  `);
  initSchema(db);
}
