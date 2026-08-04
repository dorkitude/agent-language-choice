/**
 * SQLite bootstrap and connection management.
 *
 * This module owns the lazy `DatabaseSync` instance, the schema definition,
 * and any additive migrations needed to bring older evaluator databases up to
 * the current shape. Domain-specific CRUD lives in the sibling modules under
 * `app/lib/storage/`.
 */

import { DatabaseSync } from "node:sqlite";
import { join } from "node:path";

const DB_PATH = process.env.DB_PATH || join(process.cwd(), "game.db");

let db: DatabaseSync | null = null;
let initialized = false;

function openDb(): DatabaseSync {
  if (!db) {
    db = new DatabaseSync(DB_PATH);
    db.exec("PRAGMA foreign_keys = ON;");
  }
  return db;
}

export function getDb(): DatabaseSync {
  const database = openDb();
  if (!initialized) {
    initStorage();
  }
  return database;
}

export function isStorageInitialized(): boolean {
  return initialized;
}

/**
 * Create the schema if it does not exist and run additive migrations.
 * Migrations are idempotent: each one catches failures when the change is
 * already present.
 */
export function initStorage(): void {
  const database = openDb();

  database.exec(`
    CREATE TABLE IF NOT EXISTS schema_version (
      version INTEGER PRIMARY KEY
    );

    CREATE TABLE IF NOT EXISTS users (
      username TEXT PRIMARY KEY,
      password_hash TEXT NOT NULL,
      role TEXT NOT NULL CHECK(role IN ('dm', 'player'))
    );

    CREATE TABLE IF NOT EXISTS combat_sessions (
      id TEXT PRIMARY KEY,
      round INTEGER NOT NULL DEFAULT 1,
      turn_index INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS combatants (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id TEXT NOT NULL REFERENCES combat_sessions(id) ON DELETE CASCADE,
      name TEXT NOT NULL,
      score INTEGER NOT NULL,
      dex INTEGER NOT NULL,
      order_index INTEGER NOT NULL,
      UNIQUE(session_id, name)
    );

    CREATE TABLE IF NOT EXISTS conditions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      combatant_id INTEGER NOT NULL REFERENCES combatants(id) ON DELETE CASCADE,
      condition TEXT NOT NULL,
      remaining_rounds INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS monsters (
      slug TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      cr TEXT NOT NULL,
      armor_class INTEGER NOT NULL,
      hit_points INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS monster_tags (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      monster_slug TEXT NOT NULL REFERENCES monsters(slug) ON DELETE CASCADE,
      tag TEXT NOT NULL
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
      campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
      name TEXT NOT NULL,
      level INTEGER NOT NULL,
      class TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS campaign_events (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
      kind TEXT NOT NULL,
      summary TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS campaign_quests (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
      title TEXT NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('active', 'completed', 'blocked'))
    );

    CREATE TABLE IF NOT EXISTS campaign_quest_milestones (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      quest_id TEXT NOT NULL REFERENCES campaign_quests(id) ON DELETE CASCADE,
      title TEXT NOT NULL,
      done INTEGER NOT NULL DEFAULT 0,
      UNIQUE(quest_id, title)
    );

    CREATE TABLE IF NOT EXISTS campaign_factions (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
      name TEXT NOT NULL,
      stance TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS campaign_npcs (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
      name TEXT NOT NULL,
      faction_id TEXT NOT NULL,
      disposition INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS campaign_inventory (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
      item_slug TEXT NOT NULL,
      owner TEXT NOT NULL,
      quantity INTEGER NOT NULL,
      UNIQUE(campaign_id, item_slug, owner)
    );

    CREATE TABLE IF NOT EXISTS campaign_equipment (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
      character_id TEXT NOT NULL REFERENCES campaign_characters(id) ON DELETE CASCADE,
      item_slug TEXT NOT NULL,
      quantity INTEGER NOT NULL,
      UNIQUE(campaign_id, character_id, item_slug)
    );

    CREATE TABLE IF NOT EXISTS crafting_projects (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
      character_id TEXT NOT NULL REFERENCES campaign_characters(id) ON DELETE CASCADE,
      item_slug TEXT NOT NULL,
      days_required INTEGER NOT NULL,
      days_completed INTEGER NOT NULL DEFAULT 0,
      cost_gp INTEGER NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('active', 'complete'))
    );

    CREATE TABLE IF NOT EXISTS campaign_sessions (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
      starts_at TEXT NOT NULL,
      duration_minutes INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS campaign_session_agenda (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id TEXT NOT NULL REFERENCES campaign_sessions(id) ON DELETE CASCADE,
      item TEXT NOT NULL,
      order_index INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS campaign_session_attendance (
      session_id TEXT NOT NULL REFERENCES campaign_sessions(id) ON DELETE CASCADE,
      character_id TEXT NOT NULL,
      present INTEGER NOT NULL DEFAULT 1,
      PRIMARY KEY (session_id, character_id)
    );

    CREATE TABLE IF NOT EXISTS play_campaigns (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      owner TEXT NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('lobby')),
      max_players INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS play_campaign_members (
      campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
      username TEXT NOT NULL,
      character_id TEXT NOT NULL,
      name TEXT NOT NULL,
      class TEXT NOT NULL,
      race TEXT,
      background TEXT,
      abilities TEXT,
      level INTEGER NOT NULL DEFAULT 1,
      owner TEXT,
      hp_max INTEGER NOT NULL DEFAULT 20,
      hp_current INTEGER NOT NULL DEFAULT 20,
      status TEXT NOT NULL DEFAULT 'conscious' CHECK(status IN ('conscious', 'unconscious', 'stable', 'dead')),
      death_saves_successes INTEGER NOT NULL DEFAULT 0,
      death_saves_failures INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (campaign_id, username),
      UNIQUE(campaign_id, character_id)
    );

    CREATE TABLE IF NOT EXISTS play_campaign_scenes (
      id TEXT NOT NULL,
      campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
      name TEXT NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('open', 'closed')),
      PRIMARY KEY (campaign_id, id)
    );

    CREATE TABLE IF NOT EXISTS play_campaign_current_scene (
      campaign_id TEXT PRIMARY KEY REFERENCES play_campaigns(id) ON DELETE CASCADE,
      scene_id TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS play_campaign_state (
      campaign_id TEXT PRIMARY KEY REFERENCES play_campaigns(id) ON DELETE CASCADE,
      status TEXT NOT NULL CHECK(status IN ('active')),
      current_actor TEXT NOT NULL,
      turn_number INTEGER NOT NULL,
      nudge_count INTEGER NOT NULL DEFAULT 0,
      current_location_id TEXT,
      phase TEXT NOT NULL DEFAULT 'exploration' CHECK(phase IN ('exploration', 'combat')),
      pre_combat_actor TEXT
    );

    CREATE TABLE IF NOT EXISTS play_campaign_narrations (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
      sequence INTEGER NOT NULL,
      kind TEXT NOT NULL,
      actor TEXT NOT NULL,
      text TEXT NOT NULL,
      type TEXT,
      destination_id TEXT,
      travel_turns INTEGER,
      target TEXT,
      UNIQUE(campaign_id, sequence)
    );

    CREATE TABLE IF NOT EXISTS play_campaign_documents (
      campaign_id TEXT PRIMARY KEY REFERENCES play_campaigns(id) ON DELETE CASCADE,
      story TEXT NOT NULL DEFAULT '',
      dm_notes TEXT NOT NULL DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS play_campaign_locations (
      id TEXT NOT NULL,
      campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
      name TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );

    CREATE TABLE IF NOT EXISTS play_campaign_location_connections (
      campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
      from_id TEXT NOT NULL,
      to_id TEXT NOT NULL,
      travel_turns INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, from_id, to_id),
      FOREIGN KEY (campaign_id, from_id) REFERENCES play_campaign_locations(campaign_id, id) ON DELETE CASCADE,
      FOREIGN KEY (campaign_id, to_id) REFERENCES play_campaign_locations(campaign_id, id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS play_campaign_encounters (
      campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
      id TEXT NOT NULL,
      name TEXT NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('active', 'completed')),
      round INTEGER NOT NULL DEFAULT 1,
      turn_index INTEGER NOT NULL DEFAULT 0,
      combatant_order TEXT,
      xp_awarded INTEGER NOT NULL DEFAULT 0,
      loot_awarded TEXT NOT NULL DEFAULT '[]',
      rewards_awarded INTEGER NOT NULL DEFAULT 0,
      closed INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (campaign_id, id)
    );

    CREATE TABLE IF NOT EXISTS play_campaign_encounter_combatants (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      encounter_id TEXT NOT NULL,
      member TEXT,
      character_id TEXT,
      name TEXT NOT NULL,
      score INTEGER NOT NULL,
      FOREIGN KEY (campaign_id, encounter_id) REFERENCES play_campaign_encounters(campaign_id, id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS play_campaign_encounter_monsters (
      campaign_id TEXT NOT NULL,
      encounter_id TEXT NOT NULL,
      monster_id TEXT NOT NULL,
      name TEXT NOT NULL,
      hp_max INTEGER NOT NULL,
      hp_current INTEGER NOT NULL,
      score INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, encounter_id, monster_id),
      FOREIGN KEY (campaign_id, encounter_id) REFERENCES play_campaign_encounters(campaign_id, id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS play_campaign_encounter_conditions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      encounter_id TEXT NOT NULL,
      target TEXT NOT NULL,
      condition TEXT NOT NULL,
      remaining_rounds INTEGER NOT NULL,
      FOREIGN KEY (campaign_id, encounter_id) REFERENCES play_campaign_encounters(campaign_id, id) ON DELETE CASCADE
    );
  `);

  const row = database.prepare("SELECT version FROM schema_version").get() as
    | { version: number }
    | undefined;
  if (!row) {
    database.prepare("INSERT INTO schema_version (version) VALUES (1)").run();
  } else if (row.version !== 1) {
    database.prepare("UPDATE schema_version SET version = 1").run();
  }

  // Additive migrations for evaluator databases that were created before the
  // current schema shape. Each statement is wrapped in a try/catch so that it
  // is safe to run against a database that already has the change.
  runMigrations(database);

  initialized = true;
}

function runMigrations(database: DatabaseSync): void {
  const migrations: Array<() => void> = [
    // Stage 027: nudge_count on play_campaign_state.
    () => database.exec("ALTER TABLE play_campaign_state ADD COLUMN nudge_count INTEGER NOT NULL DEFAULT 0"),
    // Stage 033: travel-related columns.
    () => database.exec("ALTER TABLE play_campaign_state ADD COLUMN current_location_id TEXT"),
    () => database.exec("ALTER TABLE play_campaign_narrations ADD COLUMN destination_id TEXT"),
    () => database.exec("ALTER TABLE play_campaign_narrations ADD COLUMN travel_turns INTEGER"),
    // Stage 034: character HP columns for rest turns.
    () => database.exec("ALTER TABLE play_campaign_members ADD COLUMN hp_max INTEGER NOT NULL DEFAULT 20"),
    () => database.exec("ALTER TABLE play_campaign_members ADD COLUMN hp_current INTEGER NOT NULL DEFAULT 20"),
    // Stage 041: character death-save state columns.
    () => database.exec("ALTER TABLE play_campaign_members ADD COLUMN status TEXT NOT NULL DEFAULT 'conscious' CHECK(status IN ('conscious', 'unconscious', 'stable', 'dead'))"),
    () => database.exec("ALTER TABLE play_campaign_members ADD COLUMN death_saves_successes INTEGER NOT NULL DEFAULT 0"),
    () => database.exec("ALTER TABLE play_campaign_members ADD COLUMN death_saves_failures INTEGER NOT NULL DEFAULT 0"),
    // Stage 036: encounter monster roster table.
    () => database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_encounter_monsters (
        campaign_id TEXT NOT NULL,
        encounter_id TEXT NOT NULL,
        monster_id TEXT NOT NULL,
        name TEXT NOT NULL,
        hp_max INTEGER NOT NULL,
        hp_current INTEGER NOT NULL,
        score INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, encounter_id, monster_id),
        FOREIGN KEY (campaign_id, encounter_id) REFERENCES play_campaign_encounters(campaign_id, id) ON DELETE CASCADE
      )
    `),
    // Stage 037: party member binding columns and unique index.
    () => database.exec("ALTER TABLE play_campaign_encounter_combatants ADD COLUMN member TEXT"),
    () => database.exec("ALTER TABLE play_campaign_encounter_combatants ADD COLUMN character_id TEXT"),
    () => database.exec("CREATE UNIQUE INDEX IF NOT EXISTS idx_play_campaign_encounter_combatants_member ON play_campaign_encounter_combatants(campaign_id, encounter_id, member)"),
    // Stage 038: encounter turn tracking columns.
    () => database.exec("ALTER TABLE play_campaign_encounters ADD COLUMN round INTEGER NOT NULL DEFAULT 1"),
    () => database.exec("ALTER TABLE play_campaign_encounters ADD COLUMN turn_index INTEGER NOT NULL DEFAULT 0"),
    // Stage 039: combat action target column.
    () => database.exec("ALTER TABLE play_campaign_narrations ADD COLUMN target TEXT"),
    // Stage 042: encounter conditions table.
    () => database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_encounter_conditions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        encounter_id TEXT NOT NULL,
        target TEXT NOT NULL,
        condition TEXT NOT NULL,
        remaining_rounds INTEGER NOT NULL,
        FOREIGN KEY (campaign_id, encounter_id) REFERENCES play_campaign_encounters(campaign_id, id) ON DELETE CASCADE
      )
    `),
    // Stage 043: encounter combatant order column.
    () => database.exec("ALTER TABLE play_campaign_encounters ADD COLUMN combatant_order TEXT"),
    // Stage 044: encounter reward and close columns.
    () => database.exec("ALTER TABLE play_campaign_encounters ADD COLUMN xp_awarded INTEGER NOT NULL DEFAULT 0"),
    () => database.exec("ALTER TABLE play_campaign_encounters ADD COLUMN loot_awarded TEXT NOT NULL DEFAULT '[]'"),
    () => database.exec("ALTER TABLE play_campaign_encounters ADD COLUMN rewards_awarded INTEGER NOT NULL DEFAULT 0"),
    () => database.exec("ALTER TABLE play_campaign_encounters ADD COLUMN closed INTEGER NOT NULL DEFAULT 0"),
    // Stage 045: campaign phase and pre-combat actor columns.
    () => database.exec("ALTER TABLE play_campaign_state ADD COLUMN phase TEXT NOT NULL DEFAULT 'exploration' CHECK(phase IN ('exploration', 'combat'))"),
    () => database.exec("ALTER TABLE play_campaign_state ADD COLUMN pre_combat_actor TEXT"),
    // Stage 046: character ownership column and backfill.
    () => database.exec("ALTER TABLE play_campaign_members ADD COLUMN owner TEXT"),
    () => database.exec("UPDATE play_campaign_members SET owner = username WHERE owner IS NULL"),
    // Stage 047: character build columns.
    () => database.exec("ALTER TABLE play_campaign_members ADD COLUMN race TEXT"),
    () => database.exec("ALTER TABLE play_campaign_members ADD COLUMN background TEXT"),
    () => database.exec("ALTER TABLE play_campaign_members ADD COLUMN abilities TEXT"),
    () => database.exec("ALTER TABLE play_campaign_members ADD COLUMN level INTEGER NOT NULL DEFAULT 1"),
  ];

  for (const migration of migrations) {
    try {
      migration();
    } catch {
      // Migration already applied or not needed.
    }
  }
}

/**
 * Drop and recreate all tables. Used by the storage reset endpoint.
 */
export function resetStorage(): void {
  const database = getDb();
  const tables = [
    "crafting_projects",
    "campaign_session_attendance",
    "campaign_session_agenda",
    "campaign_sessions",
    "campaign_equipment",
    "campaign_inventory",
    "conditions",
    "combatants",
    "combat_sessions",
    "campaign_npcs",
    "campaign_factions",
    "campaign_quest_milestones",
    "campaign_quests",
    "campaign_events",
    "campaign_characters",
    "campaigns",
    "users",
    "monster_tags",
    "monsters",
    "items",
    "schema_version",
    "play_campaign_encounter_conditions",
    "play_campaign_encounter_monsters",
    "play_campaign_encounter_combatants",
    "play_campaign_encounters",
    "play_campaign_location_connections",
    "play_campaign_locations",
    "play_campaign_documents",
    "play_campaign_narrations",
    "play_campaign_current_scene",
    "play_campaign_scenes",
    "play_campaign_members",
    "play_campaign_state",
    "play_campaigns",
  ];
  for (const table of tables) {
    database.exec(`DROP TABLE IF EXISTS ${table}`);
  }
  initialized = false;
  initStorage();
}

export function getSchemaVersion(): number {
  const database = getDb();
  const row = database.prepare("SELECT version FROM schema_version").get() as
    | { version: number }
    | undefined;
  return row?.version ?? 1;
}
