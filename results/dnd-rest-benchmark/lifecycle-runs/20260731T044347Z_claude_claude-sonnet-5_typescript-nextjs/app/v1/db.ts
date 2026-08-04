import { DatabaseSync } from "node:sqlite";
import path from "node:path";

// Bump this whenever createSchema's table/column layout changes in a way
// that existing callers of GET /v1/storage/status need to be able to detect.
// It is surfaced verbatim in the storage status/reset responses; it does not
// drive any migration logic (resetStorage always drops and recreates from
// scratch rather than migrating in place).
export const SCHEMA_VERSION = 1;

const DB_PATH = path.join(process.cwd(), "game.db");

let db: DatabaseSync | undefined;
let initialized = false;

// All domain tables (other than `users`) store their entity as an opaque
// JSON blob in a `data` column, keyed by an id/slug supplied by the client
// (this API never generates ids). This keeps the schema stable as domain
// shapes evolve, at the cost of not being queryable by anything other than
// the primary/composite key.
function createSchema(database: DatabaseSync): void {
  database.exec(`
    CREATE TABLE IF NOT EXISTS users (
      username TEXT PRIMARY KEY,
      password_hash TEXT NOT NULL,
      role TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS combat_sessions (
      id TEXT PRIMARY KEY,
      data TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS monsters (
      slug TEXT PRIMARY KEY,
      data TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS items (
      slug TEXT PRIMARY KEY,
      data TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS campaigns (
      id TEXT PRIMARY KEY,
      data TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS campaign_characters (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      data TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );
    CREATE TABLE IF NOT EXISTS campaign_events (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      data TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );
    CREATE TABLE IF NOT EXISTS campaign_quests (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      data TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );
    CREATE TABLE IF NOT EXISTS campaign_factions (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      data TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );
    CREATE TABLE IF NOT EXISTS campaign_npcs (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      data TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );
    CREATE TABLE IF NOT EXISTS campaign_inventory (
      entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      data TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS campaign_equipment (
      entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      data TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS campaign_crafting_projects (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      data TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );
    CREATE TABLE IF NOT EXISTS campaign_sessions (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      data TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );
    CREATE TABLE IF NOT EXISTS play_campaigns (
      id TEXT PRIMARY KEY,
      data TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS play_members (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      data TEXT NOT NULL,
      PRIMARY KEY (campaign_id, character_id)
    );
    CREATE TABLE IF NOT EXISTS play_events (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      data TEXT NOT NULL,
      PRIMARY KEY (campaign_id, sequence)
    );
    CREATE TABLE IF NOT EXISTS play_scenes (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      data TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );
    CREATE TABLE IF NOT EXISTS play_locations (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      data TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );
    CREATE TABLE IF NOT EXISTS play_location_connections (
      campaign_id TEXT NOT NULL,
      from_id TEXT NOT NULL,
      to_id TEXT NOT NULL,
      data TEXT NOT NULL,
      PRIMARY KEY (campaign_id, from_id, to_id)
    );
    CREATE TABLE IF NOT EXISTS play_encounters (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      data TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );
    CREATE TABLE IF NOT EXISTS play_spells (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      spell_id TEXT NOT NULL,
      data TEXT NOT NULL,
      PRIMARY KEY (campaign_id, character_id, spell_id)
    );
    CREATE TABLE IF NOT EXISTS play_casts (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      data TEXT NOT NULL,
      PRIMARY KEY (campaign_id, character_id, sequence)
    );
    CREATE TABLE IF NOT EXISTS play_currency_transfers (
      campaign_id TEXT NOT NULL,
      transfer_id INTEGER NOT NULL,
      data TEXT NOT NULL,
      PRIMARY KEY (campaign_id, transfer_id)
    );
    CREATE TABLE IF NOT EXISTS play_loot (
      campaign_id TEXT NOT NULL,
      loot_id TEXT NOT NULL,
      data TEXT NOT NULL,
      PRIMARY KEY (campaign_id, loot_id)
    );
    CREATE TABLE IF NOT EXISTS play_npcs (
      campaign_id TEXT NOT NULL,
      npc_id TEXT NOT NULL,
      data TEXT NOT NULL,
      PRIMARY KEY (campaign_id, npc_id)
    );
    CREATE TABLE IF NOT EXISTS play_factions (
      campaign_id TEXT NOT NULL,
      faction_id TEXT NOT NULL,
      data TEXT NOT NULL,
      PRIMARY KEY (campaign_id, faction_id)
    );
    CREATE TABLE IF NOT EXISTS play_faction_reputation (
      campaign_id TEXT NOT NULL,
      faction_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      total INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, faction_id, character_id)
    );
    CREATE TABLE IF NOT EXISTS play_faction_reputation_history (
      campaign_id TEXT NOT NULL,
      faction_id TEXT NOT NULL,
      entry_id INTEGER NOT NULL,
      data TEXT NOT NULL,
      PRIMARY KEY (campaign_id, faction_id, entry_id)
    );
    CREATE TABLE IF NOT EXISTS play_npc_dialogue (
      campaign_id TEXT NOT NULL,
      npc_id TEXT NOT NULL,
      dialogue_id TEXT NOT NULL,
      entry_id INTEGER NOT NULL,
      data TEXT NOT NULL,
      PRIMARY KEY (campaign_id, npc_id, entry_id)
    );
    CREATE TABLE IF NOT EXISTS play_relationships (
      row_id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      source_id TEXT NOT NULL,
      target_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      data TEXT NOT NULL,
      UNIQUE (campaign_id, source_id, target_id, kind)
    );
    CREATE TABLE IF NOT EXISTS play_clues (
      row_id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      clue_id TEXT NOT NULL,
      data TEXT NOT NULL,
      UNIQUE (campaign_id, clue_id)
    );
    CREATE TABLE IF NOT EXISTS play_quests (
      row_id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      quest_id TEXT NOT NULL,
      data TEXT NOT NULL,
      UNIQUE (campaign_id, quest_id)
    );
    CREATE TABLE IF NOT EXISTS play_character_rewards (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      data TEXT NOT NULL,
      PRIMARY KEY (campaign_id, character_id)
    );
    CREATE TABLE IF NOT EXISTS play_world_events (
      row_id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      event_id TEXT NOT NULL,
      data TEXT NOT NULL,
      UNIQUE (campaign_id, event_id)
    );
    CREATE TABLE IF NOT EXISTS play_calendars (
      campaign_id TEXT PRIMARY KEY,
      data TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS play_settlements (
      row_id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      settlement_id TEXT NOT NULL,
      data TEXT NOT NULL,
      UNIQUE (campaign_id, settlement_id)
    );
    CREATE TABLE IF NOT EXISTS play_shops (
      row_id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      settlement_id TEXT NOT NULL,
      shop_id TEXT NOT NULL,
      data TEXT NOT NULL,
      UNIQUE (campaign_id, settlement_id, shop_id)
    );
    CREATE TABLE IF NOT EXISTS play_recipes (
      row_id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      recipe_id TEXT NOT NULL,
      data TEXT NOT NULL,
      UNIQUE (campaign_id, recipe_id)
    );
    CREATE TABLE IF NOT EXISTS play_downtime_activities (
      campaign_id TEXT NOT NULL,
      activity_id TEXT NOT NULL,
      data TEXT NOT NULL,
      PRIMARY KEY (campaign_id, activity_id)
    );
    CREATE TABLE IF NOT EXISTS play_downtime_allocations (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      activity_id TEXT NOT NULL,
      data TEXT NOT NULL,
      PRIMARY KEY (campaign_id, character_id, activity_id)
    );
    CREATE TABLE IF NOT EXISTS play_content (
      row_id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      content_id TEXT NOT NULL,
      data TEXT NOT NULL,
      UNIQUE (campaign_id, content_id)
    );
    CREATE TABLE IF NOT EXISTS play_notes (
      row_id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      note_id TEXT NOT NULL,
      data TEXT NOT NULL,
      UNIQUE (campaign_id, note_id)
    );
    CREATE TABLE IF NOT EXISTS play_whispers (
      row_id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      whisper_id TEXT NOT NULL,
      data TEXT NOT NULL,
      UNIQUE (campaign_id, whisper_id)
    );
    CREATE TABLE IF NOT EXISTS play_invitations (
      row_id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      invitation_id TEXT NOT NULL,
      data TEXT NOT NULL,
      UNIQUE (campaign_id, invitation_id)
    );
    CREATE TABLE IF NOT EXISTS play_delegations (
      campaign_id TEXT NOT NULL,
      username TEXT NOT NULL,
      data TEXT NOT NULL,
      PRIMARY KEY (campaign_id, username)
    );
    CREATE TABLE IF NOT EXISTS play_delegation_audit (
      row_id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      data TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS play_audit_events (
      row_id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      correlation_id TEXT NOT NULL,
      data TEXT NOT NULL,
      UNIQUE (campaign_id, correlation_id)
    );
    CREATE TABLE IF NOT EXISTS play_projection_events (
      sequence INTEGER NOT NULL,
      campaign_id TEXT NOT NULL,
      event_id TEXT NOT NULL,
      data TEXT NOT NULL,
      PRIMARY KEY (campaign_id, sequence),
      UNIQUE (campaign_id, event_id)
    );
    CREATE TABLE IF NOT EXISTS play_idempotent_events (
      sequence INTEGER NOT NULL,
      campaign_id TEXT NOT NULL,
      event_id TEXT NOT NULL,
      idempotency_key TEXT NOT NULL,
      data TEXT NOT NULL,
      PRIMARY KEY (campaign_id, sequence),
      UNIQUE (campaign_id, event_id),
      UNIQUE (campaign_id, idempotency_key)
    );
    CREATE TABLE IF NOT EXISTS play_safe_turn_state (
      campaign_id TEXT PRIMARY KEY,
      current_turn INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS play_safe_turns (
      sequence INTEGER NOT NULL,
      campaign_id TEXT NOT NULL,
      submission_id TEXT NOT NULL,
      data TEXT NOT NULL,
      PRIMARY KEY (campaign_id, sequence),
      UNIQUE (campaign_id, submission_id)
    );
  `);
  initialized = true;
}

export function getDb(): DatabaseSync {
  if (!db) {
    db = new DatabaseSync(DB_PATH);
    createSchema(db);
  }
  return db;
}

export function isInitialized(): boolean {
  return initialized;
}

export function resetStorage(): void {
  const database = getDb();
  // `users` is deliberately not dropped here: a session token obtained
  // before a reset call must stay valid afterward.
  database.exec(`
    DROP TABLE IF EXISTS combat_sessions;
    DROP TABLE IF EXISTS monsters;
    DROP TABLE IF EXISTS items;
    DROP TABLE IF EXISTS campaigns;
    DROP TABLE IF EXISTS campaign_characters;
    DROP TABLE IF EXISTS campaign_events;
    DROP TABLE IF EXISTS campaign_quests;
    DROP TABLE IF EXISTS campaign_factions;
    DROP TABLE IF EXISTS campaign_npcs;
    DROP TABLE IF EXISTS campaign_inventory;
    DROP TABLE IF EXISTS campaign_equipment;
    DROP TABLE IF EXISTS campaign_crafting_projects;
    DROP TABLE IF EXISTS campaign_sessions;
    DROP TABLE IF EXISTS play_campaigns;
    DROP TABLE IF EXISTS play_members;
    DROP TABLE IF EXISTS play_events;
    DROP TABLE IF EXISTS play_scenes;
    DROP TABLE IF EXISTS play_locations;
    DROP TABLE IF EXISTS play_location_connections;
    DROP TABLE IF EXISTS play_encounters;
    DROP TABLE IF EXISTS play_spells;
    DROP TABLE IF EXISTS play_casts;
    DROP TABLE IF EXISTS play_currency_transfers;
    DROP TABLE IF EXISTS play_loot;
    DROP TABLE IF EXISTS play_npcs;
    DROP TABLE IF EXISTS play_factions;
    DROP TABLE IF EXISTS play_faction_reputation;
    DROP TABLE IF EXISTS play_faction_reputation_history;
    DROP TABLE IF EXISTS play_npc_dialogue;
    DROP TABLE IF EXISTS play_relationships;
    DROP TABLE IF EXISTS play_clues;
    DROP TABLE IF EXISTS play_quests;
    DROP TABLE IF EXISTS play_character_rewards;
    DROP TABLE IF EXISTS play_world_events;
    DROP TABLE IF EXISTS play_calendars;
    DROP TABLE IF EXISTS play_settlements;
    DROP TABLE IF EXISTS play_shops;
    DROP TABLE IF EXISTS play_recipes;
    DROP TABLE IF EXISTS play_downtime_activities;
    DROP TABLE IF EXISTS play_downtime_allocations;
    DROP TABLE IF EXISTS play_content;
    DROP TABLE IF EXISTS play_notes;
    DROP TABLE IF EXISTS play_whispers;
    DROP TABLE IF EXISTS play_invitations;
    DROP TABLE IF EXISTS play_delegations;
    DROP TABLE IF EXISTS play_delegation_audit;
    DROP TABLE IF EXISTS play_audit_events;
    DROP TABLE IF EXISTS play_projection_events;
    DROP TABLE IF EXISTS play_idempotent_events;
    DROP TABLE IF EXISTS play_safe_turn_state;
    DROP TABLE IF EXISTS play_safe_turns;
  `);
  createSchema(database);
}
