import { DatabaseSync } from "node:sqlite";
import { join } from "node:path";

const SCHEMA_VERSION = 1;
const DB_PATH = join(process.cwd(), "game.db");

let database: DatabaseSync | undefined;

export function db(): DatabaseSync {
  if (database === undefined) {
    database = new DatabaseSync(DB_PATH);
    initializeSchema();
  }

  return database;
}

export function initializeSchema(): void {
  const connection = database ?? new DatabaseSync(DB_PATH);
  database = connection;

  connection.exec(`
    CREATE TABLE IF NOT EXISTS metadata (
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
      hit_points INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS monster_tags (
      monster_slug TEXT NOT NULL,
      position INTEGER NOT NULL,
      tag TEXT NOT NULL,
      PRIMARY KEY (monster_slug, position),
      FOREIGN KEY (monster_slug) REFERENCES monsters(slug) ON DELETE CASCADE
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
      id TEXT NOT NULL,
      campaign_id TEXT NOT NULL,
      name TEXT NOT NULL,
      level INTEGER NOT NULL,
      class TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id),
      FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS campaign_events (
      id TEXT NOT NULL,
      campaign_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      summary TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id),
      FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    );
  `);

  connection
    .prepare("INSERT OR REPLACE INTO metadata (key, value) VALUES ('schema_version', ?)")
    .run(String(SCHEMA_VERSION));
}

export function resetStorage(): void {
  const connection = db();
  connection.exec(`
    DROP TABLE IF EXISTS monster_tags;
    DROP TABLE IF EXISTS monsters;
    DROP TABLE IF EXISTS items;
    DROP TABLE IF EXISTS campaign_events;
    DROP TABLE IF EXISTS campaign_characters;
    DROP TABLE IF EXISTS campaigns;
    DROP TABLE IF EXISTS combat_sessions;
    DROP TABLE IF EXISTS users;
    DROP TABLE IF EXISTS metadata;
  `);
  initializeSchema();
}

export function storageStatus() {
  initializeSchema();
  const row = db().prepare("SELECT value FROM metadata WHERE key = 'schema_version'").get();
  const schemaVersion = row === undefined ? SCHEMA_VERSION : Number(row.value);

  return {
    driver: "sqlite",
    schema_version: schemaVersion,
    initialized: schemaVersion === SCHEMA_VERSION,
  };
}

export { SCHEMA_VERSION };
