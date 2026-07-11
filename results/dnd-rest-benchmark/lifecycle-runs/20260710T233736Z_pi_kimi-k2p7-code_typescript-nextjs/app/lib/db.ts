import { DatabaseSync } from "node:sqlite";
import path from "node:path";

const DB_PATH = process.env.DND_DB_PATH ?? path.join(process.cwd(), "game.db");
const SCHEMA_VERSION = 1;

let db: DatabaseSync | null = null;

export function getDb(): DatabaseSync {
  if (!db) {
    db = new DatabaseSync(DB_PATH, { timeout: 5000 });
    db.exec("PRAGMA foreign_keys = ON;");
    initSchema(db);
  }
  return db;
}

function initSchema(database: DatabaseSync) {
  database.exec(`
    CREATE TABLE IF NOT EXISTS users (
      username TEXT PRIMARY KEY,
      password_hash TEXT NOT NULL,
      salt TEXT NOT NULL,
      role TEXT NOT NULL
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

    CREATE TABLE IF NOT EXISTS characters (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      name TEXT NOT NULL,
      level INTEGER NOT NULL,
      class TEXT NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS events (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      summary TEXT NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    );
  `);
}

export function resetDatabase(): void {
  const database = getDb();
  database.exec(`
    DROP TABLE IF EXISTS events;
    DROP TABLE IF EXISTS characters;
    DROP TABLE IF EXISTS campaigns;
    DROP TABLE IF EXISTS items;
    DROP TABLE IF EXISTS monsters;
    DROP TABLE IF EXISTS combat_sessions;
    DROP TABLE IF EXISTS users;
  `);
  initSchema(database);
}

export function storageStatus(): {
  driver: string;
  schema_version: number;
  initialized: boolean;
} {
  return { driver: "sqlite", schema_version: SCHEMA_VERSION, initialized: true };
}

// Initialize on first import so the DB file and schema exist on server startup.
getDb();
