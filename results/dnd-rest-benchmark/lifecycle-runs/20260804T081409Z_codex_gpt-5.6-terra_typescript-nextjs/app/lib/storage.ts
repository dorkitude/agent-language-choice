import { DatabaseSync } from "node:sqlite";
import path from "node:path";

export const SCHEMA_VERSION = 1;

// Use the project directory rather than a temporary directory so game state
// survives a server restart.
const databasePath = path.join(process.cwd(), "game.db");
const globalStorage = globalThis as typeof globalThis & { gameDatabase?: DatabaseSync };
export const database = globalStorage.gameDatabase ?? new DatabaseSync(databasePath);
globalStorage.gameDatabase = database;

function initializeSchema() {
  database.exec(`
    CREATE TABLE IF NOT EXISTS storage_metadata (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS users (
      username TEXT PRIMARY KEY,
      role TEXT NOT NULL,
      salt TEXT NOT NULL,
      password_hash TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS combat_sessions (
      id TEXT PRIMARY KEY,
      round INTEGER NOT NULL,
      turn_index INTEGER NOT NULL,
      order_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS combat_conditions (
      id INTEGER PRIMARY KEY,
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
      tags_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS compendium_items (
      slug TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      type TEXT NOT NULL,
      rarity TEXT NOT NULL,
      cost_gp REAL NOT NULL
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
      class TEXT NOT NULL,
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
  database.prepare("INSERT OR REPLACE INTO storage_metadata (key, value) VALUES (?, ?)")
    .run("schema_version", String(SCHEMA_VERSION));
}

initializeSchema();

export function storageInitialized(): boolean {
  const row = database.prepare("SELECT value FROM storage_metadata WHERE key = ?").get("schema_version") as { value?: string } | undefined;
  return row?.value === String(SCHEMA_VERSION);
}

export function resetStorage(): void {
  database.exec(`
    DROP TABLE IF EXISTS combat_conditions;
    DROP TABLE IF EXISTS combat_sessions;
    DROP TABLE IF EXISTS compendium_monsters;
    DROP TABLE IF EXISTS compendium_items;
    DROP TABLE IF EXISTS campaign_events;
    DROP TABLE IF EXISTS campaign_characters;
    DROP TABLE IF EXISTS campaigns;
    DROP TABLE IF EXISTS users;
    DROP TABLE IF EXISTS storage_metadata;
  `);
  initializeSchema();
}
