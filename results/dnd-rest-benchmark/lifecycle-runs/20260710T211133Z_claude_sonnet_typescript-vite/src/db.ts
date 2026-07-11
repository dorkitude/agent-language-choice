import { DatabaseSync } from 'node:sqlite';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const DB_PATH = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'game.db');

export const SCHEMA_VERSION = 1;

let db: DatabaseSync | undefined;
let initialized = false;

function createSchema(database: DatabaseSync): void {
  database.exec(`
    CREATE TABLE IF NOT EXISTS users (
      username TEXT PRIMARY KEY,
      role TEXT NOT NULL,
      salt TEXT NOT NULL,
      hash TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS combat_sessions (
      id TEXT PRIMARY KEY,
      data TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS monsters (
      slug TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      cr TEXT NOT NULL,
      armor_class INTEGER NOT NULL,
      hit_points INTEGER NOT NULL,
      tags TEXT NOT NULL
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
}

export function getDb(): DatabaseSync {
  if (!db) {
    db = new DatabaseSync(DB_PATH);
    createSchema(db);
    initialized = true;
  }
  return db;
}

export function resetDb(): void {
  const database = getDb();
  database.exec(
    'DROP TABLE IF EXISTS users; DROP TABLE IF EXISTS combat_sessions; DROP TABLE IF EXISTS monsters; DROP TABLE IF EXISTS items; DROP TABLE IF EXISTS campaigns; DROP TABLE IF EXISTS campaign_characters; DROP TABLE IF EXISTS campaign_events;',
  );
  createSchema(database);
}

export function storageStatus(): { driver: 'sqlite'; schema_version: number; initialized: boolean } {
  return { driver: 'sqlite', schema_version: SCHEMA_VERSION, initialized };
}

getDb();
