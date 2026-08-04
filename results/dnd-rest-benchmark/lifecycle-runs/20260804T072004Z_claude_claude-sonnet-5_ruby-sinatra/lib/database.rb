# Per-thread SQLite connection and schema management.
#
# Puma may serve requests from multiple threads, so the connection is cached
# per-thread rather than as a single global — SQLite3::Database is not
# guaranteed safe to share across threads without its own locking.

require 'sqlite3'

DB_PATH = File.join(__dir__, '..', 'game.db')
SCHEMA_VERSION = 1

# Each server boot starts from a clean database. Deterministic fixtures
# (e.g. the "dm" auth user) are registered fresh by every evaluation run,
# so leftover state — including stray WAL/SHM files from an unclean prior
# shutdown, which SQLite would otherwise replay on top of a "fresh" file —
# must not survive across process starts.
[DB_PATH, "#{DB_PATH}-wal", "#{DB_PATH}-shm"].each do |path|
  File.delete(path) if File.exist?(path)
end

def db
  Thread.current[:db] ||= begin
    conn = SQLite3::Database.new(DB_PATH)
    conn.results_as_hash = true
    conn.busy_timeout = 5000
    conn.execute('PRAGMA journal_mode = WAL')
    conn
  end
end

def init_schema!
  db.execute_batch(<<~SQL)
    CREATE TABLE IF NOT EXISTS schema_meta (
      id INTEGER PRIMARY KEY CHECK (id = 1),
      version INTEGER NOT NULL
    );
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
      summary TEXT,
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
      quantity INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS campaign_equipment (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      item_slug TEXT NOT NULL,
      quantity INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS campaign_crafting_projects (
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
      agenda_json TEXT NOT NULL,
      created_at TEXT NOT NULL,
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
      turn_index INTEGER,
      nudge_count INTEGER NOT NULL DEFAULT 0,
      story TEXT NOT NULL DEFAULT '',
      dm_notes TEXT NOT NULL DEFAULT '',
      current_scene_id TEXT,
      current_location_id TEXT,
      phase TEXT NOT NULL DEFAULT 'exploration',
      pre_combat_actor TEXT,
      pre_combat_turn_index INTEGER,
      pre_combat_turn_number INTEGER
    );
    CREATE TABLE IF NOT EXISTS play_scenes (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      name TEXT NOT NULL,
      status TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id)
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
      PRIMARY KEY (campaign_id, username)
    );
    CREATE TABLE IF NOT EXISTS play_campaign_events (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      kind TEXT NOT NULL,
      actor TEXT NOT NULL,
      type TEXT,
      target TEXT,
      text TEXT,
      PRIMARY KEY (campaign_id, sequence)
    );
    CREATE TABLE IF NOT EXISTS play_locations (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      name TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );
    CREATE TABLE IF NOT EXISTS play_location_connections (
      campaign_id TEXT NOT NULL,
      from_id TEXT NOT NULL,
      to_id TEXT NOT NULL,
      travel_turns INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, from_id, to_id)
    );
    CREATE TABLE IF NOT EXISTS play_character_owners (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      owner TEXT,
      PRIMARY KEY (campaign_id, character_id)
    );
    CREATE TABLE IF NOT EXISTS play_encounters (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      name TEXT NOT NULL,
      status TEXT NOT NULL,
      combatants_json TEXT NOT NULL,
      round INTEGER NOT NULL DEFAULT 1,
      turn_index INTEGER NOT NULL DEFAULT 0,
      conditions_json TEXT NOT NULL DEFAULT '{}',
      turn_order_json TEXT,
      xp_awarded INTEGER NOT NULL DEFAULT 0,
      rewards_json TEXT,
      PRIMARY KEY (campaign_id, id)
    );
    CREATE TABLE IF NOT EXISTS play_character_spells (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      spell_id TEXT NOT NULL,
      name TEXT NOT NULL,
      level INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, character_id, spell_id)
    );
    CREATE TABLE IF NOT EXISTS play_character_prepared_spells (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      spell_ids_json TEXT NOT NULL,
      PRIMARY KEY (campaign_id, character_id)
    );
    CREATE TABLE IF NOT EXISTS play_character_casts (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      spell_id TEXT NOT NULL,
      target TEXT NOT NULL,
      slot_level INTEGER NOT NULL,
      slots_remaining INTEGER,
      PRIMARY KEY (campaign_id, character_id, sequence)
    );
    CREATE TABLE IF NOT EXISTS play_character_concentration (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      spell_id TEXT NOT NULL,
      target TEXT NOT NULL,
      remaining_turns INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, character_id)
    );
    CREATE TABLE IF NOT EXISTS play_character_inventory_items (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      item_id TEXT NOT NULL,
      quantity INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, character_id, item_id)
    );
    CREATE TABLE IF NOT EXISTS play_character_equipment (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      slot TEXT NOT NULL,
      item_id TEXT NOT NULL,
      attuned INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (campaign_id, character_id, slot)
    );
    CREATE TABLE IF NOT EXISTS play_character_gold (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      gold INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, character_id)
    );
    CREATE TABLE IF NOT EXISTS play_gold_transfers (
      campaign_id TEXT NOT NULL,
      transfer_id INTEGER NOT NULL,
      from_character_id TEXT NOT NULL,
      to_character_id TEXT NOT NULL,
      gold INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, transfer_id)
    );
    CREATE TABLE IF NOT EXISTS play_loot (
      campaign_id TEXT NOT NULL,
      loot_id TEXT NOT NULL,
      item_id TEXT NOT NULL,
      quantity INTEGER NOT NULL,
      status TEXT NOT NULL DEFAULT 'open',
      recipient_character_id TEXT,
      PRIMARY KEY (campaign_id, loot_id)
    );
    CREATE TABLE IF NOT EXISTS play_loot_votes (
      campaign_id TEXT NOT NULL,
      loot_id TEXT NOT NULL,
      voter TEXT NOT NULL,
      recipient_character_id TEXT NOT NULL,
      PRIMARY KEY (campaign_id, loot_id, voter)
    );
    CREATE TABLE IF NOT EXISTS play_npcs (
      campaign_id TEXT NOT NULL,
      npc_id TEXT NOT NULL,
      name TEXT NOT NULL,
      agenda TEXT NOT NULL,
      public_status TEXT NOT NULL,
      PRIMARY KEY (campaign_id, npc_id)
    );
    CREATE TABLE IF NOT EXISTS play_factions (
      campaign_id TEXT NOT NULL,
      faction_id TEXT NOT NULL,
      name TEXT NOT NULL,
      PRIMARY KEY (campaign_id, faction_id)
    );
    CREATE TABLE IF NOT EXISTS play_faction_reputation (
      campaign_id TEXT NOT NULL,
      faction_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      reputation INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (campaign_id, faction_id, character_id)
    );
    CREATE TABLE IF NOT EXISTS play_faction_reputation_history (
      campaign_id TEXT NOT NULL,
      faction_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      reputation INTEGER NOT NULL,
      delta INTEGER NOT NULL,
      reason TEXT NOT NULL,
      PRIMARY KEY (campaign_id, faction_id, sequence)
    );
    CREATE TABLE IF NOT EXISTS play_npc_dialogue (
      campaign_id TEXT NOT NULL,
      npc_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      dialogue_id TEXT NOT NULL,
      speaker TEXT NOT NULL,
      text TEXT NOT NULL,
      visibility TEXT NOT NULL,
      PRIMARY KEY (campaign_id, npc_id, sequence)
    );
    CREATE TABLE IF NOT EXISTS play_relationships (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      source_id TEXT NOT NULL,
      target_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      score INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, source_id, target_id, kind)
    );
    CREATE TABLE IF NOT EXISTS play_clues (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      clue_id TEXT NOT NULL,
      text TEXT NOT NULL,
      audience TEXT NOT NULL,
      character_id TEXT,
      PRIMARY KEY (campaign_id, clue_id)
    );
    CREATE TABLE IF NOT EXISTS play_quests (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      quest_id TEXT NOT NULL,
      title TEXT NOT NULL,
      depends_on_json TEXT NOT NULL,
      state TEXT NOT NULL DEFAULT 'locked',
      rewards_json TEXT,
      rewards_awarded INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (campaign_id, quest_id)
    );
    CREATE TABLE IF NOT EXISTS play_quest_reward_grants (
      campaign_id TEXT NOT NULL,
      quest_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      xp INTEGER NOT NULL,
      items_json TEXT NOT NULL,
      PRIMARY KEY (campaign_id, quest_id, character_id)
    );
    CREATE TABLE IF NOT EXISTS play_world_events (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      event_id TEXT NOT NULL,
      turn_number INTEGER NOT NULL,
      title TEXT NOT NULL,
      text TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'scheduled',
      resolution_turn_number INTEGER,
      resolution_text TEXT,
      PRIMARY KEY (campaign_id, event_id)
    );
    CREATE TABLE IF NOT EXISTS play_calendars (
      campaign_id TEXT NOT NULL,
      day INTEGER NOT NULL,
      season TEXT NOT NULL,
      PRIMARY KEY (campaign_id)
    );
    CREATE TABLE IF NOT EXISTS play_settlements (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      settlement_id TEXT NOT NULL,
      name TEXT NOT NULL,
      services_json TEXT NOT NULL,
      availability TEXT NOT NULL,
      discovered_by_json TEXT NOT NULL DEFAULT '[]',
      PRIMARY KEY (campaign_id, settlement_id)
    );
    CREATE TABLE IF NOT EXISTS play_shops (
      campaign_id TEXT NOT NULL,
      settlement_id TEXT NOT NULL,
      shop_id TEXT NOT NULL,
      name TEXT NOT NULL,
      stock_json TEXT NOT NULL,
      buy_price INTEGER NOT NULL,
      sell_price INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, settlement_id, shop_id)
    );
    CREATE TABLE IF NOT EXISTS play_recipes (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      recipe_id TEXT NOT NULL,
      name TEXT NOT NULL,
      ingredients_json TEXT NOT NULL,
      output_item TEXT NOT NULL,
      output_quantity INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, recipe_id)
    );
    CREATE TABLE IF NOT EXISTS play_downtime_activities (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      activity_id TEXT NOT NULL,
      name TEXT NOT NULL,
      cycles_required INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, activity_id)
    );
    CREATE TABLE IF NOT EXISTS play_downtime_allocations (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      activity_id TEXT NOT NULL,
      cycles_completed INTEGER NOT NULL,
      completions INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, character_id, activity_id)
    );
    CREATE TABLE IF NOT EXISTS play_session_zero_settings (
      campaign_id TEXT NOT NULL,
      rules TEXT NOT NULL,
      tone TEXT NOT NULL,
      consent_json TEXT NOT NULL,
      PRIMARY KEY (campaign_id)
    );
    CREATE TABLE IF NOT EXISTS play_content (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      content_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      text TEXT NOT NULL,
      tags_json TEXT NOT NULL,
      PRIMARY KEY (campaign_id, content_id)
    );
    CREATE TABLE IF NOT EXISTS play_notes (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      note_id TEXT NOT NULL,
      text TEXT NOT NULL,
      visibility TEXT NOT NULL,
      owner TEXT NOT NULL,
      PRIMARY KEY (campaign_id, note_id)
    );
    CREATE TABLE IF NOT EXISTS play_whispers (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      whisper_id TEXT NOT NULL,
      from_character_id TEXT NOT NULL,
      to_character_id TEXT NOT NULL,
      text TEXT NOT NULL,
      PRIMARY KEY (campaign_id, whisper_id)
    );
    CREATE TABLE IF NOT EXISTS play_invitations (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      invitation_id TEXT NOT NULL,
      username TEXT NOT NULL,
      character_id TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending',
      PRIMARY KEY (campaign_id, invitation_id)
    );
    CREATE TABLE IF NOT EXISTS play_delegations (
      campaign_id TEXT NOT NULL,
      username TEXT NOT NULL,
      powers_json TEXT NOT NULL,
      active INTEGER NOT NULL DEFAULT 1,
      PRIMARY KEY (campaign_id, username)
    );
    CREATE TABLE IF NOT EXISTS play_delegation_audit (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      username TEXT NOT NULL,
      action TEXT NOT NULL,
      powers_json TEXT NOT NULL,
      PRIMARY KEY (campaign_id, sequence)
    );
  SQL
  db.execute('INSERT OR IGNORE INTO schema_meta (id, version) VALUES (1, ?)', [SCHEMA_VERSION])
end

def reset_schema!
  # Users are account/auth state, not campaign storage — /v1/storage/reset
  # only clears compendium and campaign data, so the users table is
  # intentionally left alone.
  db.execute_batch(<<~SQL)
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
    DROP TABLE IF EXISTS campaign_session_attendance;
    DROP TABLE IF EXISTS play_campaigns;
    DROP TABLE IF EXISTS play_campaign_members;
    DROP TABLE IF EXISTS play_campaign_events;
    DROP TABLE IF EXISTS play_scenes;
    DROP TABLE IF EXISTS play_locations;
    DROP TABLE IF EXISTS play_location_connections;
    DROP TABLE IF EXISTS play_encounters;
    DROP TABLE IF EXISTS play_character_owners;
    DROP TABLE IF EXISTS play_character_spells;
    DROP TABLE IF EXISTS play_character_prepared_spells;
    DROP TABLE IF EXISTS play_character_casts;
    DROP TABLE IF EXISTS play_character_concentration;
    DROP TABLE IF EXISTS play_character_inventory_items;
    DROP TABLE IF EXISTS play_character_equipment;
    DROP TABLE IF EXISTS play_character_gold;
    DROP TABLE IF EXISTS play_gold_transfers;
    DROP TABLE IF EXISTS play_loot;
    DROP TABLE IF EXISTS play_loot_votes;
    DROP TABLE IF EXISTS play_npcs;
    DROP TABLE IF EXISTS play_factions;
    DROP TABLE IF EXISTS play_faction_reputation;
    DROP TABLE IF EXISTS play_faction_reputation_history;
    DROP TABLE IF EXISTS play_npc_dialogue;
    DROP TABLE IF EXISTS play_relationships;
    DROP TABLE IF EXISTS play_clues;
    DROP TABLE IF EXISTS play_quests;
    DROP TABLE IF EXISTS play_quest_reward_grants;
    DROP TABLE IF EXISTS play_world_events;
    DROP TABLE IF EXISTS play_calendars;
    DROP TABLE IF EXISTS play_settlements;
    DROP TABLE IF EXISTS play_shops;
    DROP TABLE IF EXISTS play_recipes;
    DROP TABLE IF EXISTS play_downtime_activities;
    DROP TABLE IF EXISTS play_downtime_allocations;
    DROP TABLE IF EXISTS play_session_zero_settings;
    DROP TABLE IF EXISTS play_content;
    DROP TABLE IF EXISTS play_notes;
    DROP TABLE IF EXISTS play_whispers;
    DROP TABLE IF EXISTS play_invitations;
    DROP TABLE IF EXISTS play_delegations;
    DROP TABLE IF EXISTS play_delegation_audit;
    DROP TABLE IF EXISTS schema_meta;
  SQL
  init_schema!
end
