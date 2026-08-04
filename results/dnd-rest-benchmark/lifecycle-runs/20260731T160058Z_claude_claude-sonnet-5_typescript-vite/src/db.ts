import { DatabaseSync } from 'node:sqlite';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';

export const SCHEMA_VERSION = 1;

const projectRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const DB_PATH = path.join(projectRoot, 'game.db');

let db: DatabaseSync | null = null;
let initialized = false;

function createSchema(handle: DatabaseSync): void {
  handle.exec(`
    CREATE TABLE IF NOT EXISTS users (
      username TEXT PRIMARY KEY,
      role TEXT NOT NULL,
      password_hash TEXT NOT NULL,
      salt TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS combat_sessions (
      id TEXT PRIMARY KEY,
      round INTEGER NOT NULL,
      turn_index INTEGER NOT NULL,
      order_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS combat_conditions (
      session_id TEXT NOT NULL,
      target TEXT NOT NULL,
      conditions_json TEXT NOT NULL,
      PRIMARY KEY (session_id, target)
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
      cost_gp REAL NOT NULL
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
      milestones_json TEXT NOT NULL,
      completed_json TEXT NOT NULL,
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
      PRIMARY KEY (campaign_id, item_slug, owner)
    );
    CREATE TABLE IF NOT EXISTS campaign_equipment (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      item_slug TEXT NOT NULL,
      quantity INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, character_id, item_slug)
    );
    CREATE TABLE IF NOT EXISTS campaign_crafting_projects (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      item_slug TEXT NOT NULL,
      days_required INTEGER NOT NULL,
      days_completed INTEGER NOT NULL,
      cost_gp REAL NOT NULL,
      status TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );
    CREATE TABLE IF NOT EXISTS campaign_sessions (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      starts_at TEXT NOT NULL,
      duration_minutes INTEGER NOT NULL,
      agenda_json TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );
    CREATE TABLE IF NOT EXISTS campaign_session_attendance (
      campaign_id TEXT NOT NULL,
      session_id TEXT NOT NULL,
      present_json TEXT NOT NULL,
      absent_json TEXT NOT NULL,
      PRIMARY KEY (campaign_id, session_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaigns (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      owner TEXT NOT NULL,
      status TEXT NOT NULL,
      max_players INTEGER NOT NULL,
      current_actor TEXT,
      turn_number INTEGER,
      turn_nudge_count INTEGER NOT NULL DEFAULT 0,
      story TEXT NOT NULL DEFAULT '',
      dm_notes TEXT NOT NULL DEFAULT '',
      current_scene_id TEXT,
      current_location_id TEXT,
      phase TEXT
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
      level INTEGER NOT NULL DEFAULT 1,
      con_modifier INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (campaign_id, username)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_events (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      kind TEXT NOT NULL,
      actor TEXT NOT NULL,
      text TEXT NOT NULL,
      action_type TEXT,
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
    CREATE TABLE IF NOT EXISTS play_campaign_location_connections (
      campaign_id TEXT NOT NULL,
      from_id TEXT NOT NULL,
      to_id TEXT NOT NULL,
      travel_turns INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, from_id, to_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_encounters (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      name TEXT NOT NULL,
      status TEXT NOT NULL,
      combatants_json TEXT NOT NULL DEFAULT '[]',
      party_combatants_json TEXT NOT NULL DEFAULT '[]',
      round INTEGER NOT NULL DEFAULT 1,
      turn_index INTEGER NOT NULL DEFAULT 0,
      conditions_json TEXT NOT NULL DEFAULT '{}',
      order_override_json TEXT,
      rewards_json TEXT,
      xp_awarded INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (campaign_id, id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_character_owners (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      owner TEXT NOT NULL,
      PRIMARY KEY (campaign_id, character_id)
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
      spell_id TEXT NOT NULL,
      PRIMARY KEY (campaign_id, character_id, spell_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_casts (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      spell_id TEXT NOT NULL,
      target TEXT NOT NULL,
      slot_level INTEGER NOT NULL,
      slots_remaining INTEGER NOT NULL,
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
    CREATE TABLE IF NOT EXISTS play_campaign_inventory_stacks (
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
    CREATE TABLE IF NOT EXISTS play_campaign_currency_transfers (
      campaign_id TEXT NOT NULL,
      transfer_id INTEGER NOT NULL,
      from_character_id TEXT NOT NULL,
      to_character_id TEXT NOT NULL,
      gold INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, transfer_id)
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
    CREATE TABLE IF NOT EXISTS play_campaign_factions (
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
      sequence INTEGER NOT NULL,
      source_id TEXT NOT NULL,
      target_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      score INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, source_id, target_id, kind)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_clues (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      clue_id TEXT NOT NULL,
      text TEXT NOT NULL,
      audience TEXT NOT NULL,
      character_id TEXT,
      PRIMARY KEY (campaign_id, clue_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_quests (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      quest_id TEXT NOT NULL,
      title TEXT NOT NULL,
      depends_on_json TEXT NOT NULL,
      state TEXT NOT NULL,
      rewards_xp INTEGER,
      rewards_items_json TEXT,
      rewards_awarded INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (campaign_id, quest_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_quest_reward_grants (
      campaign_id TEXT NOT NULL,
      quest_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      xp INTEGER NOT NULL,
      items_json TEXT NOT NULL,
      PRIMARY KEY (campaign_id, quest_id, character_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_world_events (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      event_id TEXT NOT NULL,
      turn_number INTEGER NOT NULL,
      title TEXT NOT NULL,
      text TEXT NOT NULL,
      status TEXT NOT NULL,
      resolution_turn_number INTEGER,
      resolution_text TEXT,
      PRIMARY KEY (campaign_id, event_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_calendars (
      campaign_id TEXT PRIMARY KEY,
      day INTEGER NOT NULL,
      season TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS play_campaign_settlements (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      settlement_id TEXT NOT NULL,
      name TEXT NOT NULL,
      services_json TEXT NOT NULL,
      availability TEXT NOT NULL,
      PRIMARY KEY (campaign_id, settlement_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_settlement_discoveries (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      settlement_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      PRIMARY KEY (campaign_id, settlement_id, character_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_shops (
      campaign_id TEXT NOT NULL,
      settlement_id TEXT NOT NULL,
      shop_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      name TEXT NOT NULL,
      stock_json TEXT NOT NULL,
      buy_price INTEGER NOT NULL,
      sell_price INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, settlement_id, shop_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_recipes (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      recipe_id TEXT NOT NULL,
      name TEXT NOT NULL,
      ingredients_json TEXT NOT NULL,
      output_item TEXT NOT NULL,
      output_quantity INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, recipe_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_downtime_activities (
      campaign_id TEXT NOT NULL,
      activity_id TEXT NOT NULL,
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
      consent_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS play_campaign_content (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      content_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      text TEXT NOT NULL,
      tags_json TEXT NOT NULL,
      PRIMARY KEY (campaign_id, content_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_notes (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      note_id TEXT NOT NULL,
      text TEXT NOT NULL,
      visibility TEXT NOT NULL,
      owner TEXT NOT NULL,
      PRIMARY KEY (campaign_id, note_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_whispers (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      whisper_id TEXT NOT NULL,
      from_character_id TEXT NOT NULL,
      to_character_id TEXT NOT NULL,
      text TEXT NOT NULL,
      PRIMARY KEY (campaign_id, whisper_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_invitations (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      invitation_id TEXT NOT NULL,
      username TEXT NOT NULL,
      character_id TEXT NOT NULL,
      status TEXT NOT NULL,
      PRIMARY KEY (campaign_id, invitation_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_delegations (
      campaign_id TEXT NOT NULL,
      username TEXT NOT NULL,
      powers_json TEXT NOT NULL,
      active INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, username)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_delegation_audit (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      username TEXT NOT NULL,
      action TEXT NOT NULL,
      powers_json TEXT NOT NULL,
      PRIMARY KEY (campaign_id, sequence)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_audit_events (
      campaign_id TEXT NOT NULL,
      timestamp INTEGER NOT NULL,
      kind TEXT NOT NULL,
      actor TEXT NOT NULL,
      role TEXT NOT NULL,
      correlation_id TEXT NOT NULL,
      PRIMARY KEY (campaign_id, timestamp),
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
    CREATE TABLE IF NOT EXISTS play_campaign_safe_turns (
      campaign_id TEXT PRIMARY KEY,
      current_turn INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS play_campaign_safe_turn_submissions (
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
      input_story TEXT NOT NULL,
      story TEXT NOT NULL,
      campaign_name TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS play_campaign_search_records (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      record_id TEXT NOT NULL,
      text TEXT NOT NULL,
      PRIMARY KEY (campaign_id, record_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_rate_events (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      event_id TEXT NOT NULL,
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
      sequence INTEGER NOT NULL,
      backup_id TEXT NOT NULL,
      story TEXT NOT NULL,
      status TEXT NOT NULL,
      PRIMARY KEY (campaign_id, backup_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_replay_events (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      event_id TEXT NOT NULL,
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
      sequence INTEGER NOT NULL,
      roll_id TEXT NOT NULL,
      sides INTEGER NOT NULL,
      result INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, roll_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_moderation_reports (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      report_id TEXT NOT NULL,
      target_id TEXT NOT NULL,
      reason TEXT NOT NULL,
      status TEXT NOT NULL,
      reporter TEXT NOT NULL,
      action TEXT,
      note TEXT,
      resolver TEXT,
      PRIMARY KEY (campaign_id, report_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_safety_boundaries (
      campaign_id TEXT PRIMARY KEY,
      blocked_tags_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS play_campaign_safety_events (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      event_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      text TEXT NOT NULL,
      tags_json TEXT NOT NULL,
      PRIMARY KEY (campaign_id, event_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_fixture_seeds (
      campaign_id TEXT NOT NULL,
      fixture_id TEXT NOT NULL,
      PRIMARY KEY (campaign_id, fixture_id)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_spectators (
      campaign_id TEXT NOT NULL,
      spectator_id TEXT PRIMARY KEY,
      token TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS play_campaign_feed_events (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      event_id TEXT NOT NULL,
      text TEXT NOT NULL,
      PRIMARY KEY (campaign_id, event_id)
    );
  `);
}

function migrateSchema(handle: DatabaseSync): void {
  const columns = handle.prepare('PRAGMA table_info(play_campaigns)').all() as { name: string }[];
  const names = new Set(columns.map((column) => column.name));
  if (!names.has('current_actor')) {
    handle.exec('ALTER TABLE play_campaigns ADD COLUMN current_actor TEXT');
  }
  if (!names.has('turn_number')) {
    handle.exec('ALTER TABLE play_campaigns ADD COLUMN turn_number INTEGER');
  }
  if (!names.has('turn_nudge_count')) {
    handle.exec('ALTER TABLE play_campaigns ADD COLUMN turn_nudge_count INTEGER NOT NULL DEFAULT 0');
  }
  if (!names.has('story')) {
    handle.exec("ALTER TABLE play_campaigns ADD COLUMN story TEXT NOT NULL DEFAULT ''");
  }
  if (!names.has('dm_notes')) {
    handle.exec("ALTER TABLE play_campaigns ADD COLUMN dm_notes TEXT NOT NULL DEFAULT ''");
  }
  if (!names.has('current_scene_id')) {
    handle.exec('ALTER TABLE play_campaigns ADD COLUMN current_scene_id TEXT');
  }
  if (!names.has('current_location_id')) {
    handle.exec('ALTER TABLE play_campaigns ADD COLUMN current_location_id TEXT');
  }
  if (!names.has('phase')) {
    handle.exec('ALTER TABLE play_campaigns ADD COLUMN phase TEXT');
  }

  const eventColumns = handle.prepare('PRAGMA table_info(play_campaign_events)').all() as { name: string }[];
  const eventNames = new Set(eventColumns.map((column) => column.name));
  if (!eventNames.has('action_type')) {
    handle.exec('ALTER TABLE play_campaign_events ADD COLUMN action_type TEXT');
  }

  const memberColumns = handle.prepare('PRAGMA table_info(play_campaign_members)').all() as { name: string }[];
  const memberNames = new Set(memberColumns.map((column) => column.name));
  if (!memberNames.has('hp_current')) {
    handle.exec('ALTER TABLE play_campaign_members ADD COLUMN hp_current INTEGER NOT NULL DEFAULT 20');
  }
  if (!memberNames.has('hp_max')) {
    handle.exec('ALTER TABLE play_campaign_members ADD COLUMN hp_max INTEGER NOT NULL DEFAULT 20');
  }
  if (!memberNames.has('status')) {
    handle.exec("ALTER TABLE play_campaign_members ADD COLUMN status TEXT NOT NULL DEFAULT 'conscious'");
  }
  if (!memberNames.has('death_save_successes')) {
    handle.exec('ALTER TABLE play_campaign_members ADD COLUMN death_save_successes INTEGER NOT NULL DEFAULT 0');
  }
  if (!memberNames.has('death_save_failures')) {
    handle.exec('ALTER TABLE play_campaign_members ADD COLUMN death_save_failures INTEGER NOT NULL DEFAULT 0');
  }
  if (!memberNames.has('level')) {
    handle.exec('ALTER TABLE play_campaign_members ADD COLUMN level INTEGER NOT NULL DEFAULT 1');
  }
  if (!memberNames.has('con_modifier')) {
    handle.exec('ALTER TABLE play_campaign_members ADD COLUMN con_modifier INTEGER NOT NULL DEFAULT 0');
  }
  for (const ability of ['str', 'dex', 'int', 'wis', 'cha']) {
    const column = `${ability}_modifier`;
    if (!memberNames.has(column)) {
      handle.exec(`ALTER TABLE play_campaign_members ADD COLUMN ${column} INTEGER NOT NULL DEFAULT 0`);
    }
  }
  if (!memberNames.has('gold')) {
    handle.exec('ALTER TABLE play_campaign_members ADD COLUMN gold INTEGER NOT NULL DEFAULT 10');
  }

  const encounterColumns = handle.prepare('PRAGMA table_info(play_campaign_encounters)').all() as { name: string }[];
  const encounterNames = new Set(encounterColumns.map((column) => column.name));
  if (!encounterNames.has('party_combatants_json')) {
    handle.exec("ALTER TABLE play_campaign_encounters ADD COLUMN party_combatants_json TEXT NOT NULL DEFAULT '[]'");
  }
  if (!encounterNames.has('round')) {
    handle.exec('ALTER TABLE play_campaign_encounters ADD COLUMN round INTEGER NOT NULL DEFAULT 1');
  }
  if (!encounterNames.has('turn_index')) {
    handle.exec('ALTER TABLE play_campaign_encounters ADD COLUMN turn_index INTEGER NOT NULL DEFAULT 0');
  }
  if (!encounterNames.has('conditions_json')) {
    handle.exec("ALTER TABLE play_campaign_encounters ADD COLUMN conditions_json TEXT NOT NULL DEFAULT '{}'");
  }
  if (!encounterNames.has('order_override_json')) {
    handle.exec('ALTER TABLE play_campaign_encounters ADD COLUMN order_override_json TEXT');
  }
  if (!encounterNames.has('rewards_json')) {
    handle.exec('ALTER TABLE play_campaign_encounters ADD COLUMN rewards_json TEXT');
  }
  if (!encounterNames.has('xp_awarded')) {
    handle.exec('ALTER TABLE play_campaign_encounters ADD COLUMN xp_awarded INTEGER NOT NULL DEFAULT 0');
  }

  const questColumns = handle.prepare('PRAGMA table_info(play_campaign_quests)').all() as { name: string }[];
  const questNames = new Set(questColumns.map((column) => column.name));
  if (!questNames.has('rewards_xp')) {
    handle.exec('ALTER TABLE play_campaign_quests ADD COLUMN rewards_xp INTEGER');
  }
  if (!questNames.has('rewards_items_json')) {
    handle.exec('ALTER TABLE play_campaign_quests ADD COLUMN rewards_items_json TEXT');
  }
  if (!questNames.has('rewards_awarded')) {
    handle.exec('ALTER TABLE play_campaign_quests ADD COLUMN rewards_awarded INTEGER NOT NULL DEFAULT 0');
  }
}

export function getDb(): DatabaseSync {
  if (!db) {
    const attempts = 5;
    let lastError: unknown;
    for (let attempt = 0; attempt < attempts; attempt++) {
      try {
        if (fs.existsSync(DB_PATH)) {
          fs.rmSync(DB_PATH);
        }
        const handle = new DatabaseSync(DB_PATH);
        createSchema(handle);
        migrateSchema(handle);
        db = handle;
        initialized = true;
        return db;
      } catch (error) {
        lastError = error;
      }
    }
    throw lastError;
  }
  return db;
}

export function isInitialized(): boolean {
  return initialized;
}

export function resetStorage(): void {
  const handle = getDb();
  handle.exec(`
    DROP TABLE IF EXISTS users;
    DROP TABLE IF EXISTS combat_sessions;
    DROP TABLE IF EXISTS combat_conditions;
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
    DROP TABLE IF EXISTS campaign_session_attendance;
    DROP TABLE IF EXISTS play_campaigns;
    DROP TABLE IF EXISTS play_campaign_members;
    DROP TABLE IF EXISTS play_campaign_events;
    DROP TABLE IF EXISTS play_campaign_scenes;
    DROP TABLE IF EXISTS play_campaign_locations;
    DROP TABLE IF EXISTS play_campaign_location_connections;
    DROP TABLE IF EXISTS play_campaign_encounters;
    DROP TABLE IF EXISTS play_campaign_character_owners;
    DROP TABLE IF EXISTS play_campaign_spells;
    DROP TABLE IF EXISTS play_campaign_prepared_spells;
    DROP TABLE IF EXISTS play_campaign_casts;
    DROP TABLE IF EXISTS play_campaign_concentration;
    DROP TABLE IF EXISTS play_campaign_inventory_stacks;
    DROP TABLE IF EXISTS play_campaign_equipment;
    DROP TABLE IF EXISTS play_campaign_currency_transfers;
    DROP TABLE IF EXISTS play_campaign_loot;
    DROP TABLE IF EXISTS play_campaign_loot_votes;
    DROP TABLE IF EXISTS play_campaign_npcs;
    DROP TABLE IF EXISTS play_campaign_factions;
    DROP TABLE IF EXISTS play_campaign_faction_reputation;
    DROP TABLE IF EXISTS play_campaign_faction_reputation_history;
    DROP TABLE IF EXISTS play_campaign_npc_dialogue;
    DROP TABLE IF EXISTS play_campaign_relationships;
    DROP TABLE IF EXISTS play_campaign_clues;
    DROP TABLE IF EXISTS play_campaign_quests;
    DROP TABLE IF EXISTS play_campaign_quest_reward_grants;
    DROP TABLE IF EXISTS play_campaign_world_events;
    DROP TABLE IF EXISTS play_campaign_calendars;
    DROP TABLE IF EXISTS play_campaign_settlements;
    DROP TABLE IF EXISTS play_campaign_settlement_discoveries;
    DROP TABLE IF EXISTS play_campaign_shops;
    DROP TABLE IF EXISTS play_campaign_recipes;
    DROP TABLE IF EXISTS play_campaign_downtime_activities;
    DROP TABLE IF EXISTS play_campaign_downtime_allocations;
    DROP TABLE IF EXISTS play_campaign_notes;
    DROP TABLE IF EXISTS play_campaign_whispers;
    DROP TABLE IF EXISTS play_campaign_invitations;
    DROP TABLE IF EXISTS play_campaign_delegations;
    DROP TABLE IF EXISTS play_campaign_delegation_audit;
    DROP TABLE IF EXISTS play_campaign_audit_events;
    DROP TABLE IF EXISTS play_campaign_projection_events;
    DROP TABLE IF EXISTS play_campaign_idempotent_events;
    DROP TABLE IF EXISTS play_campaign_safe_turns;
    DROP TABLE IF EXISTS play_campaign_safe_turn_submissions;
    DROP TABLE IF EXISTS play_campaign_transactional_transfers;
    DROP TABLE IF EXISTS play_campaign_exports;
    DROP TABLE IF EXISTS play_campaign_imports;
    DROP TABLE IF EXISTS play_campaign_migrations;
    DROP TABLE IF EXISTS play_campaign_search_records;
    DROP TABLE IF EXISTS play_campaign_rate_events;
    DROP TABLE IF EXISTS play_campaign_metrics;
    DROP TABLE IF EXISTS play_campaign_backups;
    DROP TABLE IF EXISTS play_campaign_replay_events;
    DROP TABLE IF EXISTS play_campaign_rng_seeds;
    DROP TABLE IF EXISTS play_campaign_rng_rolls;
    DROP TABLE IF EXISTS play_campaign_moderation_reports;
    DROP TABLE IF EXISTS play_campaign_safety_boundaries;
    DROP TABLE IF EXISTS play_campaign_safety_events;
    DROP TABLE IF EXISTS play_campaign_fixture_seeds;
    DROP TABLE IF EXISTS play_campaign_feed_events;
  `);
  createSchema(handle);
  migrateSchema(handle);
}
