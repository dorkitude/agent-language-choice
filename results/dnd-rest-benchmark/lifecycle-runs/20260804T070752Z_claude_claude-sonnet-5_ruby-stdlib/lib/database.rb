# frozen_string_literal: true

require 'json'
require 'open3'

# Thin wrapper around the `sqlite3` CLI binary. There is no bundled sqlite3
# gem in this stdlib-only project, so every query shells out to the CLI and
# parses its JSON output. All persistent state (users, combat sessions,
# compendium entries, campaigns) lives in the single SQLite file at DB_PATH.
module Database
  SCHEMA_VERSION = 1

  module_function

  def path
    @path ||= File.join(__dir__, '..', 'game.db')
  end

  # Runs arbitrary SQL with no expectation of structured output (DDL, INSERT,
  # UPDATE, DELETE). Raises if the CLI exits non-zero.
  def exec(sql)
    run(sql)
  end

  # Runs a SELECT and parses the result as an array of row hashes via
  # sqlite3's `.mode json` output. Returns [] for an empty result set,
  # since sqlite3 prints nothing (not "[]") when a query matches no rows.
  def query(sql)
    text = run(".mode json\n#{sql}\n").strip
    return [] if text.empty?

    JSON.parse(text)
  end

  # Quotes and escapes a value for interpolation into SQL as a string
  # literal. Single quotes are doubled per SQL string-literal escaping.
  def escape(value)
    "'#{value.to_s.gsub("'", "''")}'"
  end

  # Formats a value for interpolation into SQL as a bare integer literal.
  def int(value)
    value.to_i.to_s
  end

  def init_schema
    exec(<<~SQL)
      CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        role TEXT NOT NULL,
        salt TEXT NOT NULL,
        digest TEXT NOT NULL
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
      CREATE TABLE IF NOT EXISTS campaign_quests (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        title TEXT NOT NULL,
        status TEXT NOT NULL,
        milestones_json TEXT NOT NULL,
        completed_json TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS campaign_factions (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        name TEXT NOT NULL,
        stance TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS campaign_npcs (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        name TEXT NOT NULL,
        faction_id TEXT,
        disposition INTEGER NOT NULL
      );
      CREATE TABLE IF NOT EXISTS campaign_inventory (
        campaign_id TEXT NOT NULL,
        item_slug TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        owner TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS character_equipment (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        item_slug TEXT NOT NULL,
        quantity INTEGER NOT NULL
      );
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
      CREATE TABLE IF NOT EXISTS campaign_sessions (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        starts_at TEXT NOT NULL,
        duration_minutes INTEGER NOT NULL,
        agenda_json TEXT NOT NULL,
        present_json TEXT NOT NULL,
        absent_json TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS play_campaigns (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        owner TEXT NOT NULL,
        status TEXT NOT NULL,
        max_players INTEGER NOT NULL
      );
      CREATE TABLE IF NOT EXISTS play_members (
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
        PRIMARY KEY (campaign_id, username)
      );
      CREATE TABLE IF NOT EXISTS play_events (
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        kind TEXT NOT NULL,
        actor TEXT NOT NULL,
        text TEXT NOT NULL,
        PRIMARY KEY (campaign_id, sequence)
      );
      CREATE TABLE IF NOT EXISTS play_scenes (
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        name TEXT NOT NULL,
        status TEXT NOT NULL,
        PRIMARY KEY (campaign_id, id)
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
      CREATE TABLE IF NOT EXISTS play_encounters (
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        name TEXT NOT NULL,
        status TEXT NOT NULL,
        combatants_json TEXT NOT NULL,
        conditions_json TEXT NOT NULL DEFAULT '{}',
        order_json TEXT NOT NULL DEFAULT '[]',
        ready_json TEXT NOT NULL DEFAULT '[]',
        xp_awarded INTEGER NOT NULL DEFAULT 0,
        rewards_json TEXT,
        PRIMARY KEY (campaign_id, id)
      );
      CREATE TABLE IF NOT EXISTS play_spells (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        spell_id TEXT NOT NULL,
        name TEXT NOT NULL,
        level INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, character_id, spell_id)
      );
      CREATE TABLE IF NOT EXISTS play_prepared_spells (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        spell_ids_json TEXT NOT NULL DEFAULT '[]',
        PRIMARY KEY (campaign_id, character_id)
      );
      CREATE TABLE IF NOT EXISTS play_casts (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        spell_id TEXT NOT NULL,
        target TEXT NOT NULL,
        slot_level INTEGER NOT NULL,
        slots_remaining INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (campaign_id, character_id, sequence)
      );
      CREATE TABLE IF NOT EXISTS play_concentration (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        spell_id TEXT NOT NULL,
        target TEXT NOT NULL,
        remaining_turns INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, character_id)
      );
      CREATE TABLE IF NOT EXISTS play_inventory_items (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        item_id TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, character_id, item_id)
      );
      CREATE TABLE IF NOT EXISTS play_equipment (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        slot TEXT NOT NULL,
        item_id TEXT NOT NULL,
        attuned INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (campaign_id, character_id, slot)
      );
      CREATE TABLE IF NOT EXISTS play_currency_transfers (
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
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        faction_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        reputation INTEGER NOT NULL,
        delta INTEGER NOT NULL,
        reason TEXT NOT NULL
      );
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
      CREATE TABLE IF NOT EXISTS play_relationships (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        target_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        score INTEGER NOT NULL,
        UNIQUE (campaign_id, source_id, target_id, kind)
      );
      CREATE TABLE IF NOT EXISTS play_clues (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        clue_id TEXT NOT NULL,
        text TEXT NOT NULL,
        audience TEXT NOT NULL,
        character_id TEXT,
        UNIQUE (campaign_id, clue_id)
      );
      CREATE TABLE IF NOT EXISTS play_quests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        quest_id TEXT NOT NULL,
        title TEXT NOT NULL,
        depends_on_json TEXT NOT NULL,
        state TEXT NOT NULL,
        UNIQUE (campaign_id, quest_id)
      );
      CREATE TABLE IF NOT EXISTS play_character_rewards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        xp INTEGER NOT NULL DEFAULT 0,
        items_json TEXT NOT NULL DEFAULT '{}',
        UNIQUE (campaign_id, character_id)
      );
      CREATE TABLE IF NOT EXISTS play_world_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        turn_number INTEGER NOT NULL,
        title TEXT NOT NULL,
        text TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'scheduled',
        resolution_turn_number INTEGER,
        resolution_text TEXT,
        UNIQUE (campaign_id, event_id)
      );
    SQL

    migrate_play_campaigns
    migrate_play_members
    migrate_play_events
    migrate_play_documents
    migrate_play_encounters
    migrate_play_casts
    migrate_play_quests
  end

  # play_quests predates the reward configuration columns needed for quest
  # rewards; existing databases need them added in place.
  def migrate_play_quests
    columns = query('PRAGMA table_info(play_quests);').map { |row| row['name'] }
    exec('ALTER TABLE play_quests ADD COLUMN rewards_json TEXT;') unless columns.include?('rewards_json')
    unless columns.include?('rewards_awarded')
      exec('ALTER TABLE play_quests ADD COLUMN rewards_awarded INTEGER NOT NULL DEFAULT 0;')
    end
  end

  # play_encounters predates the round/turn_index columns needed for combat
  # turn authority; existing databases need them added in place.
  def migrate_play_encounters
    columns = query('PRAGMA table_info(play_encounters);').map { |row| row['name'] }
    exec('ALTER TABLE play_encounters ADD COLUMN round INTEGER NOT NULL DEFAULT 1;') unless columns.include?('round')
    exec('ALTER TABLE play_encounters ADD COLUMN turn_index INTEGER NOT NULL DEFAULT 0;') unless columns.include?('turn_index')
    unless columns.include?('conditions_json')
      exec("ALTER TABLE play_encounters ADD COLUMN conditions_json TEXT NOT NULL DEFAULT '{}';")
    end
    unless columns.include?('order_json')
      exec("ALTER TABLE play_encounters ADD COLUMN order_json TEXT NOT NULL DEFAULT '[]';")
    end
    unless columns.include?('ready_json')
      exec("ALTER TABLE play_encounters ADD COLUMN ready_json TEXT NOT NULL DEFAULT '[]';")
    end
    unless columns.include?('xp_awarded')
      exec('ALTER TABLE play_encounters ADD COLUMN xp_awarded INTEGER NOT NULL DEFAULT 0;')
    end
    unless columns.include?('rewards_json')
      exec('ALTER TABLE play_encounters ADD COLUMN rewards_json TEXT;')
    end
  end

  # play_casts predates the slots_remaining column; existing databases need
  # it added in place.
  def migrate_play_casts
    columns = query('PRAGMA table_info(play_casts);').map { |row| row['name'] }
    unless columns.include?('slots_remaining')
      exec('ALTER TABLE play_casts ADD COLUMN slots_remaining INTEGER NOT NULL DEFAULT 0;')
    end
  end

  # play_documents holds the durable role-filtered campaign document (story +
  # dm_notes), keyed one-per-campaign.
  def migrate_play_documents
    exec(<<~SQL)
      CREATE TABLE IF NOT EXISTS play_documents (
        campaign_id TEXT PRIMARY KEY,
        story TEXT NOT NULL,
        dm_notes TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS play_calendars (
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
      CREATE TABLE IF NOT EXISTS play_recipes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        recipe_id TEXT NOT NULL,
        name TEXT NOT NULL,
        ingredients_json TEXT NOT NULL,
        output_item TEXT NOT NULL,
        output_quantity INTEGER NOT NULL,
        UNIQUE (campaign_id, recipe_id)
      );
      CREATE TABLE IF NOT EXISTS play_downtime_activities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        activity_id TEXT NOT NULL,
        name TEXT NOT NULL,
        cycles_required INTEGER NOT NULL,
        UNIQUE (campaign_id, activity_id)
      );
      CREATE TABLE IF NOT EXISTS play_downtime_allocations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        activity_id TEXT NOT NULL,
        cycles_completed INTEGER NOT NULL DEFAULT 0,
        completions INTEGER NOT NULL DEFAULT 0,
        UNIQUE (campaign_id, character_id, activity_id)
      );
      CREATE TABLE IF NOT EXISTS play_session_zero (
        campaign_id TEXT PRIMARY KEY,
        rules TEXT NOT NULL,
        tone TEXT NOT NULL,
        consent_json TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS play_content (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        content_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        text TEXT NOT NULL,
        tags_json TEXT NOT NULL,
        UNIQUE (campaign_id, content_id)
      );
      CREATE TABLE IF NOT EXISTS play_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        note_id TEXT NOT NULL,
        text TEXT NOT NULL,
        visibility TEXT NOT NULL,
        owner TEXT NOT NULL,
        UNIQUE (campaign_id, note_id)
      );
      CREATE TABLE IF NOT EXISTS play_whispers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        whisper_id TEXT NOT NULL,
        from_character_id TEXT NOT NULL,
        to_character_id TEXT NOT NULL,
        text TEXT NOT NULL,
        UNIQUE (campaign_id, whisper_id)
      );
      CREATE TABLE IF NOT EXISTS play_invitations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        invitation_id TEXT NOT NULL,
        username TEXT NOT NULL,
        character_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        UNIQUE (campaign_id, invitation_id)
      );
      CREATE TABLE IF NOT EXISTS play_delegations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        username TEXT NOT NULL,
        powers TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        UNIQUE (campaign_id, username)
      );
      CREATE TABLE IF NOT EXISTS play_delegation_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        username TEXT NOT NULL,
        action TEXT NOT NULL,
        powers TEXT NOT NULL
      );
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
      CREATE TABLE IF NOT EXISTS play_projection_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        event_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        value TEXT,
        UNIQUE (campaign_id, event_id)
      );
      CREATE TABLE IF NOT EXISTS play_idempotent_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        event_id TEXT NOT NULL,
        value TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        UNIQUE (campaign_id, event_id),
        UNIQUE (campaign_id, idempotency_key)
      );
      CREATE TABLE IF NOT EXISTS play_safe_turn_state (
        campaign_id TEXT PRIMARY KEY,
        current_turn INTEGER NOT NULL DEFAULT 1
      );
      CREATE TABLE IF NOT EXISTS play_safe_turns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        submission_id TEXT NOT NULL,
        action TEXT NOT NULL,
        accepted_turn INTEGER NOT NULL,
        next_turn INTEGER NOT NULL,
        UNIQUE (campaign_id, submission_id)
      );
      CREATE TABLE IF NOT EXISTS play_transactional_transfers (
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        from_character_id TEXT NOT NULL,
        to_character_id TEXT NOT NULL,
        amount INTEGER NOT NULL,
        from_gold INTEGER NOT NULL,
        to_gold INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, sequence)
      );
      CREATE TABLE IF NOT EXISTS play_exports (
        campaign_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        story TEXT NOT NULL,
        status TEXT NOT NULL,
        PRIMARY KEY (campaign_id, version)
      );
      CREATE TABLE IF NOT EXISTS play_backups (
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        story TEXT NOT NULL,
        status TEXT NOT NULL,
        PRIMARY KEY (campaign_id, sequence)
      );
      CREATE TABLE IF NOT EXISTS play_replay_events (
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        event_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        text TEXT NOT NULL,
        PRIMARY KEY (campaign_id, sequence),
        UNIQUE (campaign_id, event_id)
      );
      CREATE TABLE IF NOT EXISTS play_imports (
        campaign_id TEXT PRIMARY KEY,
        version INTEGER NOT NULL,
        story TEXT NOT NULL,
        status TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS play_migrations (
        campaign_id TEXT PRIMARY KEY,
        source_schema_version INTEGER NOT NULL,
        source_story TEXT NOT NULL,
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
      CREATE TABLE IF NOT EXISTS play_rate_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        actor TEXT NOT NULL,
        UNIQUE (campaign_id, event_id)
      );
      CREATE TABLE IF NOT EXISTS play_rate_event_rejections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS play_rng_seeds (
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
      CREATE TABLE IF NOT EXISTS play_moderation_reports (
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
        PRIMARY KEY (campaign_id, sequence),
        UNIQUE (campaign_id, report_id)
      );
      CREATE TABLE IF NOT EXISTS play_safety_boundaries (
        campaign_id TEXT PRIMARY KEY,
        blocked_tags_json TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS play_safety_events (
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        event_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        text TEXT NOT NULL,
        tags_json TEXT NOT NULL,
        PRIMARY KEY (campaign_id, sequence),
        UNIQUE (campaign_id, event_id)
      );
      CREATE TABLE IF NOT EXISTS play_fixture_seeds (
        campaign_id TEXT PRIMARY KEY,
        fixture_id TEXT NOT NULL,
        state_json TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS play_spectators (
        spectator_id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        token TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS play_feed_events (
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        event_id TEXT NOT NULL,
        text TEXT NOT NULL,
        PRIMARY KEY (campaign_id, sequence),
        UNIQUE (campaign_id, event_id)
      );
    SQL
  end

  # play_campaigns predates the current_actor/turn_number columns; existing
  # databases created before this stage need them added in place since
  # CREATE TABLE IF NOT EXISTS does not alter an already-existing table.
  def migrate_play_campaigns
    columns = query('PRAGMA table_info(play_campaigns);').map { |row| row['name'] }
    exec('ALTER TABLE play_campaigns ADD COLUMN current_actor TEXT;') unless columns.include?('current_actor')
    exec('ALTER TABLE play_campaigns ADD COLUMN turn_number INTEGER;') unless columns.include?('turn_number')
    exec('ALTER TABLE play_campaigns ADD COLUMN nudge_count INTEGER NOT NULL DEFAULT 0;') unless columns.include?('nudge_count')
    exec('ALTER TABLE play_campaigns ADD COLUMN current_scene_id TEXT;') unless columns.include?('current_scene_id')
    exec('ALTER TABLE play_campaigns ADD COLUMN current_location_id TEXT;') unless columns.include?('current_location_id')
    unless columns.include?('combat_phase')
      exec("ALTER TABLE play_campaigns ADD COLUMN combat_phase TEXT NOT NULL DEFAULT 'exploration';")
    end
    exec('ALTER TABLE play_campaigns ADD COLUMN pre_combat_actor TEXT;') unless columns.include?('pre_combat_actor')
    exec('ALTER TABLE play_campaigns ADD COLUMN turn_phase TEXT;') unless columns.include?('turn_phase')
  end

  # play_members predates the hp_current/hp_max columns needed for rest
  # turns, and the status/death-save columns needed for death saves;
  # existing databases need them added in place.
  def migrate_play_members
    columns = query('PRAGMA table_info(play_members);').map { |row| row['name'] }
    exec('ALTER TABLE play_members ADD COLUMN hp_current INTEGER NOT NULL DEFAULT 20;') unless columns.include?('hp_current')
    exec('ALTER TABLE play_members ADD COLUMN hp_max INTEGER NOT NULL DEFAULT 20;') unless columns.include?('hp_max')
    exec("ALTER TABLE play_members ADD COLUMN status TEXT NOT NULL DEFAULT 'conscious';") unless columns.include?('status')
    exec('ALTER TABLE play_members ADD COLUMN death_save_successes INTEGER NOT NULL DEFAULT 0;') unless columns.include?('death_save_successes')
    exec('ALTER TABLE play_members ADD COLUMN death_save_failures INTEGER NOT NULL DEFAULT 0;') unless columns.include?('death_save_failures')
    exec('ALTER TABLE play_members ADD COLUMN owner TEXT;') unless columns.include?('owner')
    exec('ALTER TABLE play_members ADD COLUMN race TEXT;') unless columns.include?('race')
    exec('ALTER TABLE play_members ADD COLUMN background TEXT;') unless columns.include?('background')
    exec('ALTER TABLE play_members ADD COLUMN level INTEGER NOT NULL DEFAULT 1;') unless columns.include?('level')
    exec('ALTER TABLE play_members ADD COLUMN con_modifier INTEGER NOT NULL DEFAULT 0;') unless columns.include?('con_modifier')
    exec('ALTER TABLE play_members ADD COLUMN hit_dice TEXT;') unless columns.include?('hit_dice')
    exec('ALTER TABLE play_members ADD COLUMN str_modifier INTEGER NOT NULL DEFAULT 0;') unless columns.include?('str_modifier')
    exec('ALTER TABLE play_members ADD COLUMN dex_modifier INTEGER NOT NULL DEFAULT 0;') unless columns.include?('dex_modifier')
    exec('ALTER TABLE play_members ADD COLUMN int_modifier INTEGER NOT NULL DEFAULT 0;') unless columns.include?('int_modifier')
    exec('ALTER TABLE play_members ADD COLUMN wis_modifier INTEGER NOT NULL DEFAULT 0;') unless columns.include?('wis_modifier')
    exec('ALTER TABLE play_members ADD COLUMN cha_modifier INTEGER NOT NULL DEFAULT 0;') unless columns.include?('cha_modifier')
    exec('ALTER TABLE play_members ADD COLUMN gold INTEGER NOT NULL DEFAULT 10;') unless columns.include?('gold')
  end

  # play_events predates the type column, used to distinguish action kinds
  # (e.g. "search") on kind:"action" rows; narration rows leave it NULL.
  def migrate_play_events
    columns = query('PRAGMA table_info(play_events);').map { |row| row['name'] }
    exec('ALTER TABLE play_events ADD COLUMN type TEXT;') unless columns.include?('type')
    exec('ALTER TABLE play_events ADD COLUMN target TEXT;') unless columns.include?('target')
  end

  def reset_schema
    exec(<<~SQL)
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
      DROP TABLE IF EXISTS character_equipment;
      DROP TABLE IF EXISTS campaign_crafting_projects;
      DROP TABLE IF EXISTS campaign_sessions;
      DROP TABLE IF EXISTS play_campaigns;
      DROP TABLE IF EXISTS play_members;
      DROP TABLE IF EXISTS play_events;
      DROP TABLE IF EXISTS play_documents;
      DROP TABLE IF EXISTS play_scenes;
      DROP TABLE IF EXISTS play_locations;
      DROP TABLE IF EXISTS play_location_connections;
      DROP TABLE IF EXISTS play_encounters;
      DROP TABLE IF EXISTS play_spells;
      DROP TABLE IF EXISTS play_prepared_spells;
      DROP TABLE IF EXISTS play_casts;
      DROP TABLE IF EXISTS play_concentration;
      DROP TABLE IF EXISTS play_inventory_items;
      DROP TABLE IF EXISTS play_equipment;
      DROP TABLE IF EXISTS play_currency_transfers;
      DROP TABLE IF EXISTS play_transactional_transfers;
      DROP TABLE IF EXISTS play_exports;
      DROP TABLE IF EXISTS play_backups;
      DROP TABLE IF EXISTS play_replay_events;
      DROP TABLE IF EXISTS play_rng_seeds;
      DROP TABLE IF EXISTS play_rng_rolls;
      DROP TABLE IF EXISTS play_moderation_reports;
      DROP TABLE IF EXISTS play_safety_boundaries;
      DROP TABLE IF EXISTS play_safety_events;
      DROP TABLE IF EXISTS play_fixture_seeds;
      DROP TABLE IF EXISTS play_imports;
      DROP TABLE IF EXISTS play_migrations;
      DROP TABLE IF EXISTS play_loot;
      DROP TABLE IF EXISTS play_loot_votes;
      DROP TABLE IF EXISTS play_npcs;
      DROP TABLE IF EXISTS play_factions;
      DROP TABLE IF EXISTS play_faction_reputation;
      DROP TABLE IF EXISTS play_faction_reputation_history;
      DROP TABLE IF EXISTS play_npc_dialogue;
      DROP TABLE IF EXISTS play_session_zero;
    SQL
    init_schema
  end

  def run(sql)
    stdout, stderr, status = Open3.capture3('sqlite3', path, stdin_data: sql)
    raise "sqlite3 error: #{stderr}" unless status.success?

    stdout
  end
  private_class_method :run
end
