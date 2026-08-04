/**
 * SQLite persistence layer.  Owns the database connection, schema migration,
 * and all repository functions.  Business logic lives in `engine.ts`; this
 * module only reads and writes rows.
 */

import { DatabaseSync } from "node:sqlite";
import { join } from "node:path";

import type {
  Abilities,
  AddEncounterConditionResult,
  AdvanceCraftingResponse,
  Campaign,
  CampaignAnalyticsSummary,
  CharacterBuildInput,
  CampaignAudit,
  CampaignCharacter,
  CampaignDocument,
  CampaignEvent,
  CampaignExport,
  CampaignLocation,
  CampaignRiskReport,
  CampaignState,
  CharacterDamageResult,
  CombatSession,
  Condition,
  CraftingProject,
  CreateConnectionInput,
  CreateCraftingProjectInput,
  CreateFactionInput,
  CreateItemInput,
  CreateLocationInput,
  CreateMonsterInput,
  CreateNpcInput,
  CreatePlayCampaignEncounterInput,
  CreatePlayCampaignEncounterMonsterInput,
  CreatePlayCampaignInput,
  CreatePlayCampaignMembershipInput,
  CreateQuestInput,
  CreateSceneInput,
  CreateSessionInput,
  CreateUserResult,
  DeathSaveResult,
  EndEncounterResult,
  EncounterCloseResult,
  EncounterLoot,
  EncounterRewardRecord,
  EquipmentAssignment,
  Faction,
  GameSession,
  InventoryItem,
  InventorySummary,
  Item,
  LocationConnection,
  Monster,
  PlayCampaignEncounter,
  PlayCampaignEncounterMonster,
  PlayCampaignEncounterStatus,
  PlayCampaignEncounterTurn,
  PlayCampaignMemberState,
  PlayCampaignMemberStatus,
  PlayCampaignScene,
  PlayEvent,
  ResolutionResult,
  RestEvent,
  NextSession,
  Npc,
  NudgeResult,
  PlayCampaign,
  PlayCampaignMembership,
  PlayCampaignStartResult,
  PlayCampaignState,
  Quest,
  QuestCreateResult,
  QuestProgress,
  QuestStatus,
  QuestSummary,
  RelationshipSummary,
  SessionAttendance,
  SessionCombatant,
  SessionCreateResult,
  StoredUser,
  TravelDestination,
  TravelEvent,
} from "./types.js";

// Re-export every domain type so route handlers can import both storage
// functions and their input/output types from the same module.
export type * from "./types.js";

const DB_PATH = process.env.DB_PATH || join(process.cwd(), "game.db");

let db: DatabaseSync | null = null;
let initialized = false;

function ensureDb(): DatabaseSync {
  if (!db) {
    db = new DatabaseSync(DB_PATH);
    db.exec("PRAGMA foreign_keys = ON;");
  }
  return db;
}

export function getDb(): DatabaseSync {
  const database = ensureDb();
  if (!initialized) {
    initStorage();
  }
  return database;
}

export function isStorageInitialized(): boolean {
  return initialized;
}

export function initStorage(): void {
  const database = ensureDb();
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

  // Stage 027: ensure nudge_count column exists in existing databases.
  try {
    database.exec(
      "ALTER TABLE play_campaign_state ADD COLUMN nudge_count INTEGER NOT NULL DEFAULT 0"
    );
  } catch {
    // Column already present.
  }

  // Stage 033: ensure travel-related columns exist in existing databases.
  try {
    database.exec(
      "ALTER TABLE play_campaign_state ADD COLUMN current_location_id TEXT"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_narrations ADD COLUMN destination_id TEXT"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_narrations ADD COLUMN travel_turns INTEGER"
    );
  } catch {
    // Column already present.
  }

  // Stage 034: ensure character HP columns exist for rest turns.
  try {
    database.exec(
      "ALTER TABLE play_campaign_members ADD COLUMN hp_max INTEGER NOT NULL DEFAULT 20"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_members ADD COLUMN hp_current INTEGER NOT NULL DEFAULT 20"
    );
  } catch {
    // Column already present.
  }

  // Stage 041: ensure character death-save state columns exist.
  try {
    database.exec(
      "ALTER TABLE play_campaign_members ADD COLUMN status TEXT NOT NULL DEFAULT 'conscious' CHECK(status IN ('conscious', 'unconscious', 'stable', 'dead'))"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_members ADD COLUMN death_saves_successes INTEGER NOT NULL DEFAULT 0"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_members ADD COLUMN death_saves_failures INTEGER NOT NULL DEFAULT 0"
    );
  } catch {
    // Column already present.
  }

  // Stage 036: ensure encounter monster roster table exists.
  try {
    database.exec(`
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
    `);
  } catch {
    // Table already present.
  }

  // Stage 037: ensure party member binding columns and unique index exist.
  try {
    database.exec(
      "ALTER TABLE play_campaign_encounter_combatants ADD COLUMN member TEXT"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_encounter_combatants ADD COLUMN character_id TEXT"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "CREATE UNIQUE INDEX IF NOT EXISTS idx_play_campaign_encounter_combatants_member ON play_campaign_encounter_combatants(campaign_id, encounter_id, member)"
    );
  } catch {
    // Index already present.
  }

  // Stage 038: ensure encounter turn tracking columns exist.
  try {
    database.exec(
      "ALTER TABLE play_campaign_encounters ADD COLUMN round INTEGER NOT NULL DEFAULT 1"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_encounters ADD COLUMN turn_index INTEGER NOT NULL DEFAULT 0"
    );
  } catch {
    // Column already present.
  }

  // Stage 039: ensure combat action target column exists.
  try {
    database.exec(
      "ALTER TABLE play_campaign_narrations ADD COLUMN target TEXT"
    );
  } catch {
    // Column already present.
  }

  // Stage 042: ensure play campaign encounter conditions table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_encounter_conditions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        encounter_id TEXT NOT NULL,
        target TEXT NOT NULL,
        condition TEXT NOT NULL,
        remaining_rounds INTEGER NOT NULL,
        FOREIGN KEY (campaign_id, encounter_id) REFERENCES play_campaign_encounters(campaign_id, id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 043: ensure encounter combatant order column exists.
  try {
    database.exec(
      "ALTER TABLE play_campaign_encounters ADD COLUMN combatant_order TEXT"
    );
  } catch {
    // Column already present.
  }

  // Stage 044: ensure encounter reward and close columns exist.
  try {
    database.exec(
      "ALTER TABLE play_campaign_encounters ADD COLUMN xp_awarded INTEGER NOT NULL DEFAULT 0"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_encounters ADD COLUMN loot_awarded TEXT NOT NULL DEFAULT '[]'"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_encounters ADD COLUMN rewards_awarded INTEGER NOT NULL DEFAULT 0"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_encounters ADD COLUMN closed INTEGER NOT NULL DEFAULT 0"
    );
  } catch {
    // Column already present.
  }

  // Stage 045: ensure campaign phase and pre-combat actor columns exist.
  try {
    database.exec(
      "ALTER TABLE play_campaign_state ADD COLUMN phase TEXT NOT NULL DEFAULT 'exploration' CHECK(phase IN ('exploration', 'combat'))"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_state ADD COLUMN pre_combat_actor TEXT"
    );
  } catch {
    // Column already present.
  }

  // Stage 046: ensure character ownership column exists and backfill existing members.
  try {
    database.exec(
      "ALTER TABLE play_campaign_members ADD COLUMN owner TEXT"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "UPDATE play_campaign_members SET owner = username WHERE owner IS NULL"
    );
  } catch {
    // Backfill already applied or not needed.
  }

  // Stage 047: ensure character build columns exist.
  try {
    database.exec(
      "ALTER TABLE play_campaign_members ADD COLUMN race TEXT"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_members ADD COLUMN background TEXT"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_members ADD COLUMN abilities TEXT"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_members ADD COLUMN level INTEGER NOT NULL DEFAULT 1"
    );
  } catch {
    // Column already present.
  }

  initialized = true;
}

export function resetStorage(): void {
  const database = getDb();
  database.exec(`
    DROP TABLE IF EXISTS crafting_projects;
    DROP TABLE IF EXISTS campaign_session_attendance;
    DROP TABLE IF EXISTS campaign_session_agenda;
    DROP TABLE IF EXISTS campaign_sessions;
    DROP TABLE IF EXISTS campaign_equipment;
    DROP TABLE IF EXISTS campaign_inventory;
    DROP TABLE IF EXISTS conditions;
    DROP TABLE IF EXISTS combatants;
    DROP TABLE IF EXISTS combat_sessions;
    DROP TABLE IF EXISTS campaign_npcs;
    DROP TABLE IF EXISTS campaign_factions;
    DROP TABLE IF EXISTS campaign_quest_milestones;
    DROP TABLE IF EXISTS campaign_quests;
    DROP TABLE IF EXISTS campaign_events;
    DROP TABLE IF EXISTS campaign_characters;
    DROP TABLE IF EXISTS campaigns;
    DROP TABLE IF EXISTS users;
    DROP TABLE IF EXISTS monster_tags;
    DROP TABLE IF EXISTS monsters;
    DROP TABLE IF EXISTS items;
    DROP TABLE IF EXISTS schema_version;
    DROP TABLE IF EXISTS play_campaign_encounter_conditions;
    DROP TABLE IF EXISTS play_campaign_encounter_monsters;
    DROP TABLE IF EXISTS play_campaign_encounter_combatants;
    DROP TABLE IF EXISTS play_campaign_encounters;
    DROP TABLE IF EXISTS play_campaign_location_connections;
    DROP TABLE IF EXISTS play_campaign_locations;
    DROP TABLE IF EXISTS play_campaign_documents;
    DROP TABLE IF EXISTS play_campaign_narrations;
    DROP TABLE IF EXISTS play_campaign_current_scene;
    DROP TABLE IF EXISTS play_campaign_scenes;
    DROP TABLE IF EXISTS play_campaign_members;
    DROP TABLE IF EXISTS play_campaign_state;
    DROP TABLE IF EXISTS play_campaigns;
  `);
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

// ---------------------------------------------------------------------------
// Users
// ---------------------------------------------------------------------------

export function getUser(username: string): StoredUser | null {
  const database = getDb();
  const row = database
    .prepare("SELECT username, password_hash, role FROM users WHERE username = ?")
    .get(username) as
    | { username: string; password_hash: string; role: "dm" | "player" }
    | undefined;
  return row || null;
}

export function createUser(
  username: string,
  passwordHash: string,
  role: "dm" | "player"
): CreateUserResult | null {
  const database = getDb();
  try {
    database
      .prepare(
        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)"
      )
      .run(username, passwordHash, role);
    return { username, role };
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Combat sessions
// ---------------------------------------------------------------------------

export function getCombatSession(id: string): CombatSession | null {
  const database = getDb();
  const sessionRow = database
    .prepare("SELECT id, round, turn_index FROM combat_sessions WHERE id = ?")
    .get(id) as { id: string; round: number; turn_index: number } | undefined;
  if (!sessionRow) return null;

  const combatantRows = database
    .prepare(
      "SELECT id, name, score, dex, order_index FROM combatants WHERE session_id = ? ORDER BY order_index"
    )
    .all(id) as Array<{
    id: number;
    name: string;
    score: number;
    dex: number;
    order_index: number;
  }>;

  const combatants: SessionCombatant[] = combatantRows.map((row) => {
    const conditionRows = database
      .prepare(
        "SELECT condition, remaining_rounds FROM conditions WHERE combatant_id = ?"
      )
      .all(row.id) as Array<{ condition: string; remaining_rounds: number }>;
    return {
      name: row.name,
      score: row.score,
      dex: row.dex,
      conditions: conditionRows.map((c) => ({
        condition: c.condition,
        remaining_rounds: c.remaining_rounds,
      })),
    };
  });

  return {
    id: sessionRow.id,
    round: sessionRow.round,
    turn_index: sessionRow.turn_index,
    combatants,
  };
}

export function insertCombatSession(
  id: string,
  combatants: SessionCombatant[]
): boolean {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    database
      .prepare(
        "INSERT INTO combat_sessions (id, round, turn_index) VALUES (?, 1, 0)"
      )
      .run(id);
    for (let i = 0; i < combatants.length; i++) {
      const c = combatants[i];
      const result = database
        .prepare(
          "INSERT INTO combatants (session_id, name, score, dex, order_index) VALUES (?, ?, ?, ?, ?)"
        )
        .run(id, c.name, c.score, c.dex, i);
      const combatantId = result.lastInsertRowid as number;
      for (const cond of c.conditions) {
        database
          .prepare(
            "INSERT INTO conditions (combatant_id, condition, remaining_rounds) VALUES (?, ?, ?)"
          )
          .run(combatantId, cond.condition, cond.remaining_rounds);
      }
    }
    database.exec("COMMIT;");
    return true;
  } catch {
    database.exec("ROLLBACK;");
    return false;
  }
}

// ---------------------------------------------------------------------------
// Compendium
// ---------------------------------------------------------------------------

export function createMonster(input: CreateMonsterInput): Monster | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    database
      .prepare(
        "INSERT INTO monsters (slug, name, cr, armor_class, hit_points) VALUES (?, ?, ?, ?, ?)"
      )
      .run(input.slug, input.name, input.cr, input.armor_class, input.hit_points);
    const tagStmt = database.prepare(
      "INSERT INTO monster_tags (monster_slug, tag) VALUES (?, ?)"
    );
    for (const tag of input.tags) {
      tagStmt.run(input.slug, tag);
    }
    database.exec("COMMIT;");
    return {
      slug: input.slug,
      name: input.name,
      cr: input.cr,
      armor_class: input.armor_class,
      hit_points: input.hit_points,
      tags: input.tags,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getMonster(slug: string): Monster | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT slug, name, cr, armor_class, hit_points FROM monsters WHERE slug = ?"
    )
    .get(slug) as
    | { slug: string; name: string; cr: string; armor_class: number; hit_points: number }
    | undefined;
  if (!row) return null;

  const tagRows = database
    .prepare("SELECT tag FROM monster_tags WHERE monster_slug = ? ORDER BY id")
    .all(slug) as Array<{ tag: string }>;

  return {
    ...row,
    tags: tagRows.map((r) => r.tag),
  };
}

export function createItem(input: CreateItemInput): Item | null {
  const database = getDb();
  try {
    database
      .prepare(
        "INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)"
      )
      .run(input.slug, input.name, input.type, input.rarity, input.cost_gp);
    return { ...input };
  } catch {
    return null;
  }
}

export function getItem(slug: string): Item | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?"
    )
    .get(slug) as
    | { slug: string; name: string; type: string; rarity: string; cost_gp: number }
    | undefined;
  return row || null;
}

/**
 * Replaces the stored combatants and conditions for a session with the current
 * in-memory state.  This is intentionally a full rewrite rather than an UPDATE
 * because conditions are owned by combatants and the simplest deterministic path
 * is to delete and reinsert.
 */
export function replaceCombatSession(session: CombatSession): void {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    database
      .prepare(
        "UPDATE combat_sessions SET round = ?, turn_index = ? WHERE id = ?"
      )
      .run(session.round, session.turn_index, session.id);
    database
      .prepare(
        "DELETE FROM conditions WHERE combatant_id IN (SELECT id FROM combatants WHERE session_id = ?)"
      )
      .run(session.id);
    database
      .prepare("DELETE FROM combatants WHERE session_id = ?")
      .run(session.id);
    for (let i = 0; i < session.combatants.length; i++) {
      const c = session.combatants[i];
      const result = database
        .prepare(
          "INSERT INTO combatants (session_id, name, score, dex, order_index) VALUES (?, ?, ?, ?, ?)"
        )
        .run(session.id, c.name, c.score, c.dex, i);
      const combatantId = result.lastInsertRowid as number;
      for (const cond of c.conditions) {
        database
          .prepare(
            "INSERT INTO conditions (combatant_id, condition, remaining_rounds) VALUES (?, ?, ?)"
          )
          .run(combatantId, cond.condition, cond.remaining_rounds);
      }
    }
    database.exec("COMMIT;");
  } catch (e) {
    database.exec("ROLLBACK;");
    throw e;
  }
}

// ---------------------------------------------------------------------------
// Campaigns
// ---------------------------------------------------------------------------

export function createCampaign(input: Campaign): Campaign | null {
  const database = getDb();
  try {
    database
      .prepare("INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)")
      .run(input.id, input.name, input.dm);
    return { ...input };
  } catch {
    return null;
  }
}

export function getCampaign(id: string): Campaign | null {
  const database = getDb();
  const row = database
    .prepare("SELECT id, name, dm FROM campaigns WHERE id = ?")
    .get(id) as { id: string; name: string; dm: string } | undefined;
  return row || null;
}

export function createCampaignCharacter(
  campaignId: string,
  input: CampaignCharacter
): CampaignCharacter | null {
  const database = getDb();
  try {
    database
      .prepare(
        "INSERT INTO campaign_characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)"
      )
      .run(input.id, campaignId, input.name, input.level, input.class);
    return { ...input };
  } catch {
    return null;
  }
}

export function getCampaignCharacters(campaignId: string): CampaignCharacter[] {
  const database = getDb();
  const rows = database
    .prepare(
      "SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY id"
    )
    .all(campaignId) as Array<{
    id: string;
    name: string;
    level: number;
    class: string;
  }>;
  return rows;
}

export function createCampaignEvent(
  campaignId: string,
  input: CampaignEvent
): CampaignEvent | null {
  const database = getDb();
  try {
    database
      .prepare(
        "INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)"
      )
      .run(input.id, campaignId, input.kind, input.summary);
    return { ...input };
  } catch {
    return null;
  }
}

export function getCampaignEventCount(campaignId: string): number {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_events WHERE campaign_id = ?"
    )
    .get(campaignId) as { count: number } | undefined;
  return row?.count ?? 0;
}

export function getLatestCampaignEvent(
  campaignId: string
): CampaignEvent | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT id, kind, summary FROM campaign_events WHERE campaign_id = ? ORDER BY id DESC LIMIT 1"
    )
    .get(campaignId) as
    | { id: string; kind: string; summary: string }
    | undefined;
  return row || null;
}

export function getCampaignState(id: string): CampaignState | null {
  const campaign = getCampaign(id);
  if (!campaign) return null;

  return {
    id: campaign.id,
    name: campaign.name,
    dm: campaign.dm,
    characters: getCampaignCharacters(id),
    log_count: getCampaignEventCount(id),
  };
}

// ---------------------------------------------------------------------------
// Quests
// ---------------------------------------------------------------------------

export function isValidQuestStatus(status: unknown): status is QuestStatus {
  return status === "active" || status === "completed" || status === "blocked";
}

export function createQuest(
  campaignId: string,
  input: CreateQuestInput
): QuestCreateResult | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    database
      .prepare(
        "INSERT INTO campaign_quests (id, campaign_id, title, status) VALUES (?, ?, ?, ?)"
      )
      .run(input.id, campaignId, input.title, input.status);
    const milestoneStmt = database.prepare(
      "INSERT INTO campaign_quest_milestones (quest_id, title, done) VALUES (?, ?, 0)"
    );
    for (const title of input.milestones) {
      milestoneStmt.run(input.id, title);
    }
    database.exec("COMMIT;");
    return {
      id: input.id,
      title: input.title,
      status: input.status,
      milestones_total: input.milestones.length,
      milestones_done: 0,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getQuest(campaignId: string, questId: string): Quest | null {
  const database = getDb();
  const questRow = database
    .prepare(
      "SELECT id, campaign_id, title, status FROM campaign_quests WHERE id = ? AND campaign_id = ?"
    )
    .get(questId, campaignId) as
    | { id: string; campaign_id: string; title: string; status: QuestStatus }
    | undefined;
  if (!questRow) return null;

  const milestoneRows = database
    .prepare(
      "SELECT title, done FROM campaign_quest_milestones WHERE quest_id = ? ORDER BY id"
    )
    .all(questId) as Array<{ title: string; done: number }>;

  return {
    ...questRow,
    milestones: milestoneRows.map((m) => ({ title: m.title, done: !!m.done })),
  };
}

export function updateQuestProgress(
  campaignId: string,
  questId: string,
  completed: string[]
): QuestProgress | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const questRow = database
      .prepare(
        "SELECT id, status FROM campaign_quests WHERE id = ? AND campaign_id = ?"
      )
      .get(questId, campaignId) as
      | { id: string; status: QuestStatus }
      | undefined;
    if (!questRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    const milestoneRows = database
      .prepare(
        "SELECT title, done FROM campaign_quest_milestones WHERE quest_id = ?"
      )
      .all(questId) as Array<{ title: string; done: number }>;
    const milestoneSet = new Set(milestoneRows.map((m) => m.title));
    for (const title of completed) {
      if (!milestoneSet.has(title)) {
        database.exec("ROLLBACK;");
        return null;
      }
    }

    const updateStmt = database.prepare(
      "UPDATE campaign_quest_milestones SET done = 1 WHERE quest_id = ? AND title = ?"
    );
    for (const title of completed) {
      updateStmt.run(questId, title);
    }

    const total = milestoneRows.length;
    const doneRow = database
      .prepare(
        "SELECT COUNT(*) AS count FROM campaign_quest_milestones WHERE quest_id = ? AND done = 1"
      )
      .get(questId) as { count: number };
    const done = doneRow.count;

    let status = questRow.status;
    if (total > 0 && done === total) {
      status = "completed";
      database
        .prepare("UPDATE campaign_quests SET status = 'completed' WHERE id = ?")
        .run(questId);
    }

    database.exec("COMMIT;");
    return { id: questId, status, milestones_total: total, milestones_done: done };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getQuestSummary(campaignId: string): QuestSummary | null {
  if (!getCampaign(campaignId)) return null;

  const database = getDb();
  const rows = database
    .prepare(
      "SELECT status, COUNT(*) AS count FROM campaign_quests WHERE campaign_id = ? GROUP BY status"
    )
    .all(campaignId) as Array<{ status: QuestStatus; count: number }>;

  const summary: QuestSummary = {
    campaign_id: campaignId,
    active: 0,
    completed: 0,
    blocked: 0,
  };
  for (const row of rows) {
    if (row.status === "active") summary.active = row.count;
    else if (row.status === "completed") summary.completed = row.count;
    else if (row.status === "blocked") summary.blocked = row.count;
  }
  return summary;
}

// ---------------------------------------------------------------------------
// Factions & NPCs
// ---------------------------------------------------------------------------

export function createFaction(
  campaignId: string,
  input: CreateFactionInput
): Faction | null {
  const database = getDb();
  try {
    database
      .prepare(
        "INSERT INTO campaign_factions (id, campaign_id, name, stance) VALUES (?, ?, ?, ?)"
      )
      .run(input.id, campaignId, input.name, input.stance);
    return { ...input };
  } catch {
    return null;
  }
}

export function getFaction(campaignId: string, factionId: string): Faction | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT id, name, stance FROM campaign_factions WHERE id = ? AND campaign_id = ?"
    )
    .get(factionId, campaignId) as
    | { id: string; name: string; stance: string }
    | undefined;
  return row || null;
}

export function createNpc(
  campaignId: string,
  input: CreateNpcInput
): Npc | null {
  const database = getDb();
  try {
    database
      .prepare(
        "INSERT INTO campaign_npcs (id, campaign_id, name, faction_id, disposition) VALUES (?, ?, ?, ?, ?)"
      )
      .run(input.id, campaignId, input.name, input.faction_id, input.disposition);
    return { ...input };
  } catch {
    return null;
  }
}

export function getRelationshipSummary(
  campaignId: string
): RelationshipSummary | null {
  if (!getCampaign(campaignId)) return null;

  const database = getDb();
  const factionRow = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_factions WHERE campaign_id = ?"
    )
    .get(campaignId) as { count: number };
  const npcRow = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_npcs WHERE campaign_id = ?"
    )
    .get(campaignId) as { count: number };
  const friendlyRow = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_npcs WHERE campaign_id = ? AND disposition > 0"
    )
    .get(campaignId) as { count: number };

  return {
    campaign_id: campaignId,
    factions: factionRow.count,
    npcs: npcRow.count,
    friendly_npcs: friendlyRow.count,
  };
}

// ---------------------------------------------------------------------------
// Inventory & equipment
// ---------------------------------------------------------------------------

export function addCampaignInventoryItem(
  campaignId: string,
  item: InventoryItem
): InventoryItem | null {
  const database = getDb();
  if (!getCampaign(campaignId)) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const existing = database
      .prepare(
        "SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?"
      )
      .get(campaignId, item.item_slug, item.owner) as
      | { quantity: number }
      | undefined;

    if (existing) {
      const total = existing.quantity + item.quantity;
      database
        .prepare(
          "UPDATE campaign_inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = ?"
        )
        .run(total, campaignId, item.item_slug, item.owner);
      database.exec("COMMIT;");
      return { item_slug: item.item_slug, owner: item.owner, quantity: total };
    }

    database
      .prepare(
        "INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES (?, ?, ?, ?)"
      )
      .run(campaignId, item.item_slug, item.owner, item.quantity);
    database.exec("COMMIT;");
    return { ...item };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function assignEquipment(
  campaignId: string,
  characterId: string,
  item: { item_slug: string; quantity: number }
): EquipmentAssignment | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    if (!getCampaign(campaignId)) {
      database.exec("ROLLBACK;");
      return null;
    }

    const charRow = database
      .prepare(
        "SELECT id FROM campaign_characters WHERE id = ? AND campaign_id = ?"
      )
      .get(characterId, campaignId) as { id: string } | undefined;
    if (!charRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    const partyItem = database
      .prepare(
        "SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = 'party'"
      )
      .get(campaignId, item.item_slug) as { quantity: number } | undefined;
    if (!partyItem || partyItem.quantity < item.quantity || item.quantity <= 0) {
      database.exec("ROLLBACK;");
      return null;
    }

    const remaining = partyItem.quantity - item.quantity;
    if (remaining > 0) {
      database
        .prepare(
          "UPDATE campaign_inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = 'party'"
        )
        .run(remaining, campaignId, item.item_slug);
    } else {
      database
        .prepare(
          "DELETE FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = 'party'"
        )
        .run(campaignId, item.item_slug);
    }

    const existing = database
      .prepare(
        "SELECT quantity FROM campaign_equipment WHERE campaign_id = ? AND character_id = ? AND item_slug = ?"
      )
      .get(campaignId, characterId, item.item_slug) as
      | { quantity: number }
      | undefined;

    if (existing) {
      const total = existing.quantity + item.quantity;
      database
        .prepare(
          "UPDATE campaign_equipment SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_slug = ?"
        )
        .run(total, campaignId, characterId, item.item_slug);
      database.exec("COMMIT;");
      return {
        character_id: characterId,
        item_slug: item.item_slug,
        quantity: total,
      };
    }

    database
      .prepare(
        "INSERT INTO campaign_equipment (campaign_id, character_id, item_slug, quantity) VALUES (?, ?, ?, ?)"
      )
      .run(campaignId, characterId, item.item_slug, item.quantity);
    database.exec("COMMIT;");
    return {
      character_id: characterId,
      item_slug: item.item_slug,
      quantity: item.quantity,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getInventorySummary(
  campaignId: string
): InventorySummary | null {
  if (!getCampaign(campaignId)) return null;

  const database = getDb();
  const partyRow = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_inventory WHERE campaign_id = ? AND owner = 'party'"
    )
    .get(campaignId) as { count: number };
  const assignedRow = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_equipment WHERE campaign_id = ?"
    )
    .get(campaignId) as { count: number };
  const potionRow = database
    .prepare(
      "SELECT COALESCE(SUM(quantity), 0) AS count FROM campaign_inventory WHERE campaign_id = ? AND item_slug = 'healing-potion' AND owner = 'party'"
    )
    .get(campaignId) as { count: number };

  return {
    campaign_id: campaignId,
    party_items: partyRow.count,
    assigned_items: assignedRow.count,
    healing_potions_available: potionRow.count,
  };
}

// ---------------------------------------------------------------------------
// Downtime crafting
// ---------------------------------------------------------------------------

export function createCraftingProject(
  campaignId: string,
  input: CreateCraftingProjectInput
): CraftingProject | null {
  const database = getDb();

  if (!getCampaign(campaignId)) return null;

  const charRow = database
    .prepare(
      "SELECT id FROM campaign_characters WHERE id = ? AND campaign_id = ?"
    )
    .get(input.character_id, campaignId) as { id: string } | undefined;
  if (!charRow) return null;

  try {
    database
      .prepare(
        "INSERT INTO crafting_projects (id, campaign_id, character_id, item_slug, days_required, days_completed, cost_gp, status) VALUES (?, ?, ?, ?, ?, 0, ?, 'active')"
      )
      .run(
        input.id,
        campaignId,
        input.character_id,
        input.item_slug,
        input.days_required,
        input.cost_gp
      );
    return {
      id: input.id,
      campaign_id: campaignId,
      character_id: input.character_id,
      item_slug: input.item_slug,
      days_required: input.days_required,
      days_completed: 0,
      cost_gp: input.cost_gp,
      status: "active",
    };
  } catch {
    return null;
  }
}

export function getCraftingProject(
  campaignId: string,
  projectId: string
): CraftingProject | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT id, campaign_id, character_id, item_slug, days_required, days_completed, cost_gp, status FROM crafting_projects WHERE id = ? AND campaign_id = ?"
    )
    .get(projectId, campaignId) as
    | {
        id: string;
        campaign_id: string;
        character_id: string;
        item_slug: string;
        days_required: number;
        days_completed: number;
        cost_gp: number;
        status: "active" | "complete";
      }
    | undefined;
  return row || null;
}

export function advanceCraftingProject(
  campaignId: string,
  projectId: string,
  days: number
): AdvanceCraftingResponse | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT id, character_id, item_slug, days_required, days_completed, status FROM crafting_projects WHERE id = ? AND campaign_id = ?"
      )
      .get(projectId, campaignId) as
      | {
          id: string;
          character_id: string;
          item_slug: string;
          days_required: number;
          days_completed: number;
          status: "active" | "complete";
        }
      | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return null;
    }

    if (row.status === "complete") {
      database.exec("COMMIT;");
      return {
        id: row.id,
        days_completed: row.days_completed,
        status: "complete",
      };
    }

    const newDaysCompleted = Math.min(
      row.days_completed + days,
      row.days_required
    );
    const newStatus: "active" | "complete" =
      newDaysCompleted >= row.days_required ? "complete" : "active";

    database
      .prepare(
        "UPDATE crafting_projects SET days_completed = ?, status = ? WHERE id = ?"
      )
      .run(newDaysCompleted, newStatus, projectId);

    if (newStatus === "complete") {
      const existing = database
        .prepare(
          "SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = 'party'"
        )
        .get(campaignId, row.item_slug) as { quantity: number } | undefined;

      if (existing) {
        database
          .prepare(
            "UPDATE campaign_inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = 'party'"
          )
          .run(existing.quantity + 1, campaignId, row.item_slug);
      } else {
        database
          .prepare(
            "INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES (?, ?, 'party', 1)"
          )
          .run(campaignId, row.item_slug);
      }
    }

    database.exec("COMMIT;");
    return {
      id: row.id,
      days_completed: newDaysCompleted,
      status: newStatus,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------

export function createSession(
  campaignId: string,
  input: CreateSessionInput
): SessionCreateResult | null {
  const database = getDb();
  if (!getCampaign(campaignId)) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    database
      .prepare(
        "INSERT INTO campaign_sessions (id, campaign_id, starts_at, duration_minutes) VALUES (?, ?, ?, ?)"
      )
      .run(input.id, campaignId, input.starts_at, input.duration_minutes);

    const agendaStmt = database.prepare(
      "INSERT INTO campaign_session_agenda (session_id, item, order_index) VALUES (?, ?, ?)"
    );
    for (let i = 0; i < input.agenda.length; i++) {
      agendaStmt.run(input.id, input.agenda[i], i);
    }

    database.exec("COMMIT;");
    return {
      id: input.id,
      starts_at: input.starts_at,
      duration_minutes: input.duration_minutes,
      agenda_count: input.agenda.length,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getSession(
  campaignId: string,
  sessionId: string
): GameSession | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT id, campaign_id, starts_at, duration_minutes FROM campaign_sessions WHERE id = ? AND campaign_id = ?"
    )
    .get(sessionId, campaignId) as
    | {
        id: string;
        campaign_id: string;
        starts_at: string;
        duration_minutes: number;
      }
    | undefined;
  if (!row) return null;

  const agendaRows = database
    .prepare(
      "SELECT item FROM campaign_session_agenda WHERE session_id = ? ORDER BY order_index"
    )
    .all(sessionId) as Array<{ item: string }>;

  return {
    ...row,
    agenda: agendaRows.map((r) => r.item),
  };
}

export function recordAttendance(
  campaignId: string,
  sessionId: string,
  present: string[],
  absent: string[]
): SessionAttendance | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const sessionRow = database
      .prepare(
        "SELECT id FROM campaign_sessions WHERE id = ? AND campaign_id = ?"
      )
      .get(sessionId, campaignId) as { id: string } | undefined;
    if (!sessionRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    database
      .prepare("DELETE FROM campaign_session_attendance WHERE session_id = ?")
      .run(sessionId);

    const presentSet = new Set(present);
    const absentSet = new Set(absent.filter((a) => !presentSet.has(a)));

    const insertStmt = database.prepare(
      "INSERT INTO campaign_session_attendance (session_id, character_id, present) VALUES (?, ?, ?)"
    );
    for (const characterId of presentSet) {
      insertStmt.run(sessionId, characterId, 1);
    }
    for (const characterId of absentSet) {
      insertStmt.run(sessionId, characterId, 0);
    }

    database.exec("COMMIT;");
    return {
      session_id: sessionId,
      present_count: presentSet.size,
      absent_count: absentSet.size,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getNextSession(campaignId: string): NextSession | null {
  if (!getCampaign(campaignId)) return null;

  const database = getDb();
  const row = database
    .prepare(
      "SELECT id, starts_at FROM campaign_sessions WHERE campaign_id = ? ORDER BY starts_at ASC, id ASC LIMIT 1"
    )
    .get(campaignId) as { id: string; starts_at: string } | undefined;
  if (!row) return null;

  const agendaRow = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_session_agenda WHERE session_id = ?"
    )
    .get(row.id) as { count: number };

  return {
    id: row.id,
    starts_at: row.starts_at,
    agenda_count: agendaRow.count,
  };
}

// ---------------------------------------------------------------------------
// Analytics, audit, and export
// ---------------------------------------------------------------------------

export function getCampaignAudit(campaignId: string): CampaignAudit | null {
  const campaign = getCampaign(campaignId);
  if (!campaign) return null;

  const database = getDb();
  const events = database
    .prepare("SELECT COUNT(*) AS count FROM campaign_events WHERE campaign_id = ?")
    .get(campaignId) as { count: number };
  const quests = database
    .prepare("SELECT COUNT(*) AS count FROM campaign_quests WHERE campaign_id = ?")
    .get(campaignId) as { count: number };
  const npcs = database
    .prepare("SELECT COUNT(*) AS count FROM campaign_npcs WHERE campaign_id = ?")
    .get(campaignId) as { count: number };
  const sessions = database
    .prepare("SELECT COUNT(*) AS count FROM campaign_sessions WHERE campaign_id = ?")
    .get(campaignId) as { count: number };

  return {
    campaign_id: campaignId,
    events: events.count,
    quests: quests.count,
    npcs: npcs.count,
    sessions: sessions.count,
  };
}

export function getCampaignExport(campaignId: string): CampaignExport | null {
  const campaign = getCampaign(campaignId);
  if (!campaign) return null;

  const database = getDb();
  const characters = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_characters WHERE campaign_id = ?"
    )
    .get(campaignId) as { count: number };
  const quests = database
    .prepare("SELECT COUNT(*) AS count FROM campaign_quests WHERE campaign_id = ?")
    .get(campaignId) as { count: number };
  const npcs = database
    .prepare("SELECT COUNT(*) AS count FROM campaign_npcs WHERE campaign_id = ?")
    .get(campaignId) as { count: number };
  const inventoryItems = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_inventory WHERE campaign_id = ?"
    )
    .get(campaignId) as { count: number };
  const sessions = database
    .prepare("SELECT COUNT(*) AS count FROM campaign_sessions WHERE campaign_id = ?")
    .get(campaignId) as { count: number };

  return {
    campaign_id: campaignId,
    name: campaign.name,
    characters: characters.count,
    quests: quests.count,
    npcs: npcs.count,
    inventory_items: inventoryItems.count,
    sessions: sessions.count,
    schema_version: getSchemaVersion(),
  };
}

export function getCampaignAnalyticsSummary(
  campaignId: string
): CampaignAnalyticsSummary | null {
  const campaign = getCampaign(campaignId);
  if (!campaign) return null;

  const database = getDb();
  const openQuests = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_quests WHERE campaign_id = ? AND status = 'active'"
    )
    .get(campaignId) as { count: number };
  const friendlyNpcs = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_npcs WHERE campaign_id = ? AND disposition > 0"
    )
    .get(campaignId) as { count: number };
  const sessions = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_sessions WHERE campaign_id = ?"
    )
    .get(campaignId) as { count: number };
  const inventory = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_inventory WHERE campaign_id = ?"
    )
    .get(campaignId) as { count: number };
  const characters = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_characters WHERE campaign_id = ?"
    )
    .get(campaignId) as { count: number };

  const hasDm = campaign.dm.length > 0;
  const hasCharacters = characters.count > 0;
  const hasNextSession = sessions.count > 0;
  const hasActiveQuest = openQuests.count > 0;

  const readinessScore =
    (hasDm ? 25 : 0) +
    (hasCharacters ? 20 : 0) +
    (hasNextSession ? 20 : 0) +
    (hasActiveQuest ? 20 : 0);

  return {
    campaign_id: campaignId,
    readiness_score: readinessScore,
    open_quests: openQuests.count,
    friendly_npcs: friendlyNpcs.count,
    scheduled_sessions: sessions.count,
    inventory_items: inventory.count,
  };
}

export function getCampaignRiskReport(
  campaignId: string
): CampaignRiskReport | null {
  const campaign = getCampaign(campaignId);
  if (!campaign) return null;

  const database = getDb();
  const characters = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_characters WHERE campaign_id = ?"
    )
    .get(campaignId) as { count: number };
  const sessions = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_sessions WHERE campaign_id = ?"
    )
    .get(campaignId) as { count: number };
  const activeQuests = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_quests WHERE campaign_id = ? AND status = 'active'"
    )
    .get(campaignId) as { count: number };

  const hasDm = campaign.dm.length > 0;
  const hasCharacters = characters.count > 0;
  const hasNextSession = sessions.count > 0;
  const hasActiveQuest = activeQuests.count > 0;

  const missing: string[] = [];
  if (!hasDm) missing.push("dm");
  if (!hasCharacters) missing.push("characters");
  if (!hasNextSession) missing.push("next_session");
  if (!hasActiveQuest) missing.push("active_quest");

  let riskLevel: CampaignRiskReport["risk_level"];
  switch (missing.length) {
    case 0:
    case 1:
      riskLevel = "low";
      break;
    case 2:
      riskLevel = "medium";
      break;
    case 3:
      riskLevel = "high";
      break;
    default:
      riskLevel = "critical";
  }

  return {
    campaign_id: campaignId,
    risk_level: riskLevel,
    missing,
    signals: {
      has_dm: hasDm,
      has_characters: hasCharacters,
      has_next_session: hasNextSession,
      has_active_quest: hasActiveQuest,
    },
  };
}

// ---------------------------------------------------------------------------
// Play campaigns (turn-based cooperative play)
// ---------------------------------------------------------------------------

export function createPlayCampaign(
  input: CreatePlayCampaignInput & { owner: string }
): PlayCampaign | null {
  const database = getDb();
  try {
    database
      .prepare(
        "INSERT INTO play_campaigns (id, name, owner, status, max_players) VALUES (?, ?, ?, 'lobby', ?)"
      )
      .run(input.id, input.name, input.owner, input.max_players);
    return {
      id: input.id,
      name: input.name,
      owner: input.owner,
      status: "lobby",
      max_players: input.max_players,
    };
  } catch {
    return null;
  }
}

export function getPlayCampaign(id: string): PlayCampaign | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT id, name, owner, status, max_players FROM play_campaigns WHERE id = ?"
    )
    .get(id) as
    | {
        id: string;
        name: string;
        owner: string;
        status: "lobby";
        max_players: number;
      }
    | undefined;
  return row || null;
}

export function createPlayCampaignMembership(
  campaignId: string,
  username: string,
  input: CreatePlayCampaignMembershipInput
): PlayCampaignMembership | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const countRow = database
      .prepare(
        "SELECT COUNT(*) AS count FROM play_campaign_members WHERE campaign_id = ?"
      )
      .get(campaignId) as { count: number };
    if (countRow.count >= campaign.max_players) {
      database.exec("ROLLBACK;");
      return null;
    }

    database
      .prepare(
        "INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class, owner) VALUES (?, ?, ?, ?, ?, ?)"
      )
      .run(campaignId, username, input.character_id, input.name, input.class, username);

    database.exec("COMMIT;");
    return {
      username,
      character_id: input.character_id,
      name: input.name,
      class: input.class,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getPlayCampaignMembers(
  campaignId: string
): PlayCampaignMembership[] {
  const database = getDb();
  const rows = database
    .prepare(
      "SELECT username, character_id, name, class FROM play_campaign_members WHERE campaign_id = ? ORDER BY username ASC"
    )
    .all(campaignId) as Array<{
    username: string;
    character_id: string;
    name: string;
    class: string;
  }>;
  return rows;
}

export function getCharacterOwner(
  campaignId: string,
  characterId: string
): { character_id: string; owner: string | null } | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT character_id, owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
    )
    .get(campaignId, characterId) as
    | { character_id: string; owner: string | null }
    | undefined;
  return row || null;
}

export function getCharacterLevelUpState(
  campaignId: string,
  characterId: string
): { class: string; abilities: Abilities; level: number; hp_max: number } | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT class, abilities, level, hp_max FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
    )
    .get(campaignId, characterId) as
    | {
        class: string;
        abilities: string | null;
        level: number;
        hp_max: number;
      }
    | undefined;
  if (!row) return null;
  if (!row.abilities) return null;

  let abilities: Abilities;
  try {
    abilities = JSON.parse(row.abilities) as Abilities;
  } catch {
    return null;
  }

  const abilityKeys: (keyof Abilities)[] = ["str", "dex", "con", "int", "wis", "cha"];
  for (const key of abilityKeys) {
    if (!Number.isInteger(abilities[key]) || abilities[key] < 1 || abilities[key] > 30) {
      return null;
    }
  }

  return {
    class: row.class,
    abilities,
    level: row.level,
    hp_max: row.hp_max,
  };
}

export function levelUpCharacter(
  campaignId: string,
  characterId: string,
  newLevel: number,
  newHpMax: number
): boolean {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, characterId) as { 1: number } | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return false;
    }

    database
      .prepare(
        "UPDATE play_campaign_members SET level = ?, hp_max = ? WHERE campaign_id = ? AND character_id = ?"
      )
      .run(newLevel, newHpMax, campaignId, characterId);

    database.exec("COMMIT;");
    return true;
  } catch {
    database.exec("ROLLBACK;");
    return false;
  }
}

export function updateCharacterBuild(
  campaignId: string,
  characterId: string,
  input: CharacterBuildInput
): boolean {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, characterId) as { 1: number } | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return false;
    }

    database
      .prepare(
        "UPDATE play_campaign_members SET race = ?, class = ?, background = ?, abilities = ?, level = ?, hp_max = ?, hp_current = ? WHERE campaign_id = ? AND character_id = ?"
      )
      .run(
        input.race,
        input.class,
        input.background,
        JSON.stringify(input.abilities),
        input.level,
        input.hp_max,
        input.hp_max,
        campaignId,
        characterId
      );

    database.exec("COMMIT;");
    return true;
  } catch {
    database.exec("ROLLBACK;");
    return false;
  }
}

export type ClaimCharacterResult =
  | { character_id: string; owner: string }
  | "conflict"
  | null;

export function claimCharacter(
  campaignId: string,
  characterId: string,
  username: string
): ClaimCharacterResult {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, characterId) as { owner: string | null } | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return null;
    }
    if (row.owner && row.owner !== username) {
      database.exec("ROLLBACK;");
      return "conflict";
    }
    if (!row.owner) {
      database
        .prepare(
          "UPDATE play_campaign_members SET owner = ? WHERE campaign_id = ? AND character_id = ?"
        )
        .run(username, campaignId, characterId);
    }
    database.exec("COMMIT;");
    return { character_id: characterId, owner: username };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export type TransferCharacterResult =
  | { character_id: string; owner: string }
  | "not_owner"
  | "not_member"
  | null;

export function transferCharacter(
  campaignId: string,
  characterId: string,
  newOwner: string,
  currentOwner: string
): TransferCharacterResult {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, characterId) as { owner: string | null } | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return null;
    }
    if (row.owner !== currentOwner) {
      database.exec("ROLLBACK;");
      return "not_owner";
    }
    const member = database
      .prepare(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?"
      )
      .get(campaignId, newOwner) as { 1: number } | undefined;
    if (!member) {
      database.exec("ROLLBACK;");
      return "not_member";
    }
    database
      .prepare(
        "UPDATE play_campaign_members SET owner = ? WHERE campaign_id = ? AND character_id = ?"
      )
      .run(newOwner, campaignId, characterId);
    database.exec("COMMIT;");
    return { character_id: characterId, owner: newOwner };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getPlayCampaignMemberState(
  campaignId: string,
  characterId: string
): PlayCampaignMemberState | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT username, character_id, name, class, hp_current, hp_max, status, death_saves_successes, death_saves_failures FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
    )
    .get(campaignId, characterId) as
    | {
        username: string;
        character_id: string;
        name: string;
        class: string;
        hp_current: number;
        hp_max: number;
        status: PlayCampaignMemberStatus;
        death_saves_successes: number;
        death_saves_failures: number;
      }
    | undefined;
  if (!row) return null;
  return {
    campaign_id: campaignId,
    username: row.username,
    character_id: row.character_id,
    name: row.name,
    class: row.class,
    hp_current: row.hp_current,
    hp_max: row.hp_max,
    status: row.status,
    death_saves_successes: row.death_saves_successes,
    death_saves_failures: row.death_saves_failures,
  };
}

export function applyDamageToCharacter(
  campaignId: string,
  characterId: string,
  amount: number
): CharacterDamageResult | null {
  if (amount <= 0) return null;

  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT hp_current, status, death_saves_successes, death_saves_failures FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, characterId) as
      | {
          hp_current: number;
          status: PlayCampaignMemberStatus;
          death_saves_successes: number;
          death_saves_failures: number;
        }
      | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return null;
    }

    const hp_before = row.hp_current;
    const hp_after = Math.max(0, hp_before - amount);
    let status = row.status;
    let successes = row.death_saves_successes;
    let failures = row.death_saves_failures;

    if (hp_before > 0 && hp_after === 0) {
      status = "unconscious";
      successes = 0;
      failures = 0;
    }

    database
      .prepare(
        "UPDATE play_campaign_members SET hp_current = ?, status = ?, death_saves_successes = ?, death_saves_failures = ? WHERE campaign_id = ? AND character_id = ?"
      )
      .run(hp_after, status, successes, failures, campaignId, characterId);

    database.exec("COMMIT;");
    return {
      character_id: characterId,
      target: characterId,
      hp_before,
      hp_after,
      damage: amount,
      status,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function recordDeathSave(
  campaignId: string,
  characterId: string,
  outcome: "success" | "failure"
): DeathSaveResult | null {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT status, death_saves_successes, death_saves_failures FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, characterId) as
      | {
          status: PlayCampaignMemberStatus;
          death_saves_successes: number;
          death_saves_failures: number;
        }
      | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return null;
    }
    if (row.status !== "unconscious") {
      database.exec("ROLLBACK;");
      return null;
    }

    let status: PlayCampaignMemberStatus = "unconscious";
    let successes = row.death_saves_successes;
    let failures = row.death_saves_failures;

    if (outcome === "success") {
      successes += 1;
      if (successes >= 3) {
        status = "stable";
      }
    } else {
      failures += 1;
      if (failures >= 3) {
        status = "dead";
      }
    }

    database
      .prepare(
        "UPDATE play_campaign_members SET status = ?, death_saves_successes = ?, death_saves_failures = ? WHERE campaign_id = ? AND character_id = ?"
      )
      .run(status, successes, failures, campaignId, characterId);

    database.exec("COMMIT;");
    return {
      character_id: characterId,
      successes,
      failures,
      status,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function startPlayCampaign(
  campaignId: string,
  currentActor: string
): PlayCampaignStartResult | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    database
      .prepare(
        "INSERT INTO play_campaign_state (campaign_id, status, current_actor, turn_number, nudge_count) VALUES (?, 'active', ?, 1, 0)"
      )
      .run(campaignId, currentActor);

    const firstLocation = database
      .prepare(
        "SELECT id FROM play_campaign_locations WHERE campaign_id = ? ORDER BY rowid ASC LIMIT 1"
      )
      .get(campaignId) as { id: string } | undefined;
    if (firstLocation) {
      database
        .prepare(
          "UPDATE play_campaign_state SET current_location_id = ? WHERE campaign_id = ?"
        )
        .run(firstLocation.id, campaignId);
    }

    database.exec("COMMIT;");
    return {
      id: campaignId,
      status: "active",
      current_actor: currentActor,
      turn_number: 1,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getPlayCampaignState(
  campaignId: string
): PlayCampaignState | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT campaign_id, current_actor, status, turn_number, nudge_count, current_location_id, phase, pre_combat_actor FROM play_campaign_state WHERE campaign_id = ?"
    )
    .get(campaignId) as
    | {
        campaign_id: string;
        current_actor: string;
        status: "active";
        turn_number: number;
        nudge_count: number;
        current_location_id: string | null;
        phase: "exploration" | "combat";
        pre_combat_actor: string | null;
      }
    | undefined;
  if (!row) return null;
  return {
    ...row,
    current_location_id: row.current_location_id ?? undefined,
    pre_combat_actor: row.pre_combat_actor ?? undefined,
  };
}

export function createNudge(
  campaignId: string,
  actor: string,
  message: string
): { nudge_count: number } | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT nudge_count FROM play_campaign_state WHERE campaign_id = ?"
      )
      .get(campaignId) as { nudge_count: number } | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return null;
    }

    const seqRow = database
      .prepare(
        "SELECT COALESCE(MAX(sequence), 0) AS next_sequence FROM play_campaign_narrations WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_sequence: number };
    const sequence = seqRow.next_sequence + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_narrations (campaign_id, sequence, kind, actor, text) VALUES (?, ?, 'nudge', ?, ?)"
      )
      .run(campaignId, sequence, actor, message);

    const nextCount = row.nudge_count + 1;
    database
      .prepare(
        "UPDATE play_campaign_state SET nudge_count = ? WHERE campaign_id = ?"
      )
      .run(nextCount, campaignId);

    database.exec("COMMIT;");
    return { nudge_count: nextCount };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function createNarration(
  campaignId: string,
  actor: string,
  text: string
): PlayEvent | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const seqRow = database
      .prepare(
        "SELECT COALESCE(MAX(sequence), 0) AS next_sequence FROM play_campaign_narrations WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_sequence: number };
    const sequence = seqRow.next_sequence + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_narrations (campaign_id, sequence, kind, actor, text) VALUES (?, ?, 'narration', ?, ?)"
      )
      .run(campaignId, sequence, actor, text);

    database.exec("COMMIT;");
    return { sequence, kind: "narration", actor, text };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function createCombatAction(
  campaignId: string,
  actor: string,
  type: string,
  target: string,
  text: string
): PlayEvent | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const seqRow = database
      .prepare(
        "SELECT COALESCE(MAX(sequence), 0) AS next_sequence FROM play_campaign_narrations WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_sequence: number };
    const sequence = seqRow.next_sequence + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_narrations (campaign_id, sequence, kind, actor, text, type, target) VALUES (?, ?, 'combat_action', ?, ?, ?, ?)"
      )
      .run(campaignId, sequence, actor, text, type, target);

    database.exec("COMMIT;");
    return { sequence, kind: "combat_action", actor, type, target, text };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function createAction(
  campaignId: string,
  actor: string,
  type: string,
  text: string,
  nextActor: string
): PlayEvent | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const seqRow = database
      .prepare(
        "SELECT COALESCE(MAX(sequence), 0) AS next_sequence FROM play_campaign_narrations WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_sequence: number };
    const sequence = seqRow.next_sequence + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_narrations (campaign_id, sequence, kind, actor, text, type) VALUES (?, ?, 'action', ?, ?, ?)"
      )
      .run(campaignId, sequence, actor, text, type);

    database
      .prepare(
        "UPDATE play_campaign_state SET current_actor = ? WHERE campaign_id = ?"
      )
      .run(nextActor, campaignId);

    database.exec("COMMIT;");
    return { sequence, kind: "action", actor, type, text };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function createResolution(
  campaignId: string,
  owner: string,
  text: string
): ResolutionResult | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const stateRow = database
      .prepare(
        "SELECT current_actor, turn_number FROM play_campaign_state WHERE campaign_id = ?"
      )
      .get(campaignId) as
      | { current_actor: string; turn_number: number }
      | undefined;
    if (!stateRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    const members = getPlayCampaignMembers(campaignId);
    if (members.length === 0) {
      database.exec("ROLLBACK;");
      return null;
    }

    const lastActionRow = database
      .prepare(
        "SELECT actor FROM play_campaign_narrations WHERE campaign_id = ? AND kind IN ('action', 'travel', 'rest') ORDER BY sequence DESC LIMIT 1"
      )
      .get(campaignId) as { actor: string } | undefined;

    const lastPlayer = lastActionRow?.actor ?? members[0].username;
    const lastIndex = members.findIndex((m) => m.username === lastPlayer);
    const nextIndex = (lastIndex + 1) % members.length;
    const nextActor = members[nextIndex].username;

    const seqRow = database
      .prepare(
        "SELECT COALESCE(MAX(sequence), 0) AS next_sequence FROM play_campaign_narrations WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_sequence: number };
    const sequence = seqRow.next_sequence + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_narrations (campaign_id, sequence, kind, actor, text) VALUES (?, ?, 'resolution', ?, ?)"
      )
      .run(campaignId, sequence, owner, text);

    const newTurnNumber = stateRow.turn_number + 1;
    database
      .prepare(
        "UPDATE play_campaign_state SET current_actor = ?, turn_number = ? WHERE campaign_id = ?"
      )
      .run(nextActor, newTurnNumber, campaignId);

    database.exec("COMMIT;");
    return {
      sequence,
      kind: "resolution",
      actor: owner,
      text,
      next_actor: nextActor,
      turn_number: newTurnNumber,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function createTravelEvent(
  campaignId: string,
  actor: string,
  destinationId: string,
  nextActor: string
): TravelEvent | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const stateRow = database
      .prepare(
        "SELECT current_location_id FROM play_campaign_state WHERE campaign_id = ?"
      )
      .get(campaignId) as { current_location_id: string | null } | undefined;
    if (!stateRow || stateRow.current_location_id === null) {
      database.exec("ROLLBACK;");
      return null;
    }

    const connectionRow = database
      .prepare(
        "SELECT travel_turns FROM play_campaign_location_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?"
      )
      .get(campaignId, stateRow.current_location_id, destinationId) as
      | { travel_turns: number }
      | undefined;
    if (!connectionRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    const seqRow = database
      .prepare(
        "SELECT COALESCE(MAX(sequence), 0) AS next_sequence FROM play_campaign_narrations WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_sequence: number };
    const sequence = seqRow.next_sequence + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_narrations (campaign_id, sequence, kind, actor, text, type, destination_id, travel_turns) VALUES (?, ?, 'travel', ?, '', 'travel', ?, ?)"
      )
      .run(campaignId, sequence, actor, destinationId, connectionRow.travel_turns);

    database
      .prepare(
        "UPDATE play_campaign_state SET current_actor = ? WHERE campaign_id = ?"
      )
      .run(nextActor, campaignId);

    database.exec("COMMIT;");
    return {
      sequence,
      kind: "travel",
      actor,
      destination_id: destinationId,
      travel_turns: connectionRow.travel_turns,
      next_actor: nextActor,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function createRestEvent(
  campaignId: string,
  actor: string,
  restType: "short" | "long",
  nextActor: string
): RestEvent | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const stateRow = database
      .prepare(
        "SELECT current_actor FROM play_campaign_state WHERE campaign_id = ?"
      )
      .get(campaignId) as { current_actor: string } | undefined;
    if (!stateRow || stateRow.current_actor !== actor) {
      database.exec("ROLLBACK;");
      return null;
    }

    const memberRow = database
      .prepare(
        "SELECT hp_current, hp_max FROM play_campaign_members WHERE campaign_id = ? AND username = ?"
      )
      .get(campaignId, actor) as
      | { hp_current: number; hp_max: number }
      | undefined;
    if (!memberRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    let hpCurrent = memberRow.hp_current;
    const hpMax = memberRow.hp_max;
    if (restType === "long") {
      hpCurrent = hpMax;
      database
        .prepare(
          "UPDATE play_campaign_members SET hp_current = ? WHERE campaign_id = ? AND username = ?"
        )
        .run(hpCurrent, campaignId, actor);
    }

    const seqRow = database
      .prepare(
        "SELECT COALESCE(MAX(sequence), 0) AS next_sequence FROM play_campaign_narrations WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_sequence: number };
    const sequence = seqRow.next_sequence + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_narrations (campaign_id, sequence, kind, actor, text, type) VALUES (?, ?, 'rest', ?, '', ?)"
      )
      .run(campaignId, sequence, actor, restType);

    database
      .prepare(
        "UPDATE play_campaign_state SET current_actor = ? WHERE campaign_id = ?"
      )
      .run(nextActor, campaignId);

    database.exec("COMMIT;");
    return {
      sequence,
      kind: "rest",
      actor,
      type: restType,
      hp_current: hpCurrent,
      hp_max: hpMax,
      next_actor: nextActor,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getNarrations(campaignId: string): PlayEvent[] {
  const database = getDb();
  const rows = database
    .prepare(
      "SELECT sequence, kind, actor, text, type, destination_id, travel_turns, target FROM play_campaign_narrations WHERE campaign_id = ? ORDER BY sequence ASC"
    )
    .all(campaignId) as Array<{
    sequence: number;
    kind: "narration" | "action" | "resolution" | "travel" | "nudge" | "scene" | "rest" | "combat_action" | "ready";
    actor: string;
    text: string;
    type: string | null;
    destination_id: string | null;
    travel_turns: number | null;
    target: string | null;
  }>;
  return rows.map((r) => ({
    sequence: r.sequence,
    kind: r.kind,
    actor: r.actor,
    text: r.text,
    type: r.type ?? undefined,
    destination_id: r.destination_id ?? undefined,
    travel_turns: r.travel_turns ?? undefined,
    target: r.target ?? undefined,
  }));
}

// ---------------------------------------------------------------------------
// Scenes
// ---------------------------------------------------------------------------

export function createScene(
  campaignId: string,
  input: CreateSceneInput
): PlayCampaignScene | null {
  const database = getDb();
  try {
    database
      .prepare(
        "INSERT INTO play_campaign_scenes (id, campaign_id, name, status) VALUES (?, ?, ?, 'open')"
      )
      .run(input.id, campaignId, input.name);
    return { id: input.id, name: input.name, status: "open" };
  } catch {
    return null;
  }
}

export function getScene(
  campaignId: string,
  sceneId: string
): PlayCampaignScene | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT id, name, status FROM play_campaign_scenes WHERE campaign_id = ? AND id = ?"
    )
    .get(campaignId, sceneId) as
    | { id: string; name: string; status: "open" | "closed" }
    | undefined;
  return row || null;
}

export function setCurrentScene(
  campaignId: string,
  sceneId: string,
  actor: string
): { current_scene_id: string; name: string } | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const sceneRow = database
      .prepare(
        "SELECT id, name FROM play_campaign_scenes WHERE campaign_id = ? AND id = ?"
      )
      .get(campaignId, sceneId) as
      | { id: string; name: string }
      | undefined;
    if (!sceneRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    const seqRow = database
      .prepare(
        "SELECT COALESCE(MAX(sequence), 0) AS next_sequence FROM play_campaign_narrations WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_sequence: number };
    const sequence = seqRow.next_sequence + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_narrations (campaign_id, sequence, kind, actor, text) VALUES (?, ?, 'scene', ?, ?)"
      )
      .run(campaignId, sequence, actor, sceneId);

    database
      .prepare(
        "INSERT INTO play_campaign_current_scene (campaign_id, scene_id) VALUES (?, ?) ON CONFLICT(campaign_id) DO UPDATE SET scene_id = excluded.scene_id"
      )
      .run(campaignId, sceneId);

    database.exec("COMMIT;");
    return { current_scene_id: sceneId, name: sceneRow.name };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getCurrentScene(
  campaignId: string
): PlayCampaignScene | null {
  const database = getDb();
  const row = database
    .prepare(
      `SELECT s.id, s.name, s.status
       FROM play_campaign_current_scene cs
       JOIN play_campaign_scenes s ON cs.scene_id = s.id
       WHERE cs.campaign_id = ? AND s.status = 'open'`
    )
    .get(campaignId) as
    | { id: string; name: string; status: "open" }
    | undefined;
  return row || null;
}

export function closeScene(
  campaignId: string,
  sceneId: string
): { id: string; status: "closed" } | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const sceneRow = database
      .prepare(
        "SELECT id, status FROM play_campaign_scenes WHERE campaign_id = ? AND id = ?"
      )
      .get(campaignId, sceneId) as
      | { id: string; status: "open" | "closed" }
      | undefined;
    if (!sceneRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    database
      .prepare(
        "UPDATE play_campaign_scenes SET status = 'closed' WHERE campaign_id = ? AND id = ?"
      )
      .run(campaignId, sceneId);

    database.exec("COMMIT;");
    return { id: sceneId, status: "closed" };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

// ---------------------------------------------------------------------------
// Campaign documents
// ---------------------------------------------------------------------------

export function getCampaignDocument(
  campaignId: string
): CampaignDocument | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT campaign_id, story, dm_notes FROM play_campaign_documents WHERE campaign_id = ?"
    )
    .get(campaignId) as
    | { campaign_id: string; story: string; dm_notes: string }
    | undefined;
  return row || null;
}

export function updateCampaignDocument(
  campaignId: string,
  story: string,
  dmNotes: string
): CampaignDocument | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    database
      .prepare(
        "INSERT OR IGNORE INTO play_campaign_documents (campaign_id, story, dm_notes) VALUES (?, '', '')"
      )
      .run(campaignId);
    database
      .prepare(
        "UPDATE play_campaign_documents SET story = ?, dm_notes = ? WHERE campaign_id = ?"
      )
      .run(story, dmNotes, campaignId);
    database.exec("COMMIT;");
    return getCampaignDocument(campaignId);
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

// ---------------------------------------------------------------------------
// Locations and connections
// ---------------------------------------------------------------------------

export function createLocation(
  campaignId: string,
  input: CreateLocationInput
): CampaignLocation | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    database
      .prepare(
        "INSERT INTO play_campaign_locations (id, campaign_id, name) VALUES (?, ?, ?)"
      )
      .run(input.id, campaignId, input.name);

    const stateRow = database
      .prepare(
        "SELECT current_location_id FROM play_campaign_state WHERE campaign_id = ?"
      )
      .get(campaignId) as { current_location_id: string | null } | undefined;
    if (stateRow && stateRow.current_location_id === null) {
      database
        .prepare(
          "UPDATE play_campaign_state SET current_location_id = ? WHERE campaign_id = ?"
        )
        .run(input.id, campaignId);
    }

    database.exec("COMMIT;");
    return { id: input.id, name: input.name };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getLocation(
  campaignId: string,
  locationId: string
): CampaignLocation | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT id, name FROM play_campaign_locations WHERE campaign_id = ? AND id = ?"
    )
    .get(campaignId, locationId) as
    | { id: string; name: string }
    | undefined;
  return row || null;
}

export function createConnection(
  campaignId: string,
  fromId: string,
  input: CreateConnectionInput
): LocationConnection | null {
  const database = getDb();

  const fromLocation = getLocation(campaignId, fromId);
  const toLocation = getLocation(campaignId, input.to_id);
  if (!fromLocation || !toLocation) {
    return null;
  }

  try {
    database
      .prepare(
        "INSERT INTO play_campaign_location_connections (campaign_id, from_id, to_id, travel_turns) VALUES (?, ?, ?, ?)"
      )
      .run(campaignId, fromId, input.to_id, input.travel_turns);
    return { from_id: fromId, to_id: input.to_id, travel_turns: input.travel_turns };
  } catch {
    return null;
  }
}

export function getOutboundConnections(
  campaignId: string,
  locationId: string
): TravelDestination[] | null {
  if (!getLocation(campaignId, locationId)) return null;

  const database = getDb();
  const rows = database
    .prepare(
      `SELECT c.to_id AS id, l.name, c.travel_turns
       FROM play_campaign_location_connections c
       JOIN play_campaign_locations l ON c.campaign_id = l.campaign_id AND c.to_id = l.id
       WHERE c.campaign_id = ? AND c.from_id = ?
       ORDER BY c.to_id ASC`
    )
    .all(campaignId, locationId) as Array<{
    id: string;
    name: string;
    travel_turns: number;
  }>;

  return rows;
}

// ---------------------------------------------------------------------------
// Encounters
// ---------------------------------------------------------------------------

interface EncounterOrderEntry {
  kind: "player" | "monster";
  id: string;
}

interface EncounterCombatant {
  id: string;
  name: string;
  kind: "player" | "monster";
  initiative: number;
  member?: string;
}

function readEncounterOrder(
  database: DatabaseSync,
  campaignId: string,
  encounterId: string
): EncounterOrderEntry[] | null {
  const row = database
    .prepare(
      "SELECT combatant_order FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?"
    )
    .get(campaignId, encounterId) as
    | { combatant_order: string | null }
    | undefined;
  if (!row?.combatant_order) return null;
  try {
    const parsed = JSON.parse(row.combatant_order) as unknown;
    if (!Array.isArray(parsed) || parsed.length === 0) return null;
    if (
      parsed.every((o) => {
        if (typeof o !== "object" || o === null) return false;
        const entry = o as Record<string, unknown>;
        return (
          (entry.kind === "player" || entry.kind === "monster") &&
          typeof entry.id === "string"
        );
      })
    ) {
      return parsed as EncounterOrderEntry[];
    }
    return null;
  } catch {
    return null;
  }
}

function writeEncounterOrder(
  database: DatabaseSync,
  campaignId: string,
  encounterId: string,
  order: EncounterOrderEntry[]
): void {
  database
    .prepare(
      "UPDATE play_campaign_encounters SET combatant_order = ? WHERE campaign_id = ? AND id = ?"
    )
    .run(JSON.stringify(order), campaignId, encounterId);
}

function buildEncounterCombatants(
  database: DatabaseSync,
  campaignId: string,
  encounterId: string
): EncounterCombatant[] {
  const combatantRows = database
    .prepare(
      "SELECT member, name, score FROM play_campaign_encounter_combatants WHERE campaign_id = ? AND encounter_id = ?"
    )
    .all(campaignId, encounterId) as Array<{
    member: string;
    name: string;
    score: number;
  }>;

  const monsterRows = database
    .prepare(
      "SELECT monster_id, name, score FROM play_campaign_encounter_monsters WHERE campaign_id = ? AND encounter_id = ?"
    )
    .all(campaignId, encounterId) as Array<{
    monster_id: string;
    name: string;
    score: number;
  }>;

  return [
    ...combatantRows.map((r) => ({
      id: r.member,
      name: r.name,
      kind: "player" as const,
      initiative: r.score,
      member: r.member,
    })),
    ...monsterRows.map((r) => ({
      id: r.monster_id,
      name: r.name,
      kind: "monster" as const,
      initiative: r.score,
    })),
  ];
}

function getEncounterCombatantsOrdered(
  database: DatabaseSync,
  campaignId: string,
  encounterId: string
): EncounterCombatant[] {
  const rows = buildEncounterCombatants(database, campaignId, encounterId);
  const order = readEncounterOrder(database, campaignId, encounterId);
  if (order && order.length > 0) {
    const orderMap = new Map(
      order.map((o, i) => [`${o.kind}:${o.id}`, i])
    );
    rows.sort((a, b) => {
      const idxA = orderMap.get(`${a.kind}:${a.id}`);
      const idxB = orderMap.get(`${b.kind}:${b.id}`);
      if (idxA !== undefined && idxB !== undefined && idxA !== idxB) {
        return idxA - idxB;
      }
      if (b.initiative !== a.initiative) return b.initiative - a.initiative;
      return a.name.localeCompare(b.name);
    });
  } else {
    rows.sort((a, b) => {
      if (b.initiative !== a.initiative) return b.initiative - a.initiative;
      return a.name.localeCompare(b.name);
    });
  }
  return rows;
}

function ensureEncounterOrder(
  database: DatabaseSync,
  campaignId: string,
  encounterId: string
): void {
  if (readEncounterOrder(database, campaignId, encounterId)) return;
  const rows = buildEncounterCombatants(database, campaignId, encounterId);
  rows.sort((a, b) => {
    if (b.initiative !== a.initiative) return b.initiative - a.initiative;
    return a.name.localeCompare(b.name);
  });
  if (rows.length > 0) {
    writeEncounterOrder(
      database,
      campaignId,
      encounterId,
      rows.map((r) => ({ kind: r.kind, id: r.id }))
    );
  }
}

function insertIntoEncounterOrder(
  database: DatabaseSync,
  campaignId: string,
  encounterId: string,
  kind: "player" | "monster",
  id: string,
  initiative: number
): void {
  ensureEncounterOrder(database, campaignId, encounterId);
  const order = readEncounterOrder(database, campaignId, encounterId);
  if (!order) return;
  const rows = getEncounterCombatantsOrdered(database, campaignId, encounterId);
  const initiatives = new Map(
    rows.map((r) => [`${r.kind}:${r.id}`, r.initiative])
  );
  let insertAt = order.length;
  for (let i = 0; i < order.length; i++) {
    const init = initiatives.get(`${order[i].kind}:${order[i].id}`);
    if (init !== undefined && initiative > init) {
      insertAt = i;
      break;
    }
  }
  order.splice(insertAt, 0, { kind, id });
  writeEncounterOrder(database, campaignId, encounterId, order);
}

function removeFromEncounterOrder(
  database: DatabaseSync,
  campaignId: string,
  encounterId: string,
  kind: "player" | "monster",
  id: string
): void {
  const order = readEncounterOrder(database, campaignId, encounterId);
  if (!order) return;
  const newOrder = order.filter((o) => o.kind !== kind || o.id !== id);
  writeEncounterOrder(database, campaignId, encounterId, newOrder);
}

export function getPlayCampaignEncounter(
  campaignId: string,
  encounterId: string
): PlayCampaignEncounter | null {
  const database = getDb();
  const encounterRow = database
    .prepare(
      "SELECT id, name, status, closed FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?"
    )
    .get(campaignId, encounterId) as
    | { id: string; name: string; status: "active" | "completed"; closed: number }
    | undefined;
  if (!encounterRow) return null;

  const ordered = getEncounterCombatantsOrdered(database, campaignId, encounterId);

  return {
    id: encounterRow.id,
    name: encounterRow.name,
    status: encounterRow.closed ? "closed" : encounterRow.status,
    combatants: ordered.map((c) => ({ name: c.name, score: c.initiative })),
  };
}

export function getActivePlayCampaignEncounter(
  campaignId: string
): PlayCampaignEncounter | null {
  const database = getDb();
  const encounterRow = database
    .prepare(
      "SELECT id, name, status FROM play_campaign_encounters WHERE campaign_id = ? AND status = 'active' ORDER BY rowid ASC LIMIT 1"
    )
    .get(campaignId) as
    | { id: string; name: string; status: "active" | "completed" }
    | undefined;
  if (!encounterRow) return null;
  return getPlayCampaignEncounter(campaignId, encounterRow.id);
}

export function createPlayCampaignEncounter(
  campaignId: string,
  input: CreatePlayCampaignEncounterInput
): PlayCampaignEncounter | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const activeRow = database
      .prepare(
        "SELECT id FROM play_campaign_encounters WHERE campaign_id = ? AND status = 'active' LIMIT 1"
      )
      .get(campaignId) as { id: string } | undefined;
    if (activeRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    const stateRow = database
      .prepare(
        "SELECT current_actor FROM play_campaign_state WHERE campaign_id = ?"
      )
      .get(campaignId) as { current_actor: string } | undefined;
    if (!stateRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    database
      .prepare(
        "INSERT INTO play_campaign_encounters (campaign_id, id, name, status, round, turn_index) VALUES (?, ?, ?, 'active', 1, 0)"
      )
      .run(campaignId, input.id, input.name);

    // Enter combat phase and remember the exploration actor to resume later.
    database
      .prepare(
        "UPDATE play_campaign_state SET phase = 'combat', pre_combat_actor = ? WHERE campaign_id = ?"
      )
      .run(stateRow.current_actor, campaignId);

    database.exec("COMMIT;");
    return {
      id: input.id,
      name: input.name,
      status: "active",
      combatants: [],
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function addPlayCampaignEncounterMonster(
  campaignId: string,
  encounterId: string,
  input: CreatePlayCampaignEncounterMonsterInput
): PlayCampaignEncounterMonster | null {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;
  if (!getPlayCampaignEncounter(campaignId, encounterId)) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    database
      .prepare(
        "INSERT INTO play_campaign_encounter_monsters (campaign_id, encounter_id, monster_id, name, hp_max, hp_current, score) VALUES (?, ?, ?, ?, ?, ?, ?)"
      )
      .run(
        campaignId,
        encounterId,
        input.monster_id,
        input.name,
        input.hp_max,
        input.hp_max,
        input.initiative
      );

    insertIntoEncounterOrder(
      database,
      campaignId,
      encounterId,
      "monster",
      input.monster_id,
      input.initiative
    );

    database.exec("COMMIT;");
    return {
      monster_id: input.monster_id,
      name: input.name,
      hp_max: input.hp_max,
      initiative: input.initiative,
      hp_current: input.hp_max,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function removePlayCampaignEncounterMonster(
  campaignId: string,
  encounterId: string,
  monsterId: string
): { removed: string } | null {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;
  if (!getPlayCampaignEncounter(campaignId, encounterId)) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const result = database
      .prepare(
        "DELETE FROM play_campaign_encounter_monsters WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?"
      )
      .run(campaignId, encounterId, monsterId);

    if (result.changes === 0) {
      database.exec("ROLLBACK;");
      return null;
    }

    removeFromEncounterOrder(database, campaignId, encounterId, "monster", monsterId);

    database.exec("COMMIT;");
    return { removed: monsterId };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function bindMemberToEncounter(
  campaignId: string,
  encounterId: string,
  member: string,
  characterId: string,
  name: string,
  initiative: number
): { member: string; character_id: string; name: string; initiative: number } | null {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;
  if (!getPlayCampaignEncounter(campaignId, encounterId)) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const existing = database
      .prepare(
        "SELECT id FROM play_campaign_encounter_combatants WHERE campaign_id = ? AND encounter_id = ? AND member = ?"
      )
      .get(campaignId, encounterId, member) as { id: number } | undefined;
    if (existing) {
      database.exec("ROLLBACK;");
      return null;
    }

    database
      .prepare(
        "INSERT INTO play_campaign_encounter_combatants (campaign_id, encounter_id, member, character_id, name, score) VALUES (?, ?, ?, ?, ?, ?)"
      )
      .run(campaignId, encounterId, member, characterId, name, initiative);

    insertIntoEncounterOrder(database, campaignId, encounterId, "player", member, initiative);

    database.exec("COMMIT;");
    return {
      member,
      character_id: characterId,
      name,
      initiative,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function unbindMemberFromEncounter(
  campaignId: string,
  encounterId: string,
  member: string
): { removed: string } | null {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;
  if (!getPlayCampaignEncounter(campaignId, encounterId)) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const result = database
      .prepare(
        "DELETE FROM play_campaign_encounter_combatants WHERE campaign_id = ? AND encounter_id = ? AND member = ?"
      )
      .run(campaignId, encounterId, member);

    if (result.changes === 0) {
      database.exec("ROLLBACK;");
      return null;
    }

    removeFromEncounterOrder(database, campaignId, encounterId, "player", member);

    database.exec("COMMIT;");
    return { removed: member };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getEncounterTurn(
  campaignId: string,
  encounterId: string
): PlayCampaignEncounterTurn | null {
  const database = getDb();
  const encounterRow = database
    .prepare(
      "SELECT round, turn_index FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?"
    )
    .get(campaignId, encounterId) as
    | { round: number; turn_index: number }
    | undefined;
  if (!encounterRow) return null;

  const ordered = getEncounterCombatantsOrdered(database, campaignId, encounterId);
  if (ordered.length === 0) return null;

  const turnIndex = encounterRow.turn_index % ordered.length;
  const active = ordered[turnIndex];

  return {
    round: encounterRow.round,
    turn_index: turnIndex,
    active:
      active.kind === "player"
        ? {
            name: active.name,
            kind: "player",
            initiative: active.initiative,
            member: active.member,
            target: active.id,
          }
        : {
            name: active.name,
            kind: "monster",
            initiative: active.initiative,
            target: active.id,
          },
  };
}

export function advanceEncounterTurn(
  campaignId: string,
  encounterId: string
): PlayCampaignEncounterTurn | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const encounterRow = database
      .prepare(
        "SELECT round, turn_index FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?"
      )
      .get(campaignId, encounterId) as
      | { round: number; turn_index: number }
      | undefined;
    if (!encounterRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    const ordered = getEncounterCombatantsOrdered(database, campaignId, encounterId);
    if (ordered.length === 0) {
      database.exec("ROLLBACK;");
      return null;
    }

    let newTurnIndex = encounterRow.turn_index + 1;
    let newRound = encounterRow.round;
    if (newTurnIndex >= ordered.length) {
      newTurnIndex = 0;
      newRound += 1;
    }

    const newActive = ordered[newTurnIndex];

    database
      .prepare(
        "UPDATE play_campaign_encounters SET round = ?, turn_index = ? WHERE campaign_id = ? AND id = ?"
      )
      .run(newRound, newTurnIndex, campaignId, encounterId);

    // Conditions on the newly active combatant tick down at the start of its turn.
    database
      .prepare(
        "DELETE FROM play_campaign_encounter_conditions WHERE campaign_id = ? AND encounter_id = ? AND target = ? AND remaining_rounds <= 1"
      )
      .run(campaignId, encounterId, newActive.id);

    database
      .prepare(
        "UPDATE play_campaign_encounter_conditions SET remaining_rounds = remaining_rounds - 1 WHERE campaign_id = ? AND encounter_id = ? AND target = ? AND remaining_rounds > 1"
      )
      .run(campaignId, encounterId, newActive.id);

    database.exec("COMMIT;");
    return getEncounterTurn(campaignId, encounterId);
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function addPlayCampaignEncounterCondition(
  campaignId: string,
  encounterId: string,
  target: string,
  condition: string,
  durationRounds: number
): AddEncounterConditionResult | null {
  if (durationRounds <= 0) return null;
  const database = getDb();
  if (!getPlayCampaign(campaignId) || !getPlayCampaignEncounter(campaignId, encounterId)) {
    return null;
  }

  database.exec("BEGIN IMMEDIATE;");
  try {
    const monsterRow = database
      .prepare(
        "SELECT 1 FROM play_campaign_encounter_monsters WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?"
      )
      .get(campaignId, encounterId, target) as { 1: number } | undefined;

    const combatantRow = database
      .prepare(
        "SELECT 1 FROM play_campaign_encounter_combatants WHERE campaign_id = ? AND encounter_id = ? AND member = ?"
      )
      .get(campaignId, encounterId, target) as { 1: number } | undefined;

    if (!monsterRow && !combatantRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    database
      .prepare(
        "INSERT INTO play_campaign_encounter_conditions (campaign_id, encounter_id, target, condition, remaining_rounds) VALUES (?, ?, ?, ?, ?)"
      )
      .run(campaignId, encounterId, target, condition, durationRounds);

    const conditionRows = database
      .prepare(
        "SELECT condition, remaining_rounds FROM play_campaign_encounter_conditions WHERE campaign_id = ? AND encounter_id = ? AND target = ? ORDER BY id ASC"
      )
      .all(campaignId, encounterId, target) as Array<{
      condition: string;
      remaining_rounds: number;
    }>;

    database.exec("COMMIT;");
    return {
      target,
      conditions: conditionRows,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getPlayCampaignEncounterConditions(
  campaignId: string,
  encounterId: string
): Record<string, Condition[]> | null {
  const database = getDb();
  if (!getPlayCampaignEncounter(campaignId, encounterId)) return null;

  const rows = database
    .prepare(
      "SELECT target, condition, remaining_rounds FROM play_campaign_encounter_conditions WHERE campaign_id = ? AND encounter_id = ? ORDER BY id ASC"
    )
    .all(campaignId, encounterId) as Array<{
    target: string;
    condition: string;
    remaining_rounds: number;
  }>;

  const conditions: Record<string, Condition[]> = {};
  for (const row of rows) {
    if (!conditions[row.target]) {
      conditions[row.target] = [];
    }
    conditions[row.target].push({
      condition: row.condition,
      remaining_rounds: row.remaining_rounds,
    });
  }

  return conditions;
}

export function getPlayCampaignEncounterStatus(
  campaignId: string,
  encounterId: string
): PlayCampaignEncounterStatus | null {
  const database = getDb();
  const encounterRow = database
    .prepare(
      "SELECT round, turn_index FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?"
    )
    .get(campaignId, encounterId) as
    | { round: number; turn_index: number }
    | undefined;
  if (!encounterRow) return null;

  const ordered = getEncounterCombatantsOrdered(database, campaignId, encounterId);
  if (ordered.length === 0) return null;

  const turnIndex = encounterRow.turn_index % ordered.length;
  const active = ordered[turnIndex];

  const conditions = getPlayCampaignEncounterConditions(campaignId, encounterId);
  if (conditions === null) return null;

  return {
    round: encounterRow.round,
    turn_index: turnIndex,
    active:
      active.kind === "player"
        ? {
            name: active.name,
            kind: "player",
            initiative: active.initiative,
            member: active.member,
            target: active.id,
          }
        : {
            name: active.name,
            kind: "monster",
            initiative: active.initiative,
            target: active.id,
          },
    order: ordered.map((o) => ({
      name: o.name,
      kind: o.kind,
      initiative: o.initiative,
      target: o.id,
    })),
    conditions,
  };
}

export function applyDamageToEncounterCombatant(
  campaignId: string,
  encounterId: string,
  target: string,
  amount: number
): { target: string; hp_before: number; hp_after: number; damage: number } | null {
  if (amount <= 0) return null;
  const database = getDb();
  if (!getPlayCampaign(campaignId) || !getPlayCampaignEncounter(campaignId, encounterId)) {
    return null;
  }

  database.exec("BEGIN IMMEDIATE;");
  try {
    const monsterRow = database
      .prepare(
        "SELECT hp_current FROM play_campaign_encounter_monsters WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?"
      )
      .get(campaignId, encounterId, target) as
      | { hp_current: number }
      | undefined;

    if (monsterRow) {
      const hp_before = monsterRow.hp_current;
      const hp_after = Math.max(0, hp_before - amount);
      database
        .prepare(
          "UPDATE play_campaign_encounter_monsters SET hp_current = ? WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?"
        )
        .run(hp_after, campaignId, encounterId, target);
      database.exec("COMMIT;");
      return { target, hp_before, hp_after, damage: amount };
    }

    const combatantRow = database
      .prepare(
        "SELECT member FROM play_campaign_encounter_combatants WHERE campaign_id = ? AND encounter_id = ? AND member = ?"
      )
      .get(campaignId, encounterId, target) as
      | { member: string }
      | undefined;

    if (combatantRow) {
      const memberRow = database
        .prepare(
          "SELECT hp_current, status, death_saves_successes, death_saves_failures FROM play_campaign_members WHERE campaign_id = ? AND username = ?"
        )
        .get(campaignId, combatantRow.member) as
        | {
            hp_current: number;
            status: PlayCampaignMemberStatus;
            death_saves_successes: number;
            death_saves_failures: number;
          }
        | undefined;
      if (!memberRow) {
        database.exec("ROLLBACK;");
        return null;
      }
      const hp_before = memberRow.hp_current;
      const hp_after = Math.max(0, hp_before - amount);
      let status = memberRow.status;
      let successes = memberRow.death_saves_successes;
      let failures = memberRow.death_saves_failures;

      if (hp_before > 0 && hp_after === 0) {
        status = "unconscious";
        successes = 0;
        failures = 0;
      }

      database
        .prepare(
          "UPDATE play_campaign_members SET hp_current = ?, status = ?, death_saves_successes = ?, death_saves_failures = ? WHERE campaign_id = ? AND username = ?"
        )
        .run(hp_after, status, successes, failures, campaignId, combatantRow.member);
      database.exec("COMMIT;");
      return { target, hp_before, hp_after, damage: amount };
    }

    database.exec("ROLLBACK;");
    return null;
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function applyHealingToEncounterCombatant(
  campaignId: string,
  encounterId: string,
  target: string,
  amount: number
): { target: string; hp_before: number; hp_after: number; healing: number } | null {
  if (amount <= 0) return null;
  const database = getDb();
  if (!getPlayCampaign(campaignId) || !getPlayCampaignEncounter(campaignId, encounterId)) {
    return null;
  }

  database.exec("BEGIN IMMEDIATE;");
  try {
    const monsterRow = database
      .prepare(
        "SELECT hp_current, hp_max FROM play_campaign_encounter_monsters WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?"
      )
      .get(campaignId, encounterId, target) as
      | { hp_current: number; hp_max: number }
      | undefined;

    if (monsterRow) {
      const hp_before = monsterRow.hp_current;
      const hp_after = Math.min(monsterRow.hp_max, hp_before + amount);
      database
        .prepare(
          "UPDATE play_campaign_encounter_monsters SET hp_current = ? WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?"
        )
        .run(hp_after, campaignId, encounterId, target);
      database.exec("COMMIT;");
      return { target, hp_before, hp_after, healing: amount };
    }

    const combatantRow = database
      .prepare(
        "SELECT member FROM play_campaign_encounter_combatants WHERE campaign_id = ? AND encounter_id = ? AND member = ?"
      )
      .get(campaignId, encounterId, target) as
      | { member: string }
      | undefined;

    if (combatantRow) {
      const memberRow = database
        .prepare(
          "SELECT hp_current, hp_max, status, death_saves_successes, death_saves_failures FROM play_campaign_members WHERE campaign_id = ? AND username = ?"
        )
        .get(campaignId, combatantRow.member) as
        | {
            hp_current: number;
            hp_max: number;
            status: PlayCampaignMemberStatus;
            death_saves_successes: number;
            death_saves_failures: number;
          }
        | undefined;
      if (!memberRow) {
        database.exec("ROLLBACK;");
        return null;
      }
      const hp_before = memberRow.hp_current;
      const hp_after = Math.min(memberRow.hp_max, hp_before + amount);
      let status = memberRow.status;
      let successes = memberRow.death_saves_successes;
      let failures = memberRow.death_saves_failures;

      if (hp_after > 0 && (status === "unconscious" || status === "stable")) {
        status = "conscious";
        successes = 0;
        failures = 0;
      }

      database
        .prepare(
          "UPDATE play_campaign_members SET hp_current = ?, status = ?, death_saves_successes = ?, death_saves_failures = ? WHERE campaign_id = ? AND username = ?"
        )
        .run(hp_after, status, successes, failures, campaignId, combatantRow.member);
      database.exec("COMMIT;");
      return { target, hp_before, hp_after, healing: amount };
    }

    database.exec("ROLLBACK;");
    return null;
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function delayEncounterTurn(
  campaignId: string,
  encounterId: string,
  newIndex: number
): { order: EncounterCombatant[] } | null | "invalid_index" {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;
  if (!getPlayCampaignEncounter(campaignId, encounterId)) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const encounterRow = database
      .prepare(
        "SELECT round, turn_index, combatant_order FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?"
      )
      .get(campaignId, encounterId) as
      | { round: number; turn_index: number; combatant_order: string | null }
      | undefined;
    if (!encounterRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    const ordered = getEncounterCombatantsOrdered(database, campaignId, encounterId);
    if (ordered.length === 0) {
      database.exec("ROLLBACK;");
      return null;
    }

    const turnIndex = encounterRow.turn_index % ordered.length;
    if (
      !Number.isInteger(newIndex) ||
      newIndex <= turnIndex ||
      newIndex >= ordered.length
    ) {
      database.exec("ROLLBACK;");
      return "invalid_index";
    }

    const current = ordered.splice(turnIndex, 1)[0];
    ordered.splice(newIndex, 0, current);

    writeEncounterOrder(
      database,
      campaignId,
      encounterId,
      ordered.map((r) => ({ kind: r.kind, id: r.id }))
    );

    database
      .prepare(
        "UPDATE play_campaign_encounters SET turn_index = ? WHERE campaign_id = ? AND id = ?"
      )
      .run(newIndex, campaignId, encounterId);

    database.exec("COMMIT;");
    return { order: ordered };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function createReadyAction(
  campaignId: string,
  encounterId: string,
  actor: string,
  trigger: string
): { actor: string; trigger: string } | null {
  const database = getDb();
  if (!getPlayCampaign(campaignId) || !getPlayCampaignEncounter(campaignId, encounterId)) {
    return null;
  }

  database.exec("BEGIN IMMEDIATE;");
  try {
    const seqRow = database
      .prepare(
        "SELECT COALESCE(MAX(sequence), 0) AS next_sequence FROM play_campaign_narrations WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_sequence: number };
    const sequence = seqRow.next_sequence + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_narrations (campaign_id, sequence, kind, actor, text, type) VALUES (?, ?, 'ready', ?, ?, 'ready')"
      )
      .run(campaignId, sequence, actor, trigger);

    database.exec("COMMIT;");
    return { actor, trigger };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function awardEncounterRewards(
  campaignId: string,
  encounterId: string,
  xp: number,
  loot: EncounterLoot[]
): EncounterRewardRecord | null | "already_awarded" {
  if (!Number.isInteger(xp) || xp < 0) return null;
  if (!Array.isArray(loot)) return null;
  for (const entry of loot) {
    if (
      typeof entry !== "object" ||
      entry === null ||
      typeof entry.slug !== "string" ||
      entry.slug.length === 0 ||
      !Number.isInteger(entry.quantity) ||
      entry.quantity <= 0
    ) {
      return null;
    }
  }

  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;
  if (!getPlayCampaignEncounter(campaignId, encounterId)) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT rewards_awarded FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?"
      )
      .get(campaignId, encounterId) as
      | { rewards_awarded: number }
      | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return null;
    }
    if (row.rewards_awarded) {
      database.exec("ROLLBACK;");
      return "already_awarded";
    }

    database
      .prepare(
        "UPDATE play_campaign_encounters SET xp_awarded = ?, loot_awarded = ?, rewards_awarded = 1 WHERE campaign_id = ? AND id = ?"
      )
      .run(xp, JSON.stringify(loot), campaignId, encounterId);

    database.exec("COMMIT;");
    return { xp, loot };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function closePlayCampaignEncounter(
  campaignId: string,
  encounterId: string
): EncounterCloseResult | null {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;
  if (!getPlayCampaignEncounter(campaignId, encounterId)) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT status, xp_awarded, closed FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?"
      )
      .get(campaignId, encounterId) as
      | { status: string; xp_awarded: number; closed: number }
      | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return null;
    }

    if (!row.closed) {
      database
        .prepare(
          "UPDATE play_campaign_encounters SET status = 'completed', closed = 1 WHERE campaign_id = ? AND id = ?"
        )
        .run(campaignId, encounterId);
    }

    database.exec("COMMIT;");
    return { id: encounterId, status: "closed", xp_awarded: row.xp_awarded };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function endPlayCampaignEncounter(
  campaignId: string,
  encounterId: string
): EndEncounterResult | null | "not_in_combat" {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;

  const state = getPlayCampaignState(campaignId);
  if (!state) return null;
  if (state.phase !== "combat") {
    return "not_in_combat";
  }

  const encounterRow = database
    .prepare(
      "SELECT status, closed FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?"
    )
    .get(campaignId, encounterId) as
    | { status: "active" | "completed"; closed: number }
    | undefined;
  if (!encounterRow) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    if (!encounterRow.closed) {
      database
        .prepare(
          "UPDATE play_campaign_encounters SET status = 'completed', closed = 1 WHERE campaign_id = ? AND id = ?"
        )
        .run(campaignId, encounterId);
    }

    const restoredActor = state.pre_combat_actor ?? state.current_actor;
    database
      .prepare(
        "UPDATE play_campaign_state SET phase = 'exploration', current_actor = ?, pre_combat_actor = NULL WHERE campaign_id = ?"
      )
      .run(restoredActor, campaignId);

    database.exec("COMMIT;");
    return {
      campaign_id: campaignId,
      status: "active",
      phase: "exploration",
      current_actor: restoredActor,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}
