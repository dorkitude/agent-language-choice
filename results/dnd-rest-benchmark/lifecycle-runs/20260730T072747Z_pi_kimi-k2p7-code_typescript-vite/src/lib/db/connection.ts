// Shared SQLite connection and schema lifecycle. The database is opened once
// when this module is imported and the schema is reset when the Vite server
// starts so each run begins with a clean, deterministic slate.

import { DatabaseSync } from 'node:sqlite';
import path from 'node:path';
import { DB_PATH, SCHEMA_VERSION } from '../constants.js';

export const db = new DatabaseSync(path.resolve(DB_PATH));

let dbInitialized = false;

export function isDbInitialized(): boolean {
  return dbInitialized;
}

function addColumnIfMissing(table: string, column: string, type: string): void {
  const info = db.prepare(`PRAGMA table_info(${table})`).all() as { name: string }[];
  if (!info.some((col) => col.name === column)) {
    db.prepare(`ALTER TABLE ${table} ADD COLUMN ${column} ${type}`).run();
  }
}

export function initializeSchema(): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS users (
      username TEXT PRIMARY KEY,
      role TEXT NOT NULL,
      password_hash TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS play_campaigns (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      owner TEXT NOT NULL,
      status TEXT NOT NULL,
      max_players INTEGER NOT NULL,
      current_actor TEXT,
      turn_number INTEGER,
      nudge_count INTEGER NOT NULL DEFAULT 0,
      current_location_id TEXT
    );

    CREATE TABLE IF NOT EXISTS play_campaign_members (
      campaign_id TEXT NOT NULL,
      username TEXT NOT NULL,
      character_id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      class TEXT NOT NULL,
      sequence INTEGER NOT NULL DEFAULT 0,
      hp_max INTEGER NOT NULL DEFAULT 20,
      hp_current INTEGER NOT NULL DEFAULT 20,
      status TEXT NOT NULL DEFAULT 'alive',
      death_successes INTEGER NOT NULL DEFAULT 0,
      death_failures INTEGER NOT NULL DEFAULT 0,
      UNIQUE(campaign_id, username),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS play_narrations (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      actor TEXT NOT NULL,
      text TEXT NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
      UNIQUE(campaign_id, sequence)
    );

    CREATE TABLE IF NOT EXISTS play_actions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      actor TEXT NOT NULL,
      type TEXT NOT NULL,
      text TEXT NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
      UNIQUE(campaign_id, sequence)
    );

    CREATE TABLE IF NOT EXISTS play_combat_actions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      encounter_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      actor TEXT NOT NULL,
      type TEXT NOT NULL,
      target TEXT NOT NULL,
      text TEXT NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
      UNIQUE(campaign_id, sequence)
    );

    CREATE TABLE IF NOT EXISTS play_resolutions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      actor TEXT NOT NULL,
      text TEXT NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
      UNIQUE(campaign_id, sequence)
    );

    CREATE TABLE IF NOT EXISTS play_travels (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      actor TEXT NOT NULL,
      destination_id TEXT NOT NULL,
      travel_turns INTEGER NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
      UNIQUE(campaign_id, sequence)
    );

    CREATE TABLE IF NOT EXISTS play_campaign_documents (
      campaign_id TEXT PRIMARY KEY,
      story TEXT NOT NULL DEFAULT '',
      dm_notes TEXT NOT NULL DEFAULT '',
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS play_scenes (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      name TEXT NOT NULL,
      status TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS play_locations (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      name TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS play_location_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      actor TEXT NOT NULL,
      location_id TEXT NOT NULL,
      name TEXT NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
      UNIQUE(campaign_id, sequence)
    );

    CREATE TABLE IF NOT EXISTS play_rests (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      actor TEXT NOT NULL,
      type TEXT NOT NULL,
      hp_current INTEGER NOT NULL,
      hp_max INTEGER NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
      UNIQUE(campaign_id, sequence)
    );

    CREATE TABLE IF NOT EXISTS play_encounters (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      name TEXT NOT NULL,
      status TEXT NOT NULL,
      round INTEGER NOT NULL DEFAULT 1,
      turn_index INTEGER NOT NULL DEFAULT 0,
      combatants TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS play_encounter_conditions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      encounter_id TEXT NOT NULL,
      target TEXT NOT NULL,
      condition TEXT NOT NULL,
      remaining_rounds INTEGER NOT NULL,
      FOREIGN KEY (campaign_id, encounter_id) REFERENCES play_encounters(campaign_id, id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS play_location_connections (
      campaign_id TEXT NOT NULL,
      from_id TEXT NOT NULL,
      to_id TEXT NOT NULL,
      travel_turns INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, from_id, to_id),
      FOREIGN KEY (campaign_id, from_id) REFERENCES play_locations(campaign_id, id) ON DELETE CASCADE,
      FOREIGN KEY (campaign_id, to_id) REFERENCES play_locations(campaign_id, id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS combat_sessions (
      id TEXT PRIMARY KEY,
      round INTEGER NOT NULL,
      turn_index INTEGER NOT NULL,
      combatants TEXT NOT NULL,
      order_data TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS conditions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id TEXT NOT NULL,
      target TEXT NOT NULL,
      condition TEXT NOT NULL,
      remaining_rounds INTEGER NOT NULL,
      FOREIGN KEY (session_id) REFERENCES combat_sessions(id) ON DELETE CASCADE
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

    CREATE TABLE IF NOT EXISTS quests (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      title TEXT NOT NULL,
      status TEXT NOT NULL,
      milestones TEXT NOT NULL,
      completed TEXT NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS factions (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      name TEXT NOT NULL,
      stance TEXT NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS npcs (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      name TEXT NOT NULL,
      faction_id TEXT NOT NULL,
      disposition INTEGER NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
      FOREIGN KEY (faction_id) REFERENCES factions(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS inventory (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      item_slug TEXT NOT NULL,
      quantity INTEGER NOT NULL,
      owner TEXT NOT NULL,
      UNIQUE(campaign_id, item_slug, owner),
      FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS equipment (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      item_slug TEXT NOT NULL,
      quantity INTEGER NOT NULL,
      UNIQUE(campaign_id, character_id, item_slug),
      FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
      FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS crafting_projects (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      item_slug TEXT NOT NULL,
      days_required INTEGER NOT NULL,
      days_completed INTEGER NOT NULL,
      cost_gp INTEGER NOT NULL,
      status TEXT NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
      FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS sessions (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      starts_at TEXT NOT NULL,
      duration_minutes INTEGER NOT NULL,
      agenda TEXT NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS attendance (
      session_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      present INTEGER NOT NULL,
      PRIMARY KEY (session_id, character_id),
      FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
    );
  `);
  addColumnIfMissing('play_campaigns', 'current_actor', 'TEXT');
  addColumnIfMissing('play_campaigns', 'turn_number', 'INTEGER');
  addColumnIfMissing('play_campaigns', 'nudge_count', 'INTEGER NOT NULL DEFAULT 0');
  addColumnIfMissing('play_campaigns', 'current_scene_id', 'TEXT');
  addColumnIfMissing('play_campaigns', 'current_location_id', 'TEXT');
  addColumnIfMissing('play_campaign_members', 'sequence', 'INTEGER NOT NULL DEFAULT 0');
  addColumnIfMissing('play_campaign_members', 'hp_max', 'INTEGER NOT NULL DEFAULT 20');
  addColumnIfMissing('play_campaign_members', 'hp_current', 'INTEGER NOT NULL DEFAULT 20');
  addColumnIfMissing('play_campaign_members', 'status', "TEXT NOT NULL DEFAULT 'alive'");
  addColumnIfMissing('play_campaign_members', 'death_successes', 'INTEGER NOT NULL DEFAULT 0');
  addColumnIfMissing('play_campaign_members', 'death_failures', 'INTEGER NOT NULL DEFAULT 0');
  addColumnIfMissing('play_encounters', 'round', 'INTEGER NOT NULL DEFAULT 1');
  addColumnIfMissing('play_encounters', 'turn_index', 'INTEGER NOT NULL DEFAULT 0');
  dbInitialized = true;
}

export function resetSchema(): void {
  db.exec(`
    DROP TABLE IF EXISTS attendance;
    DROP TABLE IF EXISTS sessions;
    DROP TABLE IF EXISTS crafting_projects;
    DROP TABLE IF EXISTS equipment;
    DROP TABLE IF EXISTS inventory;
    DROP TABLE IF EXISTS npcs;
    DROP TABLE IF EXISTS factions;
    DROP TABLE IF EXISTS quests;
    DROP TABLE IF EXISTS events;
    DROP TABLE IF EXISTS characters;
    DROP TABLE IF EXISTS campaigns;
    DROP TABLE IF EXISTS play_actions;
    DROP TABLE IF EXISTS play_combat_actions;
    DROP TABLE IF EXISTS play_narrations;
    DROP TABLE IF EXISTS play_resolutions;
    DROP TABLE IF EXISTS play_location_events;
    DROP TABLE IF EXISTS play_campaign_documents;
    DROP TABLE IF EXISTS play_rests;
    DROP TABLE IF EXISTS play_encounters;
    DROP TABLE IF EXISTS play_encounter_conditions;
    DROP TABLE IF EXISTS play_location_connections;
    DROP TABLE IF EXISTS play_locations;
    DROP TABLE IF EXISTS play_scenes;
    DROP TABLE IF EXISTS play_travels;
    DROP TABLE IF EXISTS play_campaign_members;
    DROP TABLE IF EXISTS play_campaigns;
    DROP TABLE IF EXISTS items;
    DROP TABLE IF EXISTS monsters;
    DROP TABLE IF EXISTS conditions;
    DROP TABLE IF EXISTS combat_sessions;
    DROP TABLE IF EXISTS users;
  `);
  initializeSchema();
}
