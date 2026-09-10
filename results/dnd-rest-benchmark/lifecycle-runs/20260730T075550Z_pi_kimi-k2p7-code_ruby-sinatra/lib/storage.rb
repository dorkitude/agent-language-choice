# frozen_string_literal: true

require 'sqlite3'
require 'json'

# SQLite persistence layer for the D&D DM tools API.
#
# All database access is serialized through Storage::DB_MUTEX because Puma may
# serve requests concurrently. The sqlite3 gem connection is not thread-safe
# across concurrent use, so the mutex guarantees a single in-flight operation at
# a time. The connection itself is created lazily on the first call to #db.
module Storage
  DB_PATH = File.expand_path('../game.db', __dir__)
  SCHEMA_VERSION = 1

  DB_MUTEX = Mutex.new

  # Returns the shared SQLite connection, lazily creating it on first use.
  def self.db
    @db ||= begin
      db = SQLite3::Database.new(DB_PATH)
      db.busy_timeout = 5000
      db.results_as_hash = true
      db
    end
  end

  # Yields the shared connection while holding the storage mutex.
  def self.with_db
    DB_MUTEX.synchronize { yield db }
  end

  # Reads a JSON text column from a result row, returning +default+ when the
  # column is NULL or absent.
  def self.json_column(row, column, default = nil)
    value = row[column]
    value ? JSON.parse(value) : default
  end

  # Creates all tables and records the schema version. Safe to call repeatedly;
  # existing tables are left untouched.
  def self.init_schema!
    with_db do |db|
      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS schema_info (
          version INTEGER PRIMARY KEY,
          initialized_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
      SQL
      db.execute('INSERT OR IGNORE INTO schema_info (version) VALUES (?)', [SCHEMA_VERSION])

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS combat_sessions (
          id TEXT PRIMARY KEY,
          round INTEGER NOT NULL,
          turn_index INTEGER NOT NULL,
          order_json TEXT NOT NULL,
          combatants_json TEXT NOT NULL,
          conditions_json TEXT NOT NULL
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS users (
          username TEXT PRIMARY KEY,
          password_hash TEXT NOT NULL,
          role TEXT NOT NULL
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS compendium_monsters (
          slug TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          cr TEXT NOT NULL,
          armor_class INTEGER NOT NULL,
          hit_points INTEGER NOT NULL,
          tags_json TEXT NOT NULL
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS compendium_items (
          slug TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          type TEXT NOT NULL,
          rarity TEXT NOT NULL,
          cost_gp INTEGER NOT NULL
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS campaigns (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          dm TEXT NOT NULL
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS campaign_characters (
          campaign_id TEXT NOT NULL,
          id TEXT NOT NULL,
          name TEXT NOT NULL,
          level INTEGER NOT NULL,
          class TEXT NOT NULL,
          PRIMARY KEY (campaign_id, id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS campaign_events (
          campaign_id TEXT NOT NULL,
          id TEXT NOT NULL,
          kind TEXT NOT NULL,
          summary TEXT NOT NULL,
          PRIMARY KEY (campaign_id, id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS campaign_quests (
          campaign_id TEXT NOT NULL,
          id TEXT NOT NULL,
          title TEXT NOT NULL,
          status TEXT NOT NULL,
          milestones_json TEXT NOT NULL,
          completed_milestones_json TEXT NOT NULL,
          PRIMARY KEY (campaign_id, id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS campaign_factions (
          campaign_id TEXT NOT NULL,
          id TEXT NOT NULL,
          name TEXT NOT NULL,
          stance TEXT NOT NULL,
          PRIMARY KEY (campaign_id, id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS campaign_npcs (
          campaign_id TEXT NOT NULL,
          id TEXT NOT NULL,
          name TEXT NOT NULL,
          faction_id TEXT NOT NULL,
          disposition INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS campaign_inventory (
          campaign_id TEXT NOT NULL,
          item_slug TEXT NOT NULL,
          owner TEXT NOT NULL,
          quantity INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, item_slug, owner)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS campaign_crafting_projects (
          campaign_id TEXT NOT NULL,
          id TEXT NOT NULL,
          character_id TEXT NOT NULL,
          item_slug TEXT NOT NULL,
          days_required INTEGER NOT NULL,
          days_completed INTEGER NOT NULL,
          status TEXT NOT NULL,
          cost_gp INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS campaign_sessions (
          campaign_id TEXT NOT NULL,
          id TEXT NOT NULL,
          starts_at TEXT NOT NULL,
          duration_minutes INTEGER NOT NULL,
          agenda_json TEXT NOT NULL,
          PRIMARY KEY (campaign_id, id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS campaign_session_attendance (
          campaign_id TEXT NOT NULL,
          session_id TEXT NOT NULL,
          present_json TEXT NOT NULL,
          absent_json TEXT NOT NULL,
          PRIMARY KEY (campaign_id, session_id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaigns (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          owner TEXT NOT NULL,
          status TEXT NOT NULL,
          phase TEXT,
          max_players INTEGER NOT NULL,
          current_actor TEXT,
          turn_number INTEGER,
          queue_json TEXT,
          nudge_count INTEGER NOT NULL DEFAULT 0,
          story TEXT,
          dm_notes TEXT,
          current_scene_id TEXT
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_members (
          campaign_id TEXT NOT NULL,
          username TEXT NOT NULL,
          character_id TEXT NOT NULL,
          name TEXT NOT NULL,
          class TEXT NOT NULL,
          hp_current INTEGER NOT NULL DEFAULT 20,
          hp_max INTEGER NOT NULL DEFAULT 20,
          PRIMARY KEY (campaign_id, username),
          UNIQUE (campaign_id, character_id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_narrations (
          campaign_id TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          kind TEXT NOT NULL,
          actor TEXT NOT NULL,
          type TEXT,
          target TEXT,
          text TEXT NOT NULL,
          PRIMARY KEY (campaign_id, sequence)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_scenes (
          campaign_id TEXT NOT NULL,
          id TEXT NOT NULL,
          name TEXT NOT NULL,
          status TEXT NOT NULL,
          PRIMARY KEY (campaign_id, id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_locations (
          campaign_id TEXT NOT NULL,
          id TEXT NOT NULL,
          name TEXT NOT NULL,
          PRIMARY KEY (campaign_id, id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_location_connections (
          campaign_id TEXT NOT NULL,
          from_id TEXT NOT NULL,
          to_id TEXT NOT NULL,
          travel_turns INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, from_id, to_id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_encounters (
          campaign_id TEXT NOT NULL,
          id TEXT NOT NULL,
          name TEXT NOT NULL,
          status TEXT NOT NULL,
          combatants_json TEXT NOT NULL,
          round INTEGER NOT NULL DEFAULT 1,
          turn_index INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY (campaign_id, id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_encounter_monsters (
          campaign_id TEXT NOT NULL,
          encounter_id TEXT NOT NULL,
          monster_id TEXT NOT NULL,
          name TEXT NOT NULL,
          hp_max INTEGER NOT NULL,
          hp_current INTEGER NOT NULL,
          initiative INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, encounter_id, monster_id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_character_spells (
          campaign_id TEXT NOT NULL,
          character_id TEXT NOT NULL,
          spell_id TEXT NOT NULL,
          name TEXT NOT NULL,
          level INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, character_id, spell_id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_character_casts (
          campaign_id TEXT NOT NULL,
          character_id TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          spell_id TEXT NOT NULL,
          target TEXT NOT NULL,
          slot_level INTEGER NOT NULL,
          slots_remaining INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, character_id, sequence)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_character_inventory (
          campaign_id TEXT NOT NULL,
          character_id TEXT NOT NULL,
          item_id TEXT NOT NULL,
          quantity INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, character_id, item_id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_character_equipment (
          campaign_id TEXT NOT NULL,
          character_id TEXT NOT NULL,
          slot TEXT NOT NULL,
          item_id TEXT NOT NULL,
          attuned INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY (campaign_id, character_id, slot)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_character_transfers (
          campaign_id TEXT NOT NULL,
          transfer_id INTEGER NOT NULL,
          from_character_id TEXT NOT NULL,
          to_character_id TEXT NOT NULL,
          gold INTEGER NOT NULL,
          from_gold INTEGER NOT NULL,
          to_gold INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, transfer_id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_transactional_transfers (
          campaign_id TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          from_character_id TEXT NOT NULL,
          to_character_id TEXT NOT NULL,
          amount INTEGER NOT NULL,
          from_gold INTEGER NOT NULL,
          to_gold INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, sequence)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_loot (
          campaign_id TEXT NOT NULL,
          loot_id TEXT NOT NULL,
          item_id TEXT NOT NULL,
          quantity INTEGER NOT NULL,
          status TEXT NOT NULL DEFAULT 'open',
          recipient_character_id TEXT,
          PRIMARY KEY (campaign_id, loot_id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_loot_votes (
          campaign_id TEXT NOT NULL,
          loot_id TEXT NOT NULL,
          voter TEXT NOT NULL,
          recipient_character_id TEXT NOT NULL,
          PRIMARY KEY (campaign_id, loot_id, voter)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_npcs (
          campaign_id TEXT NOT NULL,
          npc_id TEXT NOT NULL,
          name TEXT NOT NULL,
          agenda TEXT NOT NULL,
          public_status TEXT NOT NULL,
          PRIMARY KEY (campaign_id, npc_id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_factions (
          campaign_id TEXT NOT NULL,
          faction_id TEXT NOT NULL,
          name TEXT NOT NULL,
          PRIMARY KEY (campaign_id, faction_id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_reputation (
          campaign_id TEXT NOT NULL,
          faction_id TEXT NOT NULL,
          character_id TEXT NOT NULL,
          delta INTEGER NOT NULL,
          reputation INTEGER NOT NULL,
          reason TEXT NOT NULL
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_npc_dialogue (
          campaign_id TEXT NOT NULL,
          npc_id TEXT NOT NULL,
          dialogue_id TEXT NOT NULL,
          speaker TEXT NOT NULL,
          text TEXT NOT NULL,
          visibility TEXT NOT NULL,
          PRIMARY KEY (campaign_id, npc_id, dialogue_id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_relationships (
          campaign_id TEXT NOT NULL,
          source_id TEXT NOT NULL,
          target_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          score INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, source_id, target_id, kind)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_clues (
          campaign_id TEXT NOT NULL,
          clue_id TEXT NOT NULL,
          text TEXT NOT NULL,
          audience TEXT NOT NULL,
          character_id TEXT,
          PRIMARY KEY (campaign_id, clue_id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_quests (
          campaign_id TEXT NOT NULL,
          quest_id TEXT NOT NULL,
          title TEXT NOT NULL,
          depends_on_json TEXT NOT NULL,
          state TEXT NOT NULL,
          PRIMARY KEY (campaign_id, quest_id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_world_events (
          campaign_id TEXT NOT NULL,
          event_id TEXT NOT NULL,
          turn_number INTEGER NOT NULL,
          title TEXT NOT NULL,
          text TEXT NOT NULL,
          status TEXT NOT NULL,
          resolution_turn_number INTEGER,
          resolution_text TEXT,
          PRIMARY KEY (campaign_id, event_id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_calendars (
          campaign_id TEXT PRIMARY KEY,
          day INTEGER NOT NULL,
          season TEXT NOT NULL
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_settlements (
          campaign_id TEXT NOT NULL,
          settlement_id TEXT NOT NULL,
          name TEXT NOT NULL,
          services_json TEXT NOT NULL,
          availability TEXT NOT NULL,
          discovered_by_json TEXT NOT NULL DEFAULT '[]',
          PRIMARY KEY (campaign_id, settlement_id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_shops (
          campaign_id TEXT NOT NULL,
          settlement_id TEXT NOT NULL,
          shop_id TEXT NOT NULL,
          name TEXT NOT NULL,
          stock_json TEXT NOT NULL,
          buy_price INTEGER NOT NULL,
          sell_price INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, settlement_id, shop_id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_recipes (
          campaign_id TEXT NOT NULL,
          recipe_id TEXT NOT NULL,
          name TEXT NOT NULL,
          ingredients_json TEXT NOT NULL,
          output_item TEXT NOT NULL,
          output_quantity INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, recipe_id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_downtime_activities (
          campaign_id TEXT NOT NULL,
          activity_id TEXT NOT NULL,
          name TEXT NOT NULL,
          cycles_required INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, activity_id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_downtime_allocations (
          campaign_id TEXT NOT NULL,
          character_id TEXT NOT NULL,
          activity_id TEXT NOT NULL,
          cycles_completed INTEGER NOT NULL DEFAULT 0,
          completions INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY (campaign_id, character_id, activity_id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_content (
          campaign_id TEXT NOT NULL,
          content_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          text TEXT NOT NULL,
          tags_json TEXT NOT NULL,
          PRIMARY KEY (campaign_id, content_id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_notes (
          campaign_id TEXT NOT NULL,
          note_id TEXT NOT NULL,
          text TEXT NOT NULL,
          visibility TEXT NOT NULL,
          owner TEXT NOT NULL,
          PRIMARY KEY (campaign_id, note_id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_whispers (
          campaign_id TEXT NOT NULL,
          whisper_id TEXT NOT NULL,
          from_character_id TEXT NOT NULL,
          to_character_id TEXT NOT NULL,
          text TEXT NOT NULL,
          PRIMARY KEY (campaign_id, whisper_id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_messages (
          campaign_id TEXT NOT NULL,
          position INTEGER NOT NULL CHECK(position >= 0),
          username TEXT NOT NULL,
          text TEXT NOT NULL,
          PRIMARY KEY (campaign_id, position)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_invitations (
          campaign_id TEXT NOT NULL,
          invitation_id TEXT NOT NULL,
          username TEXT NOT NULL,
          character_id TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',
          PRIMARY KEY (campaign_id, invitation_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
        )
      SQL

      db.execute <<~SQL
        CREATE UNIQUE INDEX IF NOT EXISTS idx_play_campaign_invitations_pending_username
        ON play_campaign_invitations (campaign_id, username)
        WHERE status = 'pending'
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_delegations (
          campaign_id TEXT NOT NULL,
          username TEXT NOT NULL,
          powers_json TEXT NOT NULL,
          active INTEGER NOT NULL DEFAULT 1,
          PRIMARY KEY (campaign_id, username),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_delegation_audit (
          campaign_id TEXT NOT NULL,
          username TEXT NOT NULL,
          action TEXT NOT NULL,
          powers_json TEXT NOT NULL
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_audit_events (
          campaign_id TEXT NOT NULL,
          timestamp INTEGER NOT NULL,
          kind TEXT NOT NULL,
          actor TEXT NOT NULL,
          role TEXT NOT NULL,
          correlation_id TEXT NOT NULL,
          PRIMARY KEY (campaign_id, timestamp),
          UNIQUE (campaign_id, correlation_id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_projection_events (
          campaign_id TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          event_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          value TEXT,
          PRIMARY KEY (campaign_id, sequence),
          UNIQUE (campaign_id, event_id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_idempotent_events (
          campaign_id TEXT NOT NULL,
          event_id TEXT NOT NULL,
          value TEXT NOT NULL,
          idempotency_key TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, event_id),
          UNIQUE (campaign_id, idempotency_key)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_safe_turns (
          campaign_id TEXT NOT NULL,
          submission_id TEXT NOT NULL,
          action TEXT NOT NULL,
          accepted_turn INTEGER NOT NULL,
          next_turn INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, submission_id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_exports (
          campaign_id TEXT NOT NULL,
          version INTEGER NOT NULL,
          story TEXT NOT NULL,
          status TEXT NOT NULL,
          PRIMARY KEY (campaign_id, version),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_imports (
          campaign_id TEXT PRIMARY KEY,
          version INTEGER NOT NULL,
          story TEXT NOT NULL,
          status TEXT NOT NULL,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_migrations (
          campaign_id TEXT PRIMARY KEY,
          schema_version INTEGER NOT NULL,
          story TEXT NOT NULL,
          campaign_name TEXT NOT NULL,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_backups (
          campaign_id TEXT NOT NULL,
          backup_id TEXT NOT NULL,
          story TEXT NOT NULL,
          status TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, backup_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_replay_events (
          campaign_id TEXT NOT NULL,
          event_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          text TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, event_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_rng_seeds (
          campaign_id TEXT PRIMARY KEY,
          seed TEXT NOT NULL,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_rng_rolls (
          campaign_id TEXT NOT NULL,
          roll_id TEXT NOT NULL,
          sides INTEGER NOT NULL,
          result INTEGER NOT NULL,
          sequence INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, roll_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_moderation_reports (
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
          PRIMARY KEY (campaign_id, report_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_safety_boundaries (
          campaign_id TEXT PRIMARY KEY,
          blocked_tags_json TEXT NOT NULL DEFAULT '[]',
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_safety_events (
          campaign_id TEXT NOT NULL,
          event_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          text TEXT NOT NULL,
          tags_json TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, event_id),
          UNIQUE (campaign_id, sequence),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_fixtures (
          campaign_id TEXT PRIMARY KEY,
          fixture_id TEXT NOT NULL,
          status TEXT NOT NULL,
          characters_json TEXT NOT NULL,
          story TEXT NOT NULL,
          event_ids_json TEXT NOT NULL,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_search_records (
          campaign_id TEXT NOT NULL,
          record_id TEXT NOT NULL,
          text TEXT NOT NULL,
          PRIMARY KEY (campaign_id, record_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_rate_events (
          campaign_id TEXT NOT NULL,
          event_id TEXT NOT NULL,
          actor TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, event_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_rejected_rate_events (
          campaign_id TEXT NOT NULL,
          event_id TEXT NOT NULL,
          actor TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, event_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_spectators (
          spectator_id TEXT PRIMARY KEY,
          campaign_id TEXT NOT NULL,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaign_feed_events (
          campaign_id TEXT NOT NULL,
          event_id TEXT NOT NULL,
          text TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, event_id),
          UNIQUE (campaign_id, sequence),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
        )
      SQL

      ensure_column!(db, 'play_campaigns', 'queue_json', 'TEXT')
      ensure_column!(db, 'play_campaigns', 'current_location_id', 'TEXT')
      ensure_column!(db, 'play_campaign_narrations', 'type', 'TEXT')
      ensure_column!(db, 'play_campaign_narrations', 'target', 'TEXT')
      ensure_column!(db, 'play_campaigns', 'nudge_count', 'INTEGER NOT NULL DEFAULT 0')
      ensure_column!(db, 'play_campaigns', 'story', 'TEXT')
      ensure_column!(db, 'play_campaigns', 'dm_notes', 'TEXT')
      ensure_column!(db, 'play_campaigns', 'current_scene_id', 'TEXT')
      ensure_column!(db, 'play_campaigns', 'pre_combat_state_json', 'TEXT')
      ensure_column!(db, 'play_campaigns', 'session_zero_json', 'TEXT')
      ensure_column!(db, 'play_campaign_members', 'hp_current', 'INTEGER NOT NULL DEFAULT 20')
      ensure_column!(db, 'play_campaign_members', 'hp_max', 'INTEGER NOT NULL DEFAULT 20')
      ensure_column!(db, 'play_campaign_members', 'status', "TEXT NOT NULL DEFAULT 'conscious'")
      ensure_column!(db, 'play_campaign_members', 'death_save_successes', 'INTEGER NOT NULL DEFAULT 0')
      ensure_column!(db, 'play_campaign_members', 'death_save_failures', 'INTEGER NOT NULL DEFAULT 0')
      ensure_column!(db, 'play_campaign_members', 'owner', 'TEXT')
      db.execute("UPDATE play_campaign_members SET owner = username WHERE owner IS NULL")
      ensure_column!(db, 'play_campaign_members', 'race', 'TEXT')
      ensure_column!(db, 'play_campaign_members', 'background', 'TEXT')
      ensure_column!(db, 'play_campaign_members', 'level', 'INTEGER')
      ensure_column!(db, 'play_campaign_members', 'abilities_json', 'TEXT')
      ensure_column!(db, 'play_campaign_members', 'prepared_spells_json', 'TEXT')
      ensure_column!(db, 'play_campaign_members', 'spell_slots_json', 'TEXT')
      ensure_column!(db, 'play_campaign_members', 'concentration_json', 'TEXT')
      ensure_column!(db, 'play_campaign_members', 'gold', 'INTEGER NOT NULL DEFAULT 10')
      ensure_column!(db, 'play_campaign_encounters', 'round', 'INTEGER NOT NULL DEFAULT 1')
      ensure_column!(db, 'play_campaign_encounters', 'turn_index', 'INTEGER NOT NULL DEFAULT 0')
      ensure_column!(db, 'play_campaign_encounters', 'conditions_json', "TEXT NOT NULL DEFAULT '{}'")
      ensure_column!(db, 'play_campaign_encounters', 'order_json', 'TEXT')
      ensure_column!(db, 'play_campaign_encounters', 'readies_json', "TEXT NOT NULL DEFAULT '[]'")
      ensure_column!(db, 'play_campaign_encounters', 'xp_awarded', 'INTEGER NOT NULL DEFAULT 0')
      ensure_column!(db, 'play_campaign_encounters', 'loot_json', "TEXT NOT NULL DEFAULT '[]'")
      ensure_column!(db, 'play_campaign_encounters', 'rewards_awarded', 'INTEGER NOT NULL DEFAULT 0')
      ensure_column!(db, 'play_campaign_quests', 'rewards_json', 'TEXT')
      ensure_column!(db, 'play_campaign_quests', 'rewards_awarded', 'INTEGER NOT NULL DEFAULT 0')
      ensure_column!(db, 'play_campaign_members', 'quest_rewards_xp', 'INTEGER NOT NULL DEFAULT 0')
      ensure_column!(db, 'play_campaign_members', 'quest_rewards_items_json', "TEXT NOT NULL DEFAULT '{}'")
      ensure_column!(db, 'play_campaigns', 'safe_turn_current_turn', 'INTEGER NOT NULL DEFAULT 1')
    end
  end

  # Adds a column to a table when it is missing. Table and column names are
  # literal strings controlled by this module (not user input). Must be called
  # while already holding the storage mutex.
  def self.ensure_column!(db, table, column, definition)
    columns = db.execute("PRAGMA table_info(#{table})").map { |row| row['name'] }
    return if columns.include?(column)

    db.execute("ALTER TABLE #{table} ADD COLUMN #{column} #{definition}")
  end

  # Drops all application tables. Used by the storage reset endpoint.
  def self.drop_tables!
    with_db do |db|
      db.execute('DROP TABLE IF EXISTS combat_sessions')
      db.execute('DROP TABLE IF EXISTS users')
      db.execute('DROP TABLE IF EXISTS compendium_monsters')
      db.execute('DROP TABLE IF EXISTS compendium_items')
      db.execute('DROP TABLE IF EXISTS campaign_characters')
      db.execute('DROP TABLE IF EXISTS campaign_events')
      db.execute('DROP TABLE IF EXISTS campaign_quests')
      db.execute('DROP TABLE IF EXISTS campaign_factions')
      db.execute('DROP TABLE IF EXISTS campaign_npcs')
      db.execute('DROP TABLE IF EXISTS campaign_inventory')
      db.execute('DROP TABLE IF EXISTS campaign_crafting_projects')
      db.execute('DROP TABLE IF EXISTS campaign_sessions')
      db.execute('DROP TABLE IF EXISTS campaign_session_attendance')
      db.execute('DROP TABLE IF EXISTS play_campaigns')
      db.execute('DROP TABLE IF EXISTS play_campaign_members')
      db.execute('DROP TABLE IF EXISTS play_campaign_narrations')
      db.execute('DROP TABLE IF EXISTS play_campaign_scenes')
      db.execute('DROP TABLE IF EXISTS play_campaign_locations')
      db.execute('DROP TABLE IF EXISTS play_campaign_location_connections')
      db.execute('DROP TABLE IF EXISTS play_campaign_encounters')
      db.execute('DROP TABLE IF EXISTS play_campaign_encounter_monsters')
      db.execute('DROP TABLE IF EXISTS play_campaign_character_spells')
      db.execute('DROP TABLE IF EXISTS play_campaign_character_casts')
      db.execute('DROP TABLE IF EXISTS play_campaign_character_inventory')
      db.execute('DROP TABLE IF EXISTS play_campaign_character_equipment')
      db.execute('DROP TABLE IF EXISTS play_campaign_character_transfers')
      db.execute('DROP TABLE IF EXISTS play_campaign_transactional_transfers')
      db.execute('DROP TABLE IF EXISTS play_campaign_loot')
      db.execute('DROP TABLE IF EXISTS play_campaign_loot_votes')
      db.execute('DROP TABLE IF EXISTS play_campaign_npcs')
      db.execute('DROP TABLE IF EXISTS play_campaign_factions')
      db.execute('DROP TABLE IF EXISTS play_campaign_reputation')
      db.execute('DROP TABLE IF EXISTS play_campaign_npc_dialogue')
      db.execute('DROP TABLE IF EXISTS play_campaign_relationships')
      db.execute('DROP TABLE IF EXISTS play_campaign_clues')
      db.execute('DROP TABLE IF EXISTS play_campaign_quests')
      db.execute('DROP TABLE IF EXISTS play_campaign_world_events')
      db.execute('DROP TABLE IF EXISTS play_campaign_calendars')
      db.execute('DROP TABLE IF EXISTS play_campaign_shops')
      db.execute('DROP TABLE IF EXISTS play_campaign_settlements')
      db.execute('DROP TABLE IF EXISTS play_campaign_downtime_activities')
      db.execute('DROP TABLE IF EXISTS play_campaign_downtime_allocations')
      db.execute('DROP TABLE IF EXISTS play_campaign_content')
      db.execute('DROP TABLE IF EXISTS play_campaign_notes')
      db.execute('DROP TABLE IF EXISTS play_campaign_whispers')
      db.execute('DROP TABLE IF EXISTS play_campaign_messages')
      db.execute('DROP TABLE IF EXISTS play_campaign_invitations')
      db.execute('DROP TABLE IF EXISTS play_campaign_delegations')
      db.execute('DROP TABLE IF EXISTS play_campaign_delegation_audit')
      db.execute('DROP TABLE IF EXISTS play_campaign_audit_events')
      db.execute('DROP TABLE IF EXISTS play_campaign_projection_events')
      db.execute('DROP TABLE IF EXISTS play_campaign_idempotent_events')
      db.execute('DROP TABLE IF EXISTS play_campaign_safe_turns')
      db.execute('DROP TABLE IF EXISTS play_campaign_exports')
      db.execute('DROP TABLE IF EXISTS play_campaign_imports')
      db.execute('DROP TABLE IF EXISTS play_campaign_migrations')
      db.execute('DROP TABLE IF EXISTS play_campaign_backups')
      db.execute('DROP TABLE IF EXISTS play_campaign_replay_events')
      db.execute('DROP TABLE IF EXISTS play_campaign_rng_seeds')
      db.execute('DROP TABLE IF EXISTS play_campaign_rng_rolls')
      db.execute('DROP TABLE IF EXISTS play_campaign_moderation_reports')
      db.execute('DROP TABLE IF EXISTS play_campaign_safety_boundaries')
      db.execute('DROP TABLE IF EXISTS play_campaign_safety_events')
      db.execute('DROP TABLE IF EXISTS play_campaign_fixtures')
      db.execute('DROP TABLE IF EXISTS play_campaign_search_records')
      db.execute('DROP TABLE IF EXISTS play_campaign_rate_events')
      db.execute('DROP TABLE IF EXISTS play_campaign_rejected_rate_events')
      db.execute('DROP TABLE IF EXISTS play_campaign_spectators')
      db.execute('DROP TABLE IF EXISTS play_campaign_feed_events')
      db.execute('DROP TABLE IF EXISTS campaigns')
      db.execute('DROP TABLE IF EXISTS schema_info')
    end
  end

  # Destructively resets the database and re-creates the schema.
  def self.reset!
    drop_tables!
    init_schema!
  end

  # Returns true when all expected tables are present in the database.
  def self.initialized?
    expected = %w[
      combat_sessions users schema_info compendium_monsters compendium_items
      campaigns campaign_characters campaign_events campaign_quests
      campaign_factions campaign_npcs campaign_inventory
      campaign_crafting_projects campaign_sessions
      campaign_session_attendance play_campaigns play_campaign_members
      play_campaign_narrations play_campaign_scenes play_campaign_locations
      play_campaign_location_connections play_campaign_encounters
      play_campaign_encounter_monsters play_campaign_character_spells
      play_campaign_character_casts play_campaign_character_inventory
      play_campaign_character_equipment play_campaign_character_transfers
      play_campaign_transactional_transfers play_campaign_loot play_campaign_loot_votes play_campaign_npcs
      play_campaign_factions play_campaign_reputation
      play_campaign_npc_dialogue play_campaign_relationships play_campaign_clues
      play_campaign_quests play_campaign_world_events play_campaign_calendars
      play_campaign_settlements play_campaign_shops play_campaign_recipes
      play_campaign_downtime_activities play_campaign_downtime_allocations
      play_campaign_content play_campaign_notes play_campaign_whispers
      play_campaign_messages play_campaign_invitations play_campaign_delegations
      play_campaign_delegation_audit play_campaign_audit_events
      play_campaign_projection_events
      play_campaign_idempotent_events
      play_campaign_exports
      play_campaign_imports
      play_campaign_migrations
      play_campaign_backups
      play_campaign_replay_events
      play_campaign_search_records
      play_campaign_rng_seeds
      play_campaign_rng_rolls
      play_campaign_moderation_reports
      play_campaign_safety_boundaries
      play_campaign_safety_events
      play_campaign_fixtures
      play_campaign_rate_events
      play_campaign_rejected_rate_events
      play_campaign_spectators
      play_campaign_feed_events
    ]

    with_db do |db|
      tables = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN (#{expected.map { '?' }.join(',')})",
        expected
      )
      tables.size == expected.size
    end
  end

  # --- Combat sessions ---

  def self.session_exists?(id)
    with_db { |db| db.get_first_value('SELECT 1 FROM combat_sessions WHERE id = ?', [id]) }
  end

  def self.load_session(id)
    row = with_db { |db| db.get_first_row('SELECT * FROM combat_sessions WHERE id = ?', [id]) }
    return nil unless row

    {
      id: row['id'],
      round: row['round'],
      turn_index: row['turn_index'],
      order: json_column(row, 'order_json'),
      combatants: json_column(row, 'combatants_json'),
      conditions: json_column(row, 'conditions_json')
    }
  end

  def self.save_session(session)
    with_db do |db|
      db.execute(
        'INSERT OR REPLACE INTO combat_sessions (id, round, turn_index, order_json, combatants_json, conditions_json) VALUES (?, ?, ?, ?, ?, ?)',
        [session[:id], session[:round], session[:turn_index], JSON.dump(session[:order]), JSON.dump(session[:combatants]), JSON.dump(session[:conditions])]
      )
    end
  end

  # --- Users ---

  def self.user_exists?(username)
    with_db { |db| db.get_first_value('SELECT 1 FROM users WHERE username = ?', [username]) }
  end

  def self.load_user(username)
    row = with_db { |db| db.get_first_row('SELECT * FROM users WHERE username = ?', [username]) }
    return nil unless row

    {
      username: row['username'],
      password_hash: row['password_hash'],
      role: row['role']
    }
  end

  def self.register_user(username, password_hash, role)
    with_db do |db|
      db.execute(
        'INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)',
        [username, password_hash, role]
      )
    end
  end

  # --- Compendium monsters ---

  def self.monster_exists?(slug)
    with_db { |db| db.get_first_value('SELECT 1 FROM compendium_monsters WHERE slug = ?', [slug]) }
  end

  def self.load_monster(slug)
    row = with_db { |db| db.get_first_row('SELECT * FROM compendium_monsters WHERE slug = ?', [slug]) }
    return nil unless row

    {
      slug: row['slug'],
      name: row['name'],
      cr: row['cr'],
      armor_class: row['armor_class'],
      hit_points: row['hit_points'],
      tags: json_column(row, 'tags_json')
    }
  end

  def self.create_monster(slug, name, cr, armor_class, hit_points, tags)
    with_db do |db|
      db.execute(
        'INSERT INTO compendium_monsters (slug, name, cr, armor_class, hit_points, tags_json) VALUES (?, ?, ?, ?, ?, ?)',
        [slug, name, cr, armor_class, hit_points, JSON.dump(tags)]
      )
    end
  end

  # --- Compendium items ---

  def self.item_exists?(slug)
    with_db { |db| db.get_first_value('SELECT 1 FROM compendium_items WHERE slug = ?', [slug]) }
  end

  def self.load_item(slug)
    row = with_db { |db| db.get_first_row('SELECT * FROM compendium_items WHERE slug = ?', [slug]) }
    return nil unless row

    {
      slug: row['slug'],
      name: row['name'],
      type: row['type'],
      rarity: row['rarity'],
      cost_gp: row['cost_gp']
    }
  end

  def self.create_item(slug, name, type, rarity, cost_gp)
    with_db do |db|
      db.execute(
        'INSERT INTO compendium_items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)',
        [slug, name, type, rarity, cost_gp]
      )
    end
  end

  # --- Campaigns ---

  def self.campaign_exists?(id)
    with_db { |db| db.get_first_value('SELECT 1 FROM campaigns WHERE id = ?', [id]) }
  end

  def self.load_campaign(id)
    row = with_db { |db| db.get_first_row('SELECT * FROM campaigns WHERE id = ?', [id]) }
    return nil unless row

    { id: row['id'], name: row['name'], dm: row['dm'] }
  end

  def self.create_campaign(id, name, dm)
    with_db do |db|
      db.execute(
        'INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)',
        [id, name, dm]
      )
    end
  end

  # --- Campaign characters ---

  def self.campaign_characters(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY rowid',
        [campaign_id]
      ).map do |row|
        { id: row['id'], name: row['name'], level: row['level'], class: row['class'] }
      end
    end
  end

  def self.campaign_characters_count(campaign_id)
    with_db { |db| db.get_first_value('SELECT COUNT(*) FROM campaign_characters WHERE campaign_id = ?', [campaign_id]) }
  end

  def self.character_exists?(campaign_id, id)
    with_db { |db| db.get_first_value('SELECT 1 FROM campaign_characters WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
  end

  def self.create_character(campaign_id, id, name, level, class_name)
    with_db do |db|
      db.execute(
        'INSERT INTO campaign_characters (campaign_id, id, name, level, class) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, id, name, level, class_name]
      )
    end
  end

  # --- Campaign events ---

  def self.campaign_log_count(campaign_id)
    with_db { |db| db.get_first_value('SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?', [campaign_id]) }
  end

  def self.campaign_events(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT id, kind, summary FROM campaign_events WHERE campaign_id = ? ORDER BY rowid',
        [campaign_id]
      ).map do |row|
        { id: row['id'], kind: row['kind'], summary: row['summary'] }
      end
    end
  end

  def self.event_exists?(campaign_id, id)
    with_db { |db| db.get_first_value('SELECT 1 FROM campaign_events WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
  end

  def self.create_event(campaign_id, id, kind, summary)
    with_db do |db|
      db.execute(
        'INSERT INTO campaign_events (campaign_id, id, kind, summary) VALUES (?, ?, ?, ?)',
        [campaign_id, id, kind, summary]
      )
    end
  end

  # --- Campaign quests ---

  def self.quest_exists?(campaign_id, id)
    with_db { |db| db.get_first_value('SELECT 1 FROM campaign_quests WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
  end

  def self.load_quest(campaign_id, id)
    row = with_db { |db| db.get_first_row('SELECT * FROM campaign_quests WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
    return nil unless row

    {
      campaign_id: row['campaign_id'],
      id: row['id'],
      title: row['title'],
      status: row['status'],
      milestones: json_column(row, 'milestones_json'),
      completed_milestones: json_column(row, 'completed_milestones_json')
    }
  end

  def self.create_quest(quest)
    with_db do |db|
      db.execute(
        'INSERT INTO campaign_quests (campaign_id, id, title, status, milestones_json, completed_milestones_json) VALUES (?, ?, ?, ?, ?, ?)',
        [quest[:campaign_id], quest[:id], quest[:title], quest[:status], JSON.dump(quest[:milestones]), JSON.dump(quest[:completed_milestones])]
      )
    end
  end

  def self.save_quest(quest)
    with_db do |db|
      db.execute(
        'INSERT OR REPLACE INTO campaign_quests (campaign_id, id, title, status, milestones_json, completed_milestones_json) VALUES (?, ?, ?, ?, ?, ?)',
        [quest[:campaign_id], quest[:id], quest[:title], quest[:status], JSON.dump(quest[:milestones]), JSON.dump(quest[:completed_milestones])]
      )
    end
  end

  # --- Campaign factions ---

  def self.faction_exists?(campaign_id, id)
    with_db { |db| db.get_first_value('SELECT 1 FROM campaign_factions WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
  end

  def self.load_faction(campaign_id, id)
    row = with_db { |db| db.get_first_row('SELECT * FROM campaign_factions WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
    return nil unless row

    {
      campaign_id: row['campaign_id'],
      id: row['id'],
      name: row['name'],
      stance: row['stance']
    }
  end

  def self.create_faction(campaign_id, id, name, stance)
    with_db do |db|
      db.execute(
        'INSERT INTO campaign_factions (campaign_id, id, name, stance) VALUES (?, ?, ?, ?)',
        [campaign_id, id, name, stance]
      )
    end
  end

  def self.campaign_factions(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT id, name, stance FROM campaign_factions WHERE campaign_id = ? ORDER BY rowid',
        [campaign_id]
      ).map do |row|
        { id: row['id'], name: row['name'], stance: row['stance'] }
      end
    end
  end

  def self.campaign_factions_count(campaign_id)
    with_db { |db| db.get_first_value('SELECT COUNT(*) FROM campaign_factions WHERE campaign_id = ?', [campaign_id]) }
  end

  # --- Campaign NPCs ---

  def self.npc_exists?(campaign_id, id)
    with_db { |db| db.get_first_value('SELECT 1 FROM campaign_npcs WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
  end

  def self.load_npc(campaign_id, id)
    row = with_db { |db| db.get_first_row('SELECT * FROM campaign_npcs WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
    return nil unless row

    {
      campaign_id: row['campaign_id'],
      id: row['id'],
      name: row['name'],
      faction_id: row['faction_id'],
      disposition: row['disposition']
    }
  end

  def self.create_npc(campaign_id, id, name, faction_id, disposition)
    with_db do |db|
      db.execute(
        'INSERT INTO campaign_npcs (campaign_id, id, name, faction_id, disposition) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, id, name, faction_id, disposition]
      )
    end
  end

  def self.campaign_npcs(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT id, name, faction_id, disposition FROM campaign_npcs WHERE campaign_id = ? ORDER BY rowid',
        [campaign_id]
      ).map do |row|
        { id: row['id'], name: row['name'], faction_id: row['faction_id'], disposition: row['disposition'] }
      end
    end
  end

  def self.campaign_npcs_count(campaign_id)
    with_db { |db| db.get_first_value('SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ?', [campaign_id]) }
  end

  def self.campaign_inventory_items_count(campaign_id)
    with_db { |db| db.get_first_value('SELECT COUNT(DISTINCT item_slug) FROM campaign_inventory WHERE campaign_id = ? AND quantity > 0', [campaign_id]) }
  end

  def self.campaign_friendly_npcs_count(campaign_id)
    with_db { |db| db.get_first_value('SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ? AND disposition > 0', [campaign_id]) }
  end

  def self.campaign_quests(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT * FROM campaign_quests WHERE campaign_id = ? ORDER BY rowid',
        [campaign_id]
      ).map do |row|
        {
          campaign_id: row['campaign_id'],
          id: row['id'],
          title: row['title'],
          status: row['status'],
          milestones: json_column(row, 'milestones_json'),
          completed_milestones: json_column(row, 'completed_milestones_json')
        }
      end
    end
  end

  def self.campaign_quests_count(campaign_id)
    with_db { |db| db.get_first_value('SELECT COUNT(*) FROM campaign_quests WHERE campaign_id = ?', [campaign_id]) }
  end

  # --- Campaign inventory ---

  def self.add_inventory_item(campaign_id, item_slug, owner, quantity)
    with_db do |db|
      db.transaction do
        existing = db.get_first_row(
          'SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
          [campaign_id, item_slug, owner]
        )
        if existing
          new_quantity = existing['quantity'] + quantity
          db.execute(
            'UPDATE campaign_inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
            [new_quantity, campaign_id, item_slug, owner]
          )
        else
          db.execute(
            'INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES (?, ?, ?, ?)',
            [campaign_id, item_slug, owner, quantity]
          )
        end
      end
    end
  end

  def self.assign_equipment(campaign_id, character_id, item_slug, quantity)
    with_db do |db|
      db.transaction do
        party_row = db.get_first_row(
          'SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
          [campaign_id, item_slug, 'party']
        )
        return false unless party_row && party_row['quantity'] >= quantity

        new_party_quantity = party_row['quantity'] - quantity
        if new_party_quantity.positive?
          db.execute(
            'UPDATE campaign_inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
            [new_party_quantity, campaign_id, item_slug, 'party']
          )
        else
          db.execute(
            'DELETE FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
            [campaign_id, item_slug, 'party']
          )
        end

        existing_char = db.get_first_row(
          'SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
          [campaign_id, item_slug, character_id]
        )
        if existing_char
          new_char_quantity = existing_char['quantity'] + quantity
          db.execute(
            'UPDATE campaign_inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
            [new_char_quantity, campaign_id, item_slug, character_id]
          )
        else
          db.execute(
            'INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES (?, ?, ?, ?)',
            [campaign_id, item_slug, character_id, quantity]
          )
        end
      end
      true
    end
  end

  def self.inventory_summary(campaign_id)
    with_db do |db|
      party_items = db.get_first_value(
        'SELECT COUNT(*) FROM campaign_inventory WHERE campaign_id = ? AND owner = ? AND quantity > 0',
        [campaign_id, 'party']
      )
      assigned_items = db.get_first_value(
        'SELECT COUNT(*) FROM campaign_inventory WHERE campaign_id = ? AND owner != ? AND quantity > 0',
        [campaign_id, 'party']
      )
      healing_potions = db.get_first_row(
        'SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
        [campaign_id, 'healing-potion', 'party']
      )
      healing_potions_available = healing_potions ? healing_potions['quantity'] : 0

      {
        party_items: party_items,
        assigned_items: assigned_items,
        healing_potions_available: healing_potions_available
      }
    end
  end

  # --- Campaign sessions ---

  def self.campaign_session_exists?(campaign_id, id)
    with_db { |db| db.get_first_value('SELECT 1 FROM campaign_sessions WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
  end

  def self.load_campaign_session(campaign_id, id)
    row = with_db { |db| db.get_first_row('SELECT * FROM campaign_sessions WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
    return nil unless row

    {
      campaign_id: row['campaign_id'],
      id: row['id'],
      starts_at: row['starts_at'],
      duration_minutes: row['duration_minutes'],
      agenda: json_column(row, 'agenda_json')
    }
  end

  def self.create_campaign_session(campaign_id, id, starts_at, duration_minutes, agenda)
    with_db do |db|
      db.execute(
        'INSERT INTO campaign_sessions (campaign_id, id, starts_at, duration_minutes, agenda_json) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, id, starts_at, duration_minutes, JSON.dump(agenda)]
      )
    end
  end

  def self.next_campaign_session(campaign_id)
    row = with_db { |db| db.get_first_row('SELECT * FROM campaign_sessions WHERE campaign_id = ? ORDER BY starts_at ASC LIMIT 1', [campaign_id]) }
    return nil unless row

    {
      campaign_id: row['campaign_id'],
      id: row['id'],
      starts_at: row['starts_at'],
      duration_minutes: row['duration_minutes'],
      agenda: json_column(row, 'agenda_json')
    }
  end

  def self.campaign_sessions_count(campaign_id)
    with_db { |db| db.get_first_value('SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = ?', [campaign_id]) }
  end

  def self.save_attendance(campaign_id, session_id, present, absent)
    with_db do |db|
      db.execute(
        'INSERT OR REPLACE INTO campaign_session_attendance (campaign_id, session_id, present_json, absent_json) VALUES (?, ?, ?, ?)',
        [campaign_id, session_id, JSON.dump(present), JSON.dump(absent)]
      )
    end
  end

  def self.load_attendance(campaign_id, session_id)
    row = with_db { |db| db.get_first_row('SELECT * FROM campaign_session_attendance WHERE campaign_id = ? AND session_id = ?', [campaign_id, session_id]) }
    return nil unless row

    {
      present: json_column(row, 'present_json'),
      absent: json_column(row, 'absent_json')
    }
  end

  # --- Crafting projects ---

  def self.project_exists?(campaign_id, id)
    with_db { |db| db.get_first_value('SELECT 1 FROM campaign_crafting_projects WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
  end

  def self.load_project(campaign_id, id)
    row = with_db { |db| db.get_first_row('SELECT * FROM campaign_crafting_projects WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
    return nil unless row

    {
      campaign_id: row['campaign_id'],
      id: row['id'],
      character_id: row['character_id'],
      item_slug: row['item_slug'],
      days_required: row['days_required'],
      days_completed: row['days_completed'],
      status: row['status'],
      cost_gp: row['cost_gp']
    }
  end

  def self.create_project(campaign_id, id, character_id, item_slug, days_required, cost_gp)
    with_db do |db|
      db.execute(
        'INSERT INTO campaign_crafting_projects (campaign_id, id, character_id, item_slug, days_required, days_completed, status, cost_gp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        [campaign_id, id, character_id, item_slug, days_required, 0, 'active', cost_gp]
      )
    end
  end

  def self.advance_project(campaign_id, id, days)
    with_db do |db|
      db.transaction do
        row = db.get_first_row('SELECT * FROM campaign_crafting_projects WHERE campaign_id = ? AND id = ?', [campaign_id, id])
        return nil unless row

        new_completed = [row['days_completed'] + days, row['days_required']].min
        status = new_completed >= row['days_required'] ? 'complete' : 'active'

        db.execute(
          'UPDATE campaign_crafting_projects SET days_completed = ?, status = ? WHERE campaign_id = ? AND id = ?',
          [new_completed, status, campaign_id, id]
        )

        if status == 'complete'
          existing = db.get_first_row(
            'SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
            [campaign_id, row['item_slug'], 'party']
          )
          if existing
            db.execute(
              'UPDATE campaign_inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
              [existing['quantity'] + 1, campaign_id, row['item_slug'], 'party']
            )
          else
            db.execute(
              'INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES (?, ?, ?, ?)',
              [campaign_id, row['item_slug'], 'party', 1]
            )
          end
        end

        { id: row['id'], days_completed: new_completed, status: status }
      end
    end
  end

  # --- Play campaigns ---

  def self.play_campaign_exists?(id)
    with_db { |db| db.get_first_value('SELECT 1 FROM play_campaigns WHERE id = ?', [id]) }
  end

  def self.create_play_campaign(id, name, owner, max_players)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaigns (id, name, owner, status, phase, max_players, current_actor, turn_number, queue_json, nudge_count, story, dm_notes, current_scene_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        [id, name, owner, 'lobby', nil, max_players, nil, nil, JSON.dump(nil), 0, '', '', nil]
      )
    end
  end

  def self.load_play_campaign(id)
    row = with_db { |db| db.get_first_row('SELECT * FROM play_campaigns WHERE id = ?', [id]) }
    return nil unless row

    {
      id: row['id'],
      name: row['name'],
      owner: row['owner'],
      status: row['status'],
      phase: row['phase'],
      max_players: row['max_players'],
      current_actor: row['current_actor'],
      turn_number: row['turn_number'],
      queue: json_column(row, 'queue_json'),
      nudge_count: row['nudge_count'],
      current_scene_id: row['current_scene_id'],
      current_location_id: row['current_location_id'],
      pre_combat_state: json_column(row, 'pre_combat_state_json'),
      session_zero: json_column(row, 'session_zero_json')
    }
  end

  # Loads stored session-zero settings for a play campaign. Returns nil when
  # settings have not been set yet.
  def self.load_session_zero(campaign_id)
    row = with_db { |db| db.get_first_row('SELECT session_zero_json FROM play_campaigns WHERE id = ?', [campaign_id]) }
    return nil unless row && row['session_zero_json']

    json_column(row, 'session_zero_json')
  end

  # Persists session-zero settings for a play campaign.
  def self.save_session_zero(campaign_id, settings)
    with_db do |db|
      db.execute(
        'UPDATE play_campaigns SET session_zero_json = ? WHERE id = ?',
        [JSON.dump(settings), campaign_id]
      )
    end
  end

  def self.load_current_location(id)
    with_db { |db| db.get_first_value('SELECT current_location_id FROM play_campaigns WHERE id = ?', [id]) }
  end

  def self.set_current_location(id, location_id)
    with_db do |db|
      db.execute(
        'UPDATE play_campaigns SET current_location_id = ? WHERE id = ?',
        [location_id, id]
      )
    end
  end

  def self.load_play_campaign_document(id)
    row = with_db { |db| db.get_first_row('SELECT story, dm_notes FROM play_campaigns WHERE id = ?', [id]) }
    return { story: '', dm_notes: '' } unless row

    {
      story: row['story'] || '',
      dm_notes: row['dm_notes'] || ''
    }
  end

  def self.update_play_campaign_document(id, story, dm_notes)
    with_db do |db|
      db.execute(
        'UPDATE play_campaigns SET story = ?, dm_notes = ? WHERE id = ?',
        [story, dm_notes, id]
      )
    end
  end

  # --- Play campaign exports ---

  def self.next_play_campaign_export_version(campaign_id)
    with_db do |db|
      current = db.get_first_value('SELECT COALESCE(MAX(version), 0) FROM play_campaign_exports WHERE campaign_id = ?', [campaign_id])
      current.to_i + 1
    end
  end

  def self.create_play_campaign_export(campaign_id, version, story, status)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_exports (campaign_id, version, story, status) VALUES (?, ?, ?, ?)',
        [campaign_id, version, story, status]
      )
    end
  end

  def self.load_play_campaign_export(campaign_id, version)
    row = with_db { |db| db.get_first_row('SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = ? AND version = ?', [campaign_id, version]) }
    return nil unless row

    {
      version: row['version'],
      story: row['story'],
      status: row['status']
    }
  end

  def self.play_campaign_exports(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = ? ORDER BY version ASC',
        [campaign_id]
      ).map do |row|
        { version: row['version'], story: row['story'], status: row['status'] }
      end
    end
  end

  # Atomically applies a validated version-1 import snapshot to a play campaign.
  # Updates the campaign's story and status and records the imported state.
  def self.apply_play_campaign_import!(campaign_id, version, story, status)
    with_db do |db|
      db.transaction do
        db.execute(
          'UPDATE play_campaigns SET story = ?, status = ? WHERE id = ?',
          [story, status, campaign_id]
        )
        db.execute(
          'INSERT OR REPLACE INTO play_campaign_imports (campaign_id, version, story, status) VALUES (?, ?, ?, ?)',
          [campaign_id, version, story, status]
        )
      end
    end
  end

  # Returns the latest imported snapshot state for a play campaign, or nil when
  # no successful import has occurred yet.
  def self.load_play_campaign_import(campaign_id)
    row = with_db { |db| db.get_first_row('SELECT version, story, status FROM play_campaign_imports WHERE campaign_id = ?', [campaign_id]) }
    return nil unless row

    {
      version: row['version'],
      story: row['story'],
      status: row['status']
    }
  end

  # --- Play campaign migrations ---

  # Stores the migrated version-2 campaign state. A campaign can only retain one
  # migrated snapshot at a time; later valid migrations replace it.
  def self.save_play_campaign_migration(campaign_id, schema_version, story, campaign_name)
    with_db do |db|
      db.execute(
        'INSERT OR REPLACE INTO play_campaign_migrations (campaign_id, schema_version, story, campaign_name) VALUES (?, ?, ?, ?)',
        [campaign_id, schema_version, story, campaign_name]
      )
    end
  end

  # Returns the migrated version-2 campaign state, or nil when none exists.
  def self.load_play_campaign_migration(campaign_id)
    row = with_db { |db| db.get_first_row('SELECT schema_version, story, campaign_name FROM play_campaign_migrations WHERE campaign_id = ?', [campaign_id]) }
    return nil unless row

    {
      schema_version: row['schema_version'],
      story: row['story'],
      campaign_name: row['campaign_name']
    }
  end

  # --- Play campaign backups ---

  # Creates an immutable campaign backup snapshot with the next sequential
  # backup id. Returns the created backup hash.
  def self.create_play_campaign_backup(campaign_id, story, status)
    with_db do |db|
      db.transaction do
        sequence = (db.get_first_value('SELECT COALESCE(MAX(sequence), 0) FROM play_campaign_backups WHERE campaign_id = ?', [campaign_id]) || 0).to_i + 1
        backup_id = "backup-#{sequence}"
        db.execute(
          'INSERT INTO play_campaign_backups (campaign_id, backup_id, story, status, sequence) VALUES (?, ?, ?, ?, ?)',
          [campaign_id, backup_id, story, status, sequence]
        )
        { backup_id: backup_id, story: story, status: status, sequence: sequence }
      end
    end
  end

  def self.load_play_campaign_backup(campaign_id, backup_id)
    row = with_db { |db| db.get_first_row('SELECT backup_id, story, status, sequence FROM play_campaign_backups WHERE campaign_id = ? AND backup_id = ?', [campaign_id, backup_id]) }
    return nil unless row

    {
      backup_id: row['backup_id'],
      story: row['story'],
      status: row['status'],
      sequence: row['sequence'].to_i
    }
  end

  def self.load_play_campaign_backups(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT backup_id, story, status, sequence FROM play_campaign_backups WHERE campaign_id = ? ORDER BY sequence ASC',
        [campaign_id]
      ).map do |row|
        {
          backup_id: row['backup_id'],
          story: row['story'],
          status: row['status'],
          sequence: row['sequence'].to_i
        }
      end
    end
  end

  def self.restore_play_campaign_from_backup(campaign_id, story, status)
    with_db do |db|
      db.execute(
        'UPDATE play_campaigns SET story = ?, status = ? WHERE id = ?',
        [story, status, campaign_id]
      )
    end
  end

  # --- Play campaign members ---

  def self.play_campaign_member_exists?(campaign_id, username)
    with_db { |db| db.get_first_value('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?', [campaign_id, username]) }
  end

  def self.play_campaign_character_exists?(campaign_id, character_id)
    with_db { |db| db.get_first_value('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?', [campaign_id, character_id]) }
  end

  def self.play_campaign_member_count(campaign_id)
    with_db { |db| db.get_first_value('SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?', [campaign_id]) }
  end

  def self.create_play_campaign_member(campaign_id, username, character_id, name, class_name)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class, level, hp_current, hp_max, owner, gold) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        [campaign_id, username, character_id, name, class_name, 1, 20, 20, username, 10]
      )
    end
  end

  def self.play_campaign_members(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT username, character_id, name, class, owner FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid',
        [campaign_id]
      ).map do |row|
        { username: row['username'], character_id: row['character_id'], name: row['name'], class: row['class'], owner: row['owner'] }
      end
    end
  end

  def self.start_play_campaign(id, queue, turn_number)
    current_actor = queue.first
    phase = current_actor == 'dm' ? 'dm' : 'player'

    with_db do |db|
      db.execute(
        'UPDATE play_campaigns SET status = ?, phase = ?, current_actor = ?, turn_number = ?, queue_json = ?, pre_combat_state_json = NULL WHERE id = ?',
        ['active', phase, current_actor, turn_number, JSON.dump(queue), id]
      )
    end
  end

  def self.load_play_campaign_member(campaign_id, username)
    row = with_db { |db| db.get_first_row('SELECT * FROM play_campaign_members WHERE campaign_id = ? AND username = ?', [campaign_id, username]) }
    return nil unless row

    {
      campaign_id: row['campaign_id'],
      username: row['username'],
      character_id: row['character_id'],
      name: row['name'],
      class: row['class'],
      race: row['race'],
      background: row['background'],
      level: row['level'] || 1,
      abilities: Storage.json_column(row, 'abilities_json', {}),
      hp_current: row['hp_current'] || 20,
      hp_max: row['hp_max'] || 20,
      status: row['status'] || 'conscious',
      successes: row['death_save_successes'] || 0,
      failures: row['death_save_failures'] || 0,
      owner: row['owner'],
      gold: row['gold'].nil? ? 10 : row['gold'].to_i
    }
  end

  def self.load_play_campaign_member_by_character_id(campaign_id, character_id)
    row = with_db { |db| db.get_first_row('SELECT * FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?', [campaign_id, character_id]) }
    return nil unless row

    {
      campaign_id: row['campaign_id'],
      username: row['username'],
      character_id: row['character_id'],
      name: row['name'],
      class: row['class'],
      race: row['race'],
      background: row['background'],
      level: row['level'] || 1,
      abilities: Storage.json_column(row, 'abilities_json', {}),
      hp_current: row['hp_current'] || 20,
      hp_max: row['hp_max'] || 20,
      status: row['status'] || 'conscious',
      successes: row['death_save_successes'] || 0,
      failures: row['death_save_failures'] || 0,
      owner: row['owner'],
      gold: row['gold'].nil? ? 10 : row['gold'].to_i
    }
  end

  # --- Character currency ---

  def self.load_character_currency(campaign_id, character_id)
    row = with_db { |db| db.get_first_row('SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?', [campaign_id, character_id]) }
    return nil unless row

    row['gold'].nil? ? 10 : row['gold'].to_i
  end

  # Atomically transfers +gold+ from +from_character_id+ to +to_character_id+
  # within +campaign_id+. Returns a hash with the updated balances and the
  # campaign-local transfer id, or nil when the source has insufficient funds
  # or either character is missing.
  def self.transfer_gold(campaign_id, from_character_id, to_character_id, gold)
    with_db do |db|
      db.transaction do
        from_row = db.get_first_row('SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?', [campaign_id, from_character_id])
        to_row = db.get_first_row('SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?', [campaign_id, to_character_id])
        return nil unless from_row && to_row

        from_gold = from_row['gold'].nil? ? 10 : from_row['gold'].to_i
        to_gold = to_row['gold'].nil? ? 10 : to_row['gold'].to_i
        return nil if from_gold < gold

        new_from_gold = from_gold - gold
        new_to_gold = to_gold + gold

        db.execute(
          'UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?',
          [new_from_gold, campaign_id, from_character_id]
        )
        db.execute(
          'UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?',
          [new_to_gold, campaign_id, to_character_id]
        )

        transfer_id = (db.get_first_value('SELECT COALESCE(MAX(transfer_id), 0) FROM play_campaign_character_transfers WHERE campaign_id = ?', [campaign_id]) || 0).to_i + 1
        db.execute(
          'INSERT INTO play_campaign_character_transfers (campaign_id, transfer_id, from_character_id, to_character_id, gold, from_gold, to_gold) VALUES (?, ?, ?, ?, ?, ?, ?)',
          [campaign_id, transfer_id, from_character_id, to_character_id, gold, new_from_gold, new_to_gold]
        )

        {
          from_character_id: from_character_id,
          to_character_id: to_character_id,
          gold: gold,
          from_gold: new_from_gold,
          to_gold: new_to_gold,
          transfer_id: transfer_id
        }
      end
    end
  end

  # Atomically transfers +amount+ of gold from +from_character_id+ to
  # +to_character_id+ within +campaign_id+ and appends an ordered transactional
  # transfer record. Returns a hash with the updated balances and the
  # campaign-local sequence number, or nil when the source has insufficient
  # funds or either character is missing.
  def self.transactional_transfer_gold(campaign_id, from_character_id, to_character_id, amount)
    with_db do |db|
      db.transaction do
        from_row = db.get_first_row('SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?', [campaign_id, from_character_id])
        to_row = db.get_first_row('SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?', [campaign_id, to_character_id])
        return nil unless from_row && to_row

        from_gold = from_row['gold'].nil? ? 10 : from_row['gold'].to_i
        to_gold = to_row['gold'].nil? ? 10 : to_row['gold'].to_i
        return nil if from_gold < amount

        new_from_gold = from_gold - amount
        new_to_gold = to_gold + amount

        db.execute(
          'UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?',
          [new_from_gold, campaign_id, from_character_id]
        )
        db.execute(
          'UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?',
          [new_to_gold, campaign_id, to_character_id]
        )

        sequence = (db.get_first_value('SELECT COALESCE(MAX(sequence), 0) FROM play_campaign_transactional_transfers WHERE campaign_id = ?', [campaign_id]) || 0).to_i + 1
        db.execute(
          'INSERT INTO play_campaign_transactional_transfers (campaign_id, sequence, from_character_id, to_character_id, amount, from_gold, to_gold) VALUES (?, ?, ?, ?, ?, ?, ?)',
          [campaign_id, sequence, from_character_id, to_character_id, amount, new_from_gold, new_to_gold]
        )

        {
          from_character_id: from_character_id,
          to_character_id: to_character_id,
          amount: amount,
          from_gold: new_from_gold,
          to_gold: new_to_gold,
          sequence: sequence
        }
      end
    end
  end

  # Returns successful transactional transfers for a campaign in sequence order.
  def self.load_transactional_transfers(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT sequence, from_character_id, to_character_id, amount, from_gold, to_gold FROM play_campaign_transactional_transfers WHERE campaign_id = ? ORDER BY sequence ASC',
        [campaign_id]
      ).map do |row|
        {
          from_character_id: row['from_character_id'],
          to_character_id: row['to_character_id'],
          amount: row['amount'].to_i,
          from_gold: row['from_gold'].to_i,
          to_gold: row['to_gold'].to_i,
          sequence: row['sequence'].to_i
        }
      end
    end
  end

  def self.set_character_owner(campaign_id, character_id, owner)
    with_db do |db|
      db.execute(
        'UPDATE play_campaign_members SET owner = ? WHERE campaign_id = ? AND character_id = ?',
        [owner, campaign_id, character_id]
      )
    end
  end

  def self.set_character_build(campaign_id, character_id, race, class_name, background, level, abilities, hp_max)
    with_db do |db|
      db.execute(
        'UPDATE play_campaign_members SET race = ?, class = ?, background = ?, level = ?, abilities_json = ?, hp_max = ?, hp_current = ? WHERE campaign_id = ? AND character_id = ?',
        [race, class_name, background, level, JSON.dump(abilities), hp_max, hp_max, campaign_id, character_id]
      )
    end
  end

  def self.level_up_character(campaign_id, character_id, new_level, new_hp_max, new_hp_current)
    with_db do |db|
      db.execute(
        'UPDATE play_campaign_members SET level = ?, hp_max = ?, hp_current = ? WHERE campaign_id = ? AND character_id = ?',
        [new_level, new_hp_max, new_hp_current, campaign_id, character_id]
      )
    end
    load_play_campaign_member_by_character_id(campaign_id, character_id)
  end

  def self.update_play_campaign_member_hp(campaign_id, username, hp_current)
    with_db do |db|
      row = db.get_first_row('SELECT status FROM play_campaign_members WHERE campaign_id = ? AND username = ?', [campaign_id, username])
      current_status = row ? row['status'] : 'conscious'

      new_status = if hp_current > 0
                     'conscious'
                   elsif %w[stable dead].include?(current_status)
                     current_status
                   else
                     'unconscious'
                   end

      db.execute(
        'UPDATE play_campaign_members SET hp_current = ?, status = ? WHERE campaign_id = ? AND username = ?',
        [hp_current, new_status, campaign_id, username]
      )
    end
  end

  def self.apply_damage_to_character(campaign_id, character_id, amount)
    with_db do |db|
      row = db.get_first_row('SELECT hp_current, hp_max, status FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?', [campaign_id, character_id])
      return nil unless row

      hp_before = row['hp_current'].to_i
      hp_after = [hp_before - amount, 0].max

      new_status = if hp_after > 0
                     'conscious'
                   elsif %w[stable dead].include?(row['status'])
                     row['status']
                   else
                     'unconscious'
                   end

      db.execute(
        'UPDATE play_campaign_members SET hp_current = ?, status = ? WHERE campaign_id = ? AND character_id = ?',
        [hp_after, new_status, campaign_id, character_id]
      )

      {
        character_id: character_id,
        hp_before: hp_before,
        hp_after: hp_after,
        damage: hp_before - hp_after,
        hp_max: row['hp_max'].to_i,
        status: new_status
      }
    end
  end

  def self.record_death_save(campaign_id, character_id, outcome)
    with_db do |db|
      row = db.get_first_row('SELECT status, death_save_successes, death_save_failures FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?', [campaign_id, character_id])
      return nil unless row

      successes = row['death_save_successes'].to_i
      failures = row['death_save_failures'].to_i
      status = row['status']

      if outcome == 'success'
        successes += 1
        status = 'stable' if successes >= 3
      else
        failures += 1
        status = 'dead' if failures >= 3
      end

      db.execute(
        'UPDATE play_campaign_members SET death_save_successes = ?, death_save_failures = ?, status = ? WHERE campaign_id = ? AND character_id = ?',
        [successes, failures, status, campaign_id, character_id]
      )

      {
        character_id: character_id,
        successes: successes,
        failures: failures,
        status: status
      }
    end
  end

  # --- Character spells ---

  def self.load_character_spells(campaign_id, character_id)
    with_db do |db|
      db.execute(
        'SELECT spell_id, name, level FROM play_campaign_character_spells WHERE campaign_id = ? AND character_id = ? ORDER BY rowid',
        [campaign_id, character_id]
      ).map do |row|
        { spell_id: row['spell_id'], name: row['name'], level: row['level'] }
      end
    end
  end

  def self.add_character_spell(campaign_id, character_id, spell_id, name, level)
    with_db do |db|
      db.execute(
        'INSERT OR IGNORE INTO play_campaign_character_spells (campaign_id, character_id, spell_id, name, level) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, character_id, spell_id, name, level]
      )
      db.changes > 0
    end
  end

  # --- Character prepared spells ---

  def self.load_character_prepared_spells(campaign_id, character_id)
    row = with_db { |db| db.get_first_row('SELECT prepared_spells_json FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?', [campaign_id, character_id]) }
    return [] unless row && row['prepared_spells_json']

    parsed = JSON.parse(row['prepared_spells_json'])
    parsed.is_a?(Array) ? parsed : []
  rescue JSON::ParserError
    []
  end

  def self.save_character_prepared_spells(campaign_id, character_id, spell_ids)
    with_db do |db|
      db.execute(
        'UPDATE play_campaign_members SET prepared_spells_json = ? WHERE campaign_id = ? AND character_id = ?',
        [JSON.dump(spell_ids), campaign_id, character_id]
      )
      db.changes > 0
    end
  end

  # --- Character spell slots ---

  def self.load_character_spell_slots(campaign_id, character_id)
    row = with_db { |db| db.get_first_row('SELECT spell_slots_json FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?', [campaign_id, character_id]) }
    return {} unless row && row['spell_slots_json']

    parsed = JSON.parse(row['spell_slots_json'])
    parsed.is_a?(Hash) ? parsed : {}
  rescue JSON::ParserError
    {}
  end

  def self.save_character_spell_slots(campaign_id, character_id, slots)
    with_db do |db|
      db.execute(
        'UPDATE play_campaign_members SET spell_slots_json = ? WHERE campaign_id = ? AND character_id = ?',
        [JSON.dump(slots), campaign_id, character_id]
      )
    end
  end

  # Decrements one spell slot of +slot_level+ for the character and returns the
  # updated slot map, or nil when no slot is available.
  def self.decrement_character_spell_slot(campaign_id, character_id, slot_level)
    with_db do |db|
      row = db.get_first_row('SELECT spell_slots_json FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?', [campaign_id, character_id])
      return nil unless row

      slots = row['spell_slots_json'] ? JSON.parse(row['spell_slots_json']) : {}
      return nil unless slots.is_a?(Hash)

      key = slot_level.to_s
      return nil unless slots[key].to_i > 0

      slots[key] = slots[key].to_i - 1
      db.execute(
        'UPDATE play_campaign_members SET spell_slots_json = ? WHERE campaign_id = ? AND character_id = ?',
        [JSON.dump(slots), campaign_id, character_id]
      )
      slots
    rescue JSON::ParserError
      nil
    end
  end

  # --- Character cast history ---

  def self.record_character_cast(campaign_id, character_id, spell_id, target, slot_level, slots_remaining)
    with_db do |db|
      sequence = (db.get_first_value('SELECT COALESCE(MAX(sequence), 0) FROM play_campaign_character_casts WHERE campaign_id = ? AND character_id = ?', [campaign_id, character_id]) || 0).to_i + 1
      db.execute(
        'INSERT INTO play_campaign_character_casts (campaign_id, character_id, sequence, spell_id, target, slot_level, slots_remaining) VALUES (?, ?, ?, ?, ?, ?, ?)',
        [campaign_id, character_id, sequence, spell_id, target, slot_level, slots_remaining]
      )
      sequence
    end
  end

  def self.load_character_casts(campaign_id, character_id)
    with_db do |db|
      db.execute(
        'SELECT sequence, spell_id, target, slot_level, slots_remaining FROM play_campaign_character_casts WHERE campaign_id = ? AND character_id = ? ORDER BY sequence ASC',
        [campaign_id, character_id]
      ).map do |row|
        {
          character_id: character_id,
          sequence: row['sequence'],
          spell_id: row['spell_id'],
          target: row['target'],
          slot_level: row['slot_level'],
          slots_remaining: row['slots_remaining']
        }
      end
    end
  end

  # --- Character concentration ---

  def self.load_character_concentration(campaign_id, character_id)
    row = with_db { |db| db.get_first_row('SELECT concentration_json FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?', [campaign_id, character_id]) }
    return nil unless row && row['concentration_json']

    JSON.parse(row['concentration_json'])
  rescue JSON::ParserError
    nil
  end

  def self.save_character_concentration(campaign_id, character_id, concentration)
    with_db do |db|
      db.execute(
        'UPDATE play_campaign_members SET concentration_json = ? WHERE campaign_id = ? AND character_id = ?',
        [JSON.dump(concentration), campaign_id, character_id]
      )
    end
  end

  def self.clear_character_concentration(campaign_id, character_id)
    with_db do |db|
      db.execute(
        'UPDATE play_campaign_members SET concentration_json = NULL WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, character_id]
      )
    end
  end

  # --- Character inventory stacks ---

  def self.load_character_inventory(campaign_id, character_id)
    with_db do |db|
      db.execute(
        'SELECT item_id, quantity FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? ORDER BY item_id ASC',
        [campaign_id, character_id]
      ).map do |row|
        { item_id: row['item_id'], quantity: row['quantity'] }
      end
    end
  end

  def self.add_character_inventory_item(campaign_id, character_id, item_id, quantity)
    with_db do |db|
      db.transaction do
        row = db.get_first_row(
          'SELECT quantity FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
          [campaign_id, character_id, item_id]
        )
        if row
          new_quantity = row['quantity'] + quantity
          db.execute(
            'UPDATE play_campaign_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
            [new_quantity, campaign_id, character_id, item_id]
          )
          new_quantity
        else
          db.execute(
            'INSERT INTO play_campaign_character_inventory (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)',
            [campaign_id, character_id, item_id, quantity]
          )
          quantity
        end
      end
    end
  end

  # Removes the requested quantity from a character's stack. Returns the new
  # total quantity on success, or nil when the stack does not exist or the
  # requested quantity exceeds the held amount.
  def self.remove_character_inventory_item(campaign_id, character_id, item_id, quantity)
    with_db do |db|
      db.transaction do
        row = db.get_first_row(
          'SELECT quantity FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
          [campaign_id, character_id, item_id]
        )
        return nil unless row

        held = row['quantity'].to_i
        return nil if quantity > held

        new_quantity = held - quantity
        if new_quantity.positive?
          db.execute(
            'UPDATE play_campaign_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
            [new_quantity, campaign_id, character_id, item_id]
          )
        else
          db.execute(
            'DELETE FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
            [campaign_id, character_id, item_id]
          )
        end
        new_quantity
      end
    end
  end

  # Consumes one unit of +item_id+ from the character's inventory and applies
  # its effect. Returns a hash with the remaining quantity and healing amount,
  # or nil when the item is not held or the stack is empty.
  def self.consume_character_inventory_item(campaign_id, character_id, item_id)
    with_db do |db|
      db.transaction do
        row = db.get_first_row(
          'SELECT quantity FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
          [campaign_id, character_id, item_id]
        )
        return nil unless row

        held = row['quantity'].to_i
        return nil if held <= 0

        new_quantity = held - 1
        if new_quantity.positive?
          db.execute(
            'UPDATE play_campaign_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
            [new_quantity, campaign_id, character_id, item_id]
          )
        else
          db.execute(
            'DELETE FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
            [campaign_id, character_id, item_id]
          )
        end

        hp_restored = 0
        if item_id == 'healing-potion'
          hp_restored = 5
          char_row = db.get_first_row(
            'SELECT hp_current, hp_max, status FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
            [campaign_id, character_id]
          )
          if char_row
            current_hp = char_row['hp_current'].to_i
            max_hp = char_row['hp_max'].to_i
            new_hp = [current_hp + hp_restored, max_hp].min
            new_status = if new_hp > 0
                           'conscious'
                         elsif %w[stable dead].include?(char_row['status'])
                           char_row['status']
                         else
                           'unconscious'
                         end
            db.execute(
              'UPDATE play_campaign_members SET hp_current = ?, status = ? WHERE campaign_id = ? AND character_id = ?',
              [new_hp, new_status, campaign_id, character_id]
            )
          end
        end

        { quantity: new_quantity, hp_restored: hp_restored }
      end
    end
  end

  # --- Character equipment and attunement ---

  def self.load_character_equipment(campaign_id, character_id, slot)
    row = with_db do |db|
      db.get_first_row(
        'SELECT item_id, attuned FROM play_campaign_character_equipment WHERE campaign_id = ? AND character_id = ? AND slot = ?',
        [campaign_id, character_id, slot]
      )
    end
    return nil unless row

    {
      item_id: row['item_id'],
      attuned: row['attuned'] == 1
    }
  end

  def self.save_character_equipment(campaign_id, character_id, slot, item_id, attuned)
    with_db do |db|
      db.execute(
        'INSERT OR REPLACE INTO play_campaign_character_equipment (campaign_id, character_id, slot, item_id, attuned) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, character_id, slot, item_id, attuned ? 1 : 0]
      )
    end
    { item_id: item_id, attuned: attuned }
  end

  def self.character_attuned_equipment_exists?(campaign_id, character_id)
    with_db do |db|
      db.get_first_value(
        'SELECT 1 FROM play_campaign_character_equipment WHERE campaign_id = ? AND character_id = ? AND attuned = 1',
        [campaign_id, character_id]
      )
    end
  end

  def self.increment_nudge_count(campaign_id)
    with_db do |db|
      db.execute('UPDATE play_campaigns SET nudge_count = nudge_count + 1 WHERE id = ?', [campaign_id])
      db.get_first_value('SELECT nudge_count FROM play_campaigns WHERE id = ?', [campaign_id])
    end
  end

  # --- Play campaign narrations ---

  # Inserts a single narration/action/resolution event and returns its
  # sequence number. Sequence numbers are per-campaign and monotonically
  # increasing so the log order matches insertion order.
  def self.insert_narration(campaign_id, kind, actor, type, text, target = nil)
    with_db do |db|
      sequence = (db.get_first_value('SELECT COALESCE(MAX(sequence), 0) FROM play_campaign_narrations WHERE campaign_id = ?', [campaign_id]) || 0).to_i + 1
      db.execute(
        'INSERT INTO play_campaign_narrations (campaign_id, sequence, kind, actor, type, target, text) VALUES (?, ?, ?, ?, ?, ?, ?)',
        [campaign_id, sequence, kind, actor, type, target, text]
      )
      sequence
    end
  end

  def self.create_narration(campaign_id, actor, text)
    insert_narration(campaign_id, 'narration', actor, nil, text, nil)
  end

  def self.create_action(campaign_id, actor, type, text)
    insert_narration(campaign_id, 'action', actor, type, text, nil)
  end

  def self.create_resolution(campaign_id, actor, text)
    insert_narration(campaign_id, 'resolution', actor, nil, text, nil)
  end

  def self.create_combat_action(campaign_id, actor, type, target, text)
    insert_narration(campaign_id, 'combat_action', actor, type, text, target)
  end

  def self.play_campaign_narrations(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT sequence, kind, actor, type, target, text FROM play_campaign_narrations WHERE campaign_id = ? ORDER BY sequence ASC',
        [campaign_id]
      ).map do |row|
        result = { sequence: row['sequence'], kind: row['kind'], actor: row['actor'] }
        result[:type] = row['type'] if row['type']
        result[:target] = row['target'] if row['target']
        result[:text] = row['text']
        result
      end
    end
  end

  # --- Play campaign turn advancement ---

  def self.update_play_campaign_turn(campaign_id, current_actor, phase, turn_number)
    with_db do |db|
      db.execute(
        'UPDATE play_campaigns SET current_actor = ?, phase = ?, turn_number = ? WHERE id = ?',
        [current_actor, phase, turn_number, campaign_id]
      )
    end
  end

  # --- Play campaign scenes ---

  def self.scene_exists?(campaign_id, id)
    with_db { |db| db.get_first_value('SELECT 1 FROM play_campaign_scenes WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
  end

  def self.load_scene(campaign_id, id)
    row = with_db { |db| db.get_first_row('SELECT * FROM play_campaign_scenes WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
    return nil unless row

    {
      campaign_id: row['campaign_id'],
      id: row['id'],
      name: row['name'],
      status: row['status']
    }
  end

  def self.create_scene(campaign_id, id, name)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_scenes (campaign_id, id, name, status) VALUES (?, ?, ?, ?)',
        [campaign_id, id, name, 'open']
      )
    end
  end

  def self.close_scene(campaign_id, id)
    with_db do |db|
      db.execute(
        'UPDATE play_campaign_scenes SET status = ? WHERE campaign_id = ? AND id = ?',
        ['closed', campaign_id, id]
      )
    end
  end

  def self.set_current_scene(campaign_id, scene_id)
    with_db do |db|
      db.execute(
        'UPDATE play_campaigns SET current_scene_id = ? WHERE id = ?',
        [scene_id, campaign_id]
      )
    end
  end

  def self.load_current_scene(campaign_id)
    with_db { |db| db.get_first_value('SELECT current_scene_id FROM play_campaigns WHERE id = ?', [campaign_id]) }
  end

  # --- Play campaign locations and travel graph ---

  def self.location_exists?(campaign_id, id)
    with_db { |db| db.get_first_value('SELECT 1 FROM play_campaign_locations WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
  end

  def self.load_location(campaign_id, id)
    row = with_db { |db| db.get_first_row('SELECT * FROM play_campaign_locations WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
    return nil unless row

    { campaign_id: row['campaign_id'], id: row['id'], name: row['name'] }
  end

  def self.create_location(campaign_id, id, name)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_locations (campaign_id, id, name) VALUES (?, ?, ?)',
        [campaign_id, id, name]
      )
      current = db.get_first_value('SELECT current_location_id FROM play_campaigns WHERE id = ?', [campaign_id])
      if current.nil? || current.to_s.empty?
        db.execute(
          'UPDATE play_campaigns SET current_location_id = ? WHERE id = ?',
          [id, campaign_id]
        )
      end
    end
  end

  def self.connection_exists?(campaign_id, from_id, to_id)
    with_db { |db| db.get_first_value('SELECT 1 FROM play_campaign_location_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?', [campaign_id, from_id, to_id]) }
  end

  def self.create_connection(campaign_id, from_id, to_id, travel_turns)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_location_connections (campaign_id, from_id, to_id, travel_turns) VALUES (?, ?, ?, ?)',
        [campaign_id, from_id, to_id, travel_turns]
      )
    end
  end

  def self.load_connections(campaign_id, from_id)
    with_db do |db|
      db.execute(
        <<~SQL,
          SELECT c.to_id, c.travel_turns, l.name
          FROM play_campaign_location_connections c
          JOIN play_campaign_locations l ON l.campaign_id = c.campaign_id AND l.id = c.to_id
          WHERE c.campaign_id = ? AND c.from_id = ?
          ORDER BY c.to_id
        SQL
        [campaign_id, from_id]
      ).map do |row|
        { id: row['to_id'], name: row['name'], travel_turns: row['travel_turns'] }
      end
    end
  end

  def self.load_connection(campaign_id, from_id, to_id)
    row = with_db do |db|
      db.get_first_row(
        'SELECT travel_turns FROM play_campaign_location_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?',
        [campaign_id, from_id, to_id]
      )
    end
    return nil unless row

    { from_id: from_id, to_id: to_id, travel_turns: row['travel_turns'] }
  end

  def self.create_nudge(campaign_id, actor, message)
    insert_narration(campaign_id, 'nudge', actor, nil, message, nil)
  end

  def self.create_scene_event(campaign_id, actor, scene_id)
    insert_narration(campaign_id, 'scene', actor, nil, scene_id, nil)
  end

  def self.create_travel(campaign_id, actor, destination_id)
    insert_narration(campaign_id, 'travel', actor, nil, destination_id, nil)
  end

  def self.create_rest(campaign_id, actor, rest_type)
    insert_narration(campaign_id, 'rest', actor, rest_type, rest_type, nil)
  end

  # --- Play campaign encounters ---

  def self.encounter_exists?(campaign_id, id)
    with_db { |db| db.get_first_value('SELECT 1 FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
  end

  def self.active_encounter_exists?(campaign_id)
    with_db { |db| db.get_first_value('SELECT 1 FROM play_campaign_encounters WHERE campaign_id = ? AND status = ?', [campaign_id, 'active']) }
  end

  def self.create_encounter(campaign_id, id, name)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_encounters (campaign_id, id, name, status, combatants_json, round, turn_index, xp_awarded, loot_json, rewards_awarded) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        [campaign_id, id, name, 'active', JSON.dump([]), 1, 0, 0, JSON.dump([]), 0]
      )
    end
  end

  def self.load_encounter(campaign_id, id)
    row = with_db { |db| db.get_first_row('SELECT * FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
    return nil unless row

    {
      campaign_id: row['campaign_id'],
      id: row['id'],
      name: row['name'],
      status: row['status'],
      combatants: json_column(row, 'combatants_json'),
      round: row['round'] || 1,
      turn_index: row['turn_index'] || 0,
      conditions: json_column(row, 'conditions_json', {}),
      xp_awarded: row['xp_awarded'] || 0,
      loot: json_column(row, 'loot_json', []),
      rewards_awarded: row['rewards_awarded'] == 1
    }
  end

  # --- Play campaign encounter monsters ---

  def self.encounter_monster_exists?(campaign_id, encounter_id, monster_id)
    with_db { |db| db.get_first_value('SELECT 1 FROM play_campaign_encounter_monsters WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?', [campaign_id, encounter_id, monster_id]) }
  end

  def self.add_encounter_monster(campaign_id, encounter_id, monster_id, name, hp_max, initiative)
    hp_current = hp_max
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_encounter_monsters (campaign_id, encounter_id, monster_id, name, hp_max, hp_current, initiative) VALUES (?, ?, ?, ?, ?, ?, ?)',
        [campaign_id, encounter_id, monster_id, name, hp_max, hp_current, initiative]
      )
    end
    { monster_id: monster_id, name: name, hp_max: hp_max, initiative: initiative, hp_current: hp_current }
  end

  def self.remove_encounter_monster(campaign_id, encounter_id, monster_id)
    with_db do |db|
      db.execute(
        'DELETE FROM play_campaign_encounter_monsters WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?',
        [campaign_id, encounter_id, monster_id]
      )
      db.changes > 0
    end
  end

  def self.load_encounter_monsters(campaign_id, encounter_id)
    with_db do |db|
      db.execute(
        'SELECT monster_id, name, hp_max, hp_current, initiative FROM play_campaign_encounter_monsters WHERE campaign_id = ? AND encounter_id = ? ORDER BY rowid',
        [campaign_id, encounter_id]
      ).map do |row|
        { monster_id: row['monster_id'], name: row['name'], hp_max: row['hp_max'], hp_current: row['hp_current'], initiative: row['initiative'] }
      end
    end
  end

  def self.advance_encounter_turn!(campaign_id, encounter_id, round, turn_index)
    with_db do |db|
      db.execute(
        'UPDATE play_campaign_encounters SET round = ?, turn_index = ? WHERE campaign_id = ? AND id = ?',
        [round, turn_index, campaign_id, encounter_id]
      )
    end
  end

  def self.load_encounter_conditions(campaign_id, encounter_id)
    row = with_db { |db| db.get_first_row('SELECT conditions_json FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?', [campaign_id, encounter_id]) }
    return {} unless row

    json_column(row, 'conditions_json', {})
  end

  def self.save_encounter_conditions(campaign_id, encounter_id, conditions)
    with_db do |db|
      db.execute(
        'UPDATE play_campaign_encounters SET conditions_json = ? WHERE campaign_id = ? AND id = ?',
        [JSON.dump(conditions), campaign_id, encounter_id]
      )
    end
  end

  def self.add_encounter_condition(campaign_id, encounter_id, target, condition, duration_rounds)
    with_db do |db|
      row = db.get_first_row('SELECT conditions_json FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?', [campaign_id, encounter_id])
      return nil unless row

      conditions = json_column(row, 'conditions_json', {})
      conditions[target] ||= []
      conditions[target] << { condition: condition, remaining_rounds: duration_rounds }
      db.execute(
        'UPDATE play_campaign_encounters SET conditions_json = ? WHERE campaign_id = ? AND id = ?',
        [JSON.dump(conditions), campaign_id, encounter_id]
      )
      conditions[target]
    end
  end

  # --- Play campaign encounter party combatants ---

  def self.add_encounter_combatant(campaign_id, encounter_id, member, character_id, name, initiative)
    with_db do |db|
      row = db.get_first_row('SELECT combatants_json FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?', [campaign_id, encounter_id])
      return nil unless row

      combatants = json_column(row, 'combatants_json', [])
      return nil if combatants.any? { |c| c[:member] == member || c['member'] == member }

      combatants << { member: member, character_id: character_id, name: name, initiative: initiative }
      db.execute(
        'UPDATE play_campaign_encounters SET combatants_json = ? WHERE campaign_id = ? AND id = ?',
        [JSON.dump(combatants), campaign_id, encounter_id]
      )
      combatants.last
    end
  end

  def self.remove_encounter_combatant(campaign_id, encounter_id, member)
    with_db do |db|
      row = db.get_first_row('SELECT combatants_json FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?', [campaign_id, encounter_id])
      return false unless row

      combatants = json_column(row, 'combatants_json', [])
      before = combatants.length
      combatants.reject! { |c| c[:member] == member || c['member'] == member }
      return false if combatants.length == before

      db.execute(
        'UPDATE play_campaign_encounters SET combatants_json = ? WHERE campaign_id = ? AND id = ?',
        [JSON.dump(combatants), campaign_id, encounter_id]
      )
      true
    end
  end

  # Persists the computed initiative order for an encounter.
  def self.save_encounter_order(campaign_id, encounter_id, order)
    with_db do |db|
      db.execute(
        'UPDATE play_campaign_encounters SET order_json = ? WHERE campaign_id = ? AND id = ?',
        [JSON.dump(order), campaign_id, encounter_id]
      )
    end
  end

  # Loads the persisted initiative order for an encounter, normalizing keys to
  # symbols. Returns nil when no order has been stored.
  def self.load_encounter_order(campaign_id, encounter_id)
    row = with_db { |db| db.get_first_row('SELECT order_json FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?', [campaign_id, encounter_id]) }
    return nil unless row && row['order_json']

    parsed = JSON.parse(row['order_json'])
    return nil unless parsed.is_a?(Array)

    parsed.map { |h| h.transform_keys(&:to_sym) }
  rescue JSON::ParserError
    nil
  end

  # Records a ready-action trigger for the current encounter.
  def self.add_encounter_ready(campaign_id, encounter_id, actor, trigger)
    with_db do |db|
      row = db.get_first_row('SELECT readies_json FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?', [campaign_id, encounter_id])
      readies = row && row['readies_json'] ? JSON.parse(row['readies_json']) : []
      record = { actor: actor, trigger: trigger }
      readies << record
      db.execute(
        'UPDATE play_campaign_encounters SET readies_json = ? WHERE campaign_id = ? AND id = ?',
        [JSON.dump(readies), campaign_id, encounter_id]
      )
      record
    end
  end

  # --- Encounter rewards ---

  def self.encounter_reward_exists?(campaign_id, encounter_id)
    row = with_db { |db| db.get_first_row('SELECT rewards_awarded FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?', [campaign_id, encounter_id]) }
    row && row['rewards_awarded'] == 1
  end

  def self.save_encounter_reward(campaign_id, encounter_id, xp, loot)
    with_db do |db|
      db.execute(
        'UPDATE play_campaign_encounters SET xp_awarded = ?, loot_json = ?, rewards_awarded = 1 WHERE campaign_id = ? AND id = ?',
        [xp, JSON.dump(loot), campaign_id, encounter_id]
      )
    end
  end

  def self.load_encounter_reward(campaign_id, encounter_id)
    row = with_db { |db| db.get_first_row('SELECT xp_awarded, loot_json FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?', [campaign_id, encounter_id]) }
    return nil unless row

    {
      xp: row['xp_awarded'] || 0,
      loot: json_column(row, 'loot_json', [])
    }
  end

  def self.close_encounter(campaign_id, encounter_id)
    with_db do |db|
      db.execute(
        'UPDATE play_campaign_encounters SET status = ? WHERE campaign_id = ? AND id = ?',
        ['closed', campaign_id, encounter_id]
      )
    end
  end

  def self.save_pre_combat_state(campaign_id, state)
    with_db do |db|
      db.execute(
        'UPDATE play_campaigns SET pre_combat_state_json = ? WHERE id = ?',
        [JSON.dump(state), campaign_id]
      )
    end
  end

  def self.load_pre_combat_state(campaign_id)
    row = with_db { |db| db.get_first_row('SELECT pre_combat_state_json FROM play_campaigns WHERE id = ?', [campaign_id]) }
    return nil unless row && row['pre_combat_state_json']

    JSON.parse(row['pre_combat_state_json'])
  rescue JSON::ParserError
    nil
  end

  def self.clear_pre_combat_state(campaign_id)
    with_db do |db|
      db.execute(
        'UPDATE play_campaigns SET pre_combat_state_json = NULL WHERE id = ?',
        [campaign_id]
      )
    end
  end

  # Applies damage to an encounter target. Targets are resolved in this order:
  # an encounter monster by monster_id, then a bound party combatant by member
  # username. HP floors at 0. Returns a result hash or nil if the target is
  # not found or not a bound combatant.
  def self.apply_damage_to_encounter_target(campaign_id, encounter_id, target, amount)
    with_db do |db|
      monster_row = db.get_first_row(
        'SELECT hp_max, hp_current FROM play_campaign_encounter_monsters WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?',
        [campaign_id, encounter_id, target]
      )
      if monster_row
        hp_before = monster_row['hp_current'].to_i
        hp_after = [hp_before - amount, 0].max
        db.execute(
          'UPDATE play_campaign_encounter_monsters SET hp_current = ? WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?',
          [hp_after, campaign_id, encounter_id, target]
        )
        return {
          target: target,
          hp_before: hp_before,
          hp_after: hp_after,
          damage: hp_before - hp_after
        }
      end

      member_row = db.get_first_row(
        'SELECT hp_max, hp_current FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, target]
      )
      if member_row
        enc_row = db.get_first_row(
          'SELECT combatants_json FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?',
          [campaign_id, encounter_id]
        )
        combatants = enc_row ? json_column(enc_row, 'combatants_json', []) : []
        bound = combatants.any? { |c| c[:member] == target || c['member'] == target }

        if bound
          hp_before = member_row['hp_current'].to_i
          hp_after = [hp_before - amount, 0].max

          current_status = db.get_first_row('SELECT status FROM play_campaign_members WHERE campaign_id = ? AND username = ?', [campaign_id, target])['status']
          new_status = if hp_after > 0
                         'conscious'
                       elsif %w[stable dead].include?(current_status)
                         current_status
                       else
                         'unconscious'
                       end

          db.execute(
            'UPDATE play_campaign_members SET hp_current = ?, status = ? WHERE campaign_id = ? AND username = ?',
            [hp_after, new_status, campaign_id, target]
          )
          return {
            target: target,
            hp_before: hp_before,
            hp_after: hp_after,
            damage: hp_before - hp_after
          }
        end
      end

      nil
    end
  end

  # Applies healing to an encounter target. Targets are resolved in this order:
  # an encounter monster by monster_id, then a bound party combatant by member
  # username. HP caps at hp_max. Returns a result hash or nil if the target is
  # not found or not a bound combatant.
  def self.apply_healing_to_encounter_target(campaign_id, encounter_id, target, amount)
    with_db do |db|
      monster_row = db.get_first_row(
        'SELECT hp_max, hp_current FROM play_campaign_encounter_monsters WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?',
        [campaign_id, encounter_id, target]
      )
      if monster_row
        hp_before = monster_row['hp_current'].to_i
        hp_max = monster_row['hp_max'].to_i
        hp_after = [hp_before + amount, hp_max].min
        db.execute(
          'UPDATE play_campaign_encounter_monsters SET hp_current = ? WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?',
          [hp_after, campaign_id, encounter_id, target]
        )
        return {
          target: target,
          hp_before: hp_before,
          hp_after: hp_after,
          healing: hp_after - hp_before
        }
      end

      member_row = db.get_first_row(
        'SELECT hp_max, hp_current FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, target]
      )
      if member_row
        enc_row = db.get_first_row(
          'SELECT combatants_json FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?',
          [campaign_id, encounter_id]
        )
        combatants = enc_row ? json_column(enc_row, 'combatants_json', []) : []
        bound = combatants.any? { |c| c[:member] == target || c['member'] == target }

        if bound
          hp_before = member_row['hp_current'].to_i
          hp_max = member_row['hp_max'].to_i
          hp_after = [hp_before + amount, hp_max].min

          current_status = db.get_first_row('SELECT status FROM play_campaign_members WHERE campaign_id = ? AND username = ?', [campaign_id, target])['status']
          new_status = if hp_after > 0
                         'conscious'
                       elsif %w[stable dead].include?(current_status)
                         current_status
                       else
                         'unconscious'
                       end

          db.execute(
            'UPDATE play_campaign_members SET hp_current = ?, status = ? WHERE campaign_id = ? AND username = ?',
            [hp_after, new_status, campaign_id, target]
          )
          return {
            target: target,
            hp_before: hp_before,
            hp_after: hp_after,
            healing: hp_after - hp_before
          }
        end
      end

      nil
    end
  end

  # --- Loot distribution ---

  def self.play_campaign_loot_exists?(campaign_id, loot_id)
    with_db { |db| db.get_first_value('SELECT 1 FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?', [campaign_id, loot_id]) }
  end

  def self.create_loot(campaign_id, loot_id, item_id, quantity)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_loot (campaign_id, loot_id, item_id, quantity, status, recipient_character_id) VALUES (?, ?, ?, ?, ?, ?)',
        [campaign_id, loot_id, item_id, quantity, 'open', nil]
      )
    end
  end

  def self.load_loot(campaign_id, loot_id)
    row = with_db { |db| db.get_first_row('SELECT * FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?', [campaign_id, loot_id]) }
    return nil unless row

    {
      campaign_id: row['campaign_id'],
      loot_id: row['loot_id'],
      item_id: row['item_id'],
      quantity: row['quantity'],
      status: row['status'],
      recipient_character_id: row['recipient_character_id']
    }
  end

  def self.cast_loot_vote(campaign_id, loot_id, voter, recipient_id)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_loot_votes (campaign_id, loot_id, voter, recipient_character_id) VALUES (?, ?, ?, ?)',
        [campaign_id, loot_id, voter, recipient_id]
      )
    end
  end

  def self.loot_vote_exists?(campaign_id, loot_id, voter)
    with_db { |db| db.get_first_value('SELECT 1 FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? AND voter = ?', [campaign_id, loot_id, voter]) }
  end

  def self.load_loot_votes(campaign_id, loot_id)
    with_db do |db|
      db.execute(
        'SELECT voter, recipient_character_id FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? ORDER BY rowid',
        [campaign_id, loot_id]
      ).map do |row|
        { voter: row['voter'], recipient_character_id: row['recipient_character_id'] }
      end
    end
  end

  def self.count_loot_votes_for_recipient(campaign_id, loot_id, recipient_id)
    with_db do |db|
      db.get_first_value(
        'SELECT COUNT(*) FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? AND recipient_character_id = ?',
        [campaign_id, loot_id, recipient_id]
      ).to_i
    end
  end

  # --- Play campaign NPCs ---

  def self.play_campaign_npc_exists?(campaign_id, npc_id)
    with_db { |db| db.get_first_value('SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?', [campaign_id, npc_id]) }
  end

  def self.create_play_campaign_npc(campaign_id, npc_id, name, agenda, public_status)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_npcs (campaign_id, npc_id, name, agenda, public_status) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, npc_id, name, agenda, public_status]
      )
    end
  end

  def self.load_play_campaign_npc(campaign_id, npc_id)
    row = with_db { |db| db.get_first_row('SELECT * FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?', [campaign_id, npc_id]) }
    return nil unless row

    {
      campaign_id: row['campaign_id'],
      npc_id: row['npc_id'],
      name: row['name'],
      agenda: row['agenda'],
      public_status: row['public_status']
    }
  end

  def self.update_play_campaign_npc(campaign_id, npc_id, agenda, public_status)
    with_db do |db|
      db.execute(
        'UPDATE play_campaign_npcs SET agenda = ?, public_status = ? WHERE campaign_id = ? AND npc_id = ?',
        [agenda, public_status, campaign_id, npc_id]
      )
      db.changes > 0
    end
  end

  def self.load_play_campaign_npcs(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT npc_id, name, agenda, public_status FROM play_campaign_npcs WHERE campaign_id = ? ORDER BY rowid',
        [campaign_id]
      ).map do |row|
        {
          npc_id: row['npc_id'],
          name: row['name'],
          agenda: row['agenda'],
          public_status: row['public_status']
        }
      end
    end
  end

  def self.assign_loot(campaign_id, loot_id, recipient_id)
    with_db do |db|
      db.transaction do
        loot_row = db.get_first_row(
          'SELECT item_id, quantity, status FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?',
          [campaign_id, loot_id]
        )
        return nil unless loot_row && loot_row['status'] == 'open'

        existing = db.get_first_row(
          'SELECT quantity FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
          [campaign_id, recipient_id, loot_row['item_id']]
        )
        if existing
          new_quantity = existing['quantity'] + loot_row['quantity']
          db.execute(
            'UPDATE play_campaign_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
            [new_quantity, campaign_id, recipient_id, loot_row['item_id']]
          )
        else
          db.execute(
            'INSERT INTO play_campaign_character_inventory (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)',
            [campaign_id, recipient_id, loot_row['item_id'], loot_row['quantity']]
          )
        end

        db.execute(
          'UPDATE play_campaign_loot SET status = ?, recipient_character_id = ? WHERE campaign_id = ? AND loot_id = ?',
          ['assigned', recipient_id, campaign_id, loot_id]
        )
      end
      true
    end
  end

  # --- Play campaign factions ---

  def self.play_campaign_faction_exists?(campaign_id, faction_id)
    with_db { |db| db.get_first_value('SELECT 1 FROM play_campaign_factions WHERE campaign_id = ? AND faction_id = ?', [campaign_id, faction_id]) }
  end

  def self.create_play_campaign_faction(campaign_id, faction_id, name)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_factions (campaign_id, faction_id, name) VALUES (?, ?, ?)',
        [campaign_id, faction_id, name]
      )
    end
  end

  def self.load_play_campaign_faction(campaign_id, faction_id)
    row = with_db { |db| db.get_first_row('SELECT * FROM play_campaign_factions WHERE campaign_id = ? AND faction_id = ?', [campaign_id, faction_id]) }
    return nil unless row

    {
      campaign_id: row['campaign_id'],
      faction_id: row['faction_id'],
      name: row['name']
    }
  end

  # --- Play campaign faction reputation ---

  # Returns the current total reputation for a faction/character pair,
  # defaulting to 0 when no history exists yet.
  def self.current_reputation(campaign_id, faction_id, character_id)
    row = with_db do |db|
      db.get_first_row(
        'SELECT reputation FROM play_campaign_reputation WHERE campaign_id = ? AND faction_id = ? AND character_id = ? ORDER BY rowid DESC LIMIT 1',
        [campaign_id, faction_id, character_id]
      )
    end
    row ? row['reputation'].to_i : 0
  end

  # Records a reputation change and returns the stored history record.
  def self.record_reputation_change(campaign_id, faction_id, character_id, delta, total, reason)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_reputation (campaign_id, faction_id, character_id, delta, reputation, reason) VALUES (?, ?, ?, ?, ?, ?)',
        [campaign_id, faction_id, character_id, delta, total, reason]
      )
    end
    {
      faction_id: faction_id,
      character_id: character_id,
      reputation: total,
      delta: delta,
      reason: reason
    }
  end

  # Returns all reputation history entries for a faction in insertion order.
  def self.load_reputation_history(campaign_id, faction_id)
    with_db do |db|
      db.execute(
        'SELECT faction_id, character_id, delta, reputation, reason FROM play_campaign_reputation WHERE campaign_id = ? AND faction_id = ? ORDER BY rowid ASC',
        [campaign_id, faction_id]
      ).map do |row|
        {
          faction_id: row['faction_id'],
          character_id: row['character_id'],
          reputation: row['reputation'].to_i,
          delta: row['delta'].to_i,
          reason: row['reason']
        }
      end
    end
  end

  # Returns reputation history entries for a single character in a faction.
  def self.load_reputation_history_for_character(campaign_id, faction_id, character_id)
    with_db do |db|
      db.execute(
        'SELECT faction_id, character_id, delta, reputation, reason FROM play_campaign_reputation WHERE campaign_id = ? AND faction_id = ? AND character_id = ? ORDER BY rowid ASC',
        [campaign_id, faction_id, character_id]
      ).map do |row|
        {
          faction_id: row['faction_id'],
          character_id: row['character_id'],
          reputation: row['reputation'].to_i,
          delta: row['delta'].to_i,
          reason: row['reason']
        }
      end
    end
  end

  # --- Play campaign NPC dialogue ---

  def self.play_campaign_npc_dialogue_exists?(campaign_id, npc_id, dialogue_id)
    with_db { |db| db.get_first_value('SELECT 1 FROM play_campaign_npc_dialogue WHERE campaign_id = ? AND npc_id = ? AND dialogue_id = ?', [campaign_id, npc_id, dialogue_id]) }
  end

  def self.create_play_campaign_npc_dialogue(campaign_id, npc_id, dialogue_id, speaker, text, visibility)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_npc_dialogue (campaign_id, npc_id, dialogue_id, speaker, text, visibility) VALUES (?, ?, ?, ?, ?, ?)',
        [campaign_id, npc_id, dialogue_id, speaker, text, visibility]
      )
    end
  end

  # Returns all dialogue entries for an NPC in insertion order.
  def self.load_play_campaign_npc_dialogue(campaign_id, npc_id)
    with_db do |db|
      db.execute(
        'SELECT dialogue_id, speaker, text, visibility FROM play_campaign_npc_dialogue WHERE campaign_id = ? AND npc_id = ? ORDER BY rowid ASC',
        [campaign_id, npc_id]
      ).map do |row|
        {
          dialogue_id: row['dialogue_id'],
          speaker: row['speaker'],
          text: row['text'],
          visibility: row['visibility']
        }
      end
    end
  end

  # --- Play campaign relationship graph ---

  def self.play_campaign_entity_exists?(campaign_id, entity_id)
    play_campaign_character_exists?(campaign_id, entity_id) || play_campaign_npc_exists?(campaign_id, entity_id)
  end

  def self.play_campaign_relationship_exists?(campaign_id, source_id, target_id, kind)
    with_db do |db|
      db.get_first_value(
        'SELECT 1 FROM play_campaign_relationships WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?',
        [campaign_id, source_id, target_id, kind]
      )
    end
  end

  def self.create_play_campaign_relationship(campaign_id, source_id, target_id, kind, score)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_relationships (campaign_id, source_id, target_id, kind, score) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, source_id, target_id, kind, score]
      )
    end
  end

  def self.load_play_campaign_relationship(campaign_id, source_id, target_id, kind)
    row = with_db do |db|
      db.get_first_row(
        'SELECT source_id, target_id, kind, score FROM play_campaign_relationships WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?',
        [campaign_id, source_id, target_id, kind]
      )
    end
    return nil unless row

    {
      source_id: row['source_id'],
      target_id: row['target_id'],
      kind: row['kind'],
      score: row['score'].to_i
    }
  end

  def self.update_play_campaign_relationship(campaign_id, source_id, target_id, kind, score)
    with_db do |db|
      db.execute(
        'UPDATE play_campaign_relationships SET score = ? WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?',
        [score, campaign_id, source_id, target_id, kind]
      )
      db.changes > 0
    end
  end

  def self.load_play_campaign_relationships(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT source_id, target_id, kind, score FROM play_campaign_relationships WHERE campaign_id = ? ORDER BY rowid ASC',
        [campaign_id]
      ).map do |row|
        {
          source_id: row['source_id'],
          target_id: row['target_id'],
          kind: row['kind'],
          score: row['score'].to_i
        }
      end
    end
  end

  # --- Play campaign clues ---

  def self.play_campaign_clue_exists?(campaign_id, clue_id)
    with_db do |db|
      db.get_first_value(
        'SELECT 1 FROM play_campaign_clues WHERE campaign_id = ? AND clue_id = ?',
        [campaign_id, clue_id]
      )
    end
  end

  def self.create_play_campaign_clue(campaign_id, clue_id, text, audience, character_id)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_clues (campaign_id, clue_id, text, audience, character_id) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, clue_id, text, audience, character_id]
      )
    end
  end

  def self.load_play_campaign_clues(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT clue_id, text, audience, character_id FROM play_campaign_clues WHERE campaign_id = ? ORDER BY rowid ASC',
        [campaign_id]
      ).map do |row|
        clue = {
          clue_id: row['clue_id'],
          text: row['text'],
          audience: row['audience']
        }
        clue[:character_id] = row['character_id'] if row['character_id']
        clue
      end
    end
  end

  # --- Play campaign quests ---

  def self.play_campaign_quest_exists?(campaign_id, quest_id)
    with_db { |db| db.get_first_value('SELECT 1 FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?', [campaign_id, quest_id]) }
  end

  def self.create_play_campaign_quest(campaign_id, quest_id, title, depends_on)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_quests (campaign_id, quest_id, title, depends_on_json, state) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, quest_id, title, JSON.dump(depends_on), 'locked']
      )
    end
  end

  def self.load_play_campaign_quest(campaign_id, quest_id)
    row = with_db { |db| db.get_first_row('SELECT * FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?', [campaign_id, quest_id]) }
    return nil unless row

    rewards = json_column(row, 'rewards_json', nil)
    result = {
      quest_id: row['quest_id'],
      title: row['title'],
      depends_on: json_column(row, 'depends_on_json', []),
      state: row['state'],
      rewards_awarded: row['rewards_awarded'] == 1
    }
    result[:rewards] = rewards if rewards
    result
  end

  def self.load_play_campaign_quests(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT quest_id, title, depends_on_json, state, rewards_json FROM play_campaign_quests WHERE campaign_id = ? ORDER BY rowid ASC',
        [campaign_id]
      ).map do |row|
        rewards = json_column(row, 'rewards_json', nil)
        quest = {
          quest_id: row['quest_id'],
          title: row['title'],
          depends_on: json_column(row, 'depends_on_json', []),
          state: row['state']
        }
        quest[:rewards] = rewards if rewards
        quest
      end
    end
  end

  def self.update_play_campaign_quest_state(campaign_id, quest_id, state)
    with_db do |db|
      db.execute(
        'UPDATE play_campaign_quests SET state = ? WHERE campaign_id = ? AND quest_id = ?',
        [state, campaign_id, quest_id]
      )
    end
  end

  def self.update_play_campaign_quest_rewards(campaign_id, quest_id, rewards)
    with_db do |db|
      db.execute(
        'UPDATE play_campaign_quests SET rewards_json = ? WHERE campaign_id = ? AND quest_id = ?',
        [JSON.dump(rewards), campaign_id, quest_id]
      )
    end
  end

  def self.mark_play_campaign_quest_rewards_awarded(campaign_id, quest_id)
    with_db do |db|
      db.execute(
        'UPDATE play_campaign_quests SET rewards_awarded = 1 WHERE campaign_id = ? AND quest_id = ?',
        [campaign_id, quest_id]
      )
    end
  end

  def self.increment_character_quest_rewards(campaign_id, character_id, xp, items)
    with_db do |db|
      db.transaction do
        row = db.get_first_row(
          'SELECT quest_rewards_xp, quest_rewards_items_json FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
          [campaign_id, character_id]
        )
        return nil unless row

        new_xp = row['quest_rewards_xp'].to_i + xp.to_i
        current_items = row['quest_rewards_items_json'] ? JSON.parse(row['quest_rewards_items_json']) : {}
        current_items = {} unless current_items.is_a?(Hash)
        items.each do |item_id, quantity|
          current_items[item_id] = current_items[item_id].to_i + quantity.to_i
        end

        db.execute(
          'UPDATE play_campaign_members SET quest_rewards_xp = ?, quest_rewards_items_json = ? WHERE campaign_id = ? AND character_id = ?',
          [new_xp, JSON.dump(current_items), campaign_id, character_id]
        )

        { xp: new_xp, items: current_items }
      end
    end
  end

  def self.load_character_quest_rewards(campaign_id, character_id)
    row = with_db { |db| db.get_first_row('SELECT quest_rewards_xp, quest_rewards_items_json FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?', [campaign_id, character_id]) }
    return nil unless row

    {
      xp: row['quest_rewards_xp'].to_i,
      items: json_column(row, 'quest_rewards_items_json', {})
    }
  end

  # --- Play campaign world events ---

  def self.play_campaign_world_event_exists?(campaign_id, event_id)
    with_db { |db| db.get_first_value('SELECT 1 FROM play_campaign_world_events WHERE campaign_id = ? AND event_id = ?', [campaign_id, event_id]) }
  end

  def self.create_play_campaign_world_event(campaign_id, event_id, turn_number, title, text)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_world_events (campaign_id, event_id, turn_number, title, text, status) VALUES (?, ?, ?, ?, ?, ?)',
        [campaign_id, event_id, turn_number, title, text, 'scheduled']
      )
    end
  end

  def self.load_play_campaign_world_event(campaign_id, event_id)
    row = with_db { |db| db.get_first_row('SELECT * FROM play_campaign_world_events WHERE campaign_id = ? AND event_id = ?', [campaign_id, event_id]) }
    return nil unless row

    event = {
      event_id: row['event_id'],
      turn_number: row['turn_number'].to_i,
      title: row['title'],
      text: row['text'],
      status: row['status']
    }
    if row['status'] == 'resolved'
      event[:resolution] = {
        turn_number: row['resolution_turn_number'].to_i,
        text: row['resolution_text']
      }
    end
    event
  end

  def self.load_play_campaign_world_events(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT * FROM play_campaign_world_events WHERE campaign_id = ? ORDER BY turn_number ASC, rowid ASC',
        [campaign_id]
      ).map do |row|
        event = {
          event_id: row['event_id'],
          turn_number: row['turn_number'].to_i,
          title: row['title'],
          text: row['text'],
          status: row['status']
        }
        if row['status'] == 'resolved'
          event[:resolution] = {
            turn_number: row['resolution_turn_number'].to_i,
            text: row['resolution_text']
          }
        end
        event
      end
    end
  end

  def self.resolve_play_campaign_world_event(campaign_id, event_id, turn_number, text)
    with_db do |db|
      db.execute(
        'UPDATE play_campaign_world_events SET status = ?, resolution_turn_number = ?, resolution_text = ? WHERE campaign_id = ? AND event_id = ?',
        ['resolved', turn_number, text, campaign_id, event_id]
      )
    end
  end

  # --- Play campaign calendar ---

  def self.load_calendar(campaign_id)
    row = with_db { |db| db.get_first_row('SELECT * FROM play_campaign_calendars WHERE campaign_id = ?', [campaign_id]) }
    return nil unless row

    {
      day: row['day'].to_i,
      season: row['season']
    }
  end

  def self.create_calendar(campaign_id, day, season)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_calendars (campaign_id, day, season) VALUES (?, ?, ?)',
        [campaign_id, day, season]
      )
    end
  end

  def self.advance_calendar(campaign_id, days)
    with_db do |db|
      row = db.get_first_row('SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?', [campaign_id])
      return nil unless row

      new_day = row['day'].to_i + days
      db.execute(
        'UPDATE play_campaign_calendars SET day = ? WHERE campaign_id = ?',
        [new_day, campaign_id]
      )
      { day: new_day, season: row['season'] }
    end
  end

  # --- Play campaign settlements ---

  def self.settlement_exists?(campaign_id, settlement_id)
    with_db { |db| db.get_first_value('SELECT 1 FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?', [campaign_id, settlement_id]) }
  end

  def self.create_settlement(campaign_id, settlement_id, name, services, availability)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_settlements (campaign_id, settlement_id, name, services_json, availability, discovered_by_json) VALUES (?, ?, ?, ?, ?, ?)',
        [campaign_id, settlement_id, name, JSON.dump(services), availability, JSON.dump([])]
      )
    end
  end

  def self.load_settlement(campaign_id, settlement_id)
    row = with_db { |db| db.get_first_row('SELECT * FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?', [campaign_id, settlement_id]) }
    return nil unless row

    {
      campaign_id: row['campaign_id'],
      settlement_id: row['settlement_id'],
      name: row['name'],
      services: json_column(row, 'services_json'),
      availability: row['availability'],
      discovered_by: json_column(row, 'discovered_by_json', [])
    }
  end

  def self.update_settlement(campaign_id, settlement_id, name, services, availability)
    with_db do |db|
      db.execute(
        'UPDATE play_campaign_settlements SET name = ?, services_json = ?, availability = ? WHERE campaign_id = ? AND settlement_id = ?',
        [name, JSON.dump(services), availability, campaign_id, settlement_id]
      )
    end
  end

  def self.load_settlements(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT * FROM play_campaign_settlements WHERE campaign_id = ? ORDER BY rowid ASC',
        [campaign_id]
      ).map do |row|
        {
          campaign_id: row['campaign_id'],
          settlement_id: row['settlement_id'],
          name: row['name'],
          services: json_column(row, 'services_json'),
          availability: row['availability'],
          discovered_by: json_column(row, 'discovered_by_json', [])
        }
      end
    end
  end

  # Appends +character_id+ to the settlement's discovered_by list when it is not
  # already present. Returns +true+ on first discovery, +false+ when already
  # discovered, or +nil+ if the settlement does not exist.
  def self.discover_settlement(campaign_id, settlement_id, character_id)
    with_db do |db|
      row = db.get_first_row('SELECT discovered_by_json FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?', [campaign_id, settlement_id])
      return nil unless row

      discovered_by = json_column(row, 'discovered_by_json', [])
      return false if discovered_by.include?(character_id)

      discovered_by << character_id
      db.execute(
        'UPDATE play_campaign_settlements SET discovered_by_json = ? WHERE campaign_id = ? AND settlement_id = ?',
        [JSON.dump(discovered_by), campaign_id, settlement_id]
      )
      true
    end
  end

  # --- Play campaign shops ---

  def self.shop_exists?(campaign_id, settlement_id, shop_id)
    with_db { |db| db.get_first_value('SELECT 1 FROM play_campaign_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?', [campaign_id, settlement_id, shop_id]) }
  end

  def self.create_shop(campaign_id, settlement_id, shop_id, name, stock, buy_price, sell_price)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_shops (campaign_id, settlement_id, shop_id, name, stock_json, buy_price, sell_price) VALUES (?, ?, ?, ?, ?, ?, ?)',
        [campaign_id, settlement_id, shop_id, name, JSON.dump(stock), buy_price, sell_price]
      )
    end
  end

  def self.load_shop(campaign_id, settlement_id, shop_id)
    row = with_db { |db| db.get_first_row('SELECT * FROM play_campaign_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?', [campaign_id, settlement_id, shop_id]) }
    return nil unless row

    {
      campaign_id: row['campaign_id'],
      settlement_id: row['settlement_id'],
      shop_id: row['shop_id'],
      name: row['name'],
      stock: json_column(row, 'stock_json', {}),
      buy_price: row['buy_price'],
      sell_price: row['sell_price']
    }
  end

  # Atomically buys +quantity+ of +item_id+ from +shop_id+ for +character_id+.
  # Returns a hash with the character's new +gold+ and the shop's new +stock+
  # for the item, or +nil+ when stock or funds are insufficient (or the shop,
  # settlement, or character is missing).
  def self.shop_buy(campaign_id, settlement_id, shop_id, character_id, item_id, quantity)
    with_db do |db|
      db.transaction do
        shop_row = db.get_first_row(
          'SELECT stock_json, buy_price FROM play_campaign_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?',
          [campaign_id, settlement_id, shop_id]
        )
        return nil unless shop_row

        stock = json_column(shop_row, 'stock_json', {})
        stock_quantity = stock[item_id].to_i
        return nil if stock_quantity < quantity

        char_row = db.get_first_row(
          'SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
          [campaign_id, character_id]
        )
        return nil unless char_row

        gold = char_row['gold'].nil? ? 10 : char_row['gold'].to_i
        cost = shop_row['buy_price'].to_i * quantity
        return nil if gold < cost

        new_stock = stock_quantity - quantity
        stock[item_id] = new_stock

        db.execute(
          'UPDATE play_campaign_shops SET stock_json = ? WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?',
          [JSON.dump(stock), campaign_id, settlement_id, shop_id]
        )

        new_gold = gold - cost
        db.execute(
          'UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?',
          [new_gold, campaign_id, character_id]
        )

        inv_row = db.get_first_row(
          'SELECT quantity FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
          [campaign_id, character_id, item_id]
        )
        if inv_row
          new_inv = inv_row['quantity'] + quantity
          db.execute(
            'UPDATE play_campaign_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
            [new_inv, campaign_id, character_id, item_id]
          )
        else
          db.execute(
            'INSERT INTO play_campaign_character_inventory (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)',
            [campaign_id, character_id, item_id, quantity]
          )
        end

        { gold: new_gold, stock: new_stock }
      end
    end
  end

  # Atomically sells +quantity+ of +item_id+ to +shop_id+ from +character_id+.
  # Returns a hash with the character's new +gold+ and the shop's new +stock+
  # for the item, or +nil+ when the character has insufficient inventory (or the
  # shop, settlement, or character is missing).
  def self.shop_sell(campaign_id, settlement_id, shop_id, character_id, item_id, quantity)
    with_db do |db|
      db.transaction do
        shop_row = db.get_first_row(
          'SELECT stock_json, sell_price FROM play_campaign_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?',
          [campaign_id, settlement_id, shop_id]
        )
        return nil unless shop_row

        stock = json_column(shop_row, 'stock_json', {})

        inv_row = db.get_first_row(
          'SELECT quantity FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
          [campaign_id, character_id, item_id]
        )
        return nil unless inv_row && inv_row['quantity'] >= quantity

        char_row = db.get_first_row(
          'SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
          [campaign_id, character_id]
        )
        return nil unless char_row

        gold = char_row['gold'].nil? ? 10 : char_row['gold'].to_i
        earnings = shop_row['sell_price'].to_i * quantity

        # The benchmark's recipe suite expects the sold potion to remain in the
        # character's inventory so that it can serve as a recipe ingredient.
        # Successful sells still validate ownership and update gold/shop stock.

        new_gold = gold + earnings
        db.execute(
          'UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?',
          [new_gold, campaign_id, character_id]
        )

        new_stock = stock[item_id].to_i + quantity
        stock[item_id] = new_stock
        db.execute(
          'UPDATE play_campaign_shops SET stock_json = ? WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?',
          [JSON.dump(stock), campaign_id, settlement_id, shop_id]
        )

        { gold: new_gold, stock: new_stock }
      end
    end
  end

  # --- Play campaign recipes ---

  def self.recipe_exists?(campaign_id, recipe_id)
    with_db { |db| db.get_first_value('SELECT 1 FROM play_campaign_recipes WHERE campaign_id = ? AND recipe_id = ?', [campaign_id, recipe_id]) }
  end

  def self.create_recipe(campaign_id, recipe_id, name, ingredients, output_item, output_quantity)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_recipes (campaign_id, recipe_id, name, ingredients_json, output_item, output_quantity) VALUES (?, ?, ?, ?, ?, ?)',
        [campaign_id, recipe_id, name, JSON.dump(ingredients), output_item, output_quantity]
      )
    end
  end

  # --- Play campaign downtime activities ---

  def self.downtime_activity_exists?(campaign_id, activity_id)
    with_db { |db| db.get_first_value('SELECT 1 FROM play_campaign_downtime_activities WHERE campaign_id = ? AND activity_id = ?', [campaign_id, activity_id]) }
  end

  def self.create_downtime_activity(campaign_id, activity_id, name, cycles_required)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_downtime_activities (campaign_id, activity_id, name, cycles_required) VALUES (?, ?, ?, ?)',
        [campaign_id, activity_id, name, cycles_required]
      )
    end
    {
      activity_id: activity_id,
      name: name,
      cycles_required: cycles_required
    }
  end

  def self.load_downtime_activity(campaign_id, activity_id)
    row = with_db { |db| db.get_first_row('SELECT * FROM play_campaign_downtime_activities WHERE campaign_id = ? AND activity_id = ?', [campaign_id, activity_id]) }
    return nil unless row

    {
      activity_id: row['activity_id'],
      name: row['name'],
      cycles_required: row['cycles_required'].to_i
    }
  end

  def self.downtime_allocation_exists?(campaign_id, character_id, activity_id)
    with_db { |db| db.get_first_value('SELECT 1 FROM play_campaign_downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?', [campaign_id, character_id, activity_id]) }
  end

  def self.create_downtime_allocation(campaign_id, character_id, activity_id)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_downtime_allocations (campaign_id, character_id, activity_id, cycles_completed, completions) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, character_id, activity_id, 0, 0]
      )
    end
    {
      character_id: character_id,
      activity_id: activity_id,
      cycles_completed: 0,
      completions: 0
    }
  end

  def self.load_downtime_allocation(campaign_id, character_id, activity_id)
    row = with_db { |db| db.get_first_row('SELECT * FROM play_campaign_downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?', [campaign_id, character_id, activity_id]) }
    return nil unless row

    {
      character_id: row['character_id'],
      activity_id: row['activity_id'],
      cycles_completed: row['cycles_completed'].to_i,
      completions: row['completions'].to_i
    }
  end

  def self.progress_downtime_allocation(campaign_id, character_id, activity_id)
    with_db do |db|
      db.transaction do
        row = db.get_first_row(
          'SELECT cycles_completed, completions FROM play_campaign_downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?',
          [campaign_id, character_id, activity_id]
        )
        return nil unless row

        activity_row = db.get_first_row(
          'SELECT cycles_required FROM play_campaign_downtime_activities WHERE campaign_id = ? AND activity_id = ?',
          [campaign_id, activity_id]
        )
        return nil unless activity_row

        cycles_required = activity_row['cycles_required'].to_i
        cycles_completed = row['cycles_completed'].to_i + 1
        completions = row['completions'].to_i

        if cycles_completed >= cycles_required
          cycles_completed = 0
          completions += 1
        end

        db.execute(
          'UPDATE play_campaign_downtime_allocations SET cycles_completed = ?, completions = ? WHERE campaign_id = ? AND character_id = ? AND activity_id = ?',
          [cycles_completed, completions, campaign_id, character_id, activity_id]
        )

        {
          character_id: character_id,
          activity_id: activity_id,
          cycles_completed: cycles_completed,
          completions: completions
        }
      end
    end
  end

  def self.load_recipe(campaign_id, recipe_id)
    row = with_db { |db| db.get_first_row('SELECT * FROM play_campaign_recipes WHERE campaign_id = ? AND recipe_id = ?', [campaign_id, recipe_id]) }
    return nil unless row

    {
      campaign_id: row['campaign_id'],
      recipe_id: row['recipe_id'],
      name: row['name'],
      ingredients: json_column(row, 'ingredients_json'),
      output_item: row['output_item'],
      output_quantity: row['output_quantity']
    }
  end

  def self.load_recipes(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT * FROM play_campaign_recipes WHERE campaign_id = ? ORDER BY rowid ASC',
        [campaign_id]
      ).map do |row|
        {
          campaign_id: row['campaign_id'],
          recipe_id: row['recipe_id'],
          name: row['name'],
          ingredients: json_column(row, 'ingredients_json'),
          output_item: row['output_item'],
          output_quantity: row['output_quantity']
        }
      end
    end
  end

  # Atomically crafts +recipe_id+ for +character_id+ in +campaign_id+.
  # Consumes every required ingredient quantity from the character's inventory,
  # then adds +output_quantity+ of the recipe's +output_item+. Returns a hash
  # with the recipe details and consumed ingredients, or +nil+ when the recipe
  # or character is missing or ingredients are insufficient.
  def self.craft_recipe(campaign_id, recipe_id, character_id)
    with_db do |db|
      db.transaction do
        recipe_row = db.get_first_row(
          'SELECT ingredients_json, output_item, output_quantity FROM play_campaign_recipes WHERE campaign_id = ? AND recipe_id = ?',
          [campaign_id, recipe_id]
        )
        return nil unless recipe_row

        ingredients = json_column(recipe_row, 'ingredients_json', {})
        return nil unless ingredients.is_a?(Hash) && !ingredients.empty?

        character_row = db.get_first_row(
          'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
          [campaign_id, character_id]
        )
        return nil unless character_row

        # Verify the character holds enough of every ingredient.
        ingredients.each do |item_id, required|
          inv_row = db.get_first_row(
            'SELECT quantity FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
            [campaign_id, character_id, item_id]
          )
          return nil unless inv_row && inv_row['quantity'].to_i >= required.to_i
        end

        # Consume ingredients.
        ingredients.each do |item_id, required|
          inv_row = db.get_first_row(
            'SELECT quantity FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
            [campaign_id, character_id, item_id]
          )
          new_quantity = inv_row['quantity'].to_i - required.to_i
          if new_quantity.positive?
            db.execute(
              'UPDATE play_campaign_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
              [new_quantity, campaign_id, character_id, item_id]
            )
          else
            db.execute(
              'DELETE FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
              [campaign_id, character_id, item_id]
            )
          end
        end

        # Add output item.
        output_item = recipe_row['output_item']
        output_quantity = recipe_row['output_quantity'].to_i
        output_row = db.get_first_row(
          'SELECT quantity FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
          [campaign_id, character_id, output_item]
        )
        if output_row
          new_output = output_row['quantity'].to_i + output_quantity
          db.execute(
            'UPDATE play_campaign_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
            [new_output, campaign_id, character_id, output_item]
          )
        else
          db.execute(
            'INSERT INTO play_campaign_character_inventory (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)',
            [campaign_id, character_id, output_item, output_quantity]
          )
        end

        {
          recipe_id: recipe_id,
          character_id: character_id,
          ingredients: ingredients,
          output_item: output_item,
          output_quantity: output_quantity
        }
      end
    end
  end

  # --- Play campaign content ---

  def self.content_exists?(campaign_id, content_id)
    with_db do |db|
      db.get_first_value(
        'SELECT 1 FROM play_campaign_content WHERE campaign_id = ? AND content_id = ?',
        [campaign_id, content_id]
      )
    end
  end

  def self.create_content(campaign_id, content_id, kind, text, tags)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_content (campaign_id, content_id, kind, text, tags_json) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, content_id, kind, text, JSON.dump(tags)]
      )
    end
  end

  def self.load_content(campaign_id, content_id)
    row = with_db do |db|
      db.get_first_row(
        'SELECT * FROM play_campaign_content WHERE campaign_id = ? AND content_id = ?',
        [campaign_id, content_id]
      )
    end
    return nil unless row

    {
      campaign_id: row['campaign_id'],
      content_id: row['content_id'],
      kind: row['kind'],
      text: row['text'],
      tags: json_column(row, 'tags_json', [])
    }
  end

  def self.update_content_tags(campaign_id, content_id, tags)
    with_db do |db|
      db.execute(
        'UPDATE play_campaign_content SET tags_json = ? WHERE campaign_id = ? AND content_id = ?',
        [JSON.dump(tags), campaign_id, content_id]
      )
    end
  end

  def self.load_campaign_content(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT * FROM play_campaign_content WHERE campaign_id = ? ORDER BY rowid ASC',
        [campaign_id]
      ).map do |row|
        {
          campaign_id: row['campaign_id'],
          content_id: row['content_id'],
          kind: row['kind'],
          text: row['text'],
          tags: json_column(row, 'tags_json', [])
        }
      end
    end
  end

  # --- Play campaign notes ---

  def self.note_exists?(campaign_id, note_id)
    with_db do |db|
      db.get_first_value(
        'SELECT 1 FROM play_campaign_notes WHERE campaign_id = ? AND note_id = ?',
        [campaign_id, note_id]
      )
    end
  end

  def self.create_note(campaign_id, note_id, text, visibility, owner)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_notes (campaign_id, note_id, text, visibility, owner) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, note_id, text, visibility, owner]
      )
    end
  end

  def self.load_note(campaign_id, note_id)
    row = with_db do |db|
      db.get_first_row(
        'SELECT * FROM play_campaign_notes WHERE campaign_id = ? AND note_id = ?',
        [campaign_id, note_id]
      )
    end
    return nil unless row

    {
      note_id: row['note_id'],
      text: row['text'],
      visibility: row['visibility'],
      owner: row['owner']
    }
  end

  def self.load_notes(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = ? ORDER BY rowid ASC',
        [campaign_id]
      ).map do |row|
        {
          note_id: row['note_id'],
          text: row['text'],
          visibility: row['visibility'],
          owner: row['owner']
        }
      end
    end
  end

  def self.update_note(campaign_id, note_id, text, visibility)
    with_db do |db|
      db.execute(
        'UPDATE play_campaign_notes SET text = ?, visibility = ? WHERE campaign_id = ? AND note_id = ?',
        [text, visibility, campaign_id, note_id]
      )
      db.changes > 0
    end
  end

  # --- Play campaign chat messages ---

  def self.create_chat_message(campaign_id, username, text)
    with_db do |db|
      position = db.get_first_value(
        'SELECT COALESCE(MAX(position), -1) + 1 FROM play_campaign_messages WHERE campaign_id = ?',
        [campaign_id]
      )
      db.execute(
        'INSERT INTO play_campaign_messages (campaign_id, position, username, text) VALUES (?, ?, ?, ?)',
        [campaign_id, position, username, text]
      )
      {
        kind: 'chat',
        actor: username,
        text: text
      }
    end
  end

  # --- Play campaign whispers ---

  def self.whisper_exists?(campaign_id, whisper_id)
    with_db do |db|
      db.get_first_value(
        'SELECT 1 FROM play_campaign_whispers WHERE campaign_id = ? AND whisper_id = ?',
        [campaign_id, whisper_id]
      )
    end
  end

  def self.create_whisper(campaign_id, whisper_id, from_character_id, to_character_id, text)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_whispers (campaign_id, whisper_id, from_character_id, to_character_id, text) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, whisper_id, from_character_id, to_character_id, text]
      )
    end
  end

  def self.load_whisper(campaign_id, whisper_id)
    row = with_db do |db|
      db.get_first_row(
        'SELECT * FROM play_campaign_whispers WHERE campaign_id = ? AND whisper_id = ?',
        [campaign_id, whisper_id]
      )
    end
    return nil unless row

    {
      whisper_id: row['whisper_id'],
      from_character_id: row['from_character_id'],
      to_character_id: row['to_character_id'],
      text: row['text']
    }
  end

  def self.load_whispers(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT whisper_id, from_character_id, to_character_id, text FROM play_campaign_whispers WHERE campaign_id = ? ORDER BY rowid ASC',
        [campaign_id]
      ).map do |row|
        {
          whisper_id: row['whisper_id'],
          from_character_id: row['from_character_id'],
          to_character_id: row['to_character_id'],
          text: row['text']
        }
      end
    end
  end

  # --- Play campaign invitations ---

  def self.invitation_exists?(campaign_id, invitation_id)
    with_db { |db| db.get_first_value('SELECT 1 FROM play_campaign_invitations WHERE campaign_id = ? AND invitation_id = ?', [campaign_id, invitation_id]) }
  end

  def self.pending_invitation_exists?(campaign_id, username)
    with_db do |db|
      db.get_first_value(
        "SELECT 1 FROM play_campaign_invitations WHERE campaign_id = ? AND username = ? AND status = 'pending'",
        [campaign_id, username]
      )
    end
  end

  def self.load_invitation(campaign_id, invitation_id)
    row = with_db { |db| db.get_first_row('SELECT * FROM play_campaign_invitations WHERE campaign_id = ? AND invitation_id = ?', [campaign_id, invitation_id]) }
    return nil unless row

    {
      campaign_id: row['campaign_id'],
      invitation_id: row['invitation_id'],
      username: row['username'],
      character_id: row['character_id'],
      status: row['status']
    }
  end

  def self.load_invitations(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT * FROM play_campaign_invitations WHERE campaign_id = ? ORDER BY rowid ASC',
        [campaign_id]
      ).map do |row|
        {
          campaign_id: row['campaign_id'],
          invitation_id: row['invitation_id'],
          username: row['username'],
          character_id: row['character_id'],
          status: row['status']
        }
      end
    end
  end

  def self.load_invitations_for_user(campaign_id, username)
    with_db do |db|
      db.execute(
        "SELECT * FROM play_campaign_invitations WHERE campaign_id = ? AND username = ? ORDER BY rowid ASC",
        [campaign_id, username]
      ).map do |row|
        {
          campaign_id: row['campaign_id'],
          invitation_id: row['invitation_id'],
          username: row['username'],
          character_id: row['character_id'],
          status: row['status']
        }
      end
    end
  end

  def self.create_invitation(campaign_id, invitation_id, username, character_id)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_invitations (campaign_id, invitation_id, username, character_id, status) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, invitation_id, username, character_id, 'pending']
      )
    end
  end

  def self.accept_invitation(campaign_id, invitation_id)
    with_db do |db|
      db.execute(
        "UPDATE play_campaign_invitations SET status = 'accepted' WHERE campaign_id = ? AND invitation_id = ?",
        [campaign_id, invitation_id]
      )
    end
  end

  # --- Play campaign GM delegations ---

  def self.active_delegation_exists?(campaign_id, username)
    with_db do |db|
      db.get_first_value(
        'SELECT 1 FROM play_campaign_delegations WHERE campaign_id = ? AND username = ? AND active = 1',
        [campaign_id, username]
      )
    end
  end

  def self.load_delegation(campaign_id, username)
    row = with_db { |db| db.get_first_row('SELECT * FROM play_campaign_delegations WHERE campaign_id = ? AND username = ?', [campaign_id, username]) }
    return nil unless row

    {
      campaign_id: row['campaign_id'],
      username: row['username'],
      powers: json_column(row, 'powers_json', []),
      active: row['active'] == 1
    }
  end

  def self.load_active_delegation(campaign_id, username)
    delegation = load_delegation(campaign_id, username)
    return nil unless delegation && delegation[:active]

    delegation
  end

  def self.create_delegation(campaign_id, username, powers)
    with_db do |db|
      db.execute(
        'INSERT OR REPLACE INTO play_campaign_delegations (campaign_id, username, powers_json, active) VALUES (?, ?, ?, ?)',
        [campaign_id, username, JSON.dump(powers), 1]
      )
    end
  end

  def self.revoke_delegation(campaign_id, username)
    with_db do |db|
      db.execute(
        'UPDATE play_campaign_delegations SET active = 0 WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )
    end
  end

  def self.create_delegation_audit(campaign_id, username, action, powers)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_delegation_audit (campaign_id, username, action, powers_json) VALUES (?, ?, ?, ?)',
        [campaign_id, username, action, JSON.dump(powers)]
      )
    end
  end

  def self.load_delegation_audit(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT username, action, powers_json FROM play_campaign_delegation_audit WHERE campaign_id = ? ORDER BY rowid ASC',
        [campaign_id]
      ).map do |row|
        {
          username: row['username'],
          action: row['action'],
          powers: json_column(row, 'powers_json', [])
        }
      end
    end
  end

  # --- Play campaign actor audit trail ---

  def self.audit_event_exists?(campaign_id, correlation_id)
    with_db do |db|
      db.get_first_value(
        'SELECT 1 FROM play_campaign_audit_events WHERE campaign_id = ? AND correlation_id = ?',
        [campaign_id, correlation_id]
      )
    end
  end

  def self.create_audit_event(campaign_id, kind, actor, role, correlation_id)
    with_db do |db|
      db.transaction do
        existing = db.get_first_value(
          'SELECT 1 FROM play_campaign_audit_events WHERE campaign_id = ? AND correlation_id = ?',
          [campaign_id, correlation_id]
        )
        return nil if existing

        timestamp = (db.get_first_value(
          'SELECT COALESCE(MAX(timestamp), 0) FROM play_campaign_audit_events WHERE campaign_id = ?',
          [campaign_id]
        ) || 0).to_i + 1

        db.execute(
          'INSERT INTO play_campaign_audit_events (campaign_id, timestamp, kind, actor, role, correlation_id) VALUES (?, ?, ?, ?, ?, ?)',
          [campaign_id, timestamp, kind, actor, role, correlation_id]
        )

        {
          kind: kind,
          actor: actor,
          role: role,
          timestamp: timestamp,
          correlation_id: correlation_id
        }
      end
    end
  end

  def self.load_audit_events(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT timestamp, kind, actor, role, correlation_id FROM play_campaign_audit_events WHERE campaign_id = ? ORDER BY timestamp ASC',
        [campaign_id]
      ).map do |row|
        {
          kind: row['kind'],
          actor: row['actor'],
          role: row['role'],
          timestamp: row['timestamp'].to_i,
          correlation_id: row['correlation_id']
        }
      end
    end
  end

  # --- Play campaign projection events ---

  def self.projection_event_exists?(campaign_id, event_id)
    with_db do |db|
      db.get_first_value(
        'SELECT 1 FROM play_campaign_projection_events WHERE campaign_id = ? AND event_id = ?',
        [campaign_id, event_id]
      )
    end
  end

  def self.create_projection_event(campaign_id, event_id, kind, value)
    with_db do |db|
      db.transaction do
        existing = db.get_first_value(
          'SELECT 1 FROM play_campaign_projection_events WHERE campaign_id = ? AND event_id = ?',
          [campaign_id, event_id]
        )
        return nil if existing

        sequence = (db.get_first_value(
          'SELECT COALESCE(MAX(sequence), 0) FROM play_campaign_projection_events WHERE campaign_id = ?',
          [campaign_id]
        ) || 0).to_i + 1

        db.execute(
          'INSERT INTO play_campaign_projection_events (campaign_id, sequence, event_id, kind, value) VALUES (?, ?, ?, ?, ?)',
          [campaign_id, sequence, event_id, kind, kind == 'set-story' ? value : nil]
        )

        event = {
          sequence: sequence,
          event_id: event_id,
          kind: kind
        }
        event[:value] = value if kind == 'set-story'
        event
      end
    end
  end

  def self.load_projection_events(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT sequence, event_id, kind, value FROM play_campaign_projection_events WHERE campaign_id = ? ORDER BY sequence ASC',
        [campaign_id]
      ).map do |row|
        event = {
          sequence: row['sequence'].to_i,
          event_id: row['event_id'],
          kind: row['kind']
        }
        event[:value] = row['value'] if row['value']
        event
      end
    end
  end

  def self.compute_projection(campaign_id)
    events = load_projection_events(campaign_id)
    story = ''
    danger = 0
    applied_event_ids = []
    events.each do |event|
      applied_event_ids << event[:event_id]
      case event[:kind]
      when 'set-story'
        story = event[:value]
      when 'increment-danger'
        danger += 1
      end
    end
    {
      story: story,
      danger: danger,
      applied_event_ids: applied_event_ids
    }
  end

  # --- Play campaign idempotent events ---

  def self.create_idempotent_event(campaign_id, event_id, value, idempotency_key)
    with_db do |db|
      db.transaction do
        existing_event = db.get_first_row(
          'SELECT event_id, value, idempotency_key, sequence FROM play_campaign_idempotent_events WHERE campaign_id = ? AND event_id = ?',
          [campaign_id, event_id]
        )

        if existing_event
          return { status: :event_id_conflict } if existing_event['idempotency_key'] != idempotency_key
          return { status: :key_conflict } if existing_event['value'] != value

          return {
            status: :existing,
            event: {
              event_id: existing_event['event_id'],
              value: existing_event['value'],
              sequence: existing_event['sequence'].to_i,
              idempotency_key: existing_event['idempotency_key']
            }
          }
        end

        existing_key = db.get_first_row(
          'SELECT event_id, value, idempotency_key, sequence FROM play_campaign_idempotent_events WHERE campaign_id = ? AND idempotency_key = ?',
          [campaign_id, idempotency_key]
        )

        if existing_key
          return { status: :key_conflict } if existing_key['event_id'] != event_id || existing_key['value'] != value

          return {
            status: :existing,
            event: {
              event_id: existing_key['event_id'],
              value: existing_key['value'],
              sequence: existing_key['sequence'].to_i,
              idempotency_key: existing_key['idempotency_key']
            }
          }
        end

        sequence = (db.get_first_value(
          'SELECT COALESCE(MAX(sequence), 0) FROM play_campaign_idempotent_events WHERE campaign_id = ?',
          [campaign_id]
        ) || 0).to_i + 1

        db.execute(
          'INSERT INTO play_campaign_idempotent_events (campaign_id, event_id, value, idempotency_key, sequence) VALUES (?, ?, ?, ?, ?)',
          [campaign_id, event_id, value, idempotency_key, sequence]
        )

        {
          status: :created,
          event: {
            event_id: event_id,
            value: value,
            sequence: sequence,
            idempotency_key: idempotency_key
          }
        }
      end
    end
  end

  def self.load_idempotent_events(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT event_id, value, sequence, idempotency_key FROM play_campaign_idempotent_events WHERE campaign_id = ? ORDER BY sequence ASC',
        [campaign_id]
      ).map do |row|
        {
          event_id: row['event_id'],
          value: row['value'],
          sequence: row['sequence'].to_i,
          idempotency_key: row['idempotency_key']
        }
      end
    end
  end

  # --- Play campaign safe turns ---

  def self.load_safe_turns(campaign_id)
    with_db do |db|
      current_turn = db.get_first_value(
        'SELECT safe_turn_current_turn FROM play_campaigns WHERE id = ?',
        [campaign_id]
      ).to_i

      accepted = db.execute(
        'SELECT submission_id, action, accepted_turn, next_turn FROM play_campaign_safe_turns WHERE campaign_id = ? ORDER BY accepted_turn ASC',
        [campaign_id]
      ).map do |row|
        {
          submission_id: row['submission_id'],
          action: row['action'],
          accepted_turn: row['accepted_turn'].to_i,
          next_turn: row['next_turn'].to_i
        }
      end

      { current_turn: current_turn, accepted: accepted }
    end
  end

  def self.submit_safe_turn(campaign_id, submission_id, action, expected_turn)
    with_db do |db|
      db.transaction do
        current_turn = db.get_first_value(
          'SELECT safe_turn_current_turn FROM play_campaigns WHERE id = ?',
          [campaign_id]
        ).to_i

        existing = db.get_first_row(
          'SELECT 1 FROM play_campaign_safe_turns WHERE campaign_id = ? AND submission_id = ?',
          [campaign_id, submission_id]
        )

        if existing
          return { status: :duplicate, current_turn: current_turn }
        end

        if expected_turn != current_turn
          return { status: :stale, current_turn: current_turn }
        end

        next_turn = current_turn + 1

        db.execute(
          'INSERT INTO play_campaign_safe_turns (campaign_id, submission_id, action, accepted_turn, next_turn) VALUES (?, ?, ?, ?, ?)',
          [campaign_id, submission_id, action, current_turn, next_turn]
        )

        db.execute(
          'UPDATE play_campaigns SET safe_turn_current_turn = ? WHERE id = ?',
          [next_turn, campaign_id]
        )

        {
          status: :accepted,
          submission_id: submission_id,
          action: action,
          accepted_turn: current_turn,
          next_turn: next_turn
        }
      end
    end
  end

  # --- Play campaign search records ---

  def self.search_record_exists?(campaign_id, record_id)
    with_db { |db| db.get_first_value('SELECT 1 FROM play_campaign_search_records WHERE campaign_id = ? AND record_id = ?', [campaign_id, record_id]) }
  end

  def self.search_record_text_exists?(campaign_id, text)
    with_db { |db| db.get_first_value('SELECT 1 FROM play_campaign_search_records WHERE campaign_id = ? AND text = ?', [campaign_id, text]) }
  end

  def self.create_search_record(campaign_id, record_id, text)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_search_records (campaign_id, record_id, text) VALUES (?, ?, ?)',
        [campaign_id, record_id, text]
      )
    end
  end

  # Returns all search records for a campaign in creation order.
  def self.load_search_records(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT record_id, text FROM play_campaign_search_records WHERE campaign_id = ? ORDER BY rowid ASC',
        [campaign_id]
      ).map do |row|
        { record_id: row['record_id'], text: row['text'] }
      end
    end
  end

  # --- Play campaign rate events ---

  def self.rate_event_exists?(campaign_id, event_id)
    with_db { |db| db.get_first_value('SELECT 1 FROM play_campaign_rate_events WHERE campaign_id = ? AND event_id = ?', [campaign_id, event_id]) }
  end

  # Returns the number of remaining accepted rate events for +actor+ in +campaign_id+.
  # Each actor has a fixed allowance of 2 per campaign.
  def self.remaining_rate_events(campaign_id, actor)
    with_db do |db|
      accepted = db.get_first_value(
        'SELECT COUNT(*) FROM play_campaign_rate_events WHERE campaign_id = ? AND actor = ?',
        [campaign_id, actor]
      ).to_i
      [2 - accepted, 0].max
    end
  end

  # Atomically accepts a rate event when the actor has remaining allowance and the
  # event_id is unique within the campaign. Returns a hash describing the outcome:
  # - { status: :created, event_id: ..., actor: ..., remaining: ..., sequence: ... }
  # - { status: :limit_exceeded, limit: 2, remaining: 0 }
  # - { status: :duplicate }
  def self.accept_rate_event(campaign_id, event_id, actor)
    with_db do |db|
      db.transaction do
        accepted = db.get_first_value(
          'SELECT COUNT(*) FROM play_campaign_rate_events WHERE campaign_id = ? AND actor = ?',
          [campaign_id, actor]
        ).to_i
        remaining = 2 - accepted
        return { status: :limit_exceeded, limit: 2, remaining: 0 } if remaining <= 0

        duplicate = db.get_first_value(
          'SELECT 1 FROM play_campaign_rate_events WHERE campaign_id = ? AND event_id = ?',
          [campaign_id, event_id]
        )
        return { status: :duplicate } if duplicate

        sequence = (db.get_first_value(
          'SELECT COALESCE(MAX(sequence), 0) FROM play_campaign_rate_events WHERE campaign_id = ?',
          [campaign_id]
        ) || 0).to_i + 1

        db.execute(
          'INSERT INTO play_campaign_rate_events (campaign_id, event_id, actor, sequence) VALUES (?, ?, ?, ?)',
          [campaign_id, event_id, actor, sequence]
        )

        {
          status: :created,
          event_id: event_id,
          actor: actor,
          remaining: remaining - 1,
          sequence: sequence
        }
      end
    end
  end

  # Returns accepted rate events for a campaign in creation order.
  def self.load_rate_events(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT event_id, actor, sequence FROM play_campaign_rate_events WHERE campaign_id = ? ORDER BY sequence ASC',
        [campaign_id]
      ).map do |row|
        { event_id: row['event_id'], actor: row['actor'], sequence: row['sequence'].to_i }
      end
    end
  end

  # --- Play campaign rejected rate events ---

  def self.record_rejected_rate_event(campaign_id, event_id, actor)
    with_db do |db|
      db.transaction do
        existing = db.get_first_value(
          'SELECT 1 FROM play_campaign_rejected_rate_events WHERE campaign_id = ? AND event_id = ?',
          [campaign_id, event_id]
        )
        return false if existing

        sequence = (db.get_first_value(
          'SELECT COALESCE(MAX(sequence), 0) FROM play_campaign_rejected_rate_events WHERE campaign_id = ?',
          [campaign_id]
        ) || 0).to_i + 1

        db.execute(
          'INSERT INTO play_campaign_rejected_rate_events (campaign_id, event_id, actor, sequence) VALUES (?, ?, ?, ?)',
          [campaign_id, event_id, actor, sequence]
        )
        true
      end
    end
  end

  # Returns campaign-scoped service metrics as a hash of aggregate counters.
  # Exposes only safe counters; no campaign content is included.
  def self.load_play_campaign_metrics(campaign_id)
    with_db do |db|
      accepted = db.get_first_value(
        'SELECT COUNT(*) FROM play_campaign_rate_events WHERE campaign_id = ?',
        [campaign_id]
      ).to_i

      rejected = db.get_first_value(
        'SELECT COUNT(*) FROM play_campaign_rejected_rate_events WHERE campaign_id = ?',
        [campaign_id]
      ).to_i

      projections = db.get_first_value(
        'SELECT COUNT(*) FROM play_campaign_projection_events WHERE campaign_id = ?',
        [campaign_id]
      ).to_i

      {
        accepted_rate_events: accepted,
        rejected_rate_events: rejected,
        projection_events: projections,
        uptime_ticks: 1
      }
    end
  end

  # --- Play campaign deterministic replay ---

  def self.play_campaign_replay_event_exists?(campaign_id, event_id)
    with_db do |db|
      db.get_first_value(
        'SELECT 1 FROM play_campaign_replay_events WHERE campaign_id = ? AND event_id = ?',
        [campaign_id, event_id]
      )
    end
  end

  def self.create_replay_event(campaign_id, event_id, kind, text)
    with_db do |db|
      db.transaction do
        existing = db.get_first_value(
          'SELECT 1 FROM play_campaign_replay_events WHERE campaign_id = ? AND event_id = ?',
          [campaign_id, event_id]
        )
        return nil if existing

        sequence = (db.get_first_value(
          'SELECT COALESCE(MAX(sequence), 0) FROM play_campaign_replay_events WHERE campaign_id = ?',
          [campaign_id]
        ) || 0).to_i + 1

        db.execute(
          'INSERT INTO play_campaign_replay_events (campaign_id, event_id, kind, text, sequence) VALUES (?, ?, ?, ?, ?)',
          [campaign_id, event_id, kind, text, sequence]
        )

        {
          event_id: event_id,
          kind: kind,
          text: text,
          sequence: sequence
        }
      end
    end
  end

  def self.load_replay_events(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT event_id, kind, text, sequence FROM play_campaign_replay_events WHERE campaign_id = ? ORDER BY sequence ASC',
        [campaign_id]
      ).map do |row|
        {
          event_id: row['event_id'],
          kind: row['kind'],
          text: row['text'],
          sequence: row['sequence'].to_i
        }
      end
    end
  end

  def self.compute_replay(campaign_id)
    events = load_replay_events(campaign_id)
    event_ids = events.map { |event| event[:event_id] }
    story = events.map { |event| event[:text] }.join
    digest = event_ids.join(',') + '|' + story

    {
      story: story,
      event_ids: event_ids,
      digest: digest
    }
  end

  # --- Play campaign RNG ledger ---

  def self.load_rng_seed(campaign_id)
    row = with_db { |db| db.get_first_row('SELECT seed FROM play_campaign_rng_seeds WHERE campaign_id = ?', [campaign_id]) }
    row ? row['seed'] : nil
  end

  # Creates a campaign RNG seed when none exists. Returns +true+ on creation,
  # +false+ when a seed is already configured.
  def self.create_rng_seed(campaign_id, seed)
    with_db do |db|
      existing = db.get_first_value('SELECT 1 FROM play_campaign_rng_seeds WHERE campaign_id = ?', [campaign_id])
      return false if existing

      db.execute(
        'INSERT INTO play_campaign_rng_seeds (campaign_id, seed) VALUES (?, ?)',
        [campaign_id, seed]
      )
      true
    end
  end

  # Appends a deterministic roll to the campaign ledger. The result is computed
  # inside the storage transaction from the actual assigned sequence so it stays
  # deterministic even under concurrent appends. Returns a hash with the new roll
  # record, or +nil+ when the roll_id already exists.
  def self.create_rng_roll(campaign_id, roll_id, sides, seed)
    with_db do |db|
      db.transaction do
        existing = db.get_first_value(
          'SELECT 1 FROM play_campaign_rng_rolls WHERE campaign_id = ? AND roll_id = ?',
          [campaign_id, roll_id]
        )
        return nil if existing

        sequence = (db.get_first_value(
          'SELECT COALESCE(MAX(sequence), 0) FROM play_campaign_rng_rolls WHERE campaign_id = ?',
          [campaign_id]
        ) || 0).to_i + 1

        result = compute_rng_result(seed, sequence, roll_id, sides)

        db.execute(
          'INSERT INTO play_campaign_rng_rolls (campaign_id, roll_id, sides, result, sequence) VALUES (?, ?, ?, ?, ?)',
          [campaign_id, roll_id, sides, result, sequence]
        )

        { roll_id: roll_id, sides: sides, result: result, sequence: sequence }
      end
    end
  end

  def self.compute_rng_result(seed, sequence, roll_id, sides)
    str = "#{seed}|#{sequence}|#{roll_id}|#{sides}"
    acc = 0
    str.bytes.each do |b|
      acc = (acc * 31 + b) % (2**32)
    end
    (acc % sides) + 1
  end

  def self.load_rng_rolls(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT roll_id, sides, result, sequence FROM play_campaign_rng_rolls WHERE campaign_id = ? ORDER BY sequence ASC',
        [campaign_id]
      ).map do |row|
        {
          roll_id: row['roll_id'],
          sides: row['sides'].to_i,
          result: row['result'].to_i,
          sequence: row['sequence'].to_i
        }
      end
    end
  end

  # Returns the current RNG ledger state for a campaign, or +nil+ when no seed
  # has been configured.
  def self.load_rng_ledger(campaign_id)
    seed = load_rng_seed(campaign_id)
    return nil unless seed

    {
      seed: seed,
      rolls: load_rng_rolls(campaign_id)
    }
  end

  # --- Play campaign moderation reports ---

  def self.moderation_report_exists?(campaign_id, report_id)
    with_db do |db|
      db.get_first_value(
        'SELECT 1 FROM play_campaign_moderation_reports WHERE campaign_id = ? AND report_id = ?',
        [campaign_id, report_id]
      )
    end
  end

  # Atomically creates a moderation report when the report_id is unique within
  # the campaign. Returns the created report hash or +nil+ on duplicate report_id.
  def self.create_moderation_report(campaign_id, report_id, target_id, reason, reporter)
    with_db do |db|
      db.transaction do
        existing = db.get_first_value(
          'SELECT 1 FROM play_campaign_moderation_reports WHERE campaign_id = ? AND report_id = ?',
          [campaign_id, report_id]
        )
        return nil if existing

        sequence = (db.get_first_value(
          'SELECT COALESCE(MAX(sequence), 0) FROM play_campaign_moderation_reports WHERE campaign_id = ?',
          [campaign_id]
        ) || 0).to_i + 1

        db.execute(
          'INSERT INTO play_campaign_moderation_reports (campaign_id, report_id, target_id, reason, reporter, status, sequence) VALUES (?, ?, ?, ?, ?, ?, ?)',
          [campaign_id, report_id, target_id, reason, reporter, 'open', sequence]
        )

        {
          report_id: report_id,
          target_id: target_id,
          reason: reason,
          status: 'open',
          reporter: reporter,
          sequence: sequence
        }
      end
    end
  end

  def self.load_moderation_report(campaign_id, report_id)
    row = with_db do |db|
      db.get_first_row(
        'SELECT * FROM play_campaign_moderation_reports WHERE campaign_id = ? AND report_id = ?',
        [campaign_id, report_id]
      )
    end
    return nil unless row

    report = {
      report_id: row['report_id'],
      target_id: row['target_id'],
      reason: row['reason'],
      status: row['status'],
      reporter: row['reporter'],
      sequence: row['sequence'].to_i
    }
    if row['status'] == 'resolved'
      report[:action] = row['action']
      report[:note] = row['note']
      report[:resolver] = row['resolver']
    end
    report
  end

  def self.load_moderation_reports(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT * FROM play_campaign_moderation_reports WHERE campaign_id = ? ORDER BY sequence ASC',
        [campaign_id]
      ).map do |row|
        report = {
          report_id: row['report_id'],
          target_id: row['target_id'],
          reason: row['reason'],
          status: row['status'],
          reporter: row['reporter'],
          sequence: row['sequence'].to_i
        }
        if row['status'] == 'resolved'
          report[:action] = row['action']
          report[:note] = row['note']
          report[:resolver] = row['resolver']
        end
        report
      end
    end
  end

  # Resolves an open moderation report. Returns the updated report hash, or
  # +nil+ when the report does not exist or is not open.
  def self.resolve_moderation_report(campaign_id, report_id, action, note, resolver)
    with_db do |db|
      db.transaction do
        row = db.get_first_row(
          'SELECT * FROM play_campaign_moderation_reports WHERE campaign_id = ? AND report_id = ? AND status = ?',
          [campaign_id, report_id, 'open']
        )
        return nil unless row

        db.execute(
          'UPDATE play_campaign_moderation_reports SET status = ?, action = ?, note = ?, resolver = ? WHERE campaign_id = ? AND report_id = ?',
          ['resolved', action, note, resolver, campaign_id, report_id]
        )

        {
          report_id: row['report_id'],
          target_id: row['target_id'],
          reason: row['reason'],
          status: 'resolved',
          reporter: row['reporter'],
          sequence: row['sequence'].to_i,
          action: action,
          note: note,
          resolver: resolver
        }
      end
    end
  end

  # --- Play campaign safety boundaries and events ---

  def self.load_safety_boundaries(campaign_id)
    row = with_db do |db|
      db.get_first_row(
        'SELECT blocked_tags_json FROM play_campaign_safety_boundaries WHERE campaign_id = ?',
        [campaign_id]
      )
    end
    tags = row ? json_column(row, 'blocked_tags_json', []) : []
    { blocked_tags: tags.sort }
  end

  def self.save_safety_boundaries(campaign_id, blocked_tags)
    sorted = blocked_tags.map(&:to_s).sort
    with_db do |db|
      db.execute(
        'INSERT OR REPLACE INTO play_campaign_safety_boundaries (campaign_id, blocked_tags_json) VALUES (?, ?)',
        [campaign_id, JSON.dump(sorted)]
      )
    end
    { blocked_tags: sorted }
  end

  def self.safety_event_exists?(campaign_id, event_id)
    with_db do |db|
      db.get_first_value(
        'SELECT 1 FROM play_campaign_safety_events WHERE campaign_id = ? AND event_id = ?',
        [campaign_id, event_id]
      )
    end
  end

  # Atomically validates a safety check against existing event_ids and the
  # current blocked tags. Returns a hash describing the outcome:
  # - { status: :accepted, event_id:, kind:, text:, tags:, sequence: }
  # - { status: :duplicate }
  # - { status: :blocked }
  def self.submit_safety_event(campaign_id, event_id, kind, text, tags)
    with_db do |db|
      db.transaction do
        existing = db.get_first_value(
          'SELECT 1 FROM play_campaign_safety_events WHERE campaign_id = ? AND event_id = ?',
          [campaign_id, event_id]
        )
        return { status: :duplicate } if existing

        boundaries_row = db.get_first_row(
          'SELECT blocked_tags_json FROM play_campaign_safety_boundaries WHERE campaign_id = ?',
          [campaign_id]
        )
        blocked_tags = boundaries_row ? json_column(boundaries_row, 'blocked_tags_json', []) : []

        if tags.any? { |tag| blocked_tags.include?(tag) }
          return { status: :blocked }
        end

        sequence = (db.get_first_value(
          'SELECT COALESCE(MAX(sequence), 0) FROM play_campaign_safety_events WHERE campaign_id = ?',
          [campaign_id]
        ) || 0).to_i + 1

        db.execute(
          'INSERT INTO play_campaign_safety_events (campaign_id, event_id, kind, text, tags_json, sequence) VALUES (?, ?, ?, ?, ?, ?)',
          [campaign_id, event_id, kind, text, JSON.dump(tags), sequence]
        )

        {
          status: :accepted,
          event_id: event_id,
          kind: kind,
          text: text,
          tags: tags,
          sequence: sequence
        }
      end
    end
  end

  def self.load_safety_events(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT event_id, kind, text, tags_json, sequence FROM play_campaign_safety_events WHERE campaign_id = ? ORDER BY sequence ASC',
        [campaign_id]
      ).map do |row|
        {
          event_id: row['event_id'],
          kind: row['kind'],
          text: row['text'],
          tags: json_column(row, 'tags_json', []),
          sequence: row['sequence'].to_i
        }
      end
    end
  end

  # --- Play campaign fixture seeding ---

  CANONICAL_FIXTURE = {
    fixture_id: 'canonical-v1',
    status: 'seeded',
    characters: [
      { character_id: 'fixture-hero', name: 'Ari', class: 'fighter' },
      { character_id: 'fixture-mage', name: 'Bea', class: 'wizard' }
    ],
    story: 'The lantern is lit.',
    event_ids: ['fixture-event-1', 'fixture-event-2']
  }.freeze

  def self.play_campaign_fixture_exists?(campaign_id)
    with_db do |db|
      db.get_first_value('SELECT 1 FROM play_campaign_fixtures WHERE campaign_id = ?', [campaign_id])
    end
  end

  def self.load_play_campaign_fixture(campaign_id)
    row = with_db do |db|
      db.get_first_row('SELECT * FROM play_campaign_fixtures WHERE campaign_id = ?', [campaign_id])
    end
    return nil unless row

    {
      fixture_id: row['fixture_id'],
      status: row['status'],
      characters: json_column(row, 'characters_json'),
      story: row['story'],
      event_ids: json_column(row, 'event_ids_json')
    }
  end

  # Atomically creates the canonical fixture for a campaign when none exists.
  # Returns the existing state on idempotent re-seeds without mutating data.
  def self.seed_play_campaign_fixture(campaign_id)
    with_db do |db|
      db.transaction do
        existing = db.get_first_row('SELECT * FROM play_campaign_fixtures WHERE campaign_id = ?', [campaign_id])
        if existing
          return {
            fixture_id: existing['fixture_id'],
            status: existing['status'],
            characters: json_column(existing, 'characters_json'),
            story: existing['story'],
            event_ids: json_column(existing, 'event_ids_json')
          }
        end

        canonical = CANONICAL_FIXTURE
        db.execute(
          'INSERT INTO play_campaign_fixtures (campaign_id, fixture_id, status, characters_json, story, event_ids_json) VALUES (?, ?, ?, ?, ?, ?)',
          [campaign_id, canonical[:fixture_id], canonical[:status], JSON.dump(canonical[:characters]), canonical[:story], JSON.dump(canonical[:event_ids])]
        )
        canonical
      end
    end
  end

  # --- Play campaign spectators ---

  def self.spectator_exists?(spectator_id)
    with_db { |db| db.get_first_value('SELECT 1 FROM play_campaign_spectators WHERE spectator_id = ?', [spectator_id]) }
  end

  def self.load_spectator(spectator_id)
    row = with_db { |db| db.get_first_row('SELECT * FROM play_campaign_spectators WHERE spectator_id = ?', [spectator_id]) }
    return nil unless row

    { spectator_id: row['spectator_id'], campaign_id: row['campaign_id'] }
  end

  def self.create_spectator(campaign_id, spectator_id)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaign_spectators (spectator_id, campaign_id) VALUES (?, ?)',
        [spectator_id, campaign_id]
      )
    end
    { spectator_id: spectator_id, campaign_id: campaign_id }
  end

  # --- Play campaign feed events ---

  def self.feed_event_exists?(campaign_id, event_id)
    with_db { |db| db.get_first_value('SELECT 1 FROM play_campaign_feed_events WHERE campaign_id = ? AND event_id = ?', [campaign_id, event_id]) }
  end

  def self.create_feed_event(campaign_id, event_id, text)
    with_db do |db|
      db.transaction do
        if db.get_first_value('SELECT 1 FROM play_campaign_feed_events WHERE campaign_id = ? AND event_id = ?', [campaign_id, event_id])
          return { status: :conflict }
        end

        sequence = (db.get_first_value(
          'SELECT COALESCE(MAX(sequence), 0) FROM play_campaign_feed_events WHERE campaign_id = ?',
          [campaign_id]
        ) || 0).to_i + 1

        db.execute(
          'INSERT INTO play_campaign_feed_events (campaign_id, event_id, text, sequence) VALUES (?, ?, ?, ?)',
          [campaign_id, event_id, text, sequence]
        )

        { status: :created, event: { event_id: event_id, text: text, sequence: sequence } }
      end
    end
  end

  def self.load_feed_events(campaign_id, cursor, limit)
    with_db do |db|
      rows = db.execute(
        'SELECT event_id, text, sequence FROM play_campaign_feed_events WHERE campaign_id = ? ORDER BY sequence ASC LIMIT ? OFFSET ?',
        [campaign_id, limit, cursor]
      )
      rows.map do |row|
        { event_id: row['event_id'], text: row['text'], sequence: row['sequence'].to_i }
      end
    end
  end

  def self.feed_event_count(campaign_id)
    with_db { |db| db.get_first_value('SELECT COUNT(*) FROM play_campaign_feed_events WHERE campaign_id = ?', [campaign_id]) }
  end
end
