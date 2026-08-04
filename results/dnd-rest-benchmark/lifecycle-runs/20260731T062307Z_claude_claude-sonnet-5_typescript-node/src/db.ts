// SQLite storage: schema management and the shared database handle.
//
// All domain modules import `db` from here and issue their own prepared
// statements directly (no repository/ORM layer) — this keeps the SQL next to
// the code that depends on its exact shape. `db` and `storageInitialized`
// are live ES module bindings: reassigning them in `openDatabase`/
// `resetDatabase` is visible to every importer.
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath } from "node:url";
import path from "node:path";
import fs from "node:fs";

export const SCHEMA_VERSION = 1;

const DB_PATH = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "game.db");

export let db: DatabaseSync;
export let storageInitialized = false;

function initSchema(): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS users (
      username TEXT PRIMARY KEY,
      role TEXT NOT NULL,
      password_hash TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS combat_sessions (
      id TEXT PRIMARY KEY,
      round INTEGER NOT NULL,
      turn_index INTEGER NOT NULL,
      combat_order TEXT NOT NULL
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
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      name TEXT NOT NULL,
      level INTEGER NOT NULL,
      class TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );
    CREATE TABLE IF NOT EXISTS campaign_events (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      kind TEXT NOT NULL,
      summary TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );
    CREATE TABLE IF NOT EXISTS campaign_quests (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      title TEXT NOT NULL,
      status TEXT NOT NULL,
      milestones TEXT NOT NULL,
      milestones_done TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );
    CREATE TABLE IF NOT EXISTS campaign_factions (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      name TEXT NOT NULL,
      stance TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );
    CREATE TABLE IF NOT EXISTS campaign_npcs (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      name TEXT NOT NULL,
      faction_id TEXT,
      disposition INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );
    CREATE TABLE IF NOT EXISTS campaign_inventory (
      campaign_id TEXT NOT NULL,
      item_slug TEXT NOT NULL,
      owner TEXT NOT NULL,
      quantity INTEGER NOT NULL,
      countable INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS campaign_equipment (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      item_slug TEXT NOT NULL,
      quantity INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS campaign_crafting (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      item_slug TEXT NOT NULL,
      days_required INTEGER NOT NULL,
      days_completed INTEGER NOT NULL,
      cost_gp INTEGER NOT NULL,
      status TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );
    CREATE TABLE IF NOT EXISTS campaign_sessions (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      starts_at TEXT NOT NULL,
      duration_minutes INTEGER NOT NULL,
      agenda TEXT NOT NULL,
      present TEXT NOT NULL,
      absent TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );
    CREATE TABLE IF NOT EXISTS play_campaigns (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      owner TEXT NOT NULL,
      status TEXT NOT NULL,
      max_players INTEGER NOT NULL,
      current_actor TEXT,
      turn_number INTEGER,
      turn_deadline INTEGER,
      turn_nudge_count INTEGER NOT NULL DEFAULT 0,
      doc_story TEXT NOT NULL DEFAULT '',
      doc_dm_notes TEXT NOT NULL DEFAULT '',
      current_scene_id TEXT,
      current_location_id TEXT,
      pre_combat_actor TEXT,
      calendar_day INTEGER,
      calendar_season TEXT
    );
    CREATE TABLE IF NOT EXISTS play_campaign_members (
      campaign_id TEXT NOT NULL,
      username TEXT NOT NULL,
      character_id TEXT NOT NULL,
      name TEXT NOT NULL,
      class TEXT NOT NULL,
      hp_current INTEGER NOT NULL DEFAULT 20,
      hp_max INTEGER NOT NULL DEFAULT 20,
      status TEXT NOT NULL DEFAULT 'conscious',
      death_save_successes INTEGER NOT NULL DEFAULT 0,
      death_save_failures INTEGER NOT NULL DEFAULT 0,
      owner TEXT,
      race TEXT,
      background TEXT,
      level INTEGER NOT NULL DEFAULT 1,
      proficiency_bonus INTEGER NOT NULL DEFAULT 2,
      con_modifier INTEGER NOT NULL DEFAULT 0,
      str_modifier INTEGER NOT NULL DEFAULT 0,
      dex_modifier INTEGER NOT NULL DEFAULT 0,
      int_modifier INTEGER NOT NULL DEFAULT 0,
      wis_modifier INTEGER NOT NULL DEFAULT 0,
      cha_modifier INTEGER NOT NULL DEFAULT 0,
      gold INTEGER NOT NULL DEFAULT 10,
      PRIMARY KEY (campaign_id, username)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_transfers (
      campaign_id TEXT NOT NULL,
      transfer_id INTEGER NOT NULL,
      from_character_id TEXT NOT NULL,
      to_character_id TEXT NOT NULL,
      gold INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, transfer_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_events (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      kind TEXT NOT NULL,
      actor TEXT NOT NULL,
      text TEXT NOT NULL,
      destination_id TEXT,
      travel_turns INTEGER,
      action_type TEXT,
      action_target TEXT,
      PRIMARY KEY (campaign_id, sequence)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_scenes (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      name TEXT NOT NULL,
      status TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_locations (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      name TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_connections (
      campaign_id TEXT NOT NULL,
      from_id TEXT NOT NULL,
      to_id TEXT NOT NULL,
      travel_turns INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, from_id, to_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_spells (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      spell_id TEXT NOT NULL,
      name TEXT NOT NULL,
      level INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, character_id, spell_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_prepared_spells (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      spell_ids TEXT NOT NULL DEFAULT '[]',
      PRIMARY KEY (campaign_id, character_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_casts (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      spell_id TEXT NOT NULL,
      target TEXT NOT NULL,
      slot_level INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, character_id, sequence)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_concentration (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      spell_id TEXT NOT NULL,
      target TEXT NOT NULL,
      remaining_turns INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, character_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_inventory_items (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      item_id TEXT NOT NULL,
      quantity INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, character_id, item_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_equipment (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      slot TEXT NOT NULL,
      item_id TEXT NOT NULL,
      attuned INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (campaign_id, character_id, slot)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_encounters (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      name TEXT NOT NULL,
      status TEXT NOT NULL,
      combatants TEXT NOT NULL,
      party_combatants TEXT NOT NULL DEFAULT '[]',
      turn_round INTEGER NOT NULL DEFAULT 1,
      turn_index INTEGER NOT NULL DEFAULT 0,
      conditions TEXT NOT NULL DEFAULT '{}',
      turn_order TEXT,
      ready_actions TEXT NOT NULL DEFAULT '[]',
      xp_awarded INTEGER NOT NULL DEFAULT 0,
      loot TEXT NOT NULL DEFAULT '[]',
      rewarded INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (campaign_id, id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_loot (
      campaign_id TEXT NOT NULL,
      loot_id TEXT NOT NULL,
      item_id TEXT NOT NULL,
      quantity INTEGER NOT NULL,
      status TEXT NOT NULL DEFAULT 'open',
      recipient_character_id TEXT,
      PRIMARY KEY (campaign_id, loot_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_loot_votes (
      campaign_id TEXT NOT NULL,
      loot_id TEXT NOT NULL,
      voter TEXT NOT NULL,
      recipient_character_id TEXT NOT NULL,
      PRIMARY KEY (campaign_id, loot_id, voter)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_npcs (
      campaign_id TEXT NOT NULL,
      npc_id TEXT NOT NULL,
      name TEXT NOT NULL,
      agenda TEXT NOT NULL,
      public_status TEXT NOT NULL,
      PRIMARY KEY (campaign_id, npc_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_play_factions (
      campaign_id TEXT NOT NULL,
      faction_id TEXT NOT NULL,
      name TEXT NOT NULL,
      PRIMARY KEY (campaign_id, faction_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_faction_reputation (
      campaign_id TEXT NOT NULL,
      faction_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      reputation INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (campaign_id, faction_id, character_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_faction_reputation_history (
      campaign_id TEXT NOT NULL,
      faction_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      character_id TEXT NOT NULL,
      reputation INTEGER NOT NULL,
      delta INTEGER NOT NULL,
      reason TEXT NOT NULL,
      PRIMARY KEY (campaign_id, faction_id, sequence)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_npc_dialogue (
      campaign_id TEXT NOT NULL,
      npc_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      dialogue_id TEXT NOT NULL,
      speaker TEXT NOT NULL,
      text TEXT NOT NULL,
      visibility TEXT NOT NULL,
      PRIMARY KEY (campaign_id, npc_id, sequence)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_relationships (
      campaign_id TEXT NOT NULL,
      source_id TEXT NOT NULL,
      target_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      score INTEGER NOT NULL,
      sequence INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, source_id, target_id, kind)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_clues (
      campaign_id TEXT NOT NULL,
      clue_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      text TEXT NOT NULL,
      audience TEXT NOT NULL,
      character_id TEXT,
      PRIMARY KEY (campaign_id, clue_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_quests (
      campaign_id TEXT NOT NULL,
      quest_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      title TEXT NOT NULL,
      depends_on TEXT NOT NULL,
      state TEXT NOT NULL,
      rewards_xp INTEGER,
      rewards_items TEXT,
      rewards_awarded INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (campaign_id, quest_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_reward_grants (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      xp INTEGER NOT NULL DEFAULT 0,
      items TEXT NOT NULL DEFAULT '{}',
      PRIMARY KEY (campaign_id, character_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_world_events (
      campaign_id TEXT NOT NULL,
      event_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      turn_number INTEGER NOT NULL,
      title TEXT NOT NULL,
      text TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'scheduled',
      resolution_turn_number INTEGER,
      resolution_text TEXT,
      PRIMARY KEY (campaign_id, event_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_settlements (
      campaign_id TEXT NOT NULL,
      settlement_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      name TEXT NOT NULL,
      services TEXT NOT NULL,
      availability TEXT NOT NULL,
      discovered_by TEXT NOT NULL DEFAULT '[]',
      PRIMARY KEY (campaign_id, settlement_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_recipes (
      campaign_id TEXT NOT NULL,
      recipe_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      name TEXT NOT NULL,
      ingredients TEXT NOT NULL,
      output_item TEXT NOT NULL,
      output_quantity INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, recipe_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_shops (
      campaign_id TEXT NOT NULL,
      settlement_id TEXT NOT NULL,
      shop_id TEXT NOT NULL,
      name TEXT NOT NULL,
      stock TEXT NOT NULL,
      buy_price INTEGER NOT NULL,
      sell_price INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, settlement_id, shop_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_downtime_activities (
      campaign_id TEXT NOT NULL,
      activity_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      name TEXT NOT NULL,
      cycles_required INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, activity_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_downtime_allocations (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      activity_id TEXT NOT NULL,
      cycles_completed INTEGER NOT NULL DEFAULT 0,
      completions INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (campaign_id, character_id, activity_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_session_zero (
      campaign_id TEXT PRIMARY KEY,
      rules TEXT NOT NULL,
      tone TEXT NOT NULL,
      consent TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS play_campaign_content (
      campaign_id TEXT NOT NULL,
      content_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      text TEXT NOT NULL,
      tags TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, content_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_notes (
      campaign_id TEXT NOT NULL,
      note_id TEXT NOT NULL,
      text TEXT NOT NULL,
      visibility TEXT NOT NULL,
      owner TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, note_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_whispers (
      campaign_id TEXT NOT NULL,
      whisper_id TEXT NOT NULL,
      from_character_id TEXT NOT NULL,
      to_character_id TEXT NOT NULL,
      text TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, whisper_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_invitations (
      campaign_id TEXT NOT NULL,
      invitation_id TEXT NOT NULL,
      username TEXT NOT NULL,
      character_id TEXT NOT NULL,
      status TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, invitation_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_delegations (
      campaign_id TEXT NOT NULL,
      username TEXT NOT NULL,
      powers TEXT NOT NULL,
      active INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, username)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_delegation_audit (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      username TEXT NOT NULL,
      action TEXT NOT NULL,
      powers TEXT NOT NULL,
      PRIMARY KEY (campaign_id, sequence)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_audit_events (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      kind TEXT NOT NULL,
      actor TEXT NOT NULL,
      role TEXT NOT NULL,
      correlation_id TEXT NOT NULL,
      PRIMARY KEY (campaign_id, sequence),
      UNIQUE (campaign_id, correlation_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_projection_events (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      event_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      value TEXT,
      PRIMARY KEY (campaign_id, sequence),
      UNIQUE (campaign_id, event_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_idempotent_events (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      event_id TEXT NOT NULL,
      value TEXT NOT NULL,
      idempotency_key TEXT NOT NULL,
      PRIMARY KEY (campaign_id, sequence),
      UNIQUE (campaign_id, event_id),
      UNIQUE (campaign_id, idempotency_key)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_safe_turn_state (
      campaign_id TEXT PRIMARY KEY,
      current_turn INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS play_campaign_safe_turns (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      submission_id TEXT NOT NULL,
      action TEXT NOT NULL,
      accepted_turn INTEGER NOT NULL,
      next_turn INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, sequence),
      UNIQUE (campaign_id, submission_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_transactional_transfers (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      from_character_id TEXT NOT NULL,
      to_character_id TEXT NOT NULL,
      amount INTEGER NOT NULL,
      from_gold INTEGER NOT NULL,
      to_gold INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, sequence)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_exports (
      campaign_id TEXT NOT NULL,
      version INTEGER NOT NULL,
      story TEXT NOT NULL,
      status TEXT NOT NULL,
      PRIMARY KEY (campaign_id, version)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_imports (
      campaign_id TEXT PRIMARY KEY,
      version INTEGER NOT NULL,
      story TEXT NOT NULL,
      status TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS play_campaign_migrations (
      campaign_id TEXT PRIMARY KEY,
      schema_version INTEGER NOT NULL,
      story TEXT NOT NULL,
      campaign_name TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS play_campaign_search_records (
      campaign_id TEXT NOT NULL,
      record_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      text TEXT NOT NULL,
      PRIMARY KEY (campaign_id, record_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_rate_events (
      campaign_id TEXT NOT NULL,
      event_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      actor TEXT NOT NULL,
      PRIMARY KEY (campaign_id, event_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_metrics (
      campaign_id TEXT PRIMARY KEY,
      accepted_rate_events INTEGER NOT NULL DEFAULT 0,
      rejected_rate_events INTEGER NOT NULL DEFAULT 0,
      projection_events INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS play_campaign_backups (
      campaign_id TEXT NOT NULL,
      backup_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      story TEXT NOT NULL,
      status TEXT NOT NULL,
      PRIMARY KEY (campaign_id, backup_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_replay_events (
      campaign_id TEXT NOT NULL,
      event_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      kind TEXT NOT NULL,
      text TEXT NOT NULL,
      PRIMARY KEY (campaign_id, event_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_rng_seeds (
      campaign_id TEXT PRIMARY KEY,
      seed TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS play_campaign_rng_rolls (
      campaign_id TEXT NOT NULL,
      roll_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      sides INTEGER NOT NULL,
      result INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, roll_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_moderation_reports (
      campaign_id TEXT NOT NULL,
      report_id TEXT NOT NULL,
      target_id TEXT NOT NULL,
      reason TEXT NOT NULL,
      status TEXT NOT NULL,
      reporter TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      action TEXT,
      note TEXT,
      resolver TEXT,
      PRIMARY KEY (campaign_id, report_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_safety_boundaries (
      campaign_id TEXT PRIMARY KEY,
      blocked_tags TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS play_campaign_safety_events (
      campaign_id TEXT NOT NULL,
      event_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      text TEXT NOT NULL,
      tags TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, event_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_fixture_seeds (
      campaign_id TEXT PRIMARY KEY,
      fixture_id TEXT NOT NULL,
      status TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS play_campaign_spectators (
      spectator_id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      token TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS play_campaign_feed_events (
      campaign_id TEXT NOT NULL,
      event_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      text TEXT NOT NULL,
      PRIMARY KEY (campaign_id, event_id)
    );
  `);
  migrateSchema();
  storageInitialized = true;
}

// A pre-existing on-disk database (from an earlier stage's schema) may be
// missing columns introduced later. CREATE TABLE IF NOT EXISTS above is a
// no-op for tables that already exist, so backfill any new columns here.
function migrateSchema(): void {
  const columns = db.prepare("PRAGMA table_info(play_campaigns)").all() as { name: string }[];
  const columnNames = new Set(columns.map((column) => column.name));
  if (!columnNames.has("turn_deadline")) {
    db.exec("ALTER TABLE play_campaigns ADD COLUMN turn_deadline INTEGER");
  }
  if (!columnNames.has("turn_nudge_count")) {
    db.exec("ALTER TABLE play_campaigns ADD COLUMN turn_nudge_count INTEGER NOT NULL DEFAULT 0");
  }
  if (!columnNames.has("doc_story")) {
    db.exec("ALTER TABLE play_campaigns ADD COLUMN doc_story TEXT NOT NULL DEFAULT ''");
  }
  if (!columnNames.has("doc_dm_notes")) {
    db.exec("ALTER TABLE play_campaigns ADD COLUMN doc_dm_notes TEXT NOT NULL DEFAULT ''");
  }
  if (!columnNames.has("current_scene_id")) {
    db.exec("ALTER TABLE play_campaigns ADD COLUMN current_scene_id TEXT");
  }
  if (!columnNames.has("current_location_id")) {
    db.exec("ALTER TABLE play_campaigns ADD COLUMN current_location_id TEXT");
  }
  if (!columnNames.has("pre_combat_actor")) {
    db.exec("ALTER TABLE play_campaigns ADD COLUMN pre_combat_actor TEXT");
  }
  if (!columnNames.has("calendar_day")) {
    db.exec("ALTER TABLE play_campaigns ADD COLUMN calendar_day INTEGER");
  }
  if (!columnNames.has("calendar_season")) {
    db.exec("ALTER TABLE play_campaigns ADD COLUMN calendar_season TEXT");
  }
  if (!columnNames.has("turn_phase")) {
    db.exec("ALTER TABLE play_campaigns ADD COLUMN turn_phase TEXT");
  }

  const eventColumns = db.prepare("PRAGMA table_info(play_campaign_events)").all() as { name: string }[];
  const eventColumnNames = new Set(eventColumns.map((column) => column.name));
  if (!eventColumnNames.has("destination_id")) {
    db.exec("ALTER TABLE play_campaign_events ADD COLUMN destination_id TEXT");
  }
  if (!eventColumnNames.has("travel_turns")) {
    db.exec("ALTER TABLE play_campaign_events ADD COLUMN travel_turns INTEGER");
  }
  if (!eventColumnNames.has("action_type")) {
    db.exec("ALTER TABLE play_campaign_events ADD COLUMN action_type TEXT");
  }
  if (!eventColumnNames.has("action_target")) {
    db.exec("ALTER TABLE play_campaign_events ADD COLUMN action_target TEXT");
  }

  const memberColumns = db.prepare("PRAGMA table_info(play_campaign_members)").all() as { name: string }[];
  const memberColumnNames = new Set(memberColumns.map((column) => column.name));
  if (!memberColumnNames.has("hp_current")) {
    db.exec("ALTER TABLE play_campaign_members ADD COLUMN hp_current INTEGER NOT NULL DEFAULT 20");
  }
  if (!memberColumnNames.has("hp_max")) {
    db.exec("ALTER TABLE play_campaign_members ADD COLUMN hp_max INTEGER NOT NULL DEFAULT 20");
  }
  if (!memberColumnNames.has("status")) {
    db.exec("ALTER TABLE play_campaign_members ADD COLUMN status TEXT NOT NULL DEFAULT 'conscious'");
  }
  if (!memberColumnNames.has("death_save_successes")) {
    db.exec("ALTER TABLE play_campaign_members ADD COLUMN death_save_successes INTEGER NOT NULL DEFAULT 0");
  }
  if (!memberColumnNames.has("death_save_failures")) {
    db.exec("ALTER TABLE play_campaign_members ADD COLUMN death_save_failures INTEGER NOT NULL DEFAULT 0");
  }
  if (!memberColumnNames.has("owner")) {
    db.exec("ALTER TABLE play_campaign_members ADD COLUMN owner TEXT");
  }
  if (!memberColumnNames.has("race")) {
    db.exec("ALTER TABLE play_campaign_members ADD COLUMN race TEXT");
  }
  if (!memberColumnNames.has("background")) {
    db.exec("ALTER TABLE play_campaign_members ADD COLUMN background TEXT");
  }
  if (!memberColumnNames.has("level")) {
    db.exec("ALTER TABLE play_campaign_members ADD COLUMN level INTEGER NOT NULL DEFAULT 1");
  }
  if (!memberColumnNames.has("proficiency_bonus")) {
    db.exec("ALTER TABLE play_campaign_members ADD COLUMN proficiency_bonus INTEGER NOT NULL DEFAULT 2");
  }
  if (!memberColumnNames.has("con_modifier")) {
    db.exec("ALTER TABLE play_campaign_members ADD COLUMN con_modifier INTEGER NOT NULL DEFAULT 0");
  }
  if (!memberColumnNames.has("str_modifier")) {
    db.exec("ALTER TABLE play_campaign_members ADD COLUMN str_modifier INTEGER NOT NULL DEFAULT 0");
  }
  if (!memberColumnNames.has("dex_modifier")) {
    db.exec("ALTER TABLE play_campaign_members ADD COLUMN dex_modifier INTEGER NOT NULL DEFAULT 0");
  }
  if (!memberColumnNames.has("int_modifier")) {
    db.exec("ALTER TABLE play_campaign_members ADD COLUMN int_modifier INTEGER NOT NULL DEFAULT 0");
  }
  if (!memberColumnNames.has("wis_modifier")) {
    db.exec("ALTER TABLE play_campaign_members ADD COLUMN wis_modifier INTEGER NOT NULL DEFAULT 0");
  }
  if (!memberColumnNames.has("cha_modifier")) {
    db.exec("ALTER TABLE play_campaign_members ADD COLUMN cha_modifier INTEGER NOT NULL DEFAULT 0");
  }
  if (!memberColumnNames.has("gold")) {
    db.exec("ALTER TABLE play_campaign_members ADD COLUMN gold INTEGER NOT NULL DEFAULT 10");
  }

  const encounterColumns = db.prepare("PRAGMA table_info(play_campaign_encounters)").all() as { name: string }[];
  const encounterColumnNames = new Set(encounterColumns.map((column) => column.name));
  if (!encounterColumnNames.has("party_combatants")) {
    db.exec("ALTER TABLE play_campaign_encounters ADD COLUMN party_combatants TEXT NOT NULL DEFAULT '[]'");
  }
  if (!encounterColumnNames.has("turn_round")) {
    db.exec("ALTER TABLE play_campaign_encounters ADD COLUMN turn_round INTEGER NOT NULL DEFAULT 1");
  }
  if (!encounterColumnNames.has("turn_index")) {
    db.exec("ALTER TABLE play_campaign_encounters ADD COLUMN turn_index INTEGER NOT NULL DEFAULT 0");
  }
  if (!encounterColumnNames.has("conditions")) {
    db.exec("ALTER TABLE play_campaign_encounters ADD COLUMN conditions TEXT NOT NULL DEFAULT '{}'");
  }
  if (!encounterColumnNames.has("turn_order")) {
    db.exec("ALTER TABLE play_campaign_encounters ADD COLUMN turn_order TEXT");
  }
  if (!encounterColumnNames.has("ready_actions")) {
    db.exec("ALTER TABLE play_campaign_encounters ADD COLUMN ready_actions TEXT NOT NULL DEFAULT '[]'");
  }
  if (!encounterColumnNames.has("xp_awarded")) {
    db.exec("ALTER TABLE play_campaign_encounters ADD COLUMN xp_awarded INTEGER NOT NULL DEFAULT 0");
  }
  if (!encounterColumnNames.has("loot")) {
    db.exec("ALTER TABLE play_campaign_encounters ADD COLUMN loot TEXT NOT NULL DEFAULT '[]'");
  }
  if (!encounterColumnNames.has("rewarded")) {
    db.exec("ALTER TABLE play_campaign_encounters ADD COLUMN rewarded INTEGER NOT NULL DEFAULT 0");
  }

  const questColumns = db.prepare("PRAGMA table_info(play_campaign_quests)").all() as { name: string }[];
  const questColumnNames = new Set(questColumns.map((column) => column.name));
  if (!questColumnNames.has("rewards_xp")) {
    db.exec("ALTER TABLE play_campaign_quests ADD COLUMN rewards_xp INTEGER");
  }
  if (!questColumnNames.has("rewards_items")) {
    db.exec("ALTER TABLE play_campaign_quests ADD COLUMN rewards_items TEXT");
  }
  if (!questColumnNames.has("rewards_awarded")) {
    db.exec("ALTER TABLE play_campaign_quests ADD COLUMN rewards_awarded INTEGER NOT NULL DEFAULT 0");
  }
}

// Each process start is a fresh test run: any on-disk database from a prior
// run belongs to that run's process lifetime, not this one. Data persists
// across requests and reconnects *within* a run (see resetDatabase for the
// in-suite reset path), but never leaks across separate server starts.
export function openDatabase(): void {
  fs.rmSync(DB_PATH, { force: true });
  db = new DatabaseSync(DB_PATH);
  initSchema();
}

export function resetDatabase(): void {
  db.exec(`
    DROP TABLE IF EXISTS users;
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
    DROP TABLE IF EXISTS campaign_crafting;
    DROP TABLE IF EXISTS campaign_sessions;
    DROP TABLE IF EXISTS play_campaigns;
    DROP TABLE IF EXISTS play_campaign_members;
    DROP TABLE IF EXISTS play_campaign_events;
    DROP TABLE IF EXISTS play_campaign_scenes;
    DROP TABLE IF EXISTS play_campaign_locations;
    DROP TABLE IF EXISTS play_campaign_connections;
    DROP TABLE IF EXISTS play_campaign_encounters;
    DROP TABLE IF EXISTS play_campaign_spells;
    DROP TABLE IF EXISTS play_campaign_prepared_spells;
    DROP TABLE IF EXISTS play_campaign_casts;
    DROP TABLE IF EXISTS play_campaign_concentration;
    DROP TABLE IF EXISTS play_campaign_inventory_items;
    DROP TABLE IF EXISTS play_campaign_equipment;
    DROP TABLE IF EXISTS play_campaign_transfers;
    DROP TABLE IF EXISTS play_campaign_loot;
    DROP TABLE IF EXISTS play_campaign_loot_votes;
    DROP TABLE IF EXISTS play_campaign_npcs;
    DROP TABLE IF EXISTS play_campaign_play_factions;
    DROP TABLE IF EXISTS play_campaign_faction_reputation;
    DROP TABLE IF EXISTS play_campaign_faction_reputation_history;
    DROP TABLE IF EXISTS play_campaign_npc_dialogue;
    DROP TABLE IF EXISTS play_campaign_relationships;
    DROP TABLE IF EXISTS play_campaign_clues;
    DROP TABLE IF EXISTS play_campaign_quests;
    DROP TABLE IF EXISTS play_campaign_reward_grants;
    DROP TABLE IF EXISTS play_campaign_world_events;
    DROP TABLE IF EXISTS play_campaign_settlements;
    DROP TABLE IF EXISTS play_campaign_shops;
    DROP TABLE IF EXISTS play_campaign_recipes;
    DROP TABLE IF EXISTS play_campaign_downtime_activities;
    DROP TABLE IF EXISTS play_campaign_downtime_allocations;
    DROP TABLE IF EXISTS play_campaign_session_zero;
    DROP TABLE IF EXISTS play_campaign_content;
    DROP TABLE IF EXISTS play_campaign_notes;
    DROP TABLE IF EXISTS play_campaign_whispers;
    DROP TABLE IF EXISTS play_campaign_invitations;
    DROP TABLE IF EXISTS play_campaign_delegations;
    DROP TABLE IF EXISTS play_campaign_delegation_audit;
    DROP TABLE IF EXISTS play_campaign_audit_events;
    DROP TABLE IF EXISTS play_campaign_backups;
    DROP TABLE IF EXISTS play_campaign_replay_events;
    DROP TABLE IF EXISTS play_campaign_rng_seeds;
    DROP TABLE IF EXISTS play_campaign_rng_rolls;
    DROP TABLE IF EXISTS play_campaign_moderation_reports;
    DROP TABLE IF EXISTS play_campaign_safety_boundaries;
    DROP TABLE IF EXISTS play_campaign_safety_events;
    DROP TABLE IF EXISTS play_campaign_fixture_seeds;
    DROP TABLE IF EXISTS play_campaign_spectators;
    DROP TABLE IF EXISTS play_campaign_feed_events;
  `);
  initSchema();
}
