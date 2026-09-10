# frozen_string_literal: true

require 'sqlite3'
require_relative 'config'

# SQLite persistence layer.
#
# A single shared database connection is protected by a global mutex. This
# avoids connection-pooling edge cases and keeps behavior deterministic. All
# domain modules access the database through Persistence.db { |d| ... }.
module Persistence
  DB_MUTEX = Mutex.new
  DATABASE = SQLite3::Database.new(Config::DB_PATH)
  DATABASE.busy_timeout = 1000
  DATABASE.results_as_hash = false

  # Application tables in dependency order. Used to build reset drop lists.
  APP_TABLES = %w[
    users
    combat_conditions combat_sessions
    compendium_monsters compendium_items
    campaigns campaign_characters campaign_events campaign_quests campaign_factions campaign_npcs
    campaign_inventory campaign_crafting_projects campaign_sessions session_attendance
    play_campaigns play_campaign_members play_character_spells play_character_prepared_spells play_character_casts play_character_concentration play_character_inventory play_character_equipment play_character_currency play_currency_transfers play_narrations play_campaign_documents play_campaign_scenes
    play_locations play_location_connections play_encounters play_encounter_monsters
    play_encounter_actions play_encounter_conditions play_encounter_rewards
    play_loot play_loot_votes play_campaign_npcs play_npc_dialogue play_factions play_reputation_history
    play_relationships
    play_campaign_quests
    play_character_quest_rewards
    play_clues
    play_world_events
    play_campaign_calendars
    play_settlements
    play_shops
    play_recipes
    play_recipe_ingredients
    play_downtime_activities
    play_downtime_allocations
    play_campaign_session_zero
    play_campaign_content
    play_campaign_notes
    play_campaign_whispers
    play_campaign_invitations
    play_campaign_delegations
    play_delegation_audit
    play_audit_events
    play_projection_events
    play_idempotent_events
    play_safe_turns
    play_transactional_transfers
    play_campaign_exports
    play_campaign_imports
    play_campaign_migrations
    play_search_records
    play_rate_events
    play_campaign_metrics
    play_campaign_backups
    play_replay_events
    play_rng_ledger
    play_rng_rolls
    play_moderation_reports
    play_safety_boundaries
    play_safety_events
    play_fixture_seeds
    play_campaign_spectators
    play_feed_events
    schema_meta
  ].freeze

  # Tables dropped by a hard reset (everything).
  RESET_TABLES = APP_TABLES

  # Tables dropped by a soft reset (everything except users and schema_meta).
  SOFT_RESET_TABLES = APP_TABLES - %w[users schema_meta]

  SCHEMA_SQL = <<~SQL
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
      order_json TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS combat_conditions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id TEXT NOT NULL,
      target TEXT NOT NULL,
      condition TEXT NOT NULL,
      remaining_rounds INTEGER NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_conditions_session_target ON combat_conditions(session_id, target);

    CREATE TABLE IF NOT EXISTS compendium_monsters (
      slug TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      cr TEXT NOT NULL,
      armor_class INTEGER NOT NULL,
      hit_points INTEGER NOT NULL,
      tags_json TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS compendium_items (
      slug TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      type TEXT NOT NULL,
      rarity TEXT NOT NULL,
      cost_gp INTEGER NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_compendium_monsters_slug ON compendium_monsters(slug);
    CREATE INDEX IF NOT EXISTS idx_compendium_items_slug ON compendium_items(slug);

    CREATE TABLE IF NOT EXISTS schema_meta (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );

    INSERT OR IGNORE INTO schema_meta (key, value) VALUES ('schema_version', '#{Config::SCHEMA_VERSION}');

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

    CREATE INDEX IF NOT EXISTS idx_campaign_characters_campaign ON campaign_characters(campaign_id);
    CREATE INDEX IF NOT EXISTS idx_campaign_events_campaign ON campaign_events(campaign_id);

    CREATE TABLE IF NOT EXISTS campaign_quests (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      title TEXT NOT NULL,
      status TEXT NOT NULL,
      milestones_json TEXT NOT NULL,
      completed_json TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_campaign_quests_campaign ON campaign_quests(campaign_id);

    CREATE TABLE IF NOT EXISTS campaign_factions (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      name TEXT NOT NULL,
      stance TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_campaign_factions_campaign ON campaign_factions(campaign_id);

    CREATE TABLE IF NOT EXISTS campaign_npcs (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      faction_id TEXT NOT NULL,
      name TEXT NOT NULL,
      disposition INTEGER NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_campaign_npcs_campaign ON campaign_npcs(campaign_id);

    CREATE TABLE IF NOT EXISTS campaign_inventory (
      campaign_id TEXT NOT NULL,
      item_slug TEXT NOT NULL,
      owner TEXT NOT NULL,
      quantity INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, item_slug, owner)
    );

    CREATE INDEX IF NOT EXISTS idx_campaign_inventory_campaign ON campaign_inventory(campaign_id);

    CREATE TABLE IF NOT EXISTS campaign_crafting_projects (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      item_slug TEXT NOT NULL,
      days_required INTEGER NOT NULL,
      days_completed INTEGER NOT NULL,
      cost_gp INTEGER NOT NULL,
      status TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_campaign_crafting_projects_campaign ON campaign_crafting_projects(campaign_id);

    CREATE TABLE IF NOT EXISTS campaign_sessions (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      starts_at TEXT NOT NULL,
      duration_minutes INTEGER NOT NULL,
      agenda_json TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_campaign_sessions_campaign_starts ON campaign_sessions(campaign_id, starts_at);

    CREATE TABLE IF NOT EXISTS session_attendance (
      session_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      status TEXT NOT NULL,
      PRIMARY KEY (session_id, character_id)
    );

    CREATE INDEX IF NOT EXISTS idx_session_attendance_session ON session_attendance(session_id);

    CREATE TABLE IF NOT EXISTS play_campaigns (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      owner TEXT NOT NULL,
      status TEXT NOT NULL,
      max_players INTEGER NOT NULL,
      current_actor TEXT,
      turn_number INTEGER,
      nudge_count INTEGER NOT NULL DEFAULT 0,
      current_scene_id TEXT,
      current_location_id TEXT,
      phase TEXT NOT NULL DEFAULT 'exploration',
      pre_combat_actor TEXT,
      safe_turn_current INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS play_campaign_members (
      campaign_id TEXT NOT NULL,
      username TEXT NOT NULL,
      character_id TEXT NOT NULL,
      name TEXT NOT NULL,
      class TEXT NOT NULL,
      owner TEXT,
      race TEXT,
      background TEXT,
      abilities_json TEXT,
      level INTEGER NOT NULL DEFAULT 1,
      hp_current INTEGER NOT NULL DEFAULT 20,
      hp_max INTEGER NOT NULL DEFAULT 20,
      status TEXT NOT NULL DEFAULT 'conscious',
      death_save_successes INTEGER NOT NULL DEFAULT 0,
      death_save_failures INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (campaign_id, username),
      UNIQUE (campaign_id, character_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_campaign_members_campaign ON play_campaign_members(campaign_id);
    CREATE INDEX IF NOT EXISTS idx_play_campaign_members_owner ON play_campaign_members(campaign_id, owner);

    CREATE TABLE IF NOT EXISTS play_character_spells (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      spell_id TEXT NOT NULL,
      name TEXT NOT NULL,
      level INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, character_id, spell_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_character_spells_character ON play_character_spells(campaign_id, character_id);

    CREATE TABLE IF NOT EXISTS play_character_prepared_spells (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      spell_id TEXT NOT NULL,
      prepared_order INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, character_id, spell_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_character_prepared_spells_character ON play_character_prepared_spells(campaign_id, character_id);

    CREATE TABLE IF NOT EXISTS play_character_casts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      spell_id TEXT NOT NULL,
      target TEXT NOT NULL,
      slot_level INTEGER NOT NULL,
      slots_remaining INTEGER NOT NULL,
      sequence INTEGER NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_play_character_casts_character ON play_character_casts(campaign_id, character_id);

    CREATE TABLE IF NOT EXISTS play_character_concentration (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      spell_id TEXT NOT NULL,
      target TEXT NOT NULL,
      remaining_turns INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, character_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_character_concentration_character ON play_character_concentration(campaign_id, character_id);

    CREATE TABLE IF NOT EXISTS play_character_inventory (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      item_id TEXT NOT NULL,
      quantity INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, character_id, item_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_character_inventory_character ON play_character_inventory(campaign_id, character_id);

    CREATE TABLE IF NOT EXISTS play_character_equipment (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      slot TEXT NOT NULL,
      item_id TEXT NOT NULL,
      attuned INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (campaign_id, character_id, slot)
    );

    CREATE INDEX IF NOT EXISTS idx_play_character_equipment_character ON play_character_equipment(campaign_id, character_id);

    CREATE TABLE IF NOT EXISTS play_character_currency (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      gold INTEGER NOT NULL DEFAULT 10,
      PRIMARY KEY (campaign_id, character_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_character_currency_character ON play_character_currency(campaign_id, character_id);

    CREATE TABLE IF NOT EXISTS play_currency_transfers (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      from_character_id TEXT NOT NULL,
      to_character_id TEXT NOT NULL,
      gold INTEGER NOT NULL,
      transfer_id INTEGER NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_play_currency_transfers_campaign ON play_currency_transfers(campaign_id);

    CREATE TABLE IF NOT EXISTS play_narrations (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      kind TEXT NOT NULL,
      actor TEXT NOT NULL,
      text TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_play_narrations_campaign ON play_narrations(campaign_id);

    CREATE TABLE IF NOT EXISTS play_campaign_documents (
      campaign_id TEXT PRIMARY KEY,
      story TEXT NOT NULL DEFAULT '',
      dm_notes TEXT NOT NULL DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS play_campaign_scenes (
      campaign_id TEXT NOT NULL,
      scene_id TEXT NOT NULL,
      name TEXT NOT NULL,
      status TEXT NOT NULL,
      PRIMARY KEY (campaign_id, scene_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_campaign_scenes_campaign ON play_campaign_scenes(campaign_id);

    CREATE TABLE IF NOT EXISTS play_locations (
      campaign_id TEXT NOT NULL,
      location_id TEXT NOT NULL,
      name TEXT NOT NULL,
      PRIMARY KEY (campaign_id, location_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_locations_campaign ON play_locations(campaign_id);

    CREATE TABLE IF NOT EXISTS play_location_connections (
      campaign_id TEXT NOT NULL,
      from_id TEXT NOT NULL,
      to_id TEXT NOT NULL,
      travel_turns INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, from_id, to_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_location_connections_campaign ON play_location_connections(campaign_id);

    CREATE TABLE IF NOT EXISTS play_encounters (
      campaign_id TEXT NOT NULL,
      encounter_id TEXT NOT NULL,
      name TEXT NOT NULL,
      status TEXT NOT NULL,
      combatants_json TEXT NOT NULL DEFAULT '[]',
      order_json TEXT NOT NULL DEFAULT '[]',
      round INTEGER NOT NULL DEFAULT 1,
      turn_index INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (campaign_id, encounter_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_encounters_campaign ON play_encounters(campaign_id);

    CREATE TABLE IF NOT EXISTS play_encounter_monsters (
      campaign_id TEXT NOT NULL,
      encounter_id TEXT NOT NULL,
      monster_id TEXT NOT NULL,
      name TEXT NOT NULL,
      hp_max INTEGER NOT NULL,
      hp_current INTEGER NOT NULL,
      initiative INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, encounter_id, monster_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_encounter_monsters_encounter ON play_encounter_monsters(campaign_id, encounter_id);

    CREATE TABLE IF NOT EXISTS play_encounter_actions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      encounter_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      actor TEXT NOT NULL,
      kind TEXT NOT NULL DEFAULT 'combat_action',
      type TEXT NOT NULL,
      target TEXT NOT NULL,
      text TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_play_encounter_actions_encounter ON play_encounter_actions(campaign_id, encounter_id);

    CREATE TABLE IF NOT EXISTS play_encounter_conditions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      encounter_id TEXT NOT NULL,
      target TEXT NOT NULL,
      condition TEXT NOT NULL,
      remaining_rounds INTEGER NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_play_encounter_conditions_encounter_target ON play_encounter_conditions(campaign_id, encounter_id, target);

    CREATE TABLE IF NOT EXISTS play_encounter_rewards (
      campaign_id TEXT NOT NULL,
      encounter_id TEXT NOT NULL,
      xp INTEGER NOT NULL,
      loot_json TEXT NOT NULL DEFAULT '[]',
      PRIMARY KEY (campaign_id, encounter_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_encounter_rewards_encounter ON play_encounter_rewards(campaign_id, encounter_id);

    CREATE TABLE IF NOT EXISTS play_loot (
      campaign_id TEXT NOT NULL,
      loot_id TEXT NOT NULL,
      item_id TEXT NOT NULL,
      quantity INTEGER NOT NULL,
      status TEXT NOT NULL DEFAULT 'open',
      recipient_character_id TEXT,
      PRIMARY KEY (campaign_id, loot_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_loot_campaign ON play_loot(campaign_id);

    CREATE TABLE IF NOT EXISTS play_loot_votes (
      campaign_id TEXT NOT NULL,
      loot_id TEXT NOT NULL,
      voter_username TEXT NOT NULL,
      recipient_character_id TEXT NOT NULL,
      PRIMARY KEY (campaign_id, loot_id, voter_username)
    );

    CREATE INDEX IF NOT EXISTS idx_play_loot_votes_loot ON play_loot_votes(campaign_id, loot_id);

    CREATE TABLE IF NOT EXISTS play_campaign_npcs (
      campaign_id TEXT NOT NULL,
      npc_id TEXT NOT NULL,
      name TEXT NOT NULL,
      agenda TEXT NOT NULL,
      public_status TEXT NOT NULL,
      PRIMARY KEY (campaign_id, npc_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_campaign_npcs_campaign ON play_campaign_npcs(campaign_id);

    CREATE TABLE IF NOT EXISTS play_npc_dialogue (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      npc_id TEXT NOT NULL,
      dialogue_id TEXT NOT NULL,
      speaker TEXT NOT NULL,
      text TEXT NOT NULL,
      visibility TEXT NOT NULL,
      UNIQUE (campaign_id, npc_id, dialogue_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_npc_dialogue_npc ON play_npc_dialogue(campaign_id, npc_id);
    CREATE INDEX IF NOT EXISTS idx_play_npc_dialogue_order ON play_npc_dialogue(id);

    CREATE TABLE IF NOT EXISTS play_factions (
      campaign_id TEXT NOT NULL,
      faction_id TEXT NOT NULL,
      name TEXT NOT NULL,
      PRIMARY KEY (campaign_id, faction_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_factions_campaign ON play_factions(campaign_id);

    CREATE TABLE IF NOT EXISTS play_reputation_history (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      faction_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      delta INTEGER NOT NULL,
      reputation INTEGER NOT NULL,
      reason TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_play_reputation_history_lookup ON play_reputation_history(campaign_id, faction_id, character_id);
    CREATE INDEX IF NOT EXISTS idx_play_reputation_history_order ON play_reputation_history(id);

    CREATE TABLE IF NOT EXISTS play_relationships (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      source_id TEXT NOT NULL,
      target_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      score INTEGER NOT NULL,
      UNIQUE (campaign_id, source_id, target_id, kind)
    );

    CREATE INDEX IF NOT EXISTS idx_play_relationships_campaign ON play_relationships(campaign_id);

    CREATE TABLE IF NOT EXISTS play_campaign_quests (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      quest_id TEXT NOT NULL,
      title TEXT NOT NULL,
      depends_on_json TEXT NOT NULL,
      state TEXT NOT NULL,
      rewards_json TEXT NOT NULL DEFAULT '{}',
      awarded INTEGER NOT NULL DEFAULT 0,
      UNIQUE (campaign_id, quest_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_campaign_quests_campaign ON play_campaign_quests(campaign_id);
    CREATE INDEX IF NOT EXISTS idx_play_campaign_quests_order ON play_campaign_quests(id);

    CREATE TABLE IF NOT EXISTS play_character_quest_rewards (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      quest_id TEXT NOT NULL,
      xp INTEGER NOT NULL,
      items_json TEXT NOT NULL,
      PRIMARY KEY (campaign_id, character_id, quest_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_character_quest_rewards_character ON play_character_quest_rewards(campaign_id, character_id);

    CREATE TABLE IF NOT EXISTS play_clues (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      clue_id TEXT NOT NULL,
      text TEXT NOT NULL,
      audience TEXT NOT NULL,
      character_id TEXT,
      UNIQUE (campaign_id, clue_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_clues_campaign ON play_clues(campaign_id);
    CREATE INDEX IF NOT EXISTS idx_play_clues_order ON play_clues(id);

    CREATE TABLE IF NOT EXISTS play_world_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      event_id TEXT NOT NULL,
      turn_number INTEGER NOT NULL,
      title TEXT NOT NULL,
      text TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'scheduled',
      resolution_turn INTEGER,
      resolution_text TEXT,
      UNIQUE (campaign_id, event_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_world_events_campaign ON play_world_events(campaign_id);

    CREATE TABLE IF NOT EXISTS play_campaign_calendars (
      campaign_id TEXT PRIMARY KEY,
      day INTEGER NOT NULL,
      season TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS play_settlements (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      settlement_id TEXT NOT NULL,
      name TEXT NOT NULL,
      services_json TEXT NOT NULL,
      availability TEXT NOT NULL,
      discovered_by_json TEXT NOT NULL DEFAULT '[]',
      UNIQUE (campaign_id, settlement_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_settlements_campaign ON play_settlements(campaign_id);

    CREATE TABLE IF NOT EXISTS play_shops (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      settlement_id TEXT NOT NULL,
      shop_id TEXT NOT NULL,
      name TEXT NOT NULL,
      stock_json TEXT NOT NULL,
      buy_price INTEGER NOT NULL,
      sell_price INTEGER NOT NULL,
      UNIQUE (campaign_id, settlement_id, shop_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_shops_settlement ON play_shops(campaign_id, settlement_id);

    CREATE TABLE IF NOT EXISTS play_recipes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      recipe_id TEXT NOT NULL,
      name TEXT NOT NULL,
      output_item TEXT NOT NULL,
      output_quantity INTEGER NOT NULL,
      UNIQUE (campaign_id, recipe_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_recipes_campaign ON play_recipes(campaign_id);

    CREATE TABLE IF NOT EXISTS play_recipe_ingredients (
      campaign_id TEXT NOT NULL,
      recipe_id TEXT NOT NULL,
      item_id TEXT NOT NULL,
      quantity INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, recipe_id, item_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_recipe_ingredients_recipe ON play_recipe_ingredients(campaign_id, recipe_id);

    CREATE TABLE IF NOT EXISTS play_downtime_activities (
      campaign_id TEXT NOT NULL,
      activity_id TEXT NOT NULL,
      name TEXT NOT NULL,
      cycles_required INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, activity_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_downtime_activities_campaign ON play_downtime_activities(campaign_id);

    CREATE TABLE IF NOT EXISTS play_downtime_allocations (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      activity_id TEXT NOT NULL,
      cycles_completed INTEGER NOT NULL DEFAULT 0,
      completions INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (campaign_id, character_id, activity_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_downtime_allocations_character ON play_downtime_allocations(campaign_id, character_id);

    CREATE TABLE IF NOT EXISTS play_campaign_session_zero (
      campaign_id TEXT PRIMARY KEY,
      rules TEXT NOT NULL,
      tone TEXT NOT NULL,
      consent_json TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS play_campaign_content (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      content_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      text TEXT NOT NULL,
      tags_json TEXT NOT NULL,
      UNIQUE (campaign_id, content_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_campaign_content_campaign ON play_campaign_content(campaign_id);

    CREATE TABLE IF NOT EXISTS play_campaign_notes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      note_id TEXT NOT NULL,
      text TEXT NOT NULL,
      visibility TEXT NOT NULL,
      owner TEXT NOT NULL,
      UNIQUE (campaign_id, note_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_campaign_notes_campaign ON play_campaign_notes(campaign_id);
    CREATE INDEX IF NOT EXISTS idx_play_campaign_notes_order ON play_campaign_notes(id);

    CREATE TABLE IF NOT EXISTS play_campaign_whispers (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      whisper_id TEXT NOT NULL,
      from_character_id TEXT NOT NULL,
      to_character_id TEXT NOT NULL,
      text TEXT NOT NULL,
      UNIQUE (campaign_id, whisper_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_campaign_whispers_campaign ON play_campaign_whispers(campaign_id);
    CREATE INDEX IF NOT EXISTS idx_play_campaign_whispers_order ON play_campaign_whispers(id);

    CREATE TABLE IF NOT EXISTS play_campaign_invitations (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      invitation_id TEXT NOT NULL,
      username TEXT NOT NULL,
      character_id TEXT NOT NULL,
      status TEXT NOT NULL,
      UNIQUE (campaign_id, invitation_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_campaign_invitations_campaign ON play_campaign_invitations(campaign_id);
    CREATE INDEX IF NOT EXISTS idx_play_campaign_invitations_user ON play_campaign_invitations(campaign_id, username);

    CREATE TABLE IF NOT EXISTS play_campaign_delegations (
      campaign_id TEXT NOT NULL,
      username TEXT NOT NULL,
      powers_json TEXT NOT NULL,
      active INTEGER NOT NULL DEFAULT 1,
      PRIMARY KEY (campaign_id, username)
    );

    CREATE INDEX IF NOT EXISTS idx_play_campaign_delegations_campaign ON play_campaign_delegations(campaign_id);

    CREATE TABLE IF NOT EXISTS play_delegation_audit (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      username TEXT NOT NULL,
      action TEXT NOT NULL,
      powers_json TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_play_delegation_audit_campaign ON play_delegation_audit(campaign_id);
    CREATE INDEX IF NOT EXISTS idx_play_delegation_audit_order ON play_delegation_audit(id);

    CREATE TABLE IF NOT EXISTS play_audit_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      actor TEXT NOT NULL,
      role TEXT NOT NULL,
      timestamp INTEGER NOT NULL,
      correlation_id TEXT NOT NULL,
      UNIQUE (campaign_id, correlation_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_audit_events_campaign ON play_audit_events(campaign_id);
    CREATE INDEX IF NOT EXISTS idx_play_audit_events_order ON play_audit_events(timestamp);

    CREATE TABLE IF NOT EXISTS play_projection_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      event_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      value TEXT
    );

    CREATE UNIQUE INDEX IF NOT EXISTS idx_play_projection_events_event_id ON play_projection_events(campaign_id, event_id);
    CREATE INDEX IF NOT EXISTS idx_play_projection_events_sequence ON play_projection_events(campaign_id, sequence);

    CREATE TABLE IF NOT EXISTS play_idempotent_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      event_id TEXT NOT NULL,
      value TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      idempotency_key TEXT NOT NULL,
      UNIQUE (campaign_id, event_id),
      UNIQUE (campaign_id, idempotency_key)
    );

    CREATE INDEX IF NOT EXISTS idx_play_idempotent_events_campaign ON play_idempotent_events(campaign_id);
    CREATE INDEX IF NOT EXISTS idx_play_idempotent_events_sequence ON play_idempotent_events(campaign_id, sequence);

    CREATE TABLE IF NOT EXISTS play_safe_turns (
      campaign_id TEXT NOT NULL,
      submission_id TEXT NOT NULL,
      action TEXT NOT NULL,
      accepted_turn INTEGER NOT NULL,
      next_turn INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, submission_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_safe_turns_campaign ON play_safe_turns(campaign_id);

    CREATE TABLE IF NOT EXISTS play_transactional_transfers (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      from_character_id TEXT NOT NULL,
      to_character_id TEXT NOT NULL,
      amount INTEGER NOT NULL,
      from_gold INTEGER NOT NULL,
      to_gold INTEGER NOT NULL,
      sequence INTEGER NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_play_transactional_transfers_campaign ON play_transactional_transfers(campaign_id);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_play_transactional_transfers_sequence ON play_transactional_transfers(campaign_id, sequence);

    CREATE TABLE IF NOT EXISTS play_campaign_exports (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      version INTEGER NOT NULL,
      story TEXT NOT NULL,
      status TEXT NOT NULL,
      UNIQUE (campaign_id, version)
    );

    CREATE INDEX IF NOT EXISTS idx_play_campaign_exports_campaign ON play_campaign_exports(campaign_id);

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

    CREATE TABLE IF NOT EXISTS play_search_records (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      record_id TEXT NOT NULL,
      text TEXT NOT NULL,
      UNIQUE (campaign_id, record_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_search_records_campaign ON play_search_records(campaign_id);
    CREATE INDEX IF NOT EXISTS idx_play_search_records_order ON play_search_records(id);

    CREATE TABLE IF NOT EXISTS play_rate_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      event_id TEXT NOT NULL,
      actor TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      UNIQUE (campaign_id, event_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_rate_events_campaign ON play_rate_events(campaign_id);
    CREATE INDEX IF NOT EXISTS idx_play_rate_events_sequence ON play_rate_events(campaign_id, sequence);

    CREATE TABLE IF NOT EXISTS play_campaign_metrics (
      campaign_id TEXT PRIMARY KEY,
      accepted_rate_events INTEGER NOT NULL DEFAULT 0,
      rejected_rate_events INTEGER NOT NULL DEFAULT 0,
      projection_events INTEGER NOT NULL DEFAULT 0,
      uptime_ticks INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS play_campaign_backups (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      backup_id TEXT NOT NULL,
      story TEXT NOT NULL,
      status TEXT NOT NULL,
      UNIQUE (campaign_id, backup_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_campaign_backups_campaign ON play_campaign_backups(campaign_id);

CREATE TABLE IF NOT EXISTS play_replay_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  campaign_id TEXT NOT NULL,
  sequence INTEGER NOT NULL,
  event_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  text TEXT NOT NULL,
  UNIQUE (campaign_id, event_id)
);

CREATE INDEX IF NOT EXISTS idx_play_replay_events_campaign ON play_replay_events(campaign_id);
CREATE INDEX IF NOT EXISTS idx_play_replay_events_sequence ON play_replay_events(campaign_id, sequence);

CREATE TABLE IF NOT EXISTS play_rng_ledger (
  campaign_id TEXT PRIMARY KEY,
  seed TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS play_rng_rolls (
  campaign_id TEXT NOT NULL,
  sequence INTEGER NOT NULL,
  roll_id TEXT NOT NULL,
  sides INTEGER NOT NULL,
  result INTEGER NOT NULL,
  PRIMARY KEY (campaign_id, sequence),
  UNIQUE (campaign_id, roll_id)
);

CREATE INDEX IF NOT EXISTS idx_play_rng_rolls_campaign ON play_rng_rolls(campaign_id);

CREATE TABLE IF NOT EXISTS play_moderation_reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  campaign_id TEXT NOT NULL,
  report_id TEXT NOT NULL,
  target_id TEXT NOT NULL,
  reason TEXT NOT NULL,
  reporter TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  sequence INTEGER NOT NULL,
  action TEXT,
  note TEXT,
  resolver TEXT,
  UNIQUE (campaign_id, report_id)
);

CREATE INDEX IF NOT EXISTS idx_play_moderation_reports_campaign ON play_moderation_reports(campaign_id);
CREATE INDEX IF NOT EXISTS idx_play_moderation_reports_sequence ON play_moderation_reports(campaign_id, sequence);

CREATE TABLE IF NOT EXISTS play_safety_boundaries (
  campaign_id TEXT PRIMARY KEY,
  blocked_tags_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS play_safety_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  campaign_id TEXT NOT NULL,
  event_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  text TEXT NOT NULL,
  tags_json TEXT NOT NULL,
  sequence INTEGER NOT NULL,
  UNIQUE (campaign_id, event_id)
);

CREATE INDEX IF NOT EXISTS idx_play_safety_events_campaign ON play_safety_events(campaign_id);
CREATE INDEX IF NOT EXISTS idx_play_safety_events_sequence ON play_safety_events(campaign_id, sequence);

CREATE TABLE IF NOT EXISTS play_fixture_seeds (
  campaign_id TEXT PRIMARY KEY,
  fixture_id TEXT NOT NULL,
  status TEXT NOT NULL,
  characters_json TEXT NOT NULL,
  story TEXT NOT NULL,
  event_ids_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS play_campaign_spectators (
  campaign_id TEXT NOT NULL,
  spectator_id TEXT NOT NULL,
  PRIMARY KEY (campaign_id, spectator_id),
  UNIQUE (spectator_id)
);

CREATE INDEX IF NOT EXISTS idx_play_campaign_spectators_campaign ON play_campaign_spectators(campaign_id);

CREATE TABLE IF NOT EXISTS play_feed_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  campaign_id TEXT NOT NULL,
  event_id TEXT NOT NULL,
  text TEXT NOT NULL,
  sequence INTEGER NOT NULL,
  UNIQUE (campaign_id, event_id)
);

CREATE INDEX IF NOT EXISTS idx_play_feed_events_campaign_sequence ON play_feed_events(campaign_id, sequence);
  SQL

  # Yields the shared SQLite connection while serializing access.
  def self.db
    DB_MUTEX.synchronize { yield DATABASE }
  end

  def self.schema_initialized?
    db { |d| d.get_first_value("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'") } ? true : false
  end

  def self.initialize_schema!
    db { |d| d.execute_batch(SCHEMA_SQL) }
  end

  # Drops every application table and recreates the schema.
  # Used on server startup to guarantee a clean state.
  def self.reset!
    db do |d|
      RESET_TABLES.each do |table|
        d.execute("DROP TABLE IF EXISTS #{table}")
      end
      d.execute_batch(SCHEMA_SQL)
    end
  end

  # Drops every application table except users, then recreates the schema.
  # Used by the /v1/storage/reset endpoint so authentication remains usable.
  def self.soft_reset!
    db do |d|
      SOFT_RESET_TABLES.each do |table|
        d.execute("DROP TABLE IF EXISTS #{table}")
      end
      d.execute_batch(SCHEMA_SQL)
    end
  end

  def self.status
    {
      driver: 'sqlite',
      schema_version: Config::SCHEMA_VERSION,
      initialized: schema_initialized?
    }
  end
end
