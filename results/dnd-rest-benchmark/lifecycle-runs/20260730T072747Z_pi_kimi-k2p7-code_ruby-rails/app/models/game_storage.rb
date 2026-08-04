require 'json'
require 'sqlite3'

# Shared SQLite3 persistence layer for the D&D REST API.
#
# This module intentionally bypasses Active Record and uses raw SQL. The API
# stores small, mostly JSON-shaped records (combat sessions, compendium
# entries, campaigns) so SQLite3 is used directly for simplicity and
# determinism. All database writes are serialized through a Mutex because the
# Puma worker may run multiple threads and SQLite3 is compiled without full
# write concurrency by default.
module GameStorage
  DB_PATH = 'game.db'.freeze
  SCHEMA_VERSION = 1

  # Process-global maintenance switch. Not persisted; each server process starts
  # in non-maintenance mode. Guarded by a mutex because Puma may run multiple
  # request threads in the same process.
  @maintenance = false
  @maintenance_mutex = Mutex.new

  # All tables managed by #reset. Order does not matter because SQLite
  # foreign keys are not enforced by this layer, but keeping the list
  # alphabetical makes it easy to audit against #create_schema.
  TABLES = %w[
    users combat_sessions monsters items campaigns campaign_characters
    campaign_events npcs factions quests inventory crafting_projects
    sessions session_attendance play_campaigns play_campaign_members
    play_campaign_events play_campaign_feed_events play_campaign_factions play_campaign_documents
    play_campaign_downtime_activities play_campaign_downtime_allocations
    play_campaign_scenes play_campaign_locations play_campaign_location_connections
    play_campaign_encounters play_campaign_npc_dialogue play_campaign_npcs play_campaign_quests
    play_campaign_reputation play_campaign_spells play_campaign_casts play_campaign_inventory_items
    play_campaign_equipment play_campaign_exports play_campaign_imports play_campaign_loot play_campaign_loot_votes
    play_campaign_migrations
    play_campaign_currency_transfers play_campaign_relationships play_campaign_clues
    play_campaign_quest_rewards play_campaign_quests play_campaign_session_zero play_campaign_settlements
    play_campaign_world_events play_campaign_calendars play_campaign_shops
    play_campaign_recipes play_campaign_content
    play_campaign_notes play_campaign_whispers
    play_campaign_invitations
    play_campaign_delegations
    play_campaign_delegation_audit
    play_campaign_audit_events
    play_campaign_backups
    play_campaign_projection_events
    play_campaign_idempotent_events
    play_campaign_safe_turns
    play_campaign_safe_turns_state
    play_campaign_transactional_transfers
    play_campaign_search_records
    play_campaign_rate_events
    play_campaign_replay_events
    play_campaign_spectators
    play_campaign_metrics
    play_campaign_rng_state
    play_campaign_rng_rolls
    play_campaign_moderation_reports
    play_campaign_safety_boundaries
    play_campaign_safety_events
    play_campaign_fixture_seeds
    schema_version
  ].freeze

  class << self
    # Read the current global maintenance mode in a thread-safe way.
    def maintenance?
      @maintenance_mutex.synchronize { @maintenance }
    end

    # Set the global maintenance mode in a thread-safe way.
    def maintenance=(value)
      @maintenance_mutex.synchronize { @maintenance = !!value }
    end

    # Initialize the database on startup. Idempotent: creates tables and records
    # the schema version if they are missing, then adds any columns that were
    # introduced after earlier benchmark stages.
    def init
      db.execute('PRAGMA journal_mode=WAL')
      db.execute('PRAGMA busy_timeout=5000')
      create_schema
      migrate_play_campaigns
      migrate_play_events
      migrate_play_feed_events
      migrate_play_members
      migrate_play_documents
      migrate_play_scenes
      migrate_play_locations
      migrate_play_encounters
      migrate_play_npcs
      migrate_play_npc_dialogue
      migrate_play_casts
      migrate_play_equipment
      migrate_play_currency
      migrate_play_loot
      migrate_play_factions
      migrate_play_relationships
      migrate_play_clues
      migrate_play_quests
      migrate_play_settlements
      migrate_play_world_events
      migrate_play_calendars
      migrate_play_shops
      migrate_play_recipes
      migrate_play_downtime
      migrate_play_session_zero
      migrate_play_content
      migrate_play_invitations
      migrate_play_delegations
      migrate_play_projections
      migrate_play_idempotent_events
      migrate_play_safe_turns
      migrate_play_transactional_transfers
      migrate_play_exports
      migrate_play_imports
      migrate_play_migrations
      migrate_play_rate_events
      migrate_play_replay_events
      migrate_play_spectators
      migrate_play_metrics
      migrate_play_backups
      migrate_rng_ledger
      migrate_play_moderation
      migrate_play_safety_boundaries
      migrate_play_fixture_seeds
    end

    # Recreate all tables from scratch. Used by the storage reset endpoint.
    def reset
      TABLES.each do |table|
        db.execute("DROP TABLE IF EXISTS #{table}")
      end
      create_schema
      self.maintenance = false
    end

    # Return the storage driver and schema version. `initialized` is true only
    # when the expected core tables exist.
    def status
      expected = %w[combat_sessions schema_version users].sort
      actual = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('users', 'combat_sessions', 'schema_version')"
      ).map(&:first).sort

      {
        driver: 'sqlite',
        schema_version: SCHEMA_VERSION,
        initialized: actual == expected
      }
    end

    # Execute a block inside a global mutex. Use for every write and for any
    # read-modify-write sequence to keep the file database consistent under
    # concurrent requests.
    def with_lock
      (@mutex ||= Mutex.new).synchronize { yield }
    end

    # Expose a thread-local SQLite3 connection. Each Puma worker thread gets
    # its own connection so a connection left in a bad state by one thread
    # cannot block or corrupt another. The global #with_lock mutex still
    # serializes all database access to keep application-level
    # read-modify-write sequences safe. New connections inherit the same WAL
    # and busy-timeout settings used during initialization.
    def db
      Thread.current[:game_storage_db] ||= SQLite3::Database.new(DB_PATH).tap do |conn|
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=5000')
      end
    end

    private

    # Add columns to a table only if they do not already exist. Returns the
    # set of columns that existed before the call so callers can run backfills
    # only when a column is newly introduced.
    def ensure_columns(table, columns)
      existing = db.execute("PRAGMA table_info(#{table})").map { |c| c[1] }.to_set
      columns.each do |column, type|
        column_name = column.to_s
        next if existing.include?(column_name)
        db.execute("ALTER TABLE #{table} ADD COLUMN #{column_name} #{type}")
      end
      existing
    end

    def migrate_play_campaigns
      existed = ensure_columns('play_campaigns',
        current_actor: 'TEXT',
        turn_number: 'INTEGER DEFAULT 0',
        nudge_count: 'INTEGER DEFAULT 0',
        turn_deadline: 'INTEGER DEFAULT 0',
        current_scene_id: 'TEXT',
        current_location_id: 'TEXT',
        phase: "TEXT NOT NULL DEFAULT 'exploration'",
        saved_actor: 'TEXT'
      )
      # Backfill legacy rows: when turn_deadline was first added, existing
      # campaigns had no deadline, so derive it from the current turn number.
      unless existed.include?('turn_deadline')
        db.execute('UPDATE play_campaigns SET turn_deadline = turn_number + 1')
      end
    end

    def migrate_play_events
      ensure_columns('play_campaign_events',
        type: 'TEXT',
        next_actor: 'TEXT',
        destination_id: 'TEXT',
        travel_turns: 'INTEGER',
        hp_current: 'INTEGER',
        hp_max: 'INTEGER',
        target: 'TEXT'
      )
    end

    def migrate_play_feed_events
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_feed_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          event_id TEXT NOT NULL,
          text TEXT NOT NULL,
          UNIQUE (campaign_id, event_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_members
      ensure_columns('play_campaign_members',
        hp_current: 'INTEGER DEFAULT 20',
        hp_max: 'INTEGER DEFAULT 20',
        status: "TEXT NOT NULL DEFAULT 'conscious'",
        death_save_successes: 'INTEGER NOT NULL DEFAULT 0',
        death_save_failures: 'INTEGER NOT NULL DEFAULT 0',
        owner: 'TEXT',
        race: 'TEXT',
        background: 'TEXT',
        level: 'INTEGER NOT NULL DEFAULT 1',
        abilities_json: 'TEXT',
        prepared_spells_json: 'TEXT NOT NULL DEFAULT \'[]\'',
        concentration_json: 'TEXT'
      )
    end

    def migrate_play_documents
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_documents (
          campaign_id TEXT PRIMARY KEY,
          story TEXT NOT NULL DEFAULT '',
          dm_notes TEXT NOT NULL DEFAULT '',
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_scenes
      ensure_columns('play_campaigns', current_scene_id: 'TEXT')
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_scenes (
          campaign_id TEXT NOT NULL,
          id TEXT NOT NULL,
          name TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'open',
          PRIMARY KEY (campaign_id, id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_locations
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_locations (
          campaign_id TEXT NOT NULL,
          id TEXT NOT NULL,
          name TEXT NOT NULL,
          PRIMARY KEY (campaign_id, id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_location_connections (
          campaign_id TEXT NOT NULL,
          from_id TEXT NOT NULL,
          to_id TEXT NOT NULL,
          travel_turns INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, from_id, to_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
          FOREIGN KEY (campaign_id, from_id) REFERENCES play_campaign_locations(campaign_id, id) ON DELETE CASCADE,
          FOREIGN KEY (campaign_id, to_id) REFERENCES play_campaign_locations(campaign_id, id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_encounters
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_encounters (
          campaign_id TEXT NOT NULL,
          id TEXT NOT NULL,
          name TEXT NOT NULL,
          status TEXT NOT NULL,
          combatants_json TEXT NOT NULL DEFAULT '[]',
          round INTEGER NOT NULL DEFAULT 1,
          turn_index INTEGER NOT NULL DEFAULT 0,
          conditions_json TEXT NOT NULL DEFAULT '{}',
          order_json TEXT NOT NULL DEFAULT '[]',
          xp_awarded INTEGER,
          loot_json TEXT NOT NULL DEFAULT '[]',
          PRIMARY KEY (campaign_id, id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
      ensure_columns('play_campaign_encounters',
        round: 'INTEGER NOT NULL DEFAULT 1',
        turn_index: 'INTEGER NOT NULL DEFAULT 0'
      )
    end

    def migrate_play_equipment
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_equipment (
          campaign_id TEXT NOT NULL,
          character_id TEXT NOT NULL,
          slot TEXT NOT NULL,
          item_id TEXT NOT NULL,
          attuned INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY (campaign_id, character_id, slot),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_exports
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_exports (
          campaign_id TEXT NOT NULL,
          version INTEGER NOT NULL,
          story TEXT NOT NULL,
          status TEXT NOT NULL,
          PRIMARY KEY (campaign_id, version),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_imports
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_imports (
          campaign_id TEXT PRIMARY KEY,
          version INTEGER NOT NULL,
          story TEXT NOT NULL,
          status TEXT NOT NULL,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_migrations
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_migrations (
          campaign_id TEXT PRIMARY KEY,
          schema_version INTEGER NOT NULL,
          story TEXT NOT NULL,
          campaign_name TEXT NOT NULL,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_casts
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_casts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          character_id TEXT NOT NULL,
          spell_id TEXT NOT NULL,
          target TEXT NOT NULL,
          slot_level INTEGER NOT NULL,
          slots_remaining INTEGER NOT NULL,
          sequence INTEGER NOT NULL,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
      ensure_columns('play_campaign_casts', slots_remaining: 'INTEGER')
      ensure_columns('play_campaign_members', spell_slots_json: 'TEXT')
    end

    def migrate_play_currency
      ensure_columns('play_campaign_members', gold: 'INTEGER NOT NULL DEFAULT 10')
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_currency_transfers (
          campaign_id TEXT NOT NULL,
          transfer_id INTEGER NOT NULL,
          from_character_id TEXT NOT NULL,
          to_character_id TEXT NOT NULL,
          gold INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, transfer_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_npcs
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_npcs (
          campaign_id TEXT NOT NULL,
          npc_id TEXT NOT NULL,
          name TEXT NOT NULL,
          agenda TEXT NOT NULL,
          public_status TEXT NOT NULL,
          PRIMARY KEY (campaign_id, npc_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_npc_dialogue
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_npc_dialogue (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          npc_id TEXT NOT NULL,
          dialogue_id TEXT NOT NULL,
          speaker TEXT NOT NULL,
          text TEXT NOT NULL,
          visibility TEXT NOT NULL,
          UNIQUE (campaign_id, npc_id, dialogue_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_loot
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_loot (
          campaign_id TEXT NOT NULL,
          loot_id TEXT NOT NULL,
          item_id TEXT NOT NULL,
          quantity INTEGER NOT NULL,
          status TEXT NOT NULL DEFAULT 'open',
          recipient_character_id TEXT,
          PRIMARY KEY (campaign_id, loot_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_loot_votes (
          campaign_id TEXT NOT NULL,
          loot_id TEXT NOT NULL,
          voter TEXT NOT NULL,
          recipient_character_id TEXT NOT NULL,
          PRIMARY KEY (campaign_id, loot_id, voter),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
          FOREIGN KEY (campaign_id, loot_id) REFERENCES play_campaign_loot(campaign_id, loot_id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_factions
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_factions (
          campaign_id TEXT NOT NULL,
          faction_id TEXT NOT NULL,
          name TEXT NOT NULL,
          PRIMARY KEY (campaign_id, faction_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_reputation (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          faction_id TEXT NOT NULL,
          character_id TEXT NOT NULL,
          delta INTEGER NOT NULL,
          reputation INTEGER NOT NULL,
          reason TEXT NOT NULL,
          FOREIGN KEY (campaign_id, faction_id) REFERENCES play_campaign_factions(campaign_id, faction_id) ON DELETE CASCADE,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_relationships
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_relationships (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          source_id TEXT NOT NULL,
          target_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          score INTEGER NOT NULL,
          UNIQUE (campaign_id, source_id, target_id, kind),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_clues
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_clues (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          clue_id TEXT NOT NULL,
          text TEXT NOT NULL,
          audience TEXT NOT NULL,
          character_id TEXT,
          UNIQUE (campaign_id, clue_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_world_events
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_world_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          event_id TEXT NOT NULL,
          turn_number INTEGER NOT NULL,
          title TEXT NOT NULL,
          text TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'scheduled',
          resolution_turn INTEGER,
          resolution_text TEXT,
          UNIQUE (campaign_id, event_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_calendars
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_calendars (
          campaign_id TEXT PRIMARY KEY,
          day INTEGER NOT NULL,
          season TEXT NOT NULL,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_shops
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_shops (
          campaign_id TEXT NOT NULL,
          settlement_id TEXT NOT NULL,
          shop_id TEXT NOT NULL,
          name TEXT NOT NULL,
          stock_json TEXT NOT NULL,
          buy_price INTEGER NOT NULL,
          sell_price INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, settlement_id, shop_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
          FOREIGN KEY (campaign_id, settlement_id) REFERENCES play_campaign_settlements(campaign_id, settlement_id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_recipes
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_recipes (
          campaign_id TEXT NOT NULL,
          recipe_id TEXT NOT NULL,
          name TEXT NOT NULL,
          ingredients_json TEXT NOT NULL,
          output_item TEXT NOT NULL,
          output_quantity INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, recipe_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_downtime
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_downtime_activities (
          campaign_id TEXT NOT NULL,
          activity_id TEXT NOT NULL,
          name TEXT NOT NULL,
          cycles_required INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, activity_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_downtime_allocations (
          campaign_id TEXT NOT NULL,
          character_id TEXT NOT NULL,
          activity_id TEXT NOT NULL,
          cycles_completed INTEGER NOT NULL DEFAULT 0,
          completions INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY (campaign_id, character_id, activity_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
          FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE,
          FOREIGN KEY (campaign_id, activity_id) REFERENCES play_campaign_downtime_activities(campaign_id, activity_id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_session_zero
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_session_zero (
          campaign_id TEXT PRIMARY KEY,
          rules TEXT NOT NULL,
          tone TEXT NOT NULL,
          consent_json TEXT NOT NULL,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_content
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_content (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          content_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          text TEXT NOT NULL,
          tags_json TEXT NOT NULL,
          UNIQUE (campaign_id, content_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_invitations
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_invitations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          invitation_id TEXT NOT NULL,
          username TEXT NOT NULL,
          character_id TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',
          UNIQUE (campaign_id, invitation_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
      db.execute(<<-SQL)
        CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_invitations ON play_campaign_invitations(campaign_id, username) WHERE status = 'pending'
      SQL
    end

    def migrate_play_delegations
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_delegations (
          campaign_id TEXT NOT NULL,
          username TEXT NOT NULL,
          powers_json TEXT NOT NULL,
          active INTEGER NOT NULL DEFAULT 1,
          PRIMARY KEY (campaign_id, username),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_delegation_audit (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          username TEXT NOT NULL,
          action TEXT NOT NULL,
          powers_json TEXT NOT NULL,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_projections
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_projection_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          event_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          value TEXT,
          UNIQUE (campaign_id, event_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_idempotent_events
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_idempotent_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          event_id TEXT NOT NULL,
          value TEXT NOT NULL,
          idempotency_key TEXT NOT NULL,
          UNIQUE (campaign_id, idempotency_key),
          UNIQUE (campaign_id, event_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_safe_turns
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_safe_turns_state (
          campaign_id TEXT PRIMARY KEY,
          current_turn INTEGER NOT NULL DEFAULT 1,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_safe_turns (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          submission_id TEXT NOT NULL,
          action TEXT NOT NULL,
          accepted_turn INTEGER NOT NULL,
          next_turn INTEGER NOT NULL,
          UNIQUE (campaign_id, submission_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_rate_events
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_rate_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          event_id TEXT NOT NULL,
          actor TEXT NOT NULL,
          UNIQUE (campaign_id, event_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_replay_events
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_replay_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          event_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          text TEXT NOT NULL,
          UNIQUE (campaign_id, event_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_spectators
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_spectators (
          campaign_id TEXT NOT NULL,
          spectator_id TEXT PRIMARY KEY,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_metrics
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_metrics (
          campaign_id TEXT PRIMARY KEY,
          accepted_rate_events INTEGER NOT NULL DEFAULT 0,
          rejected_rate_events INTEGER NOT NULL DEFAULT 0,
          projection_events INTEGER NOT NULL DEFAULT 0,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_backups
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_backups (
          campaign_id TEXT NOT NULL,
          backup_id TEXT NOT NULL,
          story TEXT NOT NULL,
          status TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, backup_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_rng_ledger
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_rng_state (
          campaign_id TEXT PRIMARY KEY,
          seed TEXT,
          next_sequence INTEGER NOT NULL DEFAULT 1,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_rng_rolls (
          campaign_id TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          roll_id TEXT NOT NULL,
          sides INTEGER NOT NULL,
          result INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, sequence),
          UNIQUE (campaign_id, roll_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_moderation
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_moderation_reports (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          report_id TEXT NOT NULL,
          target_id TEXT NOT NULL,
          reason TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'open',
          reporter TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          action TEXT,
          note TEXT,
          resolver TEXT,
          UNIQUE (campaign_id, report_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_safety_boundaries
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_safety_boundaries (
          campaign_id TEXT PRIMARY KEY,
          blocked_tags_json TEXT NOT NULL DEFAULT '[]',
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_safety_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          event_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          text TEXT NOT NULL,
          tags_json TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          UNIQUE (campaign_id, event_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_fixture_seeds
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_fixture_seeds (
          campaign_id TEXT PRIMARY KEY,
          fixture_id TEXT NOT NULL,
          status TEXT NOT NULL,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_transactional_transfers
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_transactional_transfers (
          campaign_id TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          from_character_id TEXT NOT NULL,
          to_character_id TEXT NOT NULL,
          amount INTEGER NOT NULL,
          from_gold INTEGER NOT NULL,
          to_gold INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, sequence),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_quests
      ensure_columns('play_campaign_quests', rewards_json: 'TEXT')
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_quests (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          quest_id TEXT NOT NULL,
          title TEXT NOT NULL,
          depends_on_json TEXT NOT NULL DEFAULT '[]',
          state TEXT NOT NULL DEFAULT 'locked',
          rewards_json TEXT,
          UNIQUE (campaign_id, quest_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_quest_rewards (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          quest_id TEXT NOT NULL,
          awarded INTEGER NOT NULL DEFAULT 0,
          UNIQUE (campaign_id, quest_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def migrate_play_settlements
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_settlements (
          campaign_id TEXT NOT NULL,
          settlement_id TEXT NOT NULL,
          name TEXT NOT NULL,
          services_json TEXT NOT NULL,
          availability TEXT NOT NULL,
          discovered_by_json TEXT NOT NULL DEFAULT '[]',
          PRIMARY KEY (campaign_id, settlement_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL
    end

    def create_schema
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS users (
          username TEXT PRIMARY KEY,
          password_digest TEXT NOT NULL,
          role TEXT NOT NULL
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS combat_sessions (
          id TEXT PRIMARY KEY,
          round INTEGER NOT NULL,
          turn_index INTEGER NOT NULL,
          order_json TEXT NOT NULL,
          conditions_json TEXT NOT NULL
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS monsters (
          slug TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          cr TEXT NOT NULL,
          armor_class INTEGER NOT NULL,
          hit_points INTEGER NOT NULL,
          tags_json TEXT NOT NULL
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS items (
          slug TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          type TEXT NOT NULL,
          rarity TEXT NOT NULL,
          cost_gp INTEGER NOT NULL
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS campaigns (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          dm TEXT NOT NULL
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS campaign_characters (
          id TEXT PRIMARY KEY,
          campaign_id TEXT NOT NULL,
          name TEXT NOT NULL,
          level INTEGER NOT NULL,
          class TEXT NOT NULL,
          FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS campaign_events (
          id TEXT PRIMARY KEY,
          campaign_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          summary TEXT,
          FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS quests (
          id TEXT PRIMARY KEY,
          campaign_id TEXT NOT NULL,
          title TEXT NOT NULL,
          status TEXT NOT NULL,
          milestones_json TEXT NOT NULL,
          completed_milestones_json TEXT NOT NULL DEFAULT '[]',
          FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS factions (
          id TEXT PRIMARY KEY,
          campaign_id TEXT NOT NULL,
          name TEXT NOT NULL,
          stance TEXT NOT NULL,
          FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS npcs (
          id TEXT PRIMARY KEY,
          campaign_id TEXT NOT NULL,
          name TEXT NOT NULL,
          faction_id TEXT,
          disposition INTEGER NOT NULL,
          FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
          FOREIGN KEY (faction_id) REFERENCES factions(id) ON DELETE SET NULL
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS inventory (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          item_slug TEXT NOT NULL,
          quantity INTEGER NOT NULL,
          owner TEXT NOT NULL,
          FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS crafting_projects (
          id TEXT PRIMARY KEY,
          campaign_id TEXT NOT NULL,
          character_id TEXT NOT NULL,
          item_slug TEXT NOT NULL,
          days_required INTEGER NOT NULL,
          days_completed INTEGER NOT NULL DEFAULT 0,
          cost_gp INTEGER NOT NULL,
          status TEXT NOT NULL,
          FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS sessions (
          id TEXT PRIMARY KEY,
          campaign_id TEXT NOT NULL,
          starts_at TEXT NOT NULL,
          duration_minutes INTEGER NOT NULL,
          agenda_json TEXT NOT NULL,
          FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS session_attendance (
          session_id TEXT NOT NULL,
          character_id TEXT NOT NULL,
          status TEXT NOT NULL,
          PRIMARY KEY (session_id, character_id),
          FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaigns (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          owner TEXT NOT NULL,
          status TEXT NOT NULL,
          max_players INTEGER NOT NULL,
          current_actor TEXT,
          turn_number INTEGER DEFAULT 0,
          nudge_count INTEGER DEFAULT 0,
          turn_deadline INTEGER DEFAULT 0,
          current_scene_id TEXT,
          current_location_id TEXT,
          phase TEXT NOT NULL DEFAULT 'exploration',
          saved_actor TEXT
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_members (
          campaign_id TEXT NOT NULL,
          username TEXT NOT NULL,
          character_id TEXT NOT NULL,
          name TEXT NOT NULL,
          class TEXT NOT NULL,
          hp_current INTEGER DEFAULT 20,
          hp_max INTEGER DEFAULT 20,
          status TEXT NOT NULL DEFAULT 'conscious',
          death_save_successes INTEGER NOT NULL DEFAULT 0,
          death_save_failures INTEGER NOT NULL DEFAULT 0,
          owner TEXT,
          race TEXT,
          background TEXT,
          level INTEGER NOT NULL DEFAULT 1,
          abilities_json TEXT,
          prepared_spells_json TEXT NOT NULL DEFAULT '[]',
          spell_slots_json TEXT,
          concentration_json TEXT,
          gold INTEGER NOT NULL DEFAULT 10,
          PRIMARY KEY (campaign_id, username),
          UNIQUE (campaign_id, character_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          kind TEXT NOT NULL,
          actor TEXT NOT NULL,
          text TEXT NOT NULL,
          type TEXT,
          next_actor TEXT,
          destination_id TEXT,
          travel_turns INTEGER,
          hp_current INTEGER,
          hp_max INTEGER,
          target TEXT,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_feed_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          event_id TEXT NOT NULL,
          text TEXT NOT NULL,
          UNIQUE (campaign_id, event_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_documents (
          campaign_id TEXT PRIMARY KEY,
          story TEXT NOT NULL DEFAULT '',
          dm_notes TEXT NOT NULL DEFAULT '',
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_scenes (
          campaign_id TEXT NOT NULL,
          id TEXT NOT NULL,
          name TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'open',
          PRIMARY KEY (campaign_id, id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_locations (
          campaign_id TEXT NOT NULL,
          id TEXT NOT NULL,
          name TEXT NOT NULL,
          PRIMARY KEY (campaign_id, id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_location_connections (
          campaign_id TEXT NOT NULL,
          from_id TEXT NOT NULL,
          to_id TEXT NOT NULL,
          travel_turns INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, from_id, to_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
          FOREIGN KEY (campaign_id, from_id) REFERENCES play_campaign_locations(campaign_id, id) ON DELETE CASCADE,
          FOREIGN KEY (campaign_id, to_id) REFERENCES play_campaign_locations(campaign_id, id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_encounters (
          campaign_id TEXT NOT NULL,
          id TEXT NOT NULL,
          name TEXT NOT NULL,
          status TEXT NOT NULL,
          combatants_json TEXT NOT NULL DEFAULT '[]',
          round INTEGER NOT NULL DEFAULT 1,
          turn_index INTEGER NOT NULL DEFAULT 0,
          conditions_json TEXT NOT NULL DEFAULT '{}',
          order_json TEXT NOT NULL DEFAULT '[]',
          xp_awarded INTEGER,
          loot_json TEXT NOT NULL DEFAULT '[]',
          PRIMARY KEY (campaign_id, id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_npcs (
          campaign_id TEXT NOT NULL,
          npc_id TEXT NOT NULL,
          name TEXT NOT NULL,
          agenda TEXT NOT NULL,
          public_status TEXT NOT NULL,
          PRIMARY KEY (campaign_id, npc_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_npc_dialogue (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          npc_id TEXT NOT NULL,
          dialogue_id TEXT NOT NULL,
          speaker TEXT NOT NULL,
          text TEXT NOT NULL,
          visibility TEXT NOT NULL,
          UNIQUE (campaign_id, npc_id, dialogue_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_spells (
          campaign_id TEXT NOT NULL,
          character_id TEXT NOT NULL,
          spell_id TEXT NOT NULL,
          name TEXT NOT NULL,
          level INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, character_id, spell_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_casts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          character_id TEXT NOT NULL,
          spell_id TEXT NOT NULL,
          target TEXT NOT NULL,
          slot_level INTEGER NOT NULL,
          slots_remaining INTEGER NOT NULL,
          sequence INTEGER NOT NULL,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_inventory_items (
          campaign_id TEXT NOT NULL,
          character_id TEXT NOT NULL,
          item_id TEXT NOT NULL,
          quantity INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, character_id, item_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_equipment (
          campaign_id TEXT NOT NULL,
          character_id TEXT NOT NULL,
          slot TEXT NOT NULL,
          item_id TEXT NOT NULL,
          attuned INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY (campaign_id, character_id, slot),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_exports (
          campaign_id TEXT NOT NULL,
          version INTEGER NOT NULL,
          story TEXT NOT NULL,
          status TEXT NOT NULL,
          PRIMARY KEY (campaign_id, version),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_backups (
          campaign_id TEXT NOT NULL,
          backup_id TEXT NOT NULL,
          story TEXT NOT NULL,
          status TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, backup_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_imports (
          campaign_id TEXT PRIMARY KEY,
          version INTEGER NOT NULL,
          story TEXT NOT NULL,
          status TEXT NOT NULL,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_migrations (
          campaign_id TEXT PRIMARY KEY,
          schema_version INTEGER NOT NULL,
          story TEXT NOT NULL,
          campaign_name TEXT NOT NULL,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_loot (
          campaign_id TEXT NOT NULL,
          loot_id TEXT NOT NULL,
          item_id TEXT NOT NULL,
          quantity INTEGER NOT NULL,
          status TEXT NOT NULL DEFAULT 'open',
          recipient_character_id TEXT,
          PRIMARY KEY (campaign_id, loot_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_loot_votes (
          campaign_id TEXT NOT NULL,
          loot_id TEXT NOT NULL,
          voter TEXT NOT NULL,
          recipient_character_id TEXT NOT NULL,
          PRIMARY KEY (campaign_id, loot_id, voter),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
          FOREIGN KEY (campaign_id, loot_id) REFERENCES play_campaign_loot(campaign_id, loot_id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_currency_transfers (
          campaign_id TEXT NOT NULL,
          transfer_id INTEGER NOT NULL,
          from_character_id TEXT NOT NULL,
          to_character_id TEXT NOT NULL,
          gold INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, transfer_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_transactional_transfers (
          campaign_id TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          from_character_id TEXT NOT NULL,
          to_character_id TEXT NOT NULL,
          amount INTEGER NOT NULL,
          from_gold INTEGER NOT NULL,
          to_gold INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, sequence),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_factions (
          campaign_id TEXT NOT NULL,
          faction_id TEXT NOT NULL,
          name TEXT NOT NULL,
          PRIMARY KEY (campaign_id, faction_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_reputation (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          faction_id TEXT NOT NULL,
          character_id TEXT NOT NULL,
          delta INTEGER NOT NULL,
          reputation INTEGER NOT NULL,
          reason TEXT NOT NULL,
          FOREIGN KEY (campaign_id, faction_id) REFERENCES play_campaign_factions(campaign_id, faction_id) ON DELETE CASCADE,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_relationships (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          source_id TEXT NOT NULL,
          target_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          score INTEGER NOT NULL,
          UNIQUE (campaign_id, source_id, target_id, kind),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_clues (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          clue_id TEXT NOT NULL,
          text TEXT NOT NULL,
          audience TEXT NOT NULL,
          character_id TEXT,
          UNIQUE (campaign_id, clue_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_quests (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          quest_id TEXT NOT NULL,
          title TEXT NOT NULL,
          depends_on_json TEXT NOT NULL DEFAULT '[]',
          state TEXT NOT NULL DEFAULT 'locked',
          rewards_json TEXT,
          UNIQUE (campaign_id, quest_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_quest_rewards (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          quest_id TEXT NOT NULL,
          awarded INTEGER NOT NULL DEFAULT 0,
          UNIQUE (campaign_id, quest_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_world_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          event_id TEXT NOT NULL,
          turn_number INTEGER NOT NULL,
          title TEXT NOT NULL,
          text TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'scheduled',
          resolution_turn INTEGER,
          resolution_text TEXT,
          UNIQUE (campaign_id, event_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_calendars (
          campaign_id TEXT PRIMARY KEY,
          day INTEGER NOT NULL,
          season TEXT NOT NULL,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_settlements (
          campaign_id TEXT NOT NULL,
          settlement_id TEXT NOT NULL,
          name TEXT NOT NULL,
          services_json TEXT NOT NULL,
          availability TEXT NOT NULL,
          discovered_by_json TEXT NOT NULL DEFAULT '[]',
          PRIMARY KEY (campaign_id, settlement_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_shops (
          campaign_id TEXT NOT NULL,
          settlement_id TEXT NOT NULL,
          shop_id TEXT NOT NULL,
          name TEXT NOT NULL,
          stock_json TEXT NOT NULL,
          buy_price INTEGER NOT NULL,
          sell_price INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, settlement_id, shop_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
          FOREIGN KEY (campaign_id, settlement_id) REFERENCES play_campaign_settlements(campaign_id, settlement_id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_recipes (
          campaign_id TEXT NOT NULL,
          recipe_id TEXT NOT NULL,
          name TEXT NOT NULL,
          ingredients_json TEXT NOT NULL,
          output_item TEXT NOT NULL,
          output_quantity INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, recipe_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_downtime_activities (
          campaign_id TEXT NOT NULL,
          activity_id TEXT NOT NULL,
          name TEXT NOT NULL,
          cycles_required INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, activity_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_downtime_allocations (
          campaign_id TEXT NOT NULL,
          character_id TEXT NOT NULL,
          activity_id TEXT NOT NULL,
          cycles_completed INTEGER NOT NULL DEFAULT 0,
          completions INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY (campaign_id, character_id, activity_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
          FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE,
          FOREIGN KEY (campaign_id, activity_id) REFERENCES play_campaign_downtime_activities(campaign_id, activity_id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_content (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          content_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          text TEXT NOT NULL,
          tags_json TEXT NOT NULL,
          UNIQUE (campaign_id, content_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_notes (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          note_id TEXT NOT NULL,
          text TEXT NOT NULL,
          visibility TEXT NOT NULL,
          owner TEXT NOT NULL,
          UNIQUE (campaign_id, note_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_whispers (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          whisper_id TEXT NOT NULL,
          from_character_id TEXT NOT NULL,
          to_character_id TEXT NOT NULL,
          text TEXT NOT NULL,
          UNIQUE (campaign_id, whisper_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_session_zero (
          campaign_id TEXT PRIMARY KEY,
          rules TEXT NOT NULL,
          tone TEXT NOT NULL,
          consent_json TEXT NOT NULL,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_invitations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          invitation_id TEXT NOT NULL,
          username TEXT NOT NULL,
          character_id TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',
          UNIQUE (campaign_id, invitation_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_delegations (
          campaign_id TEXT NOT NULL,
          username TEXT NOT NULL,
          powers_json TEXT NOT NULL,
          active INTEGER NOT NULL DEFAULT 1,
          PRIMARY KEY (campaign_id, username),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_delegation_audit (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          username TEXT NOT NULL,
          action TEXT NOT NULL,
          powers_json TEXT NOT NULL,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_audit_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          actor TEXT NOT NULL,
          role TEXT NOT NULL,
          timestamp INTEGER NOT NULL,
          correlation_id TEXT NOT NULL,
          UNIQUE (campaign_id, correlation_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_projection_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          event_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          value TEXT,
          UNIQUE (campaign_id, event_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_idempotent_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          event_id TEXT NOT NULL,
          value TEXT NOT NULL,
          idempotency_key TEXT NOT NULL,
          UNIQUE (campaign_id, idempotency_key),
          UNIQUE (campaign_id, event_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_safe_turns_state (
          campaign_id TEXT PRIMARY KEY,
          current_turn INTEGER NOT NULL DEFAULT 1,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_safe_turns (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          submission_id TEXT NOT NULL,
          action TEXT NOT NULL,
          accepted_turn INTEGER NOT NULL,
          next_turn INTEGER NOT NULL,
          UNIQUE (campaign_id, submission_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_search_records (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          record_id TEXT NOT NULL,
          text TEXT NOT NULL,
          UNIQUE (campaign_id, record_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_rate_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          event_id TEXT NOT NULL,
          actor TEXT NOT NULL,
          UNIQUE (campaign_id, event_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_replay_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          event_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          text TEXT NOT NULL,
          UNIQUE (campaign_id, event_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_spectators (
          campaign_id TEXT NOT NULL,
          spectator_id TEXT PRIMARY KEY,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_metrics (
          campaign_id TEXT PRIMARY KEY,
          accepted_rate_events INTEGER NOT NULL DEFAULT 0,
          rejected_rate_events INTEGER NOT NULL DEFAULT 0,
          projection_events INTEGER NOT NULL DEFAULT 0,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_rng_state (
          campaign_id TEXT PRIMARY KEY,
          seed TEXT,
          next_sequence INTEGER NOT NULL DEFAULT 1,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_rng_rolls (
          campaign_id TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          roll_id TEXT NOT NULL,
          sides INTEGER NOT NULL,
          result INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, sequence),
          UNIQUE (campaign_id, roll_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_moderation_reports (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          report_id TEXT NOT NULL,
          target_id TEXT NOT NULL,
          reason TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'open',
          reporter TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          action TEXT,
          note TEXT,
          resolver TEXT,
          UNIQUE (campaign_id, report_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_safety_boundaries (
          campaign_id TEXT PRIMARY KEY,
          blocked_tags_json TEXT NOT NULL DEFAULT '[]',
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_safety_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id TEXT NOT NULL,
          event_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          text TEXT NOT NULL,
          tags_json TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          UNIQUE (campaign_id, event_id),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS play_campaign_fixture_seeds (
          campaign_id TEXT PRIMARY KEY,
          fixture_id TEXT NOT NULL,
          status TEXT NOT NULL,
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS schema_version (
          version INTEGER PRIMARY KEY
        )
      SQL
      db.execute('INSERT OR REPLACE INTO schema_version (version) VALUES (?)', SCHEMA_VERSION)
    end
  end
end
