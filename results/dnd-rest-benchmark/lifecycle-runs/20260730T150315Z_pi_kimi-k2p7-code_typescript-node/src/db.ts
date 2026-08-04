import { DatabaseSync } from 'node:sqlite';
import { existsSync, unlinkSync } from 'node:fs';

const DB_PATH = './game.db';
export const SCHEMA_VERSION = 1;

let db: DatabaseSync | undefined;
let initialized = false;

/** Return the open SQLite database. Throws if the database is not initialized. */
export function getDb(): DatabaseSync {
  if (!db) {
    throw new Error('Database not initialized');
  }
  return db;
}

export function isInitialized(): boolean {
  return initialized;
}

/**
 * Open the SQLite database and create the schema. Any existing database file is
 * removed first so that every server start yields a deterministic, blank slate.
 * Tests that need to reset state between cases can use `POST /v1/storage/reset`.
 */
export function initializeDatabase(): void {
  if (existsSync(DB_PATH)) {
    unlinkSync(DB_PATH);
  }
  db = new DatabaseSync(DB_PATH);
  createSchema();
  initialized = true;
}

/** Drop all tables and recreate the schema. Used by the storage reset endpoint. */
export function resetDatabase(): void {
  const d = getDb();
  d.exec(`
    DROP TABLE IF EXISTS encounter_rewards;
    DROP TABLE IF EXISTS readied_actions;
    DROP TABLE IF EXISTS combat_actions;
    DROP TABLE IF EXISTS play_encounters;
    DROP TABLE IF EXISTS rests;
    DROP TABLE IF EXISTS travels;
    DROP TABLE IF EXISTS location_connections;
    DROP TABLE IF EXISTS locations;
    DROP TABLE IF EXISTS session_attendance;
    DROP TABLE IF EXISTS sessions;
    DROP TABLE IF EXISTS crafting_projects;
    DROP TABLE IF EXISTS equipment;
    DROP TABLE IF EXISTS inventory;
    DROP TABLE IF EXISTS npcs;
    DROP TABLE IF EXISTS factions;
    DROP TABLE IF EXISTS campaign_characters;
    DROP TABLE IF EXISTS campaign_events;
    DROP TABLE IF EXISTS campaign_documents;
    DROP TABLE IF EXISTS resolutions;
    DROP TABLE IF EXISTS actions;
    DROP TABLE IF EXISTS narrations;
    DROP TABLE IF EXISTS nudges;
    DROP TABLE IF EXISTS play_members;
    DROP TABLE IF EXISTS play_campaigns;
    DROP TABLE IF EXISTS scenes;
    DROP TABLE IF EXISTS quests;
    DROP TABLE IF EXISTS campaigns;
    DROP TABLE IF EXISTS combat_sessions;
    DROP TABLE IF EXISTS monsters;
    DROP TABLE IF EXISTS items;
  `);
  createSchema();
}

/** Create every table if it does not already exist. */
function createSchema(): void {
  const d = getDb();
  d.exec(`
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
      summary TEXT
    );
    CREATE TABLE IF NOT EXISTS quests (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      title TEXT NOT NULL,
      status TEXT NOT NULL,
      milestones_json TEXT NOT NULL,
      done_milestones_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS factions (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      name TEXT NOT NULL,
      stance TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS npcs (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      name TEXT NOT NULL,
      faction_id TEXT,
      disposition INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS inventory (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      item_slug TEXT NOT NULL,
      quantity INTEGER NOT NULL,
      owner TEXT NOT NULL,
      UNIQUE(campaign_id, item_slug, owner)
    );
    CREATE TABLE IF NOT EXISTS equipment (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      item_slug TEXT NOT NULL,
      quantity INTEGER NOT NULL,
      UNIQUE(campaign_id, character_id, item_slug)
    );
    CREATE TABLE IF NOT EXISTS crafting_projects (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      item_slug TEXT NOT NULL,
      days_required INTEGER NOT NULL,
      days_completed INTEGER NOT NULL,
      status TEXT NOT NULL,
      cost_gp INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS play_campaigns (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      owner TEXT NOT NULL,
      status TEXT NOT NULL,
      max_players INTEGER NOT NULL,
      current_actor TEXT,
      turn_number INTEGER,
      phase TEXT,
      current_scene_id TEXT,
      current_location_id TEXT,
      pre_combat_actor TEXT
    );
    CREATE TABLE IF NOT EXISTS campaign_documents (
      campaign_id TEXT PRIMARY KEY,
      story TEXT NOT NULL,
      dm_notes TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS play_members (
      campaign_id TEXT NOT NULL,
      username TEXT NOT NULL,
      character_id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      class TEXT NOT NULL,
      hp_current INTEGER NOT NULL DEFAULT 20,
      hp_max INTEGER NOT NULL DEFAULT 20,
      level INTEGER NOT NULL DEFAULT 1,
      con_modifier INTEGER NOT NULL DEFAULT 0,
      status TEXT NOT NULL DEFAULT 'conscious',
      death_save_successes INTEGER NOT NULL DEFAULT 0,
      death_save_failures INTEGER NOT NULL DEFAULT 0,
      owner TEXT,
      UNIQUE(campaign_id, username)
    );
    CREATE TABLE IF NOT EXISTS sessions (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      starts_at TEXT NOT NULL,
      duration_minutes INTEGER NOT NULL,
      agenda_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS narrations (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      actor TEXT NOT NULL,
      text TEXT NOT NULL,
      UNIQUE(campaign_id, sequence)
    );
    CREATE TABLE IF NOT EXISTS actions (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      actor TEXT NOT NULL,
      type TEXT NOT NULL,
      text TEXT NOT NULL,
      UNIQUE(campaign_id, sequence)
    );
    CREATE TABLE IF NOT EXISTS resolutions (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      actor TEXT NOT NULL,
      text TEXT NOT NULL,
      UNIQUE(campaign_id, sequence)
    );
    CREATE TABLE IF NOT EXISTS nudges (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      turn_number INTEGER NOT NULL,
      actor TEXT NOT NULL,
      target TEXT NOT NULL,
      message TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      UNIQUE(campaign_id, sequence)
    );
    CREATE TABLE IF NOT EXISTS scenes (
      id TEXT NOT NULL,
      campaign_id TEXT NOT NULL,
      name TEXT NOT NULL,
      status TEXT NOT NULL,
      PRIMARY KEY (id, campaign_id)
    );
    CREATE TABLE IF NOT EXISTS locations (
      id TEXT NOT NULL,
      campaign_id TEXT NOT NULL,
      name TEXT NOT NULL,
      PRIMARY KEY (id, campaign_id)
    );
    CREATE TABLE IF NOT EXISTS location_connections (
      from_id TEXT NOT NULL,
      to_id TEXT NOT NULL,
      campaign_id TEXT NOT NULL,
      travel_turns INTEGER NOT NULL,
      PRIMARY KEY (from_id, to_id, campaign_id)
    );
    CREATE TABLE IF NOT EXISTS travels (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      actor TEXT NOT NULL,
      destination_id TEXT NOT NULL,
      travel_turns INTEGER NOT NULL,
      UNIQUE(campaign_id, sequence)
    );
    CREATE TABLE IF NOT EXISTS play_encounters (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      name TEXT NOT NULL,
      status TEXT NOT NULL,
      round INTEGER NOT NULL DEFAULT 1,
      turn_index INTEGER NOT NULL DEFAULT 0,
      combatants_json TEXT NOT NULL,
      conditions_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS encounter_rewards (
      encounter_id TEXT PRIMARY KEY,
      xp INTEGER NOT NULL,
      loot_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS combat_actions (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      encounter_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      actor TEXT NOT NULL,
      type TEXT NOT NULL,
      target TEXT NOT NULL,
      text TEXT NOT NULL,
      UNIQUE(campaign_id, sequence)
    );
    CREATE TABLE IF NOT EXISTS readied_actions (
      id TEXT PRIMARY KEY,
      encounter_id TEXT NOT NULL,
      actor TEXT NOT NULL,
      trigger TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS rests (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      actor TEXT NOT NULL,
      type TEXT NOT NULL,
      hp_current INTEGER NOT NULL,
      hp_max INTEGER NOT NULL,
      UNIQUE(campaign_id, sequence)
    );
    CREATE TABLE IF NOT EXISTS session_attendance (
      session_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      present INTEGER NOT NULL,
      PRIMARY KEY (session_id, character_id)
    );
  `);
}
