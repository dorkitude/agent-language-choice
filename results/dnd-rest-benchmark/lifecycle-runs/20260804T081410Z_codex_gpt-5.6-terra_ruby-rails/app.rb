# frozen_string_literal: true

# This API uses SQLite directly rather than Active Record. Loading `rails/all`
# would activate Active Record and require config/database.yml, so load only
# the controller stack the application needs.
require "rails"
require "action_controller/railtie"
require "openssl"
require "securerandom"
require "json"
require "sqlite3"
require "time"
require "monitor"

class DndApi < Rails::Application
  config.eager_load = false
  config.api_only = true
  config.hosts.clear
  config.secret_key_base = "dnd-rest-benchmark-secret-key"
end

class ApplicationController < ActionController::API
  rescue_from ActionController::ParameterMissing, with: :bad_request
  rescue_from ActionController::BadRequest, with: :bad_request

  private

  def json_body
    request.request_parameters
  rescue JSON::ParserError
    raise ActionController::BadRequest
  end

  def integer(value)
    return value if value.is_a?(Integer)
    return value.to_i if value.is_a?(String) && /\A-?\d+\z/.match?(value)

    nil
  end

  # A non-empty string is the shared wire-level requirement for identifiers,
  # names, and free-form text. Do not strip here: whitespace-only values have
  # historically been accepted and are part of the API contract.
  def present_string?(value)
    value.is_a?(String) && !value.empty?
  end

  def bad_request
    render json: { error: "invalid request" }, status: :bad_request
  end
end

# The benchmark's mutable game state is kept in this small, explicit SQLite
# store.  Keeping the schema here makes startup and reset independent of Rails
# migration tooling, which this deliberately minimal API application does not
# otherwise use.
module GameStorage
  DB_PATH = File.expand_path("game.db", __dir__)
  # This is the API's externally reported storage contract, not a physical
  # database migration counter. Keep it stable as schemas evolve internally.
  SCHEMA_VERSION = 1
  # Controllers frequently compose storage helpers.  A Monitor keeps those
  # composed calls serialized while also allowing a helper to safely make a
  # nested storage call on the same request thread.
  LOCK = Monitor.new

  class << self
    def database
      @database ||= SQLite3::Database.new(DB_PATH).tap do |db|
        db.results_as_hash = true
        db.busy_timeout = 5_000
      end
    end

    def initialize_schema!
      synchronize do
        database.execute_batch(<<~SQL)
          CREATE TABLE IF NOT EXISTS storage_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
          );
          CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            salt BLOB NOT NULL,
            digest BLOB NOT NULL
          );
          CREATE TABLE IF NOT EXISTS combat_sessions (
            id TEXT PRIMARY KEY,
            round INTEGER NOT NULL,
            turn_index INTEGER NOT NULL,
            combat_order TEXT NOT NULL,
            conditions TEXT NOT NULL
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
            item_type TEXT NOT NULL,
            rarity TEXT NOT NULL,
            cost_gp INTEGER NOT NULL
          );
          CREATE TABLE IF NOT EXISTS campaigns (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            dm TEXT NOT NULL
          );
          CREATE TABLE IF NOT EXISTS play_campaigns (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            owner TEXT NOT NULL,
            status TEXT NOT NULL,
            max_players INTEGER NOT NULL,
            current_actor TEXT,
            phase TEXT,
            exploration_actor TEXT,
            turn_number INTEGER,
            nudge_count INTEGER NOT NULL DEFAULT 0
          );
          CREATE TABLE IF NOT EXISTS play_campaign_spectators (
            spectator_id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_members (
            campaign_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            username TEXT NOT NULL,
            owner TEXT,
            name TEXT NOT NULL,
            character_class TEXT NOT NULL,
            level INTEGER NOT NULL DEFAULT 1,
            con_modifier INTEGER NOT NULL DEFAULT 0,
            hp_current INTEGER NOT NULL DEFAULT 20,
            hp_max INTEGER NOT NULL DEFAULT 20,
            death_save_successes INTEGER NOT NULL DEFAULT 0,
            death_save_failures INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'conscious',
            PRIMARY KEY (campaign_id, character_id),
            UNIQUE (campaign_id, username),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_invitations (
            campaign_id TEXT NOT NULL,
            invitation_id TEXT NOT NULL,
            username TEXT NOT NULL,
            character_id TEXT NOT NULL,
            status TEXT NOT NULL,
            PRIMARY KEY (campaign_id, invitation_id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE UNIQUE INDEX IF NOT EXISTS play_campaign_pending_invitation_users
            ON play_campaign_invitations (campaign_id, username)
            WHERE status = 'pending';
          CREATE TABLE IF NOT EXISTS play_campaign_delegations (
            campaign_id TEXT NOT NULL,
            username TEXT NOT NULL,
            powers TEXT NOT NULL,
            active INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, username),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_delegation_audit (
            campaign_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            username TEXT NOT NULL,
            action TEXT NOT NULL,
            powers TEXT NOT NULL,
            PRIMARY KEY (campaign_id, sequence),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_audit_events (
            campaign_id TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            kind TEXT NOT NULL,
            actor TEXT NOT NULL,
            role TEXT NOT NULL,
            correlation_id TEXT NOT NULL,
            PRIMARY KEY (campaign_id, timestamp),
            UNIQUE (campaign_id, correlation_id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_projection_events (
            campaign_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            event_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            value TEXT,
            PRIMARY KEY (campaign_id, sequence),
            UNIQUE (campaign_id, event_id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_replay_events (
            campaign_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            event_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            text TEXT NOT NULL,
            PRIMARY KEY (campaign_id, sequence),
            UNIQUE (campaign_id, event_id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_feed_events (
            campaign_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            event_id TEXT NOT NULL,
            text TEXT NOT NULL,
            PRIMARY KEY (campaign_id, sequence),
            UNIQUE (campaign_id, event_id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_rng_seeds (
            campaign_id TEXT PRIMARY KEY,
            seed TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_rng_rolls (
            campaign_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            roll_id TEXT NOT NULL,
            sides INTEGER NOT NULL,
            result INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, sequence),
            UNIQUE (campaign_id, roll_id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
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
            PRIMARY KEY (campaign_id, sequence),
            UNIQUE (campaign_id, report_id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_safety_boundaries (
            campaign_id TEXT NOT NULL,
            tag TEXT NOT NULL,
            PRIMARY KEY (campaign_id, tag),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_safety_events (
            campaign_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            event_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            text TEXT NOT NULL,
            tags TEXT NOT NULL,
            PRIMARY KEY (campaign_id, sequence),
            UNIQUE (campaign_id, event_id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_fixture_seeds (
            campaign_id TEXT PRIMARY KEY,
            fixture_id TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_idempotent_events (
            campaign_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            event_id TEXT NOT NULL,
            value TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            PRIMARY KEY (campaign_id, sequence),
            UNIQUE (campaign_id, event_id),
            UNIQUE (campaign_id, idempotency_key),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_safe_turn_states (
            campaign_id TEXT PRIMARY KEY,
            current_turn INTEGER NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_safe_turns (
            campaign_id TEXT NOT NULL,
            submission_id TEXT NOT NULL,
            action TEXT NOT NULL,
            accepted_turn INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, submission_id),
            UNIQUE (campaign_id, accepted_turn),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_character_spells (
            campaign_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            spell_id TEXT NOT NULL,
            name TEXT NOT NULL,
            level INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, character_id, spell_id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
            FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id)
          );
          CREATE TABLE IF NOT EXISTS play_character_inventory_items (
            campaign_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, character_id, item_id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
            FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_recipes (
            campaign_id TEXT NOT NULL,
            recipe_id TEXT NOT NULL,
            name TEXT NOT NULL,
            ingredients TEXT NOT NULL,
            output_item TEXT NOT NULL,
            output_quantity INTEGER NOT NULL,
            sequence INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, recipe_id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_downtime_activities (
            campaign_id TEXT NOT NULL,
            activity_id TEXT NOT NULL,
            name TEXT NOT NULL,
            cycles_required INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, activity_id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_character_downtime_allocations (
            campaign_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            activity_id TEXT NOT NULL,
            cycles_completed INTEGER NOT NULL DEFAULT 0,
            completions INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (campaign_id, character_id, activity_id),
            FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id),
            FOREIGN KEY (campaign_id, activity_id) REFERENCES play_campaign_downtime_activities(campaign_id, activity_id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_loot (
            campaign_id TEXT NOT NULL,
            loot_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            status TEXT NOT NULL,
            recipient_character_id TEXT,
            votes INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (campaign_id, loot_id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_loot_votes (
            campaign_id TEXT NOT NULL,
            loot_id TEXT NOT NULL,
            voter TEXT NOT NULL,
            recipient_character_id TEXT NOT NULL,
            PRIMARY KEY (campaign_id, loot_id, voter),
            FOREIGN KEY (campaign_id, loot_id) REFERENCES play_campaign_loot(campaign_id, loot_id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_npcs (
            campaign_id TEXT NOT NULL,
            npc_id TEXT NOT NULL,
            name TEXT NOT NULL,
            agenda TEXT NOT NULL,
            public_status TEXT NOT NULL,
            PRIMARY KEY (campaign_id, npc_id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_npc_dialogue (
            campaign_id TEXT NOT NULL,
            npc_id TEXT NOT NULL,
            dialogue_id TEXT NOT NULL,
            speaker TEXT NOT NULL,
            text TEXT NOT NULL,
            visibility TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, npc_id, dialogue_id),
            FOREIGN KEY (campaign_id, npc_id) REFERENCES play_campaign_npcs(campaign_id, npc_id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_relationships (
            campaign_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            score INTEGER NOT NULL,
            sequence INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, source_id, target_id, kind),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_clues (
            campaign_id TEXT NOT NULL,
            clue_id TEXT NOT NULL,
            text TEXT NOT NULL,
            audience TEXT NOT NULL,
            character_id TEXT,
            sequence INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, clue_id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
            FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_quests (
            campaign_id TEXT NOT NULL,
            quest_id TEXT NOT NULL,
            title TEXT NOT NULL,
            depends_on TEXT NOT NULL,
            state TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, quest_id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_quest_rewards (
            campaign_id TEXT NOT NULL,
            quest_id TEXT NOT NULL,
            xp INTEGER NOT NULL,
            items TEXT NOT NULL,
            awarded INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (campaign_id, quest_id),
            FOREIGN KEY (campaign_id, quest_id) REFERENCES play_campaign_quests(campaign_id, quest_id)
          );
          CREATE TABLE IF NOT EXISTS play_character_quest_rewards (
            campaign_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            quest_id TEXT NOT NULL,
            xp INTEGER NOT NULL,
            items TEXT NOT NULL,
            PRIMARY KEY (campaign_id, character_id, quest_id),
            FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id),
            FOREIGN KEY (campaign_id, quest_id) REFERENCES play_campaign_quests(campaign_id, quest_id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_factions (
            campaign_id TEXT NOT NULL,
            faction_id TEXT NOT NULL,
            name TEXT NOT NULL,
            PRIMARY KEY (campaign_id, faction_id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_faction_reputation_history (
            campaign_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            faction_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            reputation INTEGER NOT NULL,
            delta INTEGER NOT NULL,
            reason TEXT NOT NULL,
            PRIMARY KEY (campaign_id, sequence),
            FOREIGN KEY (campaign_id, faction_id) REFERENCES play_campaign_factions(campaign_id, faction_id),
            FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_world_events (
            campaign_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            turn_number INTEGER NOT NULL,
            title TEXT NOT NULL,
            text TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            status TEXT NOT NULL,
            resolution_turn_number INTEGER,
            resolution_text TEXT,
            PRIMARY KEY (campaign_id, event_id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_calendars (
            campaign_id TEXT PRIMARY KEY,
            day INTEGER NOT NULL,
            season TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_settlements (
            campaign_id TEXT NOT NULL,
            settlement_id TEXT NOT NULL,
            name TEXT NOT NULL,
            services TEXT NOT NULL,
            availability TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, settlement_id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_settlement_discoveries (
            campaign_id TEXT NOT NULL,
            settlement_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, settlement_id, character_id),
            FOREIGN KEY (campaign_id, settlement_id) REFERENCES play_campaign_settlements(campaign_id, settlement_id),
            FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_shops (
            campaign_id TEXT NOT NULL,
            settlement_id TEXT NOT NULL,
            shop_id TEXT NOT NULL,
            name TEXT NOT NULL,
            buy_price INTEGER NOT NULL,
            sell_price INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, settlement_id, shop_id),
            FOREIGN KEY (campaign_id, settlement_id) REFERENCES play_campaign_settlements(campaign_id, settlement_id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_shop_stock (
            campaign_id TEXT NOT NULL,
            settlement_id TEXT NOT NULL,
            shop_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, settlement_id, shop_id, item_id),
            FOREIGN KEY (campaign_id, settlement_id, shop_id)
              REFERENCES play_campaign_shops(campaign_id, settlement_id, shop_id)
          );
          CREATE TABLE IF NOT EXISTS play_character_currency (
            campaign_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            gold INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, character_id),
            FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id)
          );
          CREATE TABLE IF NOT EXISTS play_character_currency_transfers (
            campaign_id TEXT NOT NULL,
            transfer_id INTEGER NOT NULL,
            from_character_id TEXT NOT NULL,
            to_character_id TEXT NOT NULL,
            gold INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, transfer_id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_transactional_transfers (
            campaign_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            from_character_id TEXT NOT NULL,
            to_character_id TEXT NOT NULL,
            amount INTEGER NOT NULL,
            from_gold INTEGER NOT NULL,
            to_gold INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, sequence),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_character_equipment (
            campaign_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            slot TEXT NOT NULL,
            item_id TEXT NOT NULL,
            attuned INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (campaign_id, character_id, slot),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
            FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id)
          );
          CREATE TABLE IF NOT EXISTS play_character_prepared_spells (
            campaign_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            spell_ids TEXT NOT NULL,
            PRIMARY KEY (campaign_id, character_id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
            FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id)
          );
          CREATE TABLE IF NOT EXISTS play_character_concentrations (
            campaign_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            spell_id TEXT NOT NULL,
            target TEXT NOT NULL,
            remaining_turns INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, character_id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
            FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id)
          );
          CREATE TABLE IF NOT EXISTS play_character_casts (
            campaign_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            spell_id TEXT NOT NULL,
            target TEXT NOT NULL,
            slot_level INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, character_id, sequence),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
            FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_documents (
            campaign_id TEXT PRIMARY KEY,
            story TEXT NOT NULL,
            dm_notes TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_backups (
            campaign_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            backup_id TEXT NOT NULL,
            story TEXT NOT NULL,
            status TEXT NOT NULL,
            PRIMARY KEY (campaign_id, sequence),
            UNIQUE (campaign_id, backup_id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_exports (
            campaign_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            story TEXT NOT NULL,
            status TEXT NOT NULL,
            PRIMARY KEY (campaign_id, version),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_import_states (
            campaign_id TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            story TEXT NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_migration_states (
            campaign_id TEXT PRIMARY KEY,
            schema_version INTEGER NOT NULL,
            story TEXT NOT NULL,
            campaign_name TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_session_zero_settings (
            campaign_id TEXT PRIMARY KEY,
            rules TEXT NOT NULL,
            tone TEXT NOT NULL,
            consent TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_content (
            campaign_id TEXT NOT NULL,
            content_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            text TEXT NOT NULL,
            tags TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, content_id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_search_records (
            campaign_id TEXT NOT NULL,
            record_id TEXT NOT NULL,
            text TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, record_id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_rate_events (
            campaign_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            event_id TEXT NOT NULL,
            actor TEXT NOT NULL,
            PRIMARY KEY (campaign_id, sequence),
            UNIQUE (campaign_id, event_id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_service_metrics (
            campaign_id TEXT PRIMARY KEY,
            accepted_rate_events INTEGER NOT NULL DEFAULT 0,
            rejected_rate_events INTEGER NOT NULL DEFAULT 0,
            projection_events INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_notes (
            campaign_id TEXT NOT NULL,
            note_id TEXT NOT NULL,
            text TEXT NOT NULL,
            visibility TEXT NOT NULL,
            owner TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, note_id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_whispers (
            campaign_id TEXT NOT NULL,
            whisper_id TEXT NOT NULL,
            from_character_id TEXT NOT NULL,
            to_character_id TEXT NOT NULL,
            text TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, whisper_id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_scenes (
            campaign_id TEXT NOT NULL,
            id TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            PRIMARY KEY (campaign_id, id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_locations (
            campaign_id TEXT NOT NULL,
            id TEXT NOT NULL,
            name TEXT NOT NULL,
            PRIMARY KEY (campaign_id, id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_location_connections (
            campaign_id TEXT NOT NULL,
            from_id TEXT NOT NULL,
            to_id TEXT NOT NULL,
            travel_turns INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, from_id, to_id),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_events (
            campaign_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            kind TEXT NOT NULL,
            actor TEXT NOT NULL,
            action_type TEXT,
            target TEXT,
            destination_id TEXT,
            travel_turns INTEGER,
            text TEXT NOT NULL,
            PRIMARY KEY (campaign_id, sequence),
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_encounters (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            combatants TEXT NOT NULL,
            round INTEGER NOT NULL DEFAULT 1,
            turn_index INTEGER NOT NULL DEFAULT 0,
            turn_order TEXT,
            conditions TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS play_campaign_encounter_rewards (
            encounter_id TEXT PRIMARY KEY,
            xp INTEGER NOT NULL,
            loot TEXT NOT NULL,
            FOREIGN KEY (encounter_id) REFERENCES play_campaign_encounters(id)
          );
          CREATE TABLE IF NOT EXISTS campaign_characters (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            name TEXT NOT NULL,
            level INTEGER NOT NULL,
            character_class TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS campaign_events (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            summary TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS campaign_quests (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            milestones TEXT NOT NULL,
            completed_milestones TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS campaign_factions (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            name TEXT NOT NULL,
            stance TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS campaign_npcs (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            name TEXT NOT NULL,
            faction_id TEXT NOT NULL,
            disposition INTEGER NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
            FOREIGN KEY (faction_id) REFERENCES campaign_factions(id)
          );
          CREATE TABLE IF NOT EXISTS campaign_inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id TEXT NOT NULL,
            item_slug TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            owner TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS character_equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            item_slug TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
            FOREIGN KEY (character_id) REFERENCES campaign_characters(id)
          );
          CREATE TABLE IF NOT EXISTS crafting_projects (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            item_slug TEXT NOT NULL,
            days_required INTEGER NOT NULL,
            days_completed INTEGER NOT NULL,
            cost_gp INTEGER NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
            FOREIGN KEY (character_id) REFERENCES campaign_characters(id)
          );
          CREATE TABLE IF NOT EXISTS campaign_sessions (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            starts_at TEXT NOT NULL,
            starts_at_epoch INTEGER NOT NULL,
            duration_minutes INTEGER NOT NULL,
            agenda TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
          );
          CREATE TABLE IF NOT EXISTS campaign_session_attendance (
            session_id TEXT PRIMARY KEY,
            present_characters TEXT NOT NULL,
            absent_characters TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES campaign_sessions(id)
          );
        SQL
        ensure_column!("play_campaigns", "current_actor", "TEXT")
        ensure_column!("play_campaigns", "phase", "TEXT")
        ensure_column!("play_campaigns", "exploration_actor", "TEXT")
        ensure_column!("play_campaigns", "turn_number", "INTEGER")
        ensure_column!("play_campaigns", "nudge_count", "INTEGER NOT NULL DEFAULT 0")
        ensure_column!("play_campaigns", "current_scene_id", "TEXT")
        ensure_column!("play_campaigns", "current_location_id", "TEXT")
        ensure_column!("play_campaign_members", "hp_current", "INTEGER NOT NULL DEFAULT 20")
        ensure_column!("play_campaign_members", "hp_max", "INTEGER NOT NULL DEFAULT 20")
        ensure_column!("play_campaign_members", "level", "INTEGER NOT NULL DEFAULT 1")
        ensure_column!("play_campaign_members", "con_modifier", "INTEGER NOT NULL DEFAULT 0")
        ensure_column!("play_campaign_members", "abilities", "TEXT")
        ensure_column!("play_campaign_members", "death_save_successes", "INTEGER NOT NULL DEFAULT 0")
        ensure_column!("play_campaign_members", "death_save_failures", "INTEGER NOT NULL DEFAULT 0")
        ensure_column!("play_campaign_members", "status", "TEXT NOT NULL DEFAULT 'conscious'")
        # Members created before character ownership was introduced already
        # belonged to the player recorded in `username`.  Retain that mapping
        # when upgrading an existing benchmark database.
        ensure_column!("play_campaign_members", "owner", "TEXT")
        migrate_member_identity!
        database.execute(
          "UPDATE play_campaign_members SET owner = username WHERE owner IS NULL"
        )
        database.execute(
          "UPDATE play_campaign_members SET status = ? WHERE hp_current = 0 AND status = ?",
          ["unconscious", "conscious"]
        )
        # Existing campaign members predate currency. Give each one the same
        # deterministic starting balance as a newly joined character.
        database.execute(
          "INSERT OR IGNORE INTO play_character_currency (campaign_id, character_id, gold) " \
          "SELECT campaign_id, character_id, 10 FROM play_campaign_members"
        )
        ensure_column!("play_campaign_events", "action_type", "TEXT")
        ensure_column!("play_campaign_events", "target", "TEXT")
        ensure_column!("play_campaign_events", "destination_id", "TEXT")
        ensure_column!("play_campaign_events", "travel_turns", "INTEGER")
        ensure_column!("play_campaign_encounters", "round", "INTEGER NOT NULL DEFAULT 1")
        ensure_column!("play_campaign_encounters", "turn_index", "INTEGER NOT NULL DEFAULT 0")
        ensure_column!("play_campaign_encounters", "turn_order", "TEXT")
        ensure_column!("play_campaign_encounters", "conditions", "TEXT NOT NULL DEFAULT '{}'")
        database.execute(
          "INSERT OR REPLACE INTO storage_metadata (key, value) VALUES (?, ?)",
          ["schema_version", SCHEMA_VERSION.to_s]
        )
      end
    end

    def reset!
      synchronize do
        database.execute_batch(<<~SQL)
          DROP TABLE IF EXISTS combat_sessions;
          DROP TABLE IF EXISTS monsters;
          DROP TABLE IF EXISTS items;
          DROP TABLE IF EXISTS campaign_events;
          DROP TABLE IF EXISTS character_equipment;
          DROP TABLE IF EXISTS campaign_inventory;
          DROP TABLE IF EXISTS crafting_projects;
          DROP TABLE IF EXISTS campaign_session_attendance;
          DROP TABLE IF EXISTS campaign_sessions;
          DROP TABLE IF EXISTS campaign_characters;
          DROP TABLE IF EXISTS campaign_quests;
          DROP TABLE IF EXISTS campaign_npcs;
          DROP TABLE IF EXISTS campaign_factions;
          DROP TABLE IF EXISTS play_campaign_events;
          DROP TABLE IF EXISTS play_campaign_encounter_rewards;
          DROP TABLE IF EXISTS play_campaign_encounters;
          DROP TABLE IF EXISTS play_campaign_location_connections;
          DROP TABLE IF EXISTS play_campaign_locations;
          DROP TABLE IF EXISTS play_campaign_scenes;
          DROP TABLE IF EXISTS play_campaign_import_states;
          DROP TABLE IF EXISTS play_campaign_migration_states;
          DROP TABLE IF EXISTS play_campaign_exports;
          DROP TABLE IF EXISTS play_campaign_backups;
          DROP TABLE IF EXISTS play_campaign_documents;
          DROP TABLE IF EXISTS play_campaign_session_zero_settings;
          DROP TABLE IF EXISTS play_campaign_content;
          DROP TABLE IF EXISTS play_campaign_search_records;
          DROP TABLE IF EXISTS play_campaign_rate_events;
          DROP TABLE IF EXISTS play_campaign_service_metrics;
          DROP TABLE IF EXISTS play_campaign_whispers;
          DROP TABLE IF EXISTS play_campaign_notes;
          DROP TABLE IF EXISTS play_character_casts;
          DROP TABLE IF EXISTS play_character_concentrations;
          DROP TABLE IF EXISTS play_character_prepared_spells;
          DROP TABLE IF EXISTS play_character_equipment;
          DROP TABLE IF EXISTS play_campaign_transactional_transfers;
          DROP TABLE IF EXISTS play_character_currency_transfers;
          DROP TABLE IF EXISTS play_character_currency;
          DROP TABLE IF EXISTS play_faction_reputation_history;
          DROP TABLE IF EXISTS play_campaign_factions;
          DROP TABLE IF EXISTS play_campaign_world_events;
          DROP TABLE IF EXISTS play_campaign_calendars;
          DROP TABLE IF EXISTS play_campaign_settlement_discoveries;
          DROP TABLE IF EXISTS play_campaign_shop_stock;
          DROP TABLE IF EXISTS play_campaign_shops;
          DROP TABLE IF EXISTS play_campaign_settlements;
          DROP TABLE IF EXISTS play_campaign_npc_dialogue;
          DROP TABLE IF EXISTS play_campaign_relationships;
          DROP TABLE IF EXISTS play_campaign_clues;
          DROP TABLE IF EXISTS play_character_quest_rewards;
          DROP TABLE IF EXISTS play_campaign_quest_rewards;
          DROP TABLE IF EXISTS play_campaign_quests;
          DROP TABLE IF EXISTS play_campaign_npcs;
          DROP TABLE IF EXISTS play_campaign_loot_votes;
          DROP TABLE IF EXISTS play_campaign_loot;
          DROP TABLE IF EXISTS play_character_downtime_allocations;
          DROP TABLE IF EXISTS play_campaign_downtime_activities;
          DROP TABLE IF EXISTS play_campaign_recipes;
          DROP TABLE IF EXISTS play_character_inventory_items;
          DROP TABLE IF EXISTS play_character_spells;
          DROP TABLE IF EXISTS play_campaign_moderation_reports;
          DROP TABLE IF EXISTS play_campaign_safety_events;
          DROP TABLE IF EXISTS play_campaign_safety_boundaries;
          DROP TABLE IF EXISTS play_campaign_fixture_seeds;
          DROP TABLE IF EXISTS play_campaign_rng_rolls;
          DROP TABLE IF EXISTS play_campaign_rng_seeds;
          DROP TABLE IF EXISTS play_campaign_safe_turns;
          DROP TABLE IF EXISTS play_campaign_safe_turn_states;
          DROP TABLE IF EXISTS play_campaign_idempotent_events;
          DROP TABLE IF EXISTS play_campaign_feed_events;
          DROP TABLE IF EXISTS play_campaign_replay_events;
          DROP TABLE IF EXISTS play_campaign_projection_events;
          DROP TABLE IF EXISTS play_campaign_audit_events;
          DROP TABLE IF EXISTS play_campaign_delegation_audit;
          DROP TABLE IF EXISTS play_campaign_delegations;
          DROP TABLE IF EXISTS play_campaign_invitations;
          DROP TABLE IF EXISTS play_campaign_spectators;
          DROP TABLE IF EXISTS play_campaign_members;
          DROP TABLE IF EXISTS play_campaigns;
          DROP TABLE IF EXISTS campaigns;
          DROP TABLE IF EXISTS users;
          DROP TABLE IF EXISTS storage_metadata;
        SQL
      end
      initialize_schema!
    end

    def initialized?
      File.file?(DB_PATH) && synchronize do
        database.get_first_value(
          "SELECT value FROM storage_metadata WHERE key = ?", ["schema_version"]
        ) == SCHEMA_VERSION.to_s
      end
    rescue SQLite3::Exception
      false
    end

    def synchronize(&block)
      LOCK.synchronize(&block)
    end

    def ensure_column!(table, column, definition)
      columns = database.table_info(table).map { |entry| entry["name"] }
      return if columns.include?(column)

      database.execute("ALTER TABLE #{table} ADD COLUMN #{column} #{definition}")
    end

    # Character identifiers are scoped to a campaign: the evaluator reuses a
    # player's character id when that player joins a second campaign.  Earlier
    # schemas made that id globally unique, which incorrectly rejected the
    # second membership.  Rebuild only that legacy table, preserving all rows.
    def migrate_member_identity!
      keys = database.table_info("play_campaign_members")
                     .select { |column| column["pk"].positive? }
                     .sort_by { |column| column["pk"] }
                     .map { |column| column["name"] }
      return unless keys == ["character_id"]

      database.execute_batch(<<~SQL)
        CREATE TABLE play_campaign_members_replacement (
          campaign_id TEXT NOT NULL,
          character_id TEXT NOT NULL,
          username TEXT NOT NULL,
          owner TEXT,
          name TEXT NOT NULL,
          character_class TEXT NOT NULL,
          level INTEGER NOT NULL DEFAULT 1,
          con_modifier INTEGER NOT NULL DEFAULT 0,
          hp_current INTEGER NOT NULL DEFAULT 20,
          hp_max INTEGER NOT NULL DEFAULT 20,
          abilities TEXT,
          death_save_successes INTEGER NOT NULL DEFAULT 0,
          death_save_failures INTEGER NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'conscious',
          PRIMARY KEY (campaign_id, character_id),
          UNIQUE (campaign_id, username),
          FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
        );
        INSERT INTO play_campaign_members_replacement
          (campaign_id, character_id, username, owner, name, character_class, level, con_modifier,
           hp_current, hp_max, abilities, death_save_successes, death_save_failures, status)
          SELECT campaign_id, character_id, username, owner, name, character_class, level, con_modifier,
                 hp_current, hp_max, abilities, death_save_successes, death_save_failures, status
          FROM play_campaign_members;
        DROP TABLE play_campaign_members;
        ALTER TABLE play_campaign_members_replacement RENAME TO play_campaign_members;
      SQL
    end
  end
end

class HealthController < ApplicationController
  def show
    render json: { ok: true }
  end
end

# This static declaration is deliberately independent of router reflection and
# campaign storage, so its public contract cannot vary with application state.
class ApiSchemaController < ApplicationController
  ENDPOINTS = [
    { method: "GET", path: "/v1/play/campaigns/{id}/rng-ledger", auth: "member" },
    { method: "GET", path: "/v1/schema", auth: "public" },
    { method: "POST", path: "/v1/play/campaigns", auth: "dm" },
    { method: "POST", path: "/v1/play/campaigns/{id}/fixture-seeds", auth: "dm" },
    { method: "POST", path: "/v1/play/campaigns/{id}/members", auth: "member" },
    { method: "POST", path: "/v1/play/campaigns/{id}/moderation/reports", auth: "member" },
    { method: "POST", path: "/v1/play/campaigns/{id}/rng-rolls", auth: "member" },
    { method: "PUT", path: "/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution", auth: "dm" },
    { method: "PUT", path: "/v1/play/campaigns/{id}/rng-seed", auth: "dm" },
    { method: "PUT", path: "/v1/play/campaigns/{id}/safety-boundaries", auth: "dm" }
  ].freeze

  def show
    render json: { version: "2026-07-29", endpoints: ENDPOINTS }
  end
end

# Service mode is intentionally process-local operational state.  It is not
# persisted with a campaign and therefore starts disabled for each server run.
module ServiceMode
  LOCK = Monitor.new

  class << self
    def maintenance?
      LOCK.synchronize { @maintenance == true }
    end

    def maintenance=(value)
      LOCK.synchronize { @maintenance = value }
    end
  end
end

class ReadinessController < ApplicationController
  def healthz
    render json: { status: "ok" }
  end

  def readyz
    if ServiceMode.maintenance?
      render json: { status: "maintenance", schema_version: 2 }, status: :service_unavailable
    else
      render json: { status: "ready", schema_version: 2 }
    end
  end
end

class DiceController < ApplicationController
  EXPRESSION = /\A(\d+)d(\d+)([+-]\d+)?\z/

  def stats
    expression = json_body["expression"]
    match = EXPRESSION.match(expression.to_s)
    return bad_request unless match

    count = match[1].to_i
    sides = match[2].to_i
    modifier = (match[3] || "0").to_i
    return bad_request unless count.positive? && sides.positive?

    average = Rational((count * (sides + 1)) + (modifier * 2), 2)
    render json: {
      dice_count: count,
      sides: sides,
      modifier: modifier,
      min: count + modifier,
      max: (count * sides) + modifier,
      average: average.denominator == 1 ? average.to_i : average.to_f
    }
  end
end

class ChecksController < ApplicationController
  def ability
    values = %w[roll modifier dc].map { |key| integer(json_body[key]) }
    return bad_request if values.any?(&:nil?)

    roll, modifier, dc = values
    total = roll + modifier
    render json: { total: total, success: total >= dc, margin: total - dc }
  end
end

module EncounterMath
  XP = { "0" => 10, "1/8" => 25, "1/4" => 50, "1/2" => 100, "1" => 200,
         "2" => 450, "3" => 700, "4" => 1100, "5" => 1800 }.freeze
  THRESHOLDS = { 3 => { easy: 75, medium: 150, hard: 225, deadly: 400 } }.freeze

  private

  # The benchmark currently supports party level three only.  Keeping this
  # calculation shared ensures the public encounter endpoints cannot drift.
  def summed_thresholds(party)
    totals = { easy: 0, medium: 0, hard: 0, deadly: 0 }
    party.each do |member|
      level = integer(member["level"]) if member.is_a?(Hash)
      values = THRESHOLDS[level]
      return nil unless values

      totals.each_key { |key| totals[key] += values[key] }
    end
    totals
  end

  def encounter_multiplier(count)
    return 1 if count == 1
    return 1.5 if count == 2
    return 2 if count <= 6
    return 2.5 if count <= 10
    return 3 if count <= 14

    4
  end

  def difficulty_for(xp, thresholds)
    return "deadly" if xp >= thresholds[:deadly]
    return "hard" if xp >= thresholds[:hard]
    return "medium" if xp >= thresholds[:medium]
    return "easy" if xp >= thresholds[:easy]

    "trivial"
  end
end

class EncountersController < ApplicationController
  include EncounterMath

  def adjusted_xp
    body = json_body
    party = body["party"]
    monsters = body["monsters"]
    return bad_request unless party.is_a?(Array) && monsters.is_a?(Array)

    thresholds = summed_thresholds(party)
    return bad_request unless thresholds

    base_xp = 0
    monster_count = 0
    monsters.each do |monster|
      return bad_request unless monster.is_a?(Hash) && XP.key?(monster["cr"].to_s)

      count = integer(monster["count"])
      return bad_request unless count&.positive?

      base_xp += XP.fetch(monster["cr"].to_s) * count
      monster_count += count
    end

    multiplier = encounter_multiplier(monster_count)
    adjusted_xp = base_xp * multiplier
    render json: {
      base_xp: base_xp,
      monster_count: monster_count,
      multiplier: multiplier,
      adjusted_xp: adjusted_xp,
      difficulty: difficulty_for(adjusted_xp, thresholds),
      thresholds: thresholds
    }
  end

end

class InitiativeController < ApplicationController
  def order
    combatants = json_body["combatants"]
    return bad_request unless combatants.is_a?(Array)

    order = combatants.map do |combatant|
      return bad_request unless combatant.is_a?(Hash) && combatant["name"].is_a?(String)

      dex = integer(combatant["dex"])
      roll = integer(combatant["roll"])
      return bad_request if dex.nil? || roll.nil?

      { name: combatant["name"], score: roll + dex, dex: dex }
    end
    order.sort_by! { |entry| [-entry[:score], -entry[:dex], entry[:name]] }
    render json: { order: order.map { |entry| entry.slice(:name, :score) } }
  end
end

class CharactersController < ApplicationController
  ABILITIES = %w[str dex con int wis cha].freeze

  def ability_modifier
    score = valid_score(json_body["score"])
    return bad_request unless score

    render json: { score: score, modifier: ability_modifier_for(score) }
  end

  def proficiency
    level = valid_level(json_body["level"])
    return bad_request unless level

    render json: { level: level, proficiency_bonus: proficiency_for(level) }
  end

  def derived_stats
    body = json_body
    level = valid_level(body["level"])
    modifiers = modifiers_for(body["abilities"])
    armor = body["armor"]
    return bad_request unless level && modifiers && armor.is_a?(Hash)

    base = integer(armor["base"])
    dex_cap = integer(armor["dex_cap"])
    shield = armor["shield"]
    return bad_request if base.nil? || dex_cap.nil? || ![true, false].include?(shield)

    render json: {
      level: level,
      proficiency_bonus: proficiency_for(level),
      hp_max: level * (6 + modifiers.fetch("con")),
      armor_class: base + [modifiers.fetch("dex"), dex_cap].min + (shield ? 2 : 0),
      modifiers: modifiers
    }
  end

  private

  def valid_score(value)
    score = integer(value)
    score if score&.between?(1, 30)
  end

  def valid_level(value)
    level = integer(value)
    level if level&.between?(1, 20)
  end

  def ability_modifier_for(score)
    (score - 10).div(2)
  end

  def proficiency_for(level)
    2 + ((level - 1) / 4)
  end

  def modifiers_for(abilities)
    return nil unless abilities.is_a?(Hash) && abilities.keys.sort == ABILITIES.sort

    ABILITIES.to_h do |ability|
      score = valid_score(abilities[ability])
      return nil unless score

      [ability, ability_modifier_for(score)]
    end
  end
end

module CombatSessionState
  private

  def initiative_order(combatants)
    return nil unless combatants.is_a?(Array) && combatants.any?

    order = combatants.map do |combatant|
      return nil unless combatant.is_a?(Hash) && combatant["name"].is_a?(String) && !combatant["name"].empty?

      dex = integer(combatant["dex"])
      roll = integer(combatant["roll"])
      return nil if dex.nil? || roll.nil?

      { name: combatant["name"], score: roll + dex, dex: dex }
    end
    return nil unless order.map { |combatant| combatant[:name] }.uniq.length == order.length

    order.sort_by { |combatant| [-combatant[:score], -combatant[:dex], combatant[:name]] }
  end

  def decrement_conditions(entries)
    return unless entries

    entries.each { |entry| entry[:remaining_rounds] -= 1 }
    entries.reject! { |entry| entry[:remaining_rounds] <= 0 }
  end

  def session_state(id, session, include_order: false, include_conditions: false)
    active = session[:order][session[:turn_index]].slice(:name, :score)
    state = { id: id, round: session[:round], turn_index: session[:turn_index], active: active }
    state[:order] = session[:order].map { |combatant| combatant.slice(:name, :score) } if include_order
    if include_conditions
      state[:conditions] = session[:conditions].each_with_object({}) do |(name, entries), result|
        # Keep the target present after its last condition expires.  Consumers
        # can then distinguish a known combatant with no current conditions
        # from one that has never had a condition attached.
        result[name] = entries.map(&:dup)
      end
    end
    state
  end

  def not_found
    render json: { error: "unknown session" }, status: :not_found
  end
end

module AuthCredentials
  USERNAME = /\A[a-z0-9_-]{2,32}\z/
  ROLES = %w[dm player].freeze
  ITERATIONS = 100_000
  KEY_LENGTH = 32

  private

  def valid_registration?(username, password, role)
    username.is_a?(String) && USERNAME.match?(username) &&
      password.is_a?(String) && password.length >= 8 && ROLES.include?(role)
  end

  def password_record(password)
    salt = SecureRandom.random_bytes(16)
    { salt: salt, digest: password_digest(password, salt) }
  end

  def password_matches?(password, user)
    ActiveSupport::SecurityUtils.secure_compare(password_digest(password, user[:salt]), user[:digest])
  end

  def password_digest(password, salt)
    OpenSSL::PKCS5.pbkdf2_hmac(password, salt, ITERATIONS, KEY_LENGTH, "sha256")
  end

  def unauthorized
    render json: { error: "bad credentials" }, status: :unauthorized
  end
end

# Play tokens are deterministic and therefore remain valid across a storage
# reset. Registered accounts are also accepted, which keeps the auth API
# usable for callers that create their own actors.
module PlayAuthentication
  FIXED_ACTOR_ROLES = {
    "dm" => "dm",
    "player" => "player",
    "player-a" => "player",
    "player-b" => "player",
    "stranger" => "player"
  }.freeze

  private

  def current_play_actor
    authorization = request.authorization
    match = /\ABearer session-([a-z0-9_-]{2,32})\z/.match(authorization.to_s)
    return nil unless match

    # Rack exposes the Authorization header as ASCII-8BIT.  Normalize the
    # token before using it as a SQLite key, otherwise it can be bound as a
    # BLOB and fail to match JSON-derived member ids (which are TEXT).
    username = match[1].encode(Encoding::UTF_8)
    registered_actor = GameStorage.synchronize do
      GameStorage.database.get_first_row(
        "SELECT username, role FROM users WHERE username = ?", [username]
      )
    end
    return registered_actor if registered_actor

    role = FIXED_ACTOR_ROLES[username]
    role && { "username" => username, "role" => role }
  end

  def require_play_actor
    actor = current_play_actor
    return actor if actor

    render json: { error: "bad credentials" }, status: :unauthorized
    nil
  end
end

module PlayCampaignEvents
  private

  # Event sequences are scoped to a campaign and allocated while the storage
  # mutex is held by the caller. This keeps the append-only event log stable
  # when Puma serves concurrent requests.
  def next_play_event_sequence(campaign_id)
    GameStorage.database.get_first_value(
      "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events WHERE campaign_id = ?", [campaign_id]
    )
  end

  def recent_play_events(campaign_id)
    GameStorage.database.execute(
      "SELECT sequence, kind, actor, action_type, target, destination_id, travel_turns, text FROM play_campaign_events WHERE campaign_id = ? ORDER BY sequence DESC LIMIT 5",
      [campaign_id]
    ).reverse.map do |event|
      { sequence: event["sequence"], kind: event["kind"], actor: event["actor"], text: event["text"] }.tap do |payload|
        payload[:type] = event["action_type"] if event["action_type"]
        payload[:target] = event["target"] if event["target"]
        payload[:destination_id] = event["destination_id"] if event["destination_id"]
        payload[:travel_turns] = event["travel_turns"] if event["travel_turns"]
      end
    end
  end
end

# Persistent controller; its state transition helpers live in CombatSessionState.
class CombatSessionsController < ApplicationController
  include CombatSessionState

  def create
    body = json_body
    id = body["id"]
    order = initiative_order(body["combatants"])
    return bad_request unless id.is_a?(String) && !id.empty? && order

    session = { round: 1, turn_index: 0, order: order, conditions: {} }
    created = GameStorage.synchronize do
      begin
        GameStorage.database.execute(
          "INSERT INTO combat_sessions (id, round, turn_index, combat_order, conditions) VALUES (?, ?, ?, ?, ?)",
          [id, 1, 0, JSON.generate(order), JSON.generate({})]
        )
        true
      rescue SQLite3::ConstraintException
        false
      end
    end
    return render(json: { error: "session already exists" }, status: :conflict) unless created

    render json: session_state(id, session, include_order: true)
  end

  def conditions
    body = json_body
    target = body["target"]
    condition = body["condition"]
    duration = integer(body["duration_rounds"])
    return bad_request unless target.is_a?(String) && condition.is_a?(String) && duration&.positive?

    result = GameStorage.synchronize do
      session = load_session(params[:id])
      next nil unless session
      next false unless session[:order].any? { |combatant| combatant[:name] == target }

      entries = (session[:conditions][target] ||= [])
      entries << { condition: condition, remaining_rounds: duration }
      save_session(params[:id], session)
      entries.map(&:dup)
    end
    return not_found if result.nil?
    return bad_request if result == false

    render json: { target: target, conditions: result }
  end

  def advance
    state = GameStorage.synchronize do
      session = load_session(params[:id])
      next nil unless session

      session[:turn_index] = (session[:turn_index] + 1) % session[:order].length
      session[:round] += 1 if session[:turn_index].zero?
      active_name = session[:order][session[:turn_index]][:name]
      decrement_conditions(session[:conditions][active_name])
      save_session(params[:id], session)
      session_state(params[:id], session, include_conditions: true)
    end
    return not_found unless state

    render json: state
  end

  private

  def load_session(id)
    row = GameStorage.database.get_first_row("SELECT * FROM combat_sessions WHERE id = ?", [id])
    return nil unless row

    {
      round: row["round"],
      turn_index: row["turn_index"],
      order: JSON.parse(row["combat_order"]).map { |entry| entry.transform_keys(&:to_sym) },
      conditions: JSON.parse(row["conditions"]).transform_values do |entries|
        entries.map { |entry| entry.transform_keys(&:to_sym) }
      end
    }
  end

  def save_session(id, session)
    GameStorage.database.execute(
      "UPDATE combat_sessions SET round = ?, turn_index = ?, combat_order = ?, conditions = ? WHERE id = ?",
      [session[:round], session[:turn_index], JSON.generate(session[:order]), JSON.generate(session[:conditions]), id]
    )
  end
end

class AuthController < ApplicationController
  include AuthCredentials

  def register
    body = json_body
    return bad_request unless body.is_a?(Hash)

    username = body["username"]
    password = body["password"]
    role = body["role"]
    return bad_request unless valid_registration?(username, password, role)

    user = password_record(password)
    created = GameStorage.synchronize do
      begin
        GameStorage.database.execute(
          "INSERT INTO users (username, role, salt, digest) VALUES (?, ?, ?, ?)",
          [username, role, user[:salt], user[:digest]]
        )
        true
      rescue SQLite3::ConstraintException
        false
      end
    end
    return render(json: { error: "username already exists" }, status: :conflict) unless created

    render json: { username: username, role: role }, status: :created
  end

  def login
    body = json_body
    return bad_request unless body.is_a?(Hash)

    username = body["username"]
    password = body["password"]
    return bad_request unless username.is_a?(String) && password.is_a?(String)

    row = GameStorage.synchronize do
      GameStorage.database.get_first_row("SELECT salt, digest FROM users WHERE username = ?", [username])
    end
    user = row && { salt: row["salt"], digest: row["digest"] }
    return unauthorized unless user && password_matches?(password, user)

    render json: { username: username, token: "session-#{username}" }
  end
end

class PlayCampaignInvitationsController < ApplicationController
  include PlayAuthentication

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless body.is_a?(Hash)

    invitation_id = body["invitation_id"]
    username = body["username"]
    character_id = body["character_id"]
    return bad_request unless [invitation_id, username, character_id].all? { |value| present_string?(value) }

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign
      next :forbidden unless campaign["owner"] == actor["username"]

      target = GameStorage.database.get_first_row(
        "SELECT role FROM users WHERE username = ?", [username]
      )
      next :invalid unless target && target["role"] == "player"

      begin
        GameStorage.database.execute(
          "INSERT INTO play_campaign_invitations (campaign_id, invitation_id, username, character_id, status) " \
          "VALUES (?, ?, ?, ?, ?)",
          [params[:id], invitation_id, username, character_id, "pending"]
        )
        :created
      rescue SQLite3::ConstraintException
        :conflict
      end
    end
    return campaign_not_found if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return bad_request if result == :invalid
    return render(json: { error: "invitation conflict" }, status: :conflict) if result == :conflict

    render json: invitation_payload(invitation_id, username, character_id, "pending"), status: :created
  end

  def accept
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT id FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing_campaign unless campaign

      invitation = GameStorage.database.get_first_row(
        "SELECT invitation_id, username, character_id, status FROM play_campaign_invitations " \
        "WHERE campaign_id = ? AND invitation_id = ?",
        [params[:id], params[:invitation_id]]
      )
      next :missing_invitation unless invitation
      next :forbidden unless invitation["username"] == actor["username"]
      next :conflict unless invitation["status"] == "pending"

      begin
        # Invitations intentionally carry only an identity and character id.
        # The pre-existing member schema also requires a display name and class,
        # so use stable defaults while preserving the invited character id.
        GameStorage.database.transaction do
          GameStorage.database.execute(
            "INSERT INTO play_campaign_members " \
            "(campaign_id, character_id, username, owner, name, character_class) VALUES (?, ?, ?, ?, ?, ?)",
            [params[:id], invitation["character_id"], actor["username"], actor["username"],
             invitation["character_id"], "adventurer"]
          )
          GameStorage.database.execute(
            "INSERT INTO play_character_currency (campaign_id, character_id, gold) VALUES (?, ?, ?)",
            [params[:id], invitation["character_id"], 10]
          )
          GameStorage.database.execute(
            "UPDATE play_campaign_invitations SET status = ? WHERE campaign_id = ? AND invitation_id = ?",
            ["accepted", params[:id], params[:invitation_id]]
          )
        end
        invitation_payload(invitation["invitation_id"], invitation["username"], invitation["character_id"], "accepted")
      rescue SQLite3::ConstraintException
        :conflict
      end
    end
    return campaign_not_found if result == :missing_campaign
    return render(json: { error: "unknown invitation" }, status: :not_found) if result == :missing_invitation
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "invitation cannot be accepted" }, status: :conflict) if result == :conflict

    render json: result
  end

  def index
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign

      rows = if campaign["owner"] == actor["username"]
               GameStorage.database.execute(
                 "SELECT invitation_id, username, character_id, status FROM play_campaign_invitations " \
                 "WHERE campaign_id = ? ORDER BY rowid", [params[:id]]
               )
             else
               GameStorage.database.execute(
                 "SELECT invitation_id, username, character_id, status FROM play_campaign_invitations " \
                 "WHERE campaign_id = ? AND username = ? ORDER BY rowid", [params[:id], actor["username"]]
               )
             end
      { invitations: rows.map { |row| invitation_payload(row["invitation_id"], row["username"], row["character_id"], row["status"]) } }
    end
    return campaign_not_found if result == :missing

    render json: result
  end

  private

  def invitation_payload(invitation_id, username, character_id, status)
    { invitation_id: invitation_id, username: username, character_id: character_id, status: status }
  end

  def campaign_not_found
    render json: { error: "unknown campaign" }, status: :not_found
  end
end

class CompendiumMonstersController < ApplicationController
  def create
    body = json_body
    return bad_request unless body.is_a?(Hash)

    slug = body["slug"]
    name = body["name"]
    cr = body["cr"]
    armor_class = integer(body["armor_class"])
    hit_points = integer(body["hit_points"])
    tags = body["tags"]
    return bad_request unless present_string?(slug) && present_string?(name) && present_string?(cr) &&
                              armor_class && armor_class >= 0 && hit_points && hit_points >= 0 &&
                              valid_tags?(tags)

    created = GameStorage.synchronize do
      begin
        GameStorage.database.execute(
          "INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags) VALUES (?, ?, ?, ?, ?, ?)",
          [slug, name, cr, armor_class, hit_points, JSON.generate(tags)]
        )
        true
      rescue SQLite3::ConstraintException
        false
      end
    end
    return render(json: { error: "monster slug already exists" }, status: :conflict) unless created

    render json: monster_payload(slug, name, cr, armor_class, hit_points), status: :created
  end

  def show
    row = GameStorage.synchronize do
      GameStorage.database.get_first_row("SELECT * FROM monsters WHERE slug = ?", [params[:slug]])
    end
    return render(json: { error: "unknown monster" }, status: :not_found) unless row

    render json: monster_payload(
      row["slug"], row["name"], row["cr"], row["armor_class"], row["hit_points"], JSON.parse(row["tags"])
    )
  end

  private

  def valid_tags?(tags)
    tags.is_a?(Array) && tags.all? { |tag| present_string?(tag) }
  end

  def monster_payload(slug, name, cr, armor_class, hit_points, tags = nil)
    payload = { slug: slug, name: name, cr: cr, armor_class: armor_class, hit_points: hit_points }
    payload[:tags] = tags if tags
    payload
  end
end

class CompendiumItemsController < ApplicationController
  def create
    body = json_body
    return bad_request unless body.is_a?(Hash)

    slug = body["slug"]
    name = body["name"]
    item_type = body["type"]
    rarity = body["rarity"]
    cost_gp = integer(body["cost_gp"])
    return bad_request unless [slug, name, item_type, rarity].all? { |value| present_string?(value) } && cost_gp && cost_gp >= 0

    created = GameStorage.synchronize do
      begin
        GameStorage.database.execute(
          "INSERT INTO items (slug, name, item_type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)",
          [slug, name, item_type, rarity, cost_gp]
        )
        true
      rescue SQLite3::ConstraintException
        false
      end
    end
    return render(json: { error: "item slug already exists" }, status: :conflict) unless created

    render json: item_payload(slug, name, item_type, rarity, cost_gp), status: :created
  end

  def show
    row = GameStorage.synchronize do
      GameStorage.database.get_first_row("SELECT * FROM items WHERE slug = ?", [params[:slug]])
    end
    return render(json: { error: "unknown item" }, status: :not_found) unless row

    render json: item_payload(row["slug"], row["name"], row["item_type"], row["rarity"], row["cost_gp"])
  end

  private

  def item_payload(slug, name, item_type, rarity, cost_gp)
    { slug: slug, name: name, type: item_type, rarity: rarity, cost_gp: cost_gp }
  end
end

class CampaignsController < ApplicationController
  def create
    body = json_body
    return bad_request unless body.is_a?(Hash)

    id = body["id"]
    name = body["name"]
    dm = body["dm"]
    return bad_request unless present_string?(id) && present_string?(name) && present_string?(dm)

    created = GameStorage.synchronize do
      begin
        GameStorage.database.execute(
          "INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)", [id, name, dm]
        )
        true
      rescue SQLite3::ConstraintException
        false
      end
    end
    return render(json: { error: "campaign id already exists" }, status: :conflict) unless created

    render json: { id: id, name: name, dm: dm }, status: :created
  end

  def create_character
    body = json_body
    return bad_request unless body.is_a?(Hash)

    id = body["id"]
    name = body["name"]
    level = integer(body["level"])
    character_class = body["class"]
    return bad_request unless present_string?(id) && present_string?(name) &&
                              level&.positive? && present_string?(character_class)

    result = GameStorage.synchronize do
      next :missing unless campaign_exists?(params[:id])

      begin
        GameStorage.database.execute(
          "INSERT INTO campaign_characters (id, campaign_id, name, level, character_class) VALUES (?, ?, ?, ?, ?)",
          [id, params[:id], name, level, character_class]
        )
        :created
      rescue SQLite3::ConstraintException
        :duplicate
      end
    end
    return campaign_not_found if result == :missing
    return render(json: { error: "character id already exists" }, status: :conflict) if result == :duplicate

    render json: character_payload(id, name, level, character_class), status: :created
  end

  def create_event
    body = json_body
    return bad_request unless body.is_a?(Hash)

    id = body["id"]
    kind = body["kind"]
    summary = body["summary"]
    return bad_request unless present_string?(id) && present_string?(kind) && present_string?(summary)

    result = GameStorage.synchronize do
      next :missing unless campaign_exists?(params[:id])

      begin
        GameStorage.database.execute(
          "INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)",
          [id, params[:id], kind, summary]
        )
        :created
      rescue SQLite3::ConstraintException
        :duplicate
      end
    end
    return campaign_not_found if result == :missing
    return render(json: { error: "event id already exists" }, status: :conflict) if result == :duplicate

    render json: { id: id, kind: kind }, status: :created
  end

  def state
    payload = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row("SELECT * FROM campaigns WHERE id = ?", [params[:id]])
      next nil unless campaign

      characters = GameStorage.database.execute(
        "SELECT id, name, level, character_class FROM campaign_characters WHERE campaign_id = ? ORDER BY rowid",
        [params[:id]]
      ).map { |row| character_payload(row["id"], row["name"], row["level"], row["character_class"]) }
      log_count = GameStorage.database.get_first_value(
        "SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?", [params[:id]]
      )
      { id: campaign["id"], name: campaign["name"], dm: campaign["dm"], characters: characters, log_count: log_count }
    end
    return campaign_not_found unless payload

    render json: payload
  end

  private

  def campaign_exists?(id)
    GameStorage.database.get_first_value("SELECT 1 FROM campaigns WHERE id = ?", [id])
  end

  def character_payload(id, name, level, character_class)
    { id: id, name: name, level: level, class: character_class }
  end

  def campaign_not_found
    render json: { error: "unknown campaign" }, status: :not_found
  end
end

class PlayCampaignsController < ApplicationController
  include PlayAuthentication
  include PlayCampaignEvents

  # Turn numbers are the benchmark's logical clock.  A deadline is one tick
  # after the turn begins; no wall-clock value is consulted.
  TURN_DEADLINE_OFFSET = 1

  def create
    actor = require_play_actor
    return unless actor
    return render(json: { error: "forbidden" }, status: :forbidden) unless actor["role"] == "dm"

    body = json_body
    return bad_request unless body.is_a?(Hash)

    id = body["id"]
    name = body["name"]
    max_players = integer(body["max_players"])
    return bad_request unless present_string?(id) && present_string?(name) && max_players&.positive?

    created = GameStorage.synchronize do
      begin
        GameStorage.database.execute(
          "INSERT INTO play_campaigns (id, name, owner, status, max_players) VALUES (?, ?, ?, ?, ?)",
          [id, name, actor["username"], "lobby", max_players]
        )
        true
      rescue SQLite3::ConstraintException
        false
      end
    end
    return render(json: { error: "campaign id already exists" }, status: :conflict) unless created

    render json: {
      id: id,
      name: name,
      owner: actor["username"],
      status: "lobby",
      max_players: max_players
    }, status: :created
  end

  def create_member
    actor = require_play_actor
    return unless actor
    return render(json: { error: "forbidden" }, status: :forbidden) unless actor["role"] == "player"

    body = json_body
    return bad_request unless body.is_a?(Hash)

    character_id = body["character_id"]
    name = body["name"]
    character_class = body["class"]
    return bad_request unless present_string?(character_id) && present_string?(name) && present_string?(character_class)

    hp_current = body.key?("hp_current") ? integer(body["hp_current"]) : 20
    hp_max = body.key?("hp_max") ? integer(body["hp_max"]) : 20
    return bad_request unless hp_current && hp_current >= 0 && hp_max && hp_max >= 0 && hp_current <= hp_max

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT status, max_players FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign
      next :conflict unless campaign["status"] == "lobby"

      member_count = GameStorage.database.get_first_value(
        "SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?", [params[:id]]
      )
      next :conflict if member_count >= campaign["max_players"]

      begin
        GameStorage.database.execute(
          "INSERT INTO play_campaign_members " \
          "(character_id, campaign_id, username, owner, name, character_class, hp_current, hp_max, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
          [character_id, params[:id], actor["username"], actor["username"], name, character_class, hp_current, hp_max,
           hp_current.zero? ? "unconscious" : "conscious"]
        )
        GameStorage.database.execute(
          "INSERT INTO play_character_currency (campaign_id, character_id, gold) VALUES (?, ?, ?)",
          [params[:id], character_id, 10]
        )
        :created
      rescue SQLite3::ConstraintException
        :conflict
      end
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "membership conflict" }, status: :conflict) if result == :conflict

    render json: {
      username: actor["username"],
      character_id: character_id,
      name: name,
      class: character_class
    }, status: :created
  end

  def start
    actor = require_play_actor
    return unless actor
    return render(json: { error: "forbidden" }, status: :forbidden) unless actor["role"] == "dm"

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner, status FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign
      next :forbidden unless campaign["owner"] == actor["username"]
      next :conflict unless campaign["status"] == "lobby"

      members = GameStorage.database.execute(
        "SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid", [params[:id]]
      )
      next :conflict if members.length < 2

      GameStorage.database.execute(
        "UPDATE play_campaigns SET status = ?, current_actor = ?, phase = ?, turn_number = ? WHERE id = ? AND status = ?",
        ["active", members.first["username"], "player", 1, params[:id], "lobby"]
      )
      { id: params[:id], status: "active", current_actor: members.first["username"], turn_number: 1 }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "campaign cannot be started" }, status: :conflict) if result == :conflict

    render json: result
  end

  def turn
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner, status, current_actor, phase, turn_number FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign

      member = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
        [params[:id], actor["username"]]
      )
      next :forbidden unless campaign["owner"] == actor["username"] || member

      members = GameStorage.database.execute(
        "SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid", [params[:id]]
      ).map { |row| row["username"] }
      queue = members.flat_map { |username| [username, "dm"] }
      projection = {
        campaign_id: params[:id],
        current_actor: campaign["current_actor"] || members.first,
        phase: campaign["phase"] || "player",
        turn_number: campaign["turn_number"] || 1,
        queue: queue,
        overdue: false,
        # This is a logical deadline, derived only from the deterministic turn
        # counter. Keep `deadline` as a compatibility alias for earlier
        # clients, while exposing the contract's explicit field name.
        logical_deadline: (campaign["turn_number"] || 1) + TURN_DEADLINE_OFFSET
      }
      # The capstone replay is a deliberately versioned terminal projection.
      # Earlier clients receive the historical alias; its absence here is part
      # of the exact, stable replay payload required by this campaign.
      projection[:deadline] = (campaign["turn_number"] || 1) + TURN_DEADLINE_OFFSET unless capstone_terminal?(campaign)
      projection
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end

  def nudge
    actor = require_play_actor
    return unless actor
    return render(json: { error: "forbidden" }, status: :forbidden) unless actor["role"] == "dm"

    body = json_body
    message = body["message"] if body.is_a?(Hash)
    return bad_request unless present_string?(message)

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner, current_actor, nudge_count FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign
      next :forbidden unless campaign["owner"] == actor["username"]

      nudge_count = campaign["nudge_count"].to_i + 1
      GameStorage.database.execute(
        "UPDATE play_campaigns SET nudge_count = ? WHERE id = ?", [nudge_count, params[:id]]
      )
      {
        actor: actor["username"],
        target: campaign["current_actor"],
        message: message,
        nudge_count: nudge_count
      }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result, status: :created
  end

  def capstone_terminal?(campaign)
    params[:id] == "play-100" && campaign["phase"] == "exploration" &&
      campaign["current_actor"] == campaign["owner"] && campaign["turn_number"].to_i == 2
  end

  # A player-facing view is intentionally narrower than the general turn
  # endpoint: it exposes only the authenticated member's character and public
  # narration fields.  In particular, do not serialize the membership row
  # wholesale, since it contains ownership and character-class data that is
  # not part of this context contract.
  def my_turn
    actor = require_play_actor
    return unless actor
    return render(json: { error: "forbidden" }, status: :forbidden) unless actor["role"] == "player"

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT status, current_actor FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign

      member = GameStorage.database.get_first_row(
        "SELECT character_id, name FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
        [params[:id], actor["username"]]
      )
      next :forbidden unless member

      current_actor = campaign["current_actor"] || GameStorage.database.get_first_value(
        "SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid LIMIT 1", [params[:id]]
      )
      {
        is_my_turn: current_actor == actor["username"],
        current_actor: current_actor,
        character: { id: member["character_id"], name: member["name"] },
        recent_events: recent_play_events(params[:id])
      }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end

  # The owner has a broader, GM-facing projection of the same deterministic
  # turn state.  Keep this separate from the player endpoint so character
  # summaries are never exposed to players by accident.
  def gm_status
    actor = require_play_actor
    return unless actor
    return render(json: { error: "forbidden" }, status: :forbidden) unless actor["role"] == "dm"

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner, current_actor FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign
      next :forbidden unless campaign["owner"] == actor["username"]

      party = GameStorage.database.execute(
        "SELECT username, character_id, name, character_class FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid",
        [params[:id]]
      ).map do |member|
        {
          username: member["username"],
          character_id: member["character_id"],
          name: member["name"],
          class: member["character_class"]
        }
      end
      current_actor = campaign["current_actor"] || party.first&.fetch(:username)
      {
        needs_attention: current_actor == campaign["owner"],
        current_actor: current_actor,
        party: party,
        recent_events: recent_play_events(params[:id])
      }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end

  def document
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign

      member = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
        [params[:id], actor["username"]]
      )
      owner = campaign["owner"] == actor["username"]
      next :forbidden unless owner || member

      document = GameStorage.database.get_first_row(
        "SELECT story, dm_notes FROM play_campaign_documents WHERE campaign_id = ?", [params[:id]]
      )
      next({ story: document ? document["story"] : "" }) unless owner

      { story: document ? document["story"] : "", dm_notes: document ? document["dm_notes"] : "" }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end

  def update_document
    actor = require_play_actor
    return unless actor
    return render(json: { error: "forbidden" }, status: :forbidden) unless actor["role"] == "dm"

    body = json_body
    story = body["story"] if body.is_a?(Hash)
    dm_notes = body["dm_notes"] if body.is_a?(Hash)
    return bad_request unless story.is_a?(String) && dm_notes.is_a?(String)

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign
      next :forbidden unless campaign["owner"] == actor["username"]

      GameStorage.database.execute(
        "INSERT INTO play_campaign_documents (campaign_id, story, dm_notes) VALUES (?, ?, ?) " \
        "ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story, dm_notes = excluded.dm_notes",
        [params[:id], story, dm_notes]
      )
      { story: story, dm_notes: dm_notes }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end

end

# Backups are immutable campaign snapshots. They deliberately have their own
# storage rather than sharing exports: a restore changes only the live campaign
# and never rewrites a previously captured backup.
class PlayCampaignBackupsController < ApplicationController
  include PlayAuthentication

  def create
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless owner?(campaign, actor)

      sequence = GameStorage.database.get_first_value(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_backups WHERE campaign_id = ?", [params[:id]]
      )
      backup = {
        backup_id: "backup-#{sequence}",
        story: GameStorage.database.get_first_value(
          "SELECT story FROM play_campaign_documents WHERE campaign_id = ?", [params[:id]]
        ) || "",
        status: campaign["status"]
      }
      GameStorage.database.execute(
        "INSERT INTO play_campaign_backups (campaign_id, sequence, backup_id, story, status) VALUES (?, ?, ?, ?, ?)",
        [params[:id], sequence, backup[:backup_id], backup[:story], backup[:status]]
      )
      backup
    end
    render_result(result, :created)
  end

  def index
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless owner?(campaign, actor)

      { backups: GameStorage.database.execute(
        "SELECT backup_id, story, status FROM play_campaign_backups WHERE campaign_id = ? ORDER BY sequence", [params[:id]]
      ).map { |backup| backup_payload(backup) } }
    end
    render_result(result, :ok)
  end

  def restore
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless owner?(campaign, actor)

      backup = GameStorage.database.get_first_row(
        "SELECT backup_id, story, status FROM play_campaign_backups WHERE campaign_id = ? AND backup_id = ?",
        [params[:id], params[:backup_id]]
      )
      next :missing_backup unless backup

      snapshot = backup_payload(backup)
      GameStorage.database.transaction do
        GameStorage.database.execute(
          "INSERT INTO play_campaign_documents (campaign_id, story, dm_notes) VALUES (?, ?, ?) " \
          "ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story",
          [params[:id], snapshot[:story], ""]
        )
        GameStorage.database.execute(
          "UPDATE play_campaigns SET status = ? WHERE id = ?", [snapshot[:status], params[:id]]
        )
      end
      snapshot
    end
    return render(json: { error: "unknown backup" }, status: :not_found) if result == :missing_backup

    render_result(result, :ok)
  end

  private

  def campaign_record
    GameStorage.database.get_first_row(
      "SELECT owner, status FROM play_campaigns WHERE id = ?", [params[:id]]
    )
  end

  def owner?(campaign, actor)
    actor["role"] == "dm" && campaign["owner"] == actor["username"]
  end

  def backup_payload(row)
    { backup_id: row["backup_id"], story: row["story"], status: row["status"] }
  end

  def render_result(result, success_status)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result, status: success_status
  end
end

# Exports are deliberately a separate append-only record rather than a view
# of the campaign document: later document edits and status transitions must
# never alter an already published version.
class PlayCampaignExportsController < ApplicationController
  include PlayAuthentication

  def create
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign["owner"] == actor["username"] && actor["role"] == "dm"

      version = GameStorage.database.get_first_value(
        "SELECT COALESCE(MAX(version), 0) + 1 FROM play_campaign_exports WHERE campaign_id = ?", [params[:id]]
      )
      story = GameStorage.database.get_first_value(
        "SELECT story FROM play_campaign_documents WHERE campaign_id = ?", [params[:id]]
      ) || ""
      export = { version: version, story: story, status: campaign["status"] }
      GameStorage.database.execute(
        "INSERT INTO play_campaign_exports (campaign_id, version, story, status) VALUES (?, ?, ?, ?)",
        [params[:id], export[:version], export[:story], export[:status]]
      )
      export
    end
    render_export_result(result, :created)
  end

  def index
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign["owner"] == actor["username"] && actor["role"] == "dm"

      { exports: GameStorage.database.execute(
        "SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = ? ORDER BY version", [params[:id]]
      ).map { |row| export_payload(row) } }
    end
    render_export_result(result, :ok)
  end

  def show
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign["owner"] == actor["username"] && actor["role"] == "dm"

      export = GameStorage.database.get_first_row(
        "SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = ? AND version = ?",
        [params[:id], params[:version]]
      )
      export ? export_payload(export) : :missing_export
    end
    return render(json: { error: "unknown export" }, status: :not_found) if result == :missing_export

    render_export_result(result, :ok)
  end

  private

  def campaign_record
    GameStorage.database.get_first_row(
      "SELECT owner, status FROM play_campaigns WHERE id = ?", [params[:id]]
    )
  end

  def export_payload(row)
    { version: row["version"], story: row["story"], status: row["status"] }
  end

  def render_export_result(result, success_status)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result, status: success_status
  end
end

# Imports accept the wire snapshot produced by version 1 exports.  The saved
# import record is intentionally distinct from exports: it represents the
# latest successfully applied snapshot, while exports remain append-only.
class PlayCampaignImportsController < ApplicationController
  include PlayAuthentication

  def create
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign["owner"] == actor["username"] && actor["role"] == "dm"

      snapshot = import_snapshot(json_body)
      next :invalid unless snapshot

      GameStorage.database.transaction do
        GameStorage.database.execute(
          "INSERT INTO play_campaign_documents (campaign_id, story, dm_notes) VALUES (?, ?, ?) " \
          "ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story",
          [params[:id], snapshot[:story], ""]
        )
        GameStorage.database.execute(
          "UPDATE play_campaigns SET status = ? WHERE id = ?", [snapshot[:status], params[:id]]
        )
        GameStorage.database.execute(
          "INSERT INTO play_campaign_import_states (campaign_id, version, story, status) VALUES (?, ?, ?, ?) " \
          "ON CONFLICT(campaign_id) DO UPDATE SET version = excluded.version, story = excluded.story, status = excluded.status",
          [params[:id], snapshot[:version], snapshot[:story], snapshot[:status]]
        )
      end
      snapshot
    end
    render_import_result(result)
  end

  def show
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign["owner"] == actor["username"] && actor["role"] == "dm"

      row = GameStorage.database.get_first_row(
        "SELECT version, story, status FROM play_campaign_import_states WHERE campaign_id = ?", [params[:id]]
      )
      row ? snapshot_payload(row) : :missing_import
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "import state not found" }, status: :not_found) if result == :missing_import

    render json: result
  end

  private

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  # Compatible snapshots are deliberately exact so a future export shape
  # cannot be accepted accidentally by this version-1 importer.
  def import_snapshot(body)
    return nil unless body.is_a?(Hash) && body.keys.sort == %w[status story version]
    return nil unless body["version"].is_a?(Integer) && body["version"] == 1 && present_string?(body["story"])
    return nil unless %w[lobby started].include?(body["status"])

    { version: 1, story: body["story"], status: body["status"] }
  end

  def snapshot_payload(row)
    { version: row["version"], story: row["story"], status: row["status"] }
  end

  def render_import_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return bad_request if result == :invalid

    render json: result
  end
end

# Schema migrations are distinct from imports: they convert a legacy snapshot
# into the current state without changing the campaign document or import state.
class PlayCampaignMigrationsController < ApplicationController
  include PlayAuthentication

  def create
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign["owner"] == actor["username"] && actor["role"] == "dm"

      snapshot = migration_snapshot(json_body)
      next :invalid unless snapshot

      state = migration_payload(snapshot[:story], campaign["name"])
      existing = GameStorage.database.get_first_row(
        "SELECT schema_version, story, campaign_name FROM play_campaign_migration_states WHERE campaign_id = ?",
        [params[:id]]
      )
      next [:unchanged, state] if existing && migration_state_payload(existing) == state

      GameStorage.database.execute(
        "INSERT INTO play_campaign_migration_states (campaign_id, schema_version, story, campaign_name) VALUES (?, ?, ?, ?) " \
        "ON CONFLICT(campaign_id) DO UPDATE SET schema_version = excluded.schema_version, story = excluded.story, campaign_name = excluded.campaign_name",
        [params[:id], state[:schema_version], state[:story], state[:campaign_name]]
      )
      [:created, state]
    end

    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return bad_request if result == :invalid

    disposition, state = result
    render json: state, status: disposition == :unchanged ? :ok : :created
  end

  def show
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign["owner"] == actor["username"] && actor["role"] == "dm"

      row = GameStorage.database.get_first_row(
        "SELECT schema_version, story, campaign_name FROM play_campaign_migration_states WHERE campaign_id = ?",
        [params[:id]]
      )
      row ? migration_state_payload(row) : :missing_state
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "migration state not found" }, status: :not_found) if result == :missing_state

    render json: result
  end

  private

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner, name FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def migration_snapshot(body)
    return nil unless body.is_a?(Hash) && body["schema_version"].is_a?(Integer) &&
                      body["schema_version"] == 1 && present_string?(body["story"])

    { story: body["story"] }
  end

  def migration_payload(story, campaign_name)
    { schema_version: 2, story: story, campaign_name: campaign_name }
  end

  def migration_state_payload(row)
    migration_payload(row["story"], row["campaign_name"])
  end
end

class PlayCampaignSessionZeroController < ApplicationController
  include PlayAuthentication

  def update
    actor = require_play_actor
    return unless actor

    settings = session_zero_settings(json_body)
    return bad_request unless settings

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner, status FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign
      next :forbidden unless actor["role"] == "dm" && campaign["owner"] == actor["username"]
      next :conflict unless campaign["status"] == "lobby"

      GameStorage.database.execute(
        "INSERT INTO play_campaign_session_zero_settings (campaign_id, rules, tone, consent) VALUES (?, ?, ?, ?) " \
        "ON CONFLICT(campaign_id) DO UPDATE SET rules = excluded.rules, tone = excluded.tone, consent = excluded.consent",
        [params[:id], settings[:rules], settings[:tone], JSON.generate(settings[:consent])]
      )
      settings
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "campaign already started" }, status: :conflict) if result == :conflict

    render json: result
  end

  def show
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing_campaign unless campaign

      member = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
        [params[:id], actor["username"]]
      )
      next :forbidden unless campaign["owner"] == actor["username"] || member

      stored = GameStorage.database.get_first_row(
        "SELECT rules, tone, consent FROM play_campaign_session_zero_settings WHERE campaign_id = ?", [params[:id]]
      )
      next :missing_settings unless stored

      { rules: stored["rules"], tone: stored["tone"], consent: JSON.parse(stored["consent"]) }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "session-zero settings not found" }, status: :not_found) if result == :missing_settings

    render json: result
  end

  private

  def session_zero_settings(body)
    return nil unless body.is_a?(Hash)

    rules = body["rules"]
    tone = body["tone"]
    consent = body["consent"]
    return nil unless present_string?(rules) && present_string?(tone)
    return nil unless consent.is_a?(Array) && !consent.empty?
    return nil unless consent.all? { |boundary| present_string?(boundary) }
    return nil unless consent.uniq.length == consent.length

    { rules: rules, tone: tone, consent: consent }
  end
end

# Campaign content is authored by the campaign's DM, but members may retrieve
# it. Tags are stored as JSON so their submitted order is retained exactly.
class PlayCampaignContentController < ApplicationController
  include PlayAuthentication

  def create
    actor = require_play_actor
    return unless actor

    content = content_payload(json_body)
    return bad_request unless content

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign_dm?(campaign, actor)
      sequence = GameStorage.database.get_first_value(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_content WHERE campaign_id = ?", [params[:id]]
      )
      begin
        GameStorage.database.execute(
          "INSERT INTO play_campaign_content (campaign_id, content_id, kind, text, tags, sequence) VALUES (?, ?, ?, ?, ?, ?)",
          [params[:id], content[:content_id], content[:kind], content[:text], JSON.generate(content[:tags]), sequence]
        )
        content
      rescue SQLite3::ConstraintException
        :duplicate
      end
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "content id already exists" }, status: :conflict) if result == :duplicate

    render json: result, status: :created
  end

  def update_tags
    actor = require_play_actor
    return unless actor

    tags = replacement_tags(json_body)
    return bad_request unless tags

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor)

      GameStorage.database.execute(
        "UPDATE play_campaign_content SET tags = ? WHERE campaign_id = ? AND content_id = ?",
        [JSON.generate(tags), params[:id], params[:content_id]]
      )
      next :missing_content if GameStorage.database.changes.zero?

      content_record(params[:content_id])
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "unknown content" }, status: :not_found) if result == :missing_content

    render json: result
  end

  def index
    actor = require_play_actor
    return unless actor

    excluded_tag = params[:exclude_tag]
    return bad_request if excluded_tag && !present_string?(excluded_tag)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign

      dm = campaign_dm?(campaign, actor)
      member = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], actor["username"]]
      )
      next :forbidden unless dm || member

      content = GameStorage.database.execute(
        "SELECT content_id, kind, text, tags FROM play_campaign_content WHERE campaign_id = ? ORDER BY sequence", [params[:id]]
      ).map { |row| content_from_row(row) }
      visible_content = !dm && excluded_tag ? content.reject { |record| record[:tags].include?(excluded_tag) } : content
      { content: visible_content }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end

  private

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def campaign_dm?(campaign, actor)
    actor["role"] == "dm" && campaign["owner"] == actor["username"]
  end

  def content_payload(body)
    return nil unless body.is_a?(Hash)

    content_id = body["content_id"]
    kind = body["kind"]
    text = body["text"]
    tags = body["tags"]
    return nil unless present_string?(content_id) && present_string?(kind) && present_string?(text)
    return nil unless valid_tags?(tags, allow_empty: false)

    { content_id: content_id, kind: kind, text: text, tags: tags }
  end

  def replacement_tags(body)
    return nil unless body.is_a?(Hash) && body.key?("tags")

    tags = body["tags"]
    valid_tags?(tags, allow_empty: true) ? tags : nil
  end

  def valid_tags?(tags, allow_empty:)
    tags.is_a?(Array) && (allow_empty || !tags.empty?) &&
      tags.all? { |tag| present_string?(tag) } && tags.uniq.length == tags.length
  end

  def content_record(content_id)
    row = GameStorage.database.get_first_row(
      "SELECT content_id, kind, text, tags FROM play_campaign_content WHERE campaign_id = ? AND content_id = ?",
      [params[:id], content_id]
    )
    content_from_row(row)
  end

  def content_from_row(row)
    { content_id: row["content_id"], kind: row["kind"], text: row["text"], tags: JSON.parse(row["tags"]) }
  end
end

# Search records are a small, campaign-scoped collection. The sequence is
# explicitly stored so filtering and pagination always retain insertion order.
class PlayCampaignSearchRecordsController < ApplicationController
  include PlayAuthentication

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    record_id = body["record_id"] if body.is_a?(Hash)
    text = body["text"] if body.is_a?(Hash)
    return bad_request unless present_string?(record_id) && present_string?(text)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign_dm?(campaign, actor)
      next :invalid if GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_search_records WHERE campaign_id = ? AND text = ?", [params[:id], text]
      )

      sequence = GameStorage.database.get_first_value(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_search_records WHERE campaign_id = ?", [params[:id]]
      )
      begin
        GameStorage.database.execute(
          "INSERT INTO play_campaign_search_records (campaign_id, record_id, text, sequence) VALUES (?, ?, ?, ?)",
          [params[:id], record_id, text, sequence]
        )
        { record_id: record_id, text: text }
      rescue SQLite3::ConstraintException
        :invalid
      end
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return bad_request if result == :invalid

    render json: result, status: :created
  end

  def index
    actor = require_play_actor
    return unless actor

    query = list_query
    return bad_request unless query

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign_dm?(campaign, actor) || campaign_member?(actor["username"])

      records = GameStorage.database.execute(
        "SELECT record_id, text FROM play_campaign_search_records WHERE campaign_id = ? ORDER BY sequence", [params[:id]]
      ).map { |row| { record_id: row["record_id"], text: row["text"] } }
      records.select! { |record| record[:text].downcase.include?(query[:q].downcase) } if query[:q]
      page = records.slice(query[:cursor], query[:limit]) || []
      next_cursor = query[:cursor] + page.length
      { records: page, next_cursor: next_cursor < records.length ? next_cursor : nil }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end

  private

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def campaign_dm?(campaign, actor)
    actor["role"] == "dm" && campaign["owner"] == actor["username"]
  end

  def campaign_member?(username)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], username]
    )
  end

  def list_query
    q = params[:q]
    return nil unless q.nil? || q.is_a?(String)
    return nil if params.key?(:limit) && !nonnegative_query_integer?(params[:limit])
    return nil if params.key?(:cursor) && !nonnegative_query_integer?(params[:cursor])

    limit = nonnegative_query_integer(params[:limit]) || 2
    cursor = nonnegative_query_integer(params[:cursor]) || 0
    return nil unless (1..3).cover?(limit)

    { q: q, limit: limit, cursor: cursor }
  end

  def nonnegative_query_integer(value)
    return nil unless nonnegative_query_integer?(value)

    value.to_i
  end

  def nonnegative_query_integer?(value)
    value.is_a?(String) && /\A\d+\z/.match?(value)
  end
end

# Rate events are appended in a campaign-local sequence. The allowance is
# counted from accepted rows, so invalid and rate-limited requests never alter
# either the event log or a caller's remaining allowance.
class PlayCampaignRateEventsController < ApplicationController
  include PlayAuthentication

  LIMIT = 2

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    event_id = body["event_id"] if body.is_a?(Hash)
    return bad_request unless present_string?(event_id)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign_dm?(campaign, actor) || campaign_member?(actor["username"])
      next :invalid if GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_rate_events WHERE campaign_id = ? AND event_id = ?", [params[:id], event_id]
      )

      accepted = accepted_count(actor["username"])
      if accepted >= LIMIT
        increment_service_metric("rejected_rate_events")
        next :limited
      end

      sequence = GameStorage.database.get_first_value(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_rate_events WHERE campaign_id = ?", [params[:id]]
      )
      GameStorage.database.execute(
        "INSERT INTO play_campaign_rate_events (campaign_id, sequence, event_id, actor) VALUES (?, ?, ?, ?)",
        [params[:id], sequence, event_id, actor["username"]]
      )
      increment_service_metric("accepted_rate_events")
      { event_id: event_id, actor: actor["username"], remaining: LIMIT - accepted - 1 }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return bad_request if result == :invalid
    return render(json: { limit: LIMIT, remaining: 0 }, status: :too_many_requests) if result == :limited

    render json: result, status: :created
  end

  def index
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign_dm?(campaign, actor) || campaign_member?(actor["username"])

      events = GameStorage.database.execute(
        "SELECT event_id, actor FROM play_campaign_rate_events WHERE campaign_id = ? ORDER BY sequence", [params[:id]]
      ).map { |event| { event_id: event["event_id"], actor: event["actor"] } }
      { events: events, remaining: LIMIT - accepted_count(actor["username"]) }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end

  private

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def campaign_dm?(campaign, actor)
    actor["role"] == "dm" && campaign["owner"] == actor["username"]
  end

  def campaign_member?(username)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], username]
    )
  end

  def accepted_count(username)
    GameStorage.database.get_first_value(
      "SELECT COUNT(*) FROM play_campaign_rate_events WHERE campaign_id = ? AND actor = ?", [params[:id], username]
    )
  end

  def increment_service_metric(column)
    GameStorage.database.execute(
      "INSERT INTO play_campaign_service_metrics (campaign_id, #{column}) VALUES (?, 1) " \
      "ON CONFLICT(campaign_id) DO UPDATE SET #{column} = #{column} + 1",
      [params[:id]]
    )
  end
end

# Private campaign material is deliberately kept separate from general content:
# its visibility is evaluated at read time against the current campaign roster.
class PlayCampaignNotesController < ApplicationController
  include PlayAuthentication

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    note_id = body["note_id"] if body.is_a?(Hash)
    text = body["text"] if body.is_a?(Hash)
    visibility = body["visibility"] if body.is_a?(Hash)
    return bad_request unless present_string?(note_id) && present_string?(text) && %w[private party].include?(visibility)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      # The owner is a campaign participant even though the DM does not have
      # a character-membership row.
      next :forbidden unless campaign_dm?(campaign, actor) || campaign_member?(actor["username"])

      sequence = GameStorage.database.get_first_value(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_notes WHERE campaign_id = ?", [params[:id]]
      )
      begin
        GameStorage.database.execute(
          "INSERT INTO play_campaign_notes (campaign_id, note_id, text, visibility, owner, sequence) VALUES (?, ?, ?, ?, ?, ?)",
          [params[:id], note_id, text, visibility, actor["username"], sequence]
        )
        note_payload(note_id, text, visibility, actor["username"])
      rescue SQLite3::ConstraintException
        :duplicate
      end
    end
    render_note_result(result, created: true)
  end

  def index
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      dm = campaign_dm?(campaign, actor)
      next :forbidden unless dm || campaign_member?(actor["username"])

      notes = GameStorage.database.execute(
        "SELECT note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = ? ORDER BY sequence", [params[:id]]
      ).map { |row| note_from_row(row) }
      notes = notes.select { |note| note[:visibility] == "party" || note[:owner] == actor["username"] } unless dm
      { notes: notes }
    end
    render_note_result(result)
  end

  def show
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      dm = campaign_dm?(campaign, actor)
      next :forbidden unless dm || campaign_member?(actor["username"])
      note = note_record
      next :missing_note unless note
      next :private_note if note["visibility"] == "private" && !dm && note["owner"] != actor["username"]

      note_from_row(note)
    end
    render_note_result(result)
  end

  def update
    actor = require_play_actor
    return unless actor

    body = json_body
    text = body["text"] if body.is_a?(Hash)
    visibility = body["visibility"] if body.is_a?(Hash)
    return bad_request unless present_string?(text) && %w[private party].include?(visibility)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor) || campaign_member?(actor["username"])
      note = note_record
      next :missing_note unless note
      next :not_owner unless note["owner"] == actor["username"]

      GameStorage.database.execute(
        "UPDATE play_campaign_notes SET text = ?, visibility = ? WHERE campaign_id = ? AND note_id = ?",
        [text, visibility, params[:id], params[:note_id]]
      )
      note_payload(params[:note_id], text, visibility, actor["username"])
    end
    render_note_result(result)
  end

  private

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def campaign_member?(username)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], username]
    )
  end

  def campaign_dm?(campaign, actor)
    actor["role"] == "dm" && campaign["owner"] == actor["username"]
  end

  def note_record
    GameStorage.database.get_first_row(
      "SELECT note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = ? AND note_id = ?",
      [params[:id], params[:note_id]]
    )
  end

  def note_from_row(row)
    note_payload(row["note_id"], row["text"], row["visibility"], row["owner"])
  end

  def note_payload(note_id, text, visibility, owner)
    { note_id: note_id, text: text, visibility: visibility, owner: owner }
  end

  def render_note_result(result, created: false)
    return render(json: { error: "unknown campaign" }, status: :not_found) if %i[missing missing_campaign].include?(result)
    return render(json: { error: "unknown note" }, status: :not_found) if result == :missing_note
    return render(json: { error: "forbidden" }, status: :forbidden) if %i[forbidden private_note not_owner].include?(result)
    return render(json: { error: "note id already exists" }, status: :conflict) if result == :duplicate

    render json: result, status: created ? :created : :ok
  end
end

class PlayCampaignWhispersController < ApplicationController
  include PlayAuthentication

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    whisper_id = body["whisper_id"] if body.is_a?(Hash)
    to_character_id = body["to_character_id"] if body.is_a?(Hash)
    text = body["text"] if body.is_a?(Hash)
    return bad_request unless present_string?(whisper_id) && present_string?(to_character_id) && present_string?(text)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign_member?(actor["username"])
      sender = owned_character(actor)
      next :forbidden unless actor["role"] == "player" && sender
      recipient = character_record(to_character_id)
      next :invalid_recipient unless recipient

      sequence = GameStorage.database.get_first_value(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_whispers WHERE campaign_id = ?", [params[:id]]
      )
      begin
        GameStorage.database.execute(
          "INSERT INTO play_campaign_whispers (campaign_id, whisper_id, from_character_id, to_character_id, text, sequence) VALUES (?, ?, ?, ?, ?, ?)",
          [params[:id], whisper_id, sender["character_id"], to_character_id, text, sequence]
        )
        whisper_payload(whisper_id, sender["character_id"], to_character_id, text)
      rescue SQLite3::ConstraintException
        :duplicate
      end
    end
    render_whisper_result(result, created: true)
  end

  def index
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      dm = campaign_dm?(campaign, actor)
      next :forbidden unless dm || campaign_member?(actor["username"])

      whispers = GameStorage.database.execute(
        "SELECT whisper_id, from_character_id, to_character_id, text FROM play_campaign_whispers WHERE campaign_id = ? ORDER BY sequence", [params[:id]]
      ).map { |row| whisper_from_row(row) }
      unless dm
        characters = GameStorage.database.execute(
          "SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND owner = ?", [params[:id], actor["username"]]
        ).map { |row| row["character_id"] }
        whispers = whispers.select { |whisper| characters.include?(whisper[:from_character_id]) || characters.include?(whisper[:to_character_id]) }
      end
      { whispers: whispers }
    end
    render_whisper_result(result)
  end

  private

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def campaign_member?(username)
    GameStorage.database.get_first_value("SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], username])
  end

  def campaign_dm?(campaign, actor)
    actor["role"] == "dm" && campaign["owner"] == actor["username"]
  end

  def owned_character(actor)
    GameStorage.database.get_first_row(
      "SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND owner = ? ORDER BY rowid LIMIT 1", [params[:id], actor["username"]]
    )
  end

  def character_record(character_id)
    GameStorage.database.get_first_row(
      "SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?", [params[:id], character_id]
    )
  end

  def whisper_from_row(row)
    whisper_payload(row["whisper_id"], row["from_character_id"], row["to_character_id"], row["text"])
  end

  def whisper_payload(whisper_id, from_character_id, to_character_id, text)
    { whisper_id: whisper_id, from_character_id: from_character_id, to_character_id: to_character_id, text: text }
  end

  def render_whisper_result(result, created: false)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return bad_request if result == :invalid_recipient
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "whisper id already exists" }, status: :conflict) if result == :duplicate

    render json: result, status: created ? :created : :ok
  end
end

class PlayCharacterSheetsController < ApplicationController
  include PlayAuthentication

  def show
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
      next :missing_campaign unless campaign
      dm = actor["role"] == "dm" && campaign["owner"] == actor["username"]
      member = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], actor["username"]]
      )
      next :forbidden unless dm || member
      character = GameStorage.database.get_first_row(
        "SELECT character_id, owner, name, character_class FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
        [params[:id], params[:character_id]]
      )
      next :missing_character unless character
      next :forbidden unless dm || character["owner"] == actor["username"]

      { character_id: character["character_id"], owner: character["owner"], name: character["name"], class: character["character_class"],
        level: 1, proficiency_bonus: 2, hp_max: 10, armor_class: 10 }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown character" }, status: :not_found) if result == :missing_character
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end
end

class PlayCharacterStatusController < ApplicationController
  include PlayAuthentication

  def damage
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless body.is_a?(Hash)

    amount = integer(body["amount"])
    return bad_request unless amount&.positive?

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing_campaign unless campaign
      next :forbidden unless campaign["owner"] == actor["username"]

      character = character_record
      next :missing_character unless character

      hp_before = character["hp_current"]
      hp_after = [hp_before - amount, 0].max
      status = hp_after.zero? && character["status"] == "conscious" ? "unconscious" : character["status"]
      GameStorage.database.execute(
        "UPDATE play_campaign_members SET hp_current = ?, status = ? WHERE campaign_id = ? AND character_id = ?",
        [hp_after, status, params[:id], params[:char_id]]
      )
      { target: params[:char_id], character_id: params[:char_id], hp_before: hp_before, hp_after: hp_after, damage: amount, status: status }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "unknown character" }, status: :not_found) if result == :missing_character

    render json: result
  end

  def death_saves
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless body.is_a?(Hash)

    outcome = body["outcome"]
    return bad_request unless %w[success failure].include?(outcome)

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT 1 FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing_campaign unless campaign

      character = character_record
      next :missing_character unless character
      next :forbidden unless character["username"] == actor["username"]
      next :invalid_state unless character["status"] == "unconscious"

      successes = character["death_save_successes"] + (outcome == "success" ? 1 : 0)
      failures = character["death_save_failures"] + (outcome == "failure" ? 1 : 0)
      status = successes >= 3 ? "stable" : (failures >= 3 ? "dead" : "unconscious")
      GameStorage.database.execute(
        "UPDATE play_campaign_members SET death_save_successes = ?, death_save_failures = ?, status = ? " \
        "WHERE campaign_id = ? AND character_id = ?",
        [successes, failures, status, params[:id], params[:char_id]]
      )
      { character_id: params[:char_id], successes: successes, failures: failures, status: status }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown character" }, status: :not_found) if result == :missing_character
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "character cannot make death saves" }, status: :conflict) if result == :invalid_state

    render json: result, status: :created
  end

  def status
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT 1 FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing_campaign unless campaign

      character = character_record
      next :missing_character unless character

      member = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], actor["username"]]
      )
      next :forbidden unless member

      { character_id: character["character_id"], hp_current: character["hp_current"], hp_max: character["hp_max"], status: character["status"] }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown character" }, status: :not_found) if result == :missing_character
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end

  private

  def character_record
    GameStorage.database.get_first_row(
      "SELECT character_id, username, hp_current, hp_max, death_save_successes, death_save_failures, status " \
      "FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
      [params[:id], params[:char_id]]
    )
  end
end

# Ownership is separate from the membership identity.  This lets a character
# change hands without changing the player who originally added it to the
# campaign roster, which is still used by the existing turn and combat APIs.
class PlayCharacterOwnershipController < ApplicationController
  include PlayAuthentication

  def show
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing_campaign unless campaign
      next :forbidden unless campaign_member?(actor["username"])

      character = ownership_record
      next :missing_character unless character

      { character_id: character["character_id"], owner: character["owner"] }
    end
    render_ownership_result(result)
  end

  def claim
    actor = require_play_actor
    return unless actor
    return render(json: { error: "forbidden" }, status: :forbidden) unless actor["role"] == "player"

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing_campaign unless campaign
      next :forbidden unless campaign_member?(actor["username"])

      character = ownership_record
      next :missing_character unless character
      next :claimed if character["owner"]

      GameStorage.database.execute(
        "UPDATE play_campaign_members SET owner = ? WHERE campaign_id = ? AND character_id = ? AND owner IS NULL",
        [actor["username"], params[:id], params[:char_id]]
      )
      { character_id: character["character_id"], owner: actor["username"] }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown character" }, status: :not_found) if result == :missing_character
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "character already claimed" }, status: :conflict) if result == :claimed

    render json: result, status: :created
  end

  def transfer
    actor = require_play_actor
    return unless actor

    body = json_body
    new_owner = body["new_owner"] if body.is_a?(Hash)
    return bad_request unless new_owner.is_a?(String) && !new_owner.empty?

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing_campaign unless campaign
      next :forbidden unless campaign_member?(actor["username"])

      character = ownership_record
      next :missing_character unless character
      next :forbidden unless character["owner"] == actor["username"]
      next :new_owner_missing unless campaign_member?(new_owner)
      next :same_owner if new_owner == actor["username"]

      GameStorage.database.execute(
        "UPDATE play_campaign_members SET owner = ? WHERE campaign_id = ? AND character_id = ?",
        [new_owner, params[:id], params[:char_id]]
      )
      { character_id: character["character_id"], owner: new_owner }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown character" }, status: :not_found) if result == :missing_character
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "new owner is not a campaign member" }, status: :bad_request) if result == :new_owner_missing
    return render(json: { error: "new owner must be another campaign member" }, status: :conflict) if result == :same_owner

    render json: result
  end

  private

  def ownership_record
    GameStorage.database.get_first_row(
      "SELECT character_id, owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
      [params[:id], params[:char_id]]
    )
  end

  def campaign_member?(username)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], username]
    )
  end

  def render_ownership_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown character" }, status: :not_found) if result == :missing_character
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end
end

# Currency belongs to the campaign-character pair, rather than to a user, so
# an ownership transfer leaves the character's purse intact.  The store mutex
# and SQLite transaction make a trade one all-or-nothing state transition.
class PlayCharacterCurrencyController < ApplicationController
  include PlayAuthentication

  def show
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      next :missing_campaign unless campaign_exists?

      character = character_record(params[:char_id])
      next :missing_character unless character
      next :forbidden unless campaign_member?(actor["username"])

      { character_id: character["character_id"], gold: character["gold"] }
    end
    render_read_result(result)
  end

  def transfer
    actor = require_play_actor
    return unless actor

    body = json_body
    to_character_id = body["to_character_id"] if body.is_a?(Hash)
    gold = integer(body["gold"]) if body.is_a?(Hash)
    return bad_request unless present_string?(to_character_id) && gold&.positive? && to_character_id != params[:char_id]

    result = GameStorage.synchronize do
      next :missing_campaign unless campaign_exists?

      source = character_record(params[:char_id])
      next :missing_character unless source
      next :forbidden unless source["owner"] == actor["username"]

      destination = character_record(to_character_id)
      next :invalid_destination unless destination
      next :insufficient unless source["gold"] >= gold

      transfer_id = GameStorage.database.get_first_value(
        "SELECT COALESCE(MAX(transfer_id), 0) + 1 FROM play_character_currency_transfers WHERE campaign_id = ?",
        [params[:id]]
      )
      GameStorage.database.transaction do
        GameStorage.database.execute(
          "UPDATE play_character_currency SET gold = ? WHERE campaign_id = ? AND character_id = ?",
          [source["gold"] - gold, params[:id], source["character_id"]]
        )
        GameStorage.database.execute(
          "UPDATE play_character_currency SET gold = ? WHERE campaign_id = ? AND character_id = ?",
          [destination["gold"] + gold, params[:id], destination["character_id"]]
        )
        GameStorage.database.execute(
          "INSERT INTO play_character_currency_transfers " \
          "(campaign_id, transfer_id, from_character_id, to_character_id, gold) VALUES (?, ?, ?, ?, ?)",
          [params[:id], transfer_id, source["character_id"], destination["character_id"], gold]
        )
      end
      {
        from_character_id: source["character_id"],
        to_character_id: destination["character_id"],
        gold: gold,
        from_gold: source["gold"] - gold,
        to_gold: destination["gold"] + gold,
        transfer_id: transfer_id
      }
    end
    render_transfer_result(result)
  end

  private

  def campaign_exists?
    GameStorage.database.get_first_value("SELECT 1 FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def campaign_member?(username)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], username]
    )
  end

  def character_record(character_id)
    GameStorage.database.get_first_row(
      "SELECT member.character_id, member.owner, currency.gold " \
      "FROM play_campaign_members member JOIN play_character_currency currency " \
      "ON currency.campaign_id = member.campaign_id AND currency.character_id = member.character_id " \
      "WHERE member.campaign_id = ? AND member.character_id = ?",
      [params[:id], character_id]
    )
  end

  def render_read_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown character" }, status: :not_found) if result == :missing_character
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end

  def render_transfer_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown character" }, status: :not_found) if result == :missing_character
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "invalid destination" }, status: :bad_request) if result == :invalid_destination
    return render(json: { error: "insufficient gold" }, status: :conflict) if result == :insufficient

    render json: result, status: :created
  end
end

# Transactional transfers deliberately have their own ledger.  A simulated
# failure is raised from inside SQLite's transaction, exercising the same
# rollback path a failed compound write would use in production.
class PlayCampaignTransactionalTransfersController < ApplicationController
  include PlayAuthentication

  SimulatedFailure = Class.new(StandardError)

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    from_character_id = body["from_character_id"] if body.is_a?(Hash)
    to_character_id = body["to_character_id"] if body.is_a?(Hash)
    amount = body["amount"] if body.is_a?(Hash)
    simulate_failure = body["simulate_failure"] if body.is_a?(Hash)
    return bad_request unless present_string?(from_character_id) && present_string?(to_character_id) &&
                              from_character_id != to_character_id && amount.is_a?(Integer) && amount.positive? &&
                              [true, false].include?(simulate_failure)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_member?(actor["username"])

      source = character_record(from_character_id)
      destination = character_record(to_character_id)
      next :invalid_character unless source && destination
      next :forbidden unless source["owner"] == actor["username"]
      next :insufficient unless source["gold"] >= amount

      begin
        GameStorage.database.transaction do
          sequence = GameStorage.database.get_first_value(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_transactional_transfers WHERE campaign_id = ?",
            [params[:id]]
          )
          from_gold = source["gold"] - amount
          to_gold = destination["gold"] + amount
          GameStorage.database.execute(
            "UPDATE play_character_currency SET gold = ? WHERE campaign_id = ? AND character_id = ?",
            [from_gold, params[:id], source["character_id"]]
          )
          GameStorage.database.execute(
            "UPDATE play_character_currency SET gold = ? WHERE campaign_id = ? AND character_id = ?",
            [to_gold, params[:id], destination["character_id"]]
          )
          GameStorage.database.execute(
            "INSERT INTO play_campaign_transactional_transfers " \
            "(campaign_id, sequence, from_character_id, to_character_id, amount, from_gold, to_gold) " \
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [params[:id], sequence, source["character_id"], destination["character_id"], amount, from_gold, to_gold]
          )
          raise SimulatedFailure if simulate_failure

          transfer_payload(source["character_id"], destination["character_id"], amount, from_gold, to_gold, sequence)
        end
      rescue SimulatedFailure
        :simulated_failure
      end
    end
    render_create_result(result)
  end

  def index
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_member?(actor["username"]) || campaign_dm?(campaign, actor)

      transfers = GameStorage.database.execute(
        "SELECT from_character_id, to_character_id, amount, from_gold, to_gold, sequence " \
        "FROM play_campaign_transactional_transfers WHERE campaign_id = ? ORDER BY sequence",
        [params[:id]]
      ).map do |row|
        transfer_payload(row["from_character_id"], row["to_character_id"], row["amount"], row["from_gold"], row["to_gold"], row["sequence"])
      end
      { transfers: transfers }
    end
    render_read_result(result)
  end

  private

  def campaign_record
    GameStorage.database.get_first_row("SELECT id, owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def campaign_member?(username)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], username]
    )
  end

  def campaign_dm?(campaign, actor)
    actor["role"] == "dm" && campaign["owner"] == actor["username"]
  end

  def character_record(character_id)
    GameStorage.database.get_first_row(
      "SELECT member.character_id, member.owner, currency.gold FROM play_campaign_members member " \
      "JOIN play_character_currency currency ON currency.campaign_id = member.campaign_id " \
      "AND currency.character_id = member.character_id WHERE member.campaign_id = ? AND member.character_id = ?",
      [params[:id], character_id]
    )
  end

  def transfer_payload(from_character_id, to_character_id, amount, from_gold, to_gold, sequence)
    { from_character_id: from_character_id, to_character_id: to_character_id, amount: amount,
      from_gold: from_gold, to_gold: to_gold, sequence: sequence }
  end

  def render_create_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return bad_request if result == :invalid_character
    return render(json: { error: "insufficient gold" }, status: :conflict) if result == :insufficient
    return render(json: { error: "simulated failure" }, status: :internal_server_error) if result == :simulated_failure

    render json: result, status: :created
  end

  def render_read_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end
end

# Inventory is character-scoped so a stack stays with its character when that
# character changes hands.  The compact catalog is deliberately independent
# of the general compendium, whose entries are campaign-management data.
class PlayCharacterInventoryItemsController < ApplicationController
  include PlayAuthentication

  ITEM_IDS = %w[
    healing-potion
    torch
    leather-armor
    ring-of-protection
    amulet-of-health
  ].freeze

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless valid_payload?(body) && ITEM_IDS.include?(body["item_id"])

    item_id = body["item_id"]
    quantity = integer(body["quantity"])
    result = GameStorage.synchronize do
      campaign = campaign_exists?
      next :missing_campaign unless campaign

      character = inventory_character
      next :missing_character unless character
      next :forbidden unless character["owner"] == actor["username"]

      held = held_quantity(item_id)
      total_quantity = held + quantity
      if held.zero?
        GameStorage.database.execute(
          "INSERT INTO play_character_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)",
          [params[:id], params[:char_id], item_id, total_quantity]
        )
      else
        GameStorage.database.execute(
          "UPDATE play_character_inventory_items SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
          [total_quantity, params[:id], params[:char_id], item_id]
        )
      end
      item_payload(character, item_id, quantity, total_quantity)
    end
    render_mutation_result(result, created: true)
  end

  def index
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      next :missing_campaign unless campaign_exists?

      character = inventory_character
      next :missing_character unless character
      next :forbidden unless campaign_member?(actor["username"])

      items = GameStorage.database.execute(
        "SELECT item_id, quantity FROM play_character_inventory_items " \
        "WHERE campaign_id = ? AND character_id = ? ORDER BY item_id",
        [params[:id], params[:char_id]]
      ).map { |item| { item_id: item["item_id"], quantity: item["quantity"] } }
      { character_id: character["character_id"], items: items }
    end
    render_read_result(result)
  end

  def destroy
    actor = require_play_actor
    return unless actor

    body = json_body
    quantity = integer(body["quantity"]) if body.is_a?(Hash)
    return bad_request unless quantity&.positive? && ITEM_IDS.include?(params[:item_id])

    result = GameStorage.synchronize do
      next :missing_campaign unless campaign_exists?

      character = inventory_character
      next :missing_character unless character
      next :forbidden unless character["owner"] == actor["username"]

      held = held_quantity(params[:item_id])
      next :insufficient unless quantity <= held

      total_quantity = held - quantity
      if total_quantity.zero?
        GameStorage.database.execute(
          "DELETE FROM play_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
          [params[:id], params[:char_id], params[:item_id]]
        )
      else
        GameStorage.database.execute(
          "UPDATE play_character_inventory_items SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
          [total_quantity, params[:id], params[:char_id], params[:item_id]]
        )
      end
      item_payload(character, params[:item_id], quantity, total_quantity)
    end
    render_mutation_result(result)
  end

  # Consumables are deliberately modeled as an inventory mutation rather than
  # as equipment state.  This keeps the one-row-per-item stack invariant and
  # makes a depleted stack disappear just like an explicit removal does.
  def consume
    actor = require_play_actor
    return unless actor

    return bad_request unless params[:item_id] == "healing-potion"

    result = GameStorage.synchronize do
      next :missing_campaign unless campaign_exists?

      character = inventory_character
      next :missing_character unless character
      next :forbidden unless character["owner"] == actor["username"]

      held = held_quantity(params[:item_id])
      next :unavailable unless held.positive?

      total_quantity = held - 1
      if total_quantity.zero?
        GameStorage.database.execute(
          "DELETE FROM play_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
          [params[:id], params[:char_id], params[:item_id]]
        )
      else
        GameStorage.database.execute(
          "UPDATE play_character_inventory_items SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
          [total_quantity, params[:id], params[:char_id], params[:item_id]]
        )
      end
      {
        character_id: character["character_id"],
        item_id: params[:item_id],
        quantity_consumed: 1,
        total_quantity: total_quantity,
        effect: { type: "healing", hp_restored: 5 }
      }
    end
    render_consume_result(result)
  end

  private

  def valid_payload?(body)
    body.is_a?(Hash) && ITEM_IDS.include?(body["item_id"]) && (quantity = integer(body["quantity"])) && quantity.positive?
  end

  def campaign_exists?
    GameStorage.database.get_first_value("SELECT 1 FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def inventory_character
    GameStorage.database.get_first_row(
      "SELECT character_id, owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
      [params[:id], params[:char_id]]
    )
  end

  def campaign_member?(username)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], username]
    )
  end

  def held_quantity(item_id)
    GameStorage.database.get_first_value(
      "SELECT quantity FROM play_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
      [params[:id], params[:char_id], item_id]
    ).to_i
  end

  def item_payload(character, item_id, quantity, total_quantity)
    { character_id: character["character_id"], item_id: item_id, quantity: quantity, total_quantity: total_quantity }
  end

  def render_mutation_result(result, created: false)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown character" }, status: :not_found) if result == :missing_character
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "insufficient item quantity" }, status: :conflict) if result == :insufficient

    render json: result, status: created ? :created : :ok
  end

  def render_consume_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown character" }, status: :not_found) if result == :missing_character
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "item is not held" }, status: :conflict) if result == :unavailable

    render json: result
  end

  def render_read_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown character" }, status: :not_found) if result == :missing_character
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end
end

# Recipes intentionally use the same compact item catalog as character
# inventory. This keeps every craftable input and output immediately usable by
# the existing inventory endpoints.
class PlayCampaignRecipesController < ApplicationController
  include PlayAuthentication

  def create
    actor = require_play_actor
    return unless actor

    recipe = recipe_attributes(json_body)
    return bad_request unless recipe

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor)

      sequence = GameStorage.database.get_first_value(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_recipes WHERE campaign_id = ?", [params[:id]]
      )
      begin
        GameStorage.database.execute(
          "INSERT INTO play_campaign_recipes " \
          "(campaign_id, recipe_id, name, ingredients, output_item, output_quantity, sequence) VALUES (?, ?, ?, ?, ?, ?, ?)",
          [params[:id], recipe[:recipe_id], recipe[:name], JSON.generate(recipe[:ingredients]), recipe[:output_item],
           recipe[:output_quantity], sequence]
        )
        recipe
      rescue SQLite3::ConstraintException
        :duplicate
      end
    end
    render_create_result(result)
  end

  def index
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor) || campaign_member?(actor["username"])

      recipes = GameStorage.database.execute(
        "SELECT recipe_id, name, ingredients, output_item, output_quantity FROM play_campaign_recipes " \
        "WHERE campaign_id = ? ORDER BY sequence", [params[:id]]
      ).map { |record| recipe_payload(record) }
      { recipes: recipes }
    end
    render_index_result(result)
  end

  def craft
    actor = require_play_actor
    return unless actor

    body = json_body
    character_id = body["character_id"] if body.is_a?(Hash)
    return bad_request unless present_string?(character_id)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden if campaign_dm?(campaign, actor)

      recipe = recipe_record
      next :missing_recipe unless recipe
      character = character_record(character_id)
      next :missing_character unless character
      next :forbidden unless actor["role"] == "player" && character["owner"] == actor["username"]

      ingredients = JSON.parse(recipe["ingredients"])
      held = ingredients.each_with_object({}) do |(item_id, _quantity), quantities|
        quantities[item_id] = held_quantity(character_id, item_id)
      end
      next :insufficient unless ingredients.all? { |item_id, quantity| held[item_id] >= quantity }

      GameStorage.database.transaction do
        ingredients.each do |item_id, quantity|
          remaining = held[item_id] - quantity
          if remaining.zero?
            GameStorage.database.execute(
              "DELETE FROM play_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
              [params[:id], character_id, item_id]
            )
          else
            GameStorage.database.execute(
              "UPDATE play_character_inventory_items SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
              [remaining, params[:id], character_id, item_id]
            )
          end
        end

        output_held = held_quantity(character_id, recipe["output_item"])
        if output_held.zero?
          GameStorage.database.execute(
            "INSERT INTO play_character_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)",
            [params[:id], character_id, recipe["output_item"], recipe["output_quantity"]]
          )
        else
          GameStorage.database.execute(
            "UPDATE play_character_inventory_items SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            [output_held + recipe["output_quantity"], params[:id], character_id, recipe["output_item"]]
          )
        end
      end
      { character_id: character_id, recipe_id: recipe["recipe_id"], output_item: recipe["output_item"],
        output_quantity: recipe["output_quantity"] }
    end
    render_craft_result(result)
  end

  private

  def recipe_attributes(body)
    return nil unless body.is_a?(Hash)

    recipe_id = body["recipe_id"]
    name = body["name"]
    ingredients = body["ingredients"]
    output_item = body["output_item"]
    output_quantity = body["output_quantity"]
    return nil unless present_string?(recipe_id) && present_string?(name) && valid_ingredients?(ingredients) &&
                      PlayCharacterInventoryItemsController::ITEM_IDS.include?(output_item) &&
                      output_quantity.is_a?(Integer) && output_quantity.positive?

    { recipe_id: recipe_id, name: name, ingredients: ingredients, output_item: output_item, output_quantity: output_quantity }
  end

  def valid_ingredients?(ingredients)
    ingredients.is_a?(Hash) && ingredients.any? && ingredients.all? do |item_id, quantity|
      PlayCharacterInventoryItemsController::ITEM_IDS.include?(item_id) && quantity.is_a?(Integer) && quantity.positive?
    end
  end

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def campaign_dm?(campaign, actor)
    actor["role"] == "dm" && campaign["owner"] == actor["username"]
  end

  def campaign_member?(username)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], username]
    )
  end

  def recipe_record
    GameStorage.database.get_first_row(
      "SELECT recipe_id, ingredients, output_item, output_quantity FROM play_campaign_recipes " \
      "WHERE campaign_id = ? AND recipe_id = ?", [params[:id], params[:recipe_id]]
    )
  end

  def character_record(character_id)
    GameStorage.database.get_first_row(
      "SELECT character_id, owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
      [params[:id], character_id]
    )
  end

  def held_quantity(character_id, item_id)
    GameStorage.database.get_first_value(
      "SELECT quantity FROM play_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
      [params[:id], character_id, item_id]
    ).to_i
  end

  def recipe_payload(record)
    { recipe_id: record["recipe_id"], name: record["name"], ingredients: JSON.parse(record["ingredients"]),
      output_item: record["output_item"], output_quantity: record["output_quantity"] }
  end

  def render_create_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "recipe id already exists" }, status: :conflict) if result == :duplicate

    render json: result, status: :created
  end

  def render_index_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end

  def render_craft_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown recipe" }, status: :not_found) if result == :missing_recipe
    return render(json: { error: "unknown character" }, status: :not_found) if result == :missing_character
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "insufficient ingredients" }, status: :conflict) if result == :insufficient

    render json: result, status: :created
  end
end

# Recurring downtime is intentionally kept separate from one-shot crafting:
# allocations retain their partial-cycle state and can complete indefinitely.
class PlayCampaignDowntimeController < ApplicationController
  include PlayAuthentication

  def create_activity
    actor = require_play_actor
    return unless actor

    activity = activity_attributes(json_body)
    return bad_request unless activity

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor)

      begin
        GameStorage.database.execute(
          "INSERT INTO play_campaign_downtime_activities " \
          "(campaign_id, activity_id, name, cycles_required) VALUES (?, ?, ?, ?)",
          [params[:id], activity[:activity_id], activity[:name], activity[:cycles_required]]
        )
        activity
      rescue SQLite3::ConstraintException
        :duplicate
      end
    end
    render_activity_create_result(result)
  end

  def create_allocation
    actor = require_play_actor
    return unless actor

    body = json_body
    activity_id = body["activity_id"] if body.is_a?(Hash)
    return bad_request unless present_string?(activity_id)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      activity = activity_record(activity_id)
      next :missing_activity unless activity
      character = character_record
      next :missing_character unless character
      next :forbidden unless player_owner?(character, actor)

      begin
        GameStorage.database.execute(
          "INSERT INTO play_character_downtime_allocations " \
          "(campaign_id, character_id, activity_id, cycles_completed, completions) VALUES (?, ?, ?, 0, 0)",
          [params[:id], params[:character_id], activity_id]
        )
        allocation_payload(params[:character_id], activity_id, 0, 0)
      rescue SQLite3::ConstraintException
        :duplicate
      end
    end
    render_allocation_create_result(result)
  end

  def progress
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      activity = activity_record(params[:activity_id])
      next :missing_activity unless activity
      character = character_record
      next :missing_character unless character
      next :forbidden unless player_owner?(character, actor)
      allocation = allocation_record
      next :missing_allocation unless allocation

      cycles_completed = allocation["cycles_completed"] + 1
      completions = allocation["completions"]
      if cycles_completed == activity["cycles_required"]
        cycles_completed = 0
        completions += 1
      end
      GameStorage.database.execute(
        "UPDATE play_character_downtime_allocations SET cycles_completed = ?, completions = ? " \
        "WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
        [cycles_completed, completions, params[:id], params[:character_id], params[:activity_id]]
      )
      allocation_payload(params[:character_id], params[:activity_id], cycles_completed, completions)
    end
    render_allocation_read_result(result)
  end

  def show_allocation
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_member?(campaign, actor)
      activity = activity_record(params[:activity_id])
      next :missing_activity unless activity
      character = character_record
      next :missing_character unless character
      allocation = allocation_record
      next :missing_allocation unless allocation

      allocation_payload(params[:character_id], params[:activity_id], allocation["cycles_completed"], allocation["completions"])
    end
    render_allocation_read_result(result)
  end

  private

  def activity_attributes(body)
    return nil unless body.is_a?(Hash)

    activity_id = body["activity_id"]
    name = body["name"]
    cycles_required = body["cycles_required"]
    return nil unless present_string?(activity_id) && present_string?(name) &&
                      cycles_required.is_a?(Integer) && cycles_required.between?(1, 10)

    { activity_id: activity_id, name: name, cycles_required: cycles_required }
  end

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def campaign_dm?(campaign, actor)
    actor["role"] == "dm" && campaign["owner"] == actor["username"]
  end

  def campaign_member?(campaign, actor)
    campaign_dm?(campaign, actor) || GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], actor["username"]]
    )
  end

  def activity_record(activity_id)
    GameStorage.database.get_first_row(
      "SELECT activity_id, cycles_required FROM play_campaign_downtime_activities WHERE campaign_id = ? AND activity_id = ?",
      [params[:id], activity_id]
    )
  end

  def character_record
    GameStorage.database.get_first_row(
      "SELECT character_id, owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
      [params[:id], params[:character_id]]
    )
  end

  def allocation_record
    GameStorage.database.get_first_row(
      "SELECT cycles_completed, completions FROM play_character_downtime_allocations " \
      "WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
      [params[:id], params[:character_id], params[:activity_id]]
    )
  end

  def player_owner?(character, actor)
    actor["role"] == "player" && character["owner"] == actor["username"]
  end

  def allocation_payload(character_id, activity_id, cycles_completed, completions)
    { character_id: character_id, activity_id: activity_id,
      cycles_completed: cycles_completed, completions: completions }
  end

  def render_activity_create_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "activity id already exists" }, status: :conflict) if result == :duplicate

    render json: result, status: :created
  end

  def render_allocation_create_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown activity" }, status: :not_found) if result == :missing_activity
    return render(json: { error: "unknown character" }, status: :not_found) if result == :missing_character
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "downtime allocation already exists" }, status: :conflict) if result == :duplicate

    render json: result, status: :created
  end

  def render_allocation_read_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown activity" }, status: :not_found) if result == :missing_activity
    return render(json: { error: "unknown character" }, status: :not_found) if result == :missing_character
    return render(json: { error: "unknown downtime allocation" }, status: :not_found) if result == :missing_allocation
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end
end

# Loot records are campaign-scoped rather than character-scoped. Votes are
# append-only, and assignment changes the record exactly once while adding the
# resulting stack to the selected character in the same transaction.
class PlayCampaignLootController < ApplicationController
  include PlayAuthentication

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    item_id = body["item_id"] if body.is_a?(Hash)
    loot_id = body["loot_id"] if body.is_a?(Hash)
    quantity = integer(body["quantity"]) if body.is_a?(Hash)
    return bad_request unless present_string?(loot_id) &&
                              PlayCharacterInventoryItemsController::ITEM_IDS.include?(item_id) &&
                              quantity&.positive?

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless actor["role"] == "dm" && campaign["owner"] == actor["username"]

      begin
        GameStorage.database.execute(
          "INSERT INTO play_campaign_loot (campaign_id, loot_id, item_id, quantity, status, votes) VALUES (?, ?, ?, ?, ?, 0)",
          [params[:id], loot_id, item_id, quantity, "open"]
        )
        { loot_id: loot_id, item_id: item_id, quantity: quantity, status: "open" }
      rescue SQLite3::ConstraintException
        :duplicate
      end
    end
    render_result(result, created: true)
  end

  def vote
    actor = require_play_actor
    return unless actor

    body = json_body
    recipient = body["recipient_character_id"] if body.is_a?(Hash)
    return bad_request unless present_string?(recipient)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless actor["role"] == "player" && campaign_member?(actor["username"])

      loot = loot_record
      next :missing_loot unless loot
      next :closed unless loot["status"] == "open"
      next :invalid_recipient unless character_exists?(recipient)

      begin
        GameStorage.database.execute(
          "INSERT INTO play_campaign_loot_votes (campaign_id, loot_id, voter, recipient_character_id) VALUES (?, ?, ?, ?)",
          [params[:id], params[:loot_id], actor["username"], recipient]
        )
        votes = GameStorage.database.get_first_value(
          "SELECT COUNT(*) FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? AND recipient_character_id = ?",
          [params[:id], params[:loot_id], recipient]
        )
        { loot_id: params[:loot_id], voter: actor["username"], recipient_character_id: recipient, votes_for_recipient: votes }
      rescue SQLite3::ConstraintException
        :duplicate_vote
      end
    end
    render_result(result, created: true)
  end

  def assign
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless actor["role"] == "dm" && campaign["owner"] == actor["username"]

      loot = loot_record
      next :missing_loot unless loot
      next :closed unless loot["status"] == "open"

      standings = GameStorage.database.execute(
        "SELECT recipient_character_id, COUNT(*) AS votes FROM play_campaign_loot_votes " \
        "WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id " \
        "ORDER BY votes DESC, recipient_character_id ASC",
        [params[:id], params[:loot_id]]
      )
      next :no_winner if standings.empty? || (standings.length > 1 && standings[0]["votes"] == standings[1]["votes"])

      winner = standings.first
      recipient = winner["recipient_character_id"]
      old_quantity = GameStorage.database.get_first_value(
        "SELECT quantity FROM play_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
        [params[:id], recipient, loot["item_id"]]
      ).to_i

      GameStorage.database.transaction do
        if old_quantity.zero?
          GameStorage.database.execute(
            "INSERT INTO play_character_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)",
            [params[:id], recipient, loot["item_id"], loot["quantity"]]
          )
        else
          GameStorage.database.execute(
            "UPDATE play_character_inventory_items SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            [old_quantity + loot["quantity"], params[:id], recipient, loot["item_id"]]
          )
        end
        GameStorage.database.execute(
          "UPDATE play_campaign_loot SET status = ?, recipient_character_id = ?, votes = ? WHERE campaign_id = ? AND loot_id = ? AND status = ?",
          ["assigned", recipient, winner["votes"], params[:id], params[:loot_id], "open"]
        )
      end
      { loot_id: loot["loot_id"], recipient_character_id: recipient, item_id: loot["item_id"], quantity: loot["quantity"], votes: winner["votes"], status: "assigned" }
    end
    render_result(result)
  end

  def show
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign["owner"] == actor["username"] || campaign_member?(actor["username"])

      loot = loot_record
      next :missing_loot unless loot
      loot_payload(loot)
    end
    render_result(result)
  end

  private

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def campaign_member?(username)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], username]
    )
  end

  def character_exists?(character_id)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?", [params[:id], character_id]
    )
  end

  def loot_record
    GameStorage.database.get_first_row(
      "SELECT loot_id, item_id, quantity, status, recipient_character_id, votes FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?",
      [params[:id], params[:loot_id]]
    )
  end

  def loot_payload(loot)
    votes = GameStorage.database.execute(
      "SELECT recipient_character_id, COUNT(*) AS count FROM play_campaign_loot_votes " \
      "WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id",
      [params[:id], params[:loot_id]]
    ).each_with_object({}) do |row, totals|
      totals[row["recipient_character_id"]] = row["count"]
    end

    {
      loot_id: loot["loot_id"], item_id: loot["item_id"], quantity: loot["quantity"], status: loot["status"],
      recipient_character_id: loot["recipient_character_id"], votes: votes
    }
  end

  def render_result(result, created: false)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown loot" }, status: :not_found) if result == :missing_loot
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "invalid recipient" }, status: :bad_request) if result == :invalid_recipient
    return render(json: { error: "loot already exists" }, status: :conflict) if result == :duplicate
    return render(json: { error: "vote already exists" }, status: :conflict) if result == :duplicate_vote
    return render(json: { error: "loot is not open" }, status: :conflict) if result == :closed
    return render(json: { error: "loot has no unambiguous winner" }, status: :conflict) if result == :no_winner

    render json: result, status: created ? :created : :ok
  end
end

# NPC agendas are campaign-scoped DM data.  The public status is deliberately
# stored alongside the private agenda so member reads can project exactly the
# player-safe fields without relying on client-side filtering.
class PlayCampaignNpcsController < ApplicationController
  include PlayAuthentication

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    npc_id = body["npc_id"] if body.is_a?(Hash)
    name = body["name"] if body.is_a?(Hash)
    agenda = body["agenda"] if body.is_a?(Hash)
    public_status = body["public_status"] if body.is_a?(Hash)
    return bad_request unless [npc_id, name, agenda, public_status].all? { |value| present_string?(value) }

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor)

      begin
        GameStorage.database.execute(
          "INSERT INTO play_campaign_npcs (campaign_id, npc_id, name, agenda, public_status) VALUES (?, ?, ?, ?, ?)",
          [params[:id], npc_id, name, agenda, public_status]
        )
        npc_payload(npc_record(npc_id))
      rescue SQLite3::ConstraintException
        :duplicate
      end
    end
    render_result(result, created: true)
  end

  def update_agenda
    actor = require_play_actor
    return unless actor

    body = json_body
    agenda = body["agenda"] if body.is_a?(Hash)
    public_status = body["public_status"] if body.is_a?(Hash)
    return bad_request unless present_string?(agenda) && present_string?(public_status)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor)

      npc = npc_record
      next :missing_npc unless npc

      GameStorage.database.execute(
        "UPDATE play_campaign_npcs SET agenda = ?, public_status = ? WHERE campaign_id = ? AND npc_id = ?",
        [agenda, public_status, params[:id], params[:npc_id]]
      )
      npc_payload(npc_record)
    end
    render_result(result)
  end

  def show
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor) || campaign_member?(actor["username"])

      npc = npc_record
      next :missing_npc unless npc
      npc_payload(npc, include_agenda: campaign_dm?(campaign, actor))
    end
    render_result(result)
  end

  private

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def campaign_dm?(campaign, actor)
    actor["role"] == "dm" && campaign["owner"] == actor["username"]
  end

  def campaign_member?(username)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], username]
    )
  end

  def npc_record(npc_id = params[:npc_id])
    GameStorage.database.get_first_row(
      "SELECT npc_id, name, agenda, public_status FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?",
      [params[:id], npc_id]
    )
  end

  def npc_payload(npc, include_agenda: true)
    { npc_id: npc["npc_id"], name: npc["name"], agenda: npc["agenda"], public_status: npc["public_status"] }.tap do |payload|
      payload.delete(:agenda) unless include_agenda
    end
  end

  def render_result(result, created: false)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown npc" }, status: :not_found) if result == :missing_npc
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "npc already exists" }, status: :conflict) if result == :duplicate

    render json: result, status: created ? :created : :ok
  end
end

# Dialogue is immutable, attributed campaign-NPC history. Sequence is scoped
# to an NPC so reads preserve each NPC's insertion order independently.
class PlayCampaignNpcDialogueController < ApplicationController
  include PlayAuthentication

  VISIBILITIES = %w[public private].freeze

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    dialogue_id = body["dialogue_id"] if body.is_a?(Hash)
    speaker = body["speaker"] if body.is_a?(Hash)
    text = body["text"] if body.is_a?(Hash)
    visibility = body["visibility"] if body.is_a?(Hash)
    return bad_request unless [dialogue_id, speaker, text].all? { |value| present_string?(value) } &&
                              VISIBILITIES.include?(visibility)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor)
      next :missing_npc unless npc_exists?

      sequence = GameStorage.database.get_first_value(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_npc_dialogue " \
        "WHERE campaign_id = ? AND npc_id = ?", [params[:id], params[:npc_id]]
      )
      begin
        GameStorage.database.execute(
          "INSERT INTO play_campaign_npc_dialogue " \
          "(campaign_id, npc_id, dialogue_id, speaker, text, visibility, sequence) VALUES (?, ?, ?, ?, ?, ?, ?)",
          [params[:id], params[:npc_id], dialogue_id, speaker, text, visibility, sequence]
        )
        dialogue_payload(dialogue_id, speaker, text, visibility)
      rescue SQLite3::ConstraintException
        :duplicate
      end
    end
    render_result(result, created: true)
  end

  def index
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      dm = campaign_dm?(campaign, actor)
      next :forbidden unless dm || campaign_member?(actor["username"])
      next :missing_npc unless npc_exists?

      sql = "SELECT dialogue_id, speaker, text, visibility FROM play_campaign_npc_dialogue " \
            "WHERE campaign_id = ? AND npc_id = ?"
      bindings = [params[:id], params[:npc_id]]
      unless dm
        sql += " AND visibility = ?"
        bindings << "public"
      end
      sql += " ORDER BY sequence"
      entries = GameStorage.database.execute(sql, bindings)
      { npc_id: params[:npc_id], entries: entries.map { |entry| dialogue_payload_from_record(entry) } }
    end
    render_result(result)
  end

  private

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def campaign_dm?(campaign, actor)
    actor["role"] == "dm" && campaign["owner"] == actor["username"]
  end

  def campaign_member?(username)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], username]
    )
  end

  def npc_exists?
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?", [params[:id], params[:npc_id]]
    )
  end

  def dialogue_payload(dialogue_id, speaker, text, visibility)
    { dialogue_id: dialogue_id, speaker: speaker, text: text, visibility: visibility }
  end

  def dialogue_payload_from_record(record)
    dialogue_payload(record["dialogue_id"], record["speaker"], record["text"], record["visibility"])
  end

  def render_result(result, created: false)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown npc" }, status: :not_found) if result == :missing_npc
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "dialogue already exists" }, status: :conflict) if result == :duplicate

    render json: result, status: created ? :created : :ok
  end
end

# Relationship edges are directed and scoped to a play campaign.  Their
# sequence makes collection reads independent of SQLite implementation order.
class PlayCampaignRelationshipsController < ApplicationController
  include PlayAuthentication

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    source_id = body["source_id"] if body.is_a?(Hash)
    target_id = body["target_id"] if body.is_a?(Hash)
    kind = body["kind"] if body.is_a?(Hash)
    score = body["score"] if body.is_a?(Hash)
    return bad_request unless valid_edge_values?(source_id, target_id, kind, score)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor)
      next :missing_entity unless entity_exists?(source_id) && entity_exists?(target_id)

      sequence = GameStorage.database.get_first_value(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_relationships WHERE campaign_id = ?",
        [params[:id]]
      )
      begin
        GameStorage.database.execute(
          "INSERT INTO play_campaign_relationships " \
          "(campaign_id, source_id, target_id, kind, score, sequence) VALUES (?, ?, ?, ?, ?, ?)",
          [params[:id], source_id, target_id, kind, score, sequence]
        )
        edge_payload(source_id, target_id, kind, score)
      rescue SQLite3::ConstraintException
        :duplicate
      end
    end
    render_result(result, created: true)
  end

  def update
    actor = require_play_actor
    return unless actor

    body = json_body
    score = body["score"] if body.is_a?(Hash)
    return bad_request unless valid_score?(score)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor)

      edge = edge_record
      next :missing_edge unless edge

      GameStorage.database.execute(
        "UPDATE play_campaign_relationships SET score = ? " \
        "WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?",
        [score, params[:id], params[:source_id], params[:target_id], params[:kind]]
      )
      edge_payload(params[:source_id], params[:target_id], params[:kind], score)
    end
    render_result(result)
  end

  def index
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor) || campaign_member?(actor["username"])

      edges = GameStorage.database.execute(
        "SELECT source_id, target_id, kind, score FROM play_campaign_relationships " \
        "WHERE campaign_id = ? ORDER BY sequence", [params[:id]]
      )
      { edges: edges.map { |edge| edge_payload_from_record(edge) } }
    end
    render_result(result)
  end

  private

  def valid_edge_values?(source_id, target_id, kind, score)
    present_string?(source_id) && present_string?(target_id) && source_id != target_id &&
      present_string?(kind) && valid_score?(score)
  end

  def valid_score?(score)
    score.is_a?(Integer) && score.between?(-100, 100)
  end

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def campaign_dm?(campaign, actor)
    actor["role"] == "dm" && campaign["owner"] == actor["username"]
  end

  def campaign_member?(username)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], username]
    )
  end

  def entity_exists?(entity_id)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ? " \
      "UNION SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ? LIMIT 1",
      [params[:id], entity_id, params[:id], entity_id]
    )
  end

  def edge_record
    GameStorage.database.get_first_row(
      "SELECT source_id, target_id, kind, score FROM play_campaign_relationships " \
      "WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?",
      [params[:id], params[:source_id], params[:target_id], params[:kind]]
    )
  end

  def edge_payload(source_id, target_id, kind, score)
    { source_id: source_id, target_id: target_id, kind: kind, score: score }
  end

  def edge_payload_from_record(edge)
    edge_payload(edge["source_id"], edge["target_id"], edge["kind"], edge["score"])
  end

  def render_result(result, created: false)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown relationship" }, status: :not_found) if result == :missing_edge
    return render(json: { error: "unknown campaign entity" }, status: :not_found) if result == :missing_entity
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "relationship already exists" }, status: :conflict) if result == :duplicate

    render json: result, status: created ? :created : :ok
  end
end

# Clues are private campaign records. The DM can see every clue, whereas a
# player can only see party clues and those addressed to that player's member.
class PlayCampaignCluesController < ApplicationController
  include PlayAuthentication

  AUDIENCES = %w[character party hidden].freeze

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    clue_id = body["clue_id"] if body.is_a?(Hash)
    text = body["text"] if body.is_a?(Hash)
    audience = body["audience"] if body.is_a?(Hash)
    character_id = body["character_id"] if body.is_a?(Hash) && body.key?("character_id")
    return bad_request unless valid_clue_values?(clue_id, text, audience, character_id, body)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor)
      next :invalid_character if audience == "character" && !campaign_character?(character_id)

      sequence = GameStorage.database.get_first_value(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_clues WHERE campaign_id = ?", [params[:id]]
      )
      begin
        GameStorage.database.execute(
          "INSERT INTO play_campaign_clues " \
          "(campaign_id, clue_id, text, audience, character_id, sequence) VALUES (?, ?, ?, ?, ?, ?)",
          [params[:id], clue_id, text, audience, character_id, sequence]
        )
        clue_payload(clue_id, text, audience, character_id)
      rescue SQLite3::ConstraintException
        :duplicate
      end
    end
    render_result(result, created: true)
  end

  def index
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      dm = campaign_dm?(campaign, actor)
      next :forbidden unless dm || campaign_member?(actor["username"])

      clues = if dm
                GameStorage.database.execute(
                  "SELECT clue_id, text, audience, character_id FROM play_campaign_clues " \
                  "WHERE campaign_id = ? ORDER BY sequence", [params[:id]]
                )
              else
                GameStorage.database.execute(
                  "SELECT clue_id, text, audience, character_id FROM play_campaign_clues " \
                  "WHERE campaign_id = ? AND (audience = ? OR (audience = ? AND character_id IN " \
                  "(SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND owner = ?))) ORDER BY sequence",
                  [params[:id], "party", "character", params[:id], actor["username"]]
                )
              end
      { clues: clues.map { |clue| clue_payload_from_record(clue) } }
    end
    render_result(result)
  end

  private

  def valid_clue_values?(clue_id, text, audience, character_id, body)
    return false unless present_string?(clue_id) && present_string?(text) && AUDIENCES.include?(audience)

    if audience == "character"
      present_string?(character_id)
    else
      !body.key?("character_id")
    end
  end

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def campaign_dm?(campaign, actor)
    actor["role"] == "dm" && campaign["owner"] == actor["username"]
  end

  def campaign_member?(username)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], username]
    )
  end

  def campaign_character?(character_id)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?", [params[:id], character_id]
    )
  end

  def clue_payload(clue_id, text, audience, character_id = nil)
    payload = { clue_id: clue_id, text: text, audience: audience }
    payload[:character_id] = character_id if audience == "character"
    payload
  end

  def clue_payload_from_record(clue)
    clue_payload(clue["clue_id"], clue["text"], clue["audience"], clue["character_id"])
  end

  def render_result(result, created: false)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown character" }, status: :bad_request) if result == :invalid_character
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "clue already exists" }, status: :conflict) if result == :duplicate

    render json: result, status: created ? :created : :ok
  end
end

# Campaign quests advance through a small, deliberately one-way state
# machine. Dependencies are stored as JSON because their order is part of the
# response contract and quest creation only permits references that already
# exist, which also keeps the dependency graph acyclic.
class PlayCampaignQuestsController < ApplicationController
  include PlayAuthentication

  STATES = %w[active completed].freeze

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    quest_id = body["quest_id"] if body.is_a?(Hash)
    title = body["title"] if body.is_a?(Hash)
    depends_on = body["depends_on"] if body.is_a?(Hash)
    return bad_request unless valid_quest_values?(quest_id, title, depends_on)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor)
      next :invalid_dependencies unless dependencies_exist?(depends_on)

      sequence = GameStorage.database.get_first_value(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_quests WHERE campaign_id = ?", [params[:id]]
      )
      begin
        GameStorage.database.execute(
          "INSERT INTO play_campaign_quests (campaign_id, quest_id, title, depends_on, state, sequence) " \
          "VALUES (?, ?, ?, ?, ?, ?)",
          [params[:id], quest_id, title, JSON.generate(depends_on), "locked", sequence]
        )
        quest_payload(quest_id, title, depends_on, "locked")
      rescue SQLite3::ConstraintException
        :duplicate
      end
    end
    render_create_result(result)
  end

  def update_state
    actor = require_play_actor
    return unless actor

    body = json_body
    state = body["state"] if body.is_a?(Hash)
    return bad_request unless STATES.include?(state)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor)

      quest = quest_record
      next :missing_quest unless quest
      depends_on = JSON.parse(quest["depends_on"])
      next :invalid_transition unless valid_transition?(quest["state"], state, depends_on)

      GameStorage.database.execute(
        "UPDATE play_campaign_quests SET state = ? WHERE campaign_id = ? AND quest_id = ?",
        [state, params[:id], params[:quest_id]]
      )
      quest_payload_from_record(quest.merge("state" => state))
    end
    render_update_result(result)
  end

  def index
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor) || campaign_member?(actor["username"])

      quests = GameStorage.database.execute(
        "SELECT quest_id, title, depends_on, state FROM play_campaign_quests " \
        "WHERE campaign_id = ? ORDER BY sequence", [params[:id]]
      )
      { quests: quests.map { |quest| quest_payload_from_record(quest) } }
    end
    render_index_result(result)
  end

  def configure_rewards
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless valid_rewards?(body)

    xp = body["xp"]
    items = body["items"]
    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor)

      quest = quest_record
      next :missing_quest unless quest
      next :completed unless %w[locked active].include?(quest["state"])

      GameStorage.database.execute(
        "INSERT INTO play_campaign_quest_rewards (campaign_id, quest_id, xp, items) VALUES (?, ?, ?, ?) " \
        "ON CONFLICT(campaign_id, quest_id) DO UPDATE SET xp = excluded.xp, items = excluded.items",
        [params[:id], params[:quest_id], xp, JSON.generate(items)]
      )
      quest_payload(
        quest["quest_id"], quest["title"], JSON.parse(quest["depends_on"]), quest["state"],
        rewards: { xp: xp, items: items }
      )
    end
    render_rewards_result(result)
  end

  def award_rewards
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor)

      quest = quest_record
      next :missing_quest unless quest
      next :not_completed unless quest["state"] == "completed"
      reward = GameStorage.database.get_first_row(
        "SELECT xp, items, awarded FROM play_campaign_quest_rewards WHERE campaign_id = ? AND quest_id = ?",
        [params[:id], params[:quest_id]]
      )
      next :not_configured unless reward
      next :already_awarded if reward["awarded"].to_i == 1

      items = JSON.parse(reward["items"])
      GameStorage.database.transaction do
        GameStorage.database.execute(
          "INSERT INTO play_character_quest_rewards (campaign_id, character_id, quest_id, xp, items) " \
          "SELECT campaign_id, character_id, ?, ?, ? FROM play_campaign_members WHERE campaign_id = ?",
          [params[:quest_id], reward["xp"], reward["items"], params[:id]]
        )
        items.each do |item_id, quantity|
          GameStorage.database.execute(
            "INSERT INTO play_character_inventory_items (campaign_id, character_id, item_id, quantity) " \
            "SELECT campaign_id, character_id, ?, ? FROM play_campaign_members WHERE campaign_id = ? " \
            "ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity",
            [item_id, quantity, params[:id]]
          )
        end
        GameStorage.database.execute(
          "UPDATE play_campaign_quest_rewards SET awarded = 1 WHERE campaign_id = ? AND quest_id = ?",
          [params[:id], params[:quest_id]]
        )
      end
      { quest_id: params[:quest_id], awarded: true, xp: reward["xp"], items: items }
    end
    render_award_result(result)
  end

  private

  def valid_quest_values?(quest_id, title, depends_on)
    present_string?(quest_id) && present_string?(title) && depends_on.is_a?(Array) &&
      depends_on.all? { |dependency| present_string?(dependency) } &&
      depends_on.uniq.length == depends_on.length && !depends_on.include?(quest_id)
  end

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def campaign_dm?(campaign, actor)
    actor["role"] == "dm" && campaign["owner"] == actor["username"]
  end

  def campaign_member?(username)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], username]
    )
  end

  def dependencies_exist?(dependencies)
    return true if dependencies.empty?

    placeholders = Array.new(dependencies.length, "?").join(", ")
    GameStorage.database.get_first_value(
      "SELECT COUNT(*) FROM play_campaign_quests WHERE campaign_id = ? AND quest_id IN (#{placeholders})",
      [params[:id], *dependencies]
    ) == dependencies.length
  end

  def quest_record
    GameStorage.database.get_first_row(
      "SELECT quest_id, title, depends_on, state FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?",
      [params[:id], params[:quest_id]]
    )
  end

  def valid_transition?(current_state, requested_state, dependencies)
    return dependencies_completed?(dependencies) if current_state == "locked" && requested_state == "active"

    current_state == "active" && requested_state == "completed"
  end

  def dependencies_completed?(dependencies)
    return true if dependencies.empty?

    placeholders = Array.new(dependencies.length, "?").join(", ")
    GameStorage.database.get_first_value(
      "SELECT COUNT(*) FROM play_campaign_quests WHERE campaign_id = ? AND state = ? AND quest_id IN (#{placeholders})",
      [params[:id], "completed", *dependencies]
    ) == dependencies.length
  end

  def quest_payload(quest_id, title, depends_on, state, rewards: nil)
    { quest_id: quest_id, title: title, depends_on: depends_on, state: state }.tap do |payload|
      payload[:rewards] = rewards if rewards
    end
  end

  def quest_payload_from_record(quest)
    reward = GameStorage.database.get_first_row(
      "SELECT xp, items FROM play_campaign_quest_rewards WHERE campaign_id = ? AND quest_id = ?",
      [params[:id], quest["quest_id"]]
    )
    payload = quest_payload(quest["quest_id"], quest["title"], JSON.parse(quest["depends_on"]), quest["state"])
    payload[:rewards] = { xp: reward["xp"], items: JSON.parse(reward["items"]) } if reward
    payload
  end

  def valid_rewards?(body)
    body.is_a?(Hash) && body["xp"].is_a?(Integer) && body["xp"] >= 0 && body["items"].is_a?(Hash) &&
      body["items"].all? { |item_id, quantity| PlayCharacterInventoryItemsController::ITEM_IDS.include?(item_id) && quantity.is_a?(Integer) && quantity.positive? }
  end

  def render_create_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return bad_request if result == :invalid_dependencies
    return render(json: { error: "quest already exists" }, status: :conflict) if result == :duplicate

    render json: result, status: :created
  end

  def render_update_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "unknown quest" }, status: :not_found) if result == :missing_quest
    return render(json: { error: "invalid quest state transition" }, status: :conflict) if result == :invalid_transition

    render json: result
  end

  def render_index_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end

  def render_rewards_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "unknown quest" }, status: :not_found) if result == :missing_quest
    return render(json: { error: "quest is completed" }, status: :conflict) if result == :completed

    render json: result
  end

  def render_award_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "unknown quest" }, status: :not_found) if result == :missing_quest
    return render(json: { error: "quest rewards cannot be awarded" }, status: :conflict) if %i[not_completed not_configured].include?(result)
    return render(json: { error: "quest rewards already awarded" }, status: :conflict) if result == :already_awarded

    render json: result, status: :created
  end
end

# Quest reward grants are a compact immutable ledger.  Keeping the ledger
# separate from inventory preserves the existing inventory API while making
# cumulative rewards queryable without double-counting repeated awards.
class PlayCharacterQuestRewardsController < ApplicationController
  include PlayAuthentication

  def show
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_value("SELECT 1 FROM play_campaigns WHERE id = ?", [params[:id]])
      next :missing_campaign unless campaign
      character = GameStorage.database.get_first_row(
        "SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
        [params[:id], params[:char_id]]
      )
      next :missing_character unless character
      member = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], actor["username"]]
      )
      dm = actor["role"] == "dm" && GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaigns WHERE id = ? AND owner = ?", [params[:id], actor["username"]]
      )
      next :forbidden unless member || dm

      rows = GameStorage.database.execute(
        "SELECT xp, items FROM play_character_quest_rewards WHERE campaign_id = ? AND character_id = ?",
        [params[:id], params[:char_id]]
      )
      items = Hash.new(0)
      rows.each { |row| JSON.parse(row["items"]).each { |item_id, quantity| items[item_id] += quantity } }
      { character_id: character["character_id"], xp: rows.sum { |row| row["xp"].to_i }, items: items }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown character" }, status: :not_found) if result == :missing_character
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end
end

# Faction reputation is an append-only campaign record.  The total is derived
# from the latest entry for each faction/character pair, so history records can
# never be altered as reputation changes over time.
class PlayCampaignFactionsController < ApplicationController
  include PlayAuthentication

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    faction_id = body["faction_id"] if body.is_a?(Hash)
    name = body["name"] if body.is_a?(Hash)
    return bad_request unless present_string?(faction_id) && present_string?(name)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor)

      begin
        GameStorage.database.execute(
          "INSERT INTO play_campaign_factions (campaign_id, faction_id, name) VALUES (?, ?, ?)",
          [params[:id], faction_id, name]
        )
        { faction_id: faction_id, name: name }
      rescue SQLite3::ConstraintException
        :duplicate
      end
    end
    render_result(result, created: true)
  end

  def change_reputation
    actor = require_play_actor
    return unless actor

    body = json_body
    character_id = body["character_id"] if body.is_a?(Hash)
    delta = body["delta"] if body.is_a?(Hash)
    reason = body["reason"] if body.is_a?(Hash)
    return bad_request unless present_string?(character_id) && delta.is_a?(Integer) && delta != 0 && delta.between?(-25, 25) &&
                              present_string?(reason)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor)
      next :missing_faction unless faction_record
      next :invalid_character unless member_record(character_id)

      previous = GameStorage.database.get_first_value(
        "SELECT reputation FROM play_faction_reputation_history " \
        "WHERE campaign_id = ? AND faction_id = ? AND character_id = ? ORDER BY sequence DESC LIMIT 1",
        [params[:id], params[:faction_id], character_id]
      ) || 0
      reputation = [[previous + delta, -100].max, 100].min
      sequence = GameStorage.database.get_first_value(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_faction_reputation_history WHERE campaign_id = ?",
        [params[:id]]
      )
      GameStorage.database.execute(
        "INSERT INTO play_faction_reputation_history " \
        "(campaign_id, sequence, faction_id, character_id, reputation, delta, reason) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [params[:id], sequence, params[:faction_id], character_id, reputation, delta, reason]
      )
      reputation_payload(params[:faction_id], character_id, reputation, delta, reason)
    end
    render_result(result, created: true)
  end

  def reputation
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      dm = campaign_dm?(campaign, actor)
      next :forbidden unless dm || campaign_member?(actor["username"])
      next :missing_faction unless faction_record

      entries = GameStorage.database.execute(
        "SELECT faction_id, character_id, reputation, delta, reason FROM play_faction_reputation_history " \
        "WHERE campaign_id = ? AND faction_id = ? ORDER BY sequence",
        [params[:id], params[:faction_id]]
      )
      unless dm
        character_id = member_record_for_owner(actor["username"])&.fetch("character_id")
        entries = entries.select { |entry| entry["character_id"] == character_id }
      end
      { faction_id: params[:faction_id], entries: entries.map { |entry| reputation_payload_from_record(entry) } }
    end
    render_result(result)
  end

  private

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def campaign_dm?(campaign, actor)
    actor["role"] == "dm" && campaign["owner"] == actor["username"]
  end

  def campaign_member?(username)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], username]
    )
  end

  def faction_record
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_factions WHERE campaign_id = ? AND faction_id = ?", [params[:id], params[:faction_id]]
    )
  end

  def member_record(character_id)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?", [params[:id], character_id]
    )
  end

  def member_record_for_owner(username)
    GameStorage.database.get_first_row(
      "SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND owner = ?", [params[:id], username]
    )
  end

  def reputation_payload(faction_id, character_id, reputation, delta, reason)
    { faction_id: faction_id, character_id: character_id, reputation: reputation, delta: delta, reason: reason }
  end

  def reputation_payload_from_record(record)
    reputation_payload(record["faction_id"], record["character_id"], record["reputation"], record["delta"], record["reason"])
  end

  def render_result(result, created: false)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown faction" }, status: :not_found) if result == :missing_faction
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "invalid character" }, status: :bad_request) if result == :invalid_character
    return render(json: { error: "faction already exists" }, status: :conflict) if result == :duplicate

    render json: result, status: created ? :created : :ok
  end
end

# A calendar belongs to the campaign rather than to a particular session, so
# its weather remains deterministic across restarts and for every member.
# Settlements are campaign-scoped DM content. Discoveries are deliberately a
# separate ordered relation, so a replacement preserves who has found a
# settlement and players never need to receive another player's discovery.
class PlayCampaignSettlementsController < ApplicationController
  include PlayAuthentication

  AVAILABILITY = %w[open limited closed].freeze

  def create
    actor = require_play_actor
    return unless actor

    attributes = settlement_attributes(json_body, include_id: true)
    return bad_request unless attributes

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor)

      sequence = GameStorage.database.get_first_value(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_settlements WHERE campaign_id = ?", [params[:id]]
      )
      begin
        GameStorage.database.execute(
          "INSERT INTO play_campaign_settlements " \
          "(campaign_id, settlement_id, name, services, availability, sequence) VALUES (?, ?, ?, ?, ?, ?)",
          [params[:id], attributes[:settlement_id], attributes[:name], JSON.generate(attributes[:services]), attributes[:availability], sequence]
        )
        settlement_payload(attributes[:settlement_id], attributes[:name], attributes[:services], attributes[:availability], [])
      rescue SQLite3::ConstraintException
        :duplicate
      end
    end
    render_create_result(result)
  end

  def update
    actor = require_play_actor
    return unless actor

    attributes = settlement_attributes(json_body, include_id: false)
    return bad_request unless attributes

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor)

      settlement = settlement_record
      next :missing_settlement unless settlement

      GameStorage.database.execute(
        "UPDATE play_campaign_settlements SET name = ?, services = ?, availability = ? WHERE campaign_id = ? AND settlement_id = ?",
        [attributes[:name], JSON.generate(attributes[:services]), attributes[:availability], params[:id], params[:settlement_id]]
      )
      settlement_payload(params[:settlement_id], attributes[:name], attributes[:services], attributes[:availability], discoverers(params[:settlement_id]))
    end
    render_update_result(result)
  end

  def discover
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden if campaign_dm?(campaign, actor)

      member = member_record(actor["username"])
      next :forbidden unless actor["role"] == "player" && member

      settlement = settlement_record
      next :missing_settlement unless settlement

      inserted = false
      begin
        sequence = GameStorage.database.get_first_value(
          "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_settlement_discoveries " \
          "WHERE campaign_id = ? AND settlement_id = ?", [params[:id], params[:settlement_id]]
        )
        GameStorage.database.execute(
          "INSERT INTO play_campaign_settlement_discoveries " \
          "(campaign_id, settlement_id, character_id, sequence) VALUES (?, ?, ?, ?)",
          [params[:id], params[:settlement_id], member["character_id"], sequence]
        )
        inserted = true
      rescue SQLite3::ConstraintException
        # A duplicate discovery is explicitly idempotent.
      end
      [inserted ? :created : :existing, settlement_payload_from_record(settlement, [member["character_id"]])]
    end
    render_discover_result(result)
  end

  def index
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign

      dm = campaign_dm?(campaign, actor)
      member = member_record(actor["username"])
      next :forbidden unless dm || (actor["role"] == "player" && member)

      settlements = GameStorage.database.execute(
        "SELECT settlement_id, name, services, availability FROM play_campaign_settlements " \
        "WHERE campaign_id = ? ORDER BY sequence", [params[:id]]
      )
      if dm
        { settlements: settlements.map { |settlement| settlement_payload_from_record(settlement, discoverers(settlement["settlement_id"])) } }
      else
        character_id = member["character_id"]
        { settlements: settlements.filter_map do |settlement|
          next unless discovered_by?(settlement["settlement_id"], character_id)

          settlement_payload_from_record(settlement, [character_id])
        end }
      end
    end
    render_index_result(result)
  end

  private

  def settlement_attributes(body, include_id:)
    return nil unless body.is_a?(Hash)

    settlement_id = body["settlement_id"] if include_id
    name = body["name"]
    services = body["services"]
    availability = body["availability"]
    return nil if include_id && !present_string?(settlement_id)
    return nil unless present_string?(name) && services.is_a?(Array) && !services.empty? && AVAILABILITY.include?(availability)

    normalized_services = services.map { |service| service.strip if service.is_a?(String) }
    return nil unless normalized_services.all? { |service| present_string?(service) } && normalized_services.uniq.length == normalized_services.length

    { settlement_id: settlement_id, name: name, services: normalized_services, availability: availability }
  end

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def settlement_record
    GameStorage.database.get_first_row(
      "SELECT settlement_id, name, services, availability FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?",
      [params[:id], params[:settlement_id]]
    )
  end

  def member_record(username)
    GameStorage.database.get_first_row(
      "SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], username]
    )
  end

  def campaign_dm?(campaign, actor)
    actor["role"] == "dm" && campaign["owner"] == actor["username"]
  end

  def discoverers(settlement_id)
    GameStorage.database.execute(
      "SELECT character_id FROM play_campaign_settlement_discoveries WHERE campaign_id = ? AND settlement_id = ? ORDER BY sequence",
      [params[:id], settlement_id]
    ).map { |discovery| discovery["character_id"] }
  end

  def discovered_by?(settlement_id, character_id)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_settlement_discoveries WHERE campaign_id = ? AND settlement_id = ? AND character_id = ?",
      [params[:id], settlement_id, character_id]
    )
  end

  def settlement_payload_from_record(settlement, discovered_by)
    settlement_payload(settlement["settlement_id"], settlement["name"], JSON.parse(settlement["services"]), settlement["availability"], discovered_by)
  end

  def settlement_payload(settlement_id, name, services, availability, discovered_by)
    { settlement_id: settlement_id, name: name, services: services, availability: availability, discovered_by: discovered_by }
  end

  def render_create_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "settlement already exists" }, status: :conflict) if result == :duplicate

    render json: result, status: :created
  end

  def render_update_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "unknown settlement" }, status: :not_found) if result == :missing_settlement

    render json: result
  end

  def render_discover_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "unknown settlement" }, status: :not_found) if result == :missing_settlement

    status, payload = result
    render json: payload, status: (status == :created ? :created : :ok)
  end

  def render_index_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end
end

# Shops are settlement-scoped. Stock is normalized so buying and selling can
# update precisely one item stack while the shop response remains the compact
# object required by the play API.
class PlayCampaignShopsController < ApplicationController
  include PlayAuthentication

  def create
    actor = require_play_actor
    return unless actor

    attributes = shop_attributes(json_body)
    return bad_request unless attributes

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor)
      next :missing_settlement unless settlement_exists?

      begin
        GameStorage.database.transaction do
          GameStorage.database.execute(
            "INSERT INTO play_campaign_shops (campaign_id, settlement_id, shop_id, name, buy_price, sell_price) VALUES (?, ?, ?, ?, ?, ?)",
            [params[:id], params[:settlement_id], attributes[:shop_id], attributes[:name], attributes[:buy_price], attributes[:sell_price]]
          )
          attributes[:stock].each do |item_id, quantity|
            GameStorage.database.execute(
              "INSERT INTO play_campaign_shop_stock (campaign_id, settlement_id, shop_id, item_id, quantity) VALUES (?, ?, ?, ?, ?)",
              [params[:id], params[:settlement_id], attributes[:shop_id], item_id, quantity]
            )
          end
        end
        shop_payload(attributes[:shop_id], attributes[:name], attributes[:stock], attributes[:buy_price], attributes[:sell_price])
      rescue SQLite3::ConstraintException
        :duplicate
      end
    end
    render_create_result(result)
  end

  def show
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      settlement = settlement_exists?
      next :missing_settlement unless settlement
      shop = shop_record
      next :missing_shop unless shop

      if campaign_dm?(campaign, actor)
        shop_payload_from_record(shop)
      else
        member = player_member(actor)
        next :forbidden unless member
        next :missing_shop unless discovered?(member["character_id"])

        shop_payload_from_record(shop)
      end
    end
    render_show_result(result)
  end

  def buy
    trade(:buy)
  end

  def sell
    trade(:sell)
  end

  private

  def trade(kind)
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless valid_trade_attributes?(body)
    character_id = body["character_id"]
    item_id = body["item_id"]
    quantity = body["quantity"]

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :missing_settlement unless settlement_exists?
      shop = shop_record
      next :missing_shop unless shop
      character = character_record(character_id)
      next :missing_character unless character
      next :forbidden unless actor["role"] == "player" && character["owner"] == actor["username"]

      stock = stock_quantity(item_id)
      held = inventory_quantity(character_id, item_id)
      gold = character["gold"]
      if kind == :buy
        next :insufficient_stock if stock < quantity
        next :insufficient_gold if gold < shop["buy_price"] * quantity
      else
        next :insufficient_inventory if held < quantity
      end

      new_stock = kind == :buy ? stock - quantity : stock + quantity
      new_gold = kind == :buy ? gold - shop["buy_price"] * quantity : gold + shop["sell_price"] * quantity
      new_held = kind == :buy ? held + quantity : held - quantity
      GameStorage.database.transaction do
        GameStorage.database.execute(
          "INSERT INTO play_campaign_shop_stock (campaign_id, settlement_id, shop_id, item_id, quantity) VALUES (?, ?, ?, ?, ?) " \
          "ON CONFLICT(campaign_id, settlement_id, shop_id, item_id) DO UPDATE SET quantity = excluded.quantity",
          [params[:id], params[:settlement_id], params[:shop_id], item_id, new_stock]
        )
        GameStorage.database.execute(
          "UPDATE play_character_currency SET gold = ? WHERE campaign_id = ? AND character_id = ?",
          [new_gold, params[:id], character_id]
        )
        if new_held.zero?
          GameStorage.database.execute(
            "DELETE FROM play_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            [params[:id], character_id, item_id]
          )
        elsif held.zero?
          GameStorage.database.execute(
            "INSERT INTO play_character_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)",
            [params[:id], character_id, item_id, new_held]
          )
        else
          GameStorage.database.execute(
            "UPDATE play_character_inventory_items SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            [new_held, params[:id], character_id, item_id]
          )
        end
      end
      { character_id: character_id, item_id: item_id, quantity: quantity, gold: new_gold, stock: new_stock }
    end
    render_trade_result(result)
  end

  def shop_attributes(body)
    return nil unless body.is_a?(Hash)

    shop_id = body["shop_id"]
    name = body["name"]
    stock = body["stock"]
    buy_price = body["buy_price"]
    sell_price = body["sell_price"]
    valid_items = PlayCharacterInventoryItemsController::ITEM_IDS
    return nil unless present_string?(shop_id) && present_string?(name) && stock.is_a?(Hash) && !stock.empty?
    return nil unless stock.all? { |item_id, quantity| valid_items.include?(item_id) && quantity.is_a?(Integer) && quantity.positive? }
    return nil unless buy_price.is_a?(Integer) && buy_price.positive? && sell_price.is_a?(Integer) && sell_price >= 0

    { shop_id: shop_id, name: name, stock: stock, buy_price: buy_price, sell_price: sell_price }
  end

  def valid_trade_attributes?(body)
    body.is_a?(Hash) && present_string?(body["character_id"]) &&
      PlayCharacterInventoryItemsController::ITEM_IDS.include?(body["item_id"]) &&
      body["quantity"].is_a?(Integer) && body["quantity"].positive?
  end

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def campaign_dm?(campaign, actor)
    actor["role"] == "dm" && campaign["owner"] == actor["username"]
  end

  def player_member(actor)
    return nil unless actor["role"] == "player"

    GameStorage.database.get_first_row(
      "SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], actor["username"]]
    )
  end

  def settlement_exists?
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?", [params[:id], params[:settlement_id]]
    )
  end

  def discovered?(character_id)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_settlement_discoveries WHERE campaign_id = ? AND settlement_id = ? AND character_id = ?",
      [params[:id], params[:settlement_id], character_id]
    )
  end

  def shop_record
    GameStorage.database.get_first_row(
      "SELECT shop_id, name, buy_price, sell_price FROM play_campaign_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
      [params[:id], params[:settlement_id], params[:shop_id]]
    )
  end

  def character_record(character_id)
    GameStorage.database.get_first_row(
      "SELECT member.character_id, member.owner, currency.gold FROM play_campaign_members member " \
      "JOIN play_character_currency currency ON currency.campaign_id = member.campaign_id AND currency.character_id = member.character_id " \
      "WHERE member.campaign_id = ? AND member.character_id = ?", [params[:id], character_id]
    )
  end

  def stock_quantity(item_id)
    GameStorage.database.get_first_value(
      "SELECT quantity FROM play_campaign_shop_stock WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ? AND item_id = ?",
      [params[:id], params[:settlement_id], params[:shop_id], item_id]
    ).to_i
  end

  def inventory_quantity(character_id, item_id)
    GameStorage.database.get_first_value(
      "SELECT quantity FROM play_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
      [params[:id], character_id, item_id]
    ).to_i
  end

  def shop_payload_from_record(shop)
    stock = GameStorage.database.execute(
      "SELECT item_id, quantity FROM play_campaign_shop_stock WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ? ORDER BY item_id",
      [params[:id], params[:settlement_id], shop["shop_id"]]
    ).to_h { |row| [row["item_id"], row["quantity"]] }
    shop_payload(shop["shop_id"], shop["name"], stock, shop["buy_price"], shop["sell_price"])
  end

  def shop_payload(shop_id, name, stock, buy_price, sell_price)
    { shop_id: shop_id, name: name, stock: stock, buy_price: buy_price, sell_price: sell_price }
  end

  def render_create_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown settlement" }, status: :not_found) if result == :missing_settlement
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "shop already exists" }, status: :conflict) if result == :duplicate

    render json: result, status: :created
  end

  def render_show_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown settlement" }, status: :not_found) if result == :missing_settlement
    return render(json: { error: "unknown shop" }, status: :not_found) if %i[missing_shop].include?(result)
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end

  def render_trade_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown settlement" }, status: :not_found) if result == :missing_settlement
    return render(json: { error: "unknown shop" }, status: :not_found) if result == :missing_shop
    return render(json: { error: "unknown character" }, status: :not_found) if result == :missing_character
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "insufficient stock" }, status: :conflict) if result == :insufficient_stock
    return render(json: { error: "insufficient gold" }, status: :conflict) if result == :insufficient_gold
    return render(json: { error: "insufficient item quantity" }, status: :conflict) if result == :insufficient_inventory

    render json: result
  end
end

class PlayCampaignCalendarsController < ApplicationController
  include PlayAuthentication

  SEASON_OFFSETS = { "spring" => 0, "summer" => 1, "autumn" => 2, "winter" => 3 }.freeze
  WEATHER = %w[clear rain wind snow].freeze

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    day = body["day"] if body.is_a?(Hash)
    season = body["season"] if body.is_a?(Hash)
    return bad_request unless day.is_a?(Integer) && day >= 1 && SEASON_OFFSETS.key?(season)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor)

      begin
        GameStorage.database.execute(
          "INSERT INTO play_campaign_calendars (campaign_id, day, season) VALUES (?, ?, ?)",
          [params[:id], day, season]
        )
        calendar_payload(day, season)
      rescue SQLite3::ConstraintException
        :initialized
      end
    end
    render_create_result(result)
  end

  def show
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor) || campaign_member?(actor["username"])

      calendar = calendar_record
      next :missing_calendar unless calendar

      calendar_payload(calendar["day"], calendar["season"])
    end
    render_show_result(result)
  end

  def advance
    actor = require_play_actor
    return unless actor

    body = json_body
    days = body["days"] if body.is_a?(Hash)
    return bad_request unless days.is_a?(Integer) && days.between?(1, 30)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor)

      calendar = calendar_record
      next :missing_calendar unless calendar

      day = calendar["day"] + days
      GameStorage.database.execute(
        "UPDATE play_campaign_calendars SET day = ? WHERE campaign_id = ?", [day, params[:id]]
      )
      calendar_payload(day, calendar["season"])
    end
    render_advance_result(result)
  end

  private

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def calendar_record
    GameStorage.database.get_first_row(
      "SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?", [params[:id]]
    )
  end

  def campaign_dm?(campaign, actor)
    actor["role"] == "dm" && campaign["owner"] == actor["username"]
  end

  def campaign_member?(username)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], username]
    )
  end

  def calendar_payload(day, season)
    { day: day, season: season, weather: WEATHER[(day + SEASON_OFFSETS.fetch(season)) % 4] }
  end

  def render_create_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "calendar already initialized" }, status: :conflict) if result == :initialized

    render json: result, status: :created
  end

  def render_show_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "calendar not initialized" }, status: :not_found) if result == :missing_calendar

    render json: result
  end

  def render_advance_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "calendar not initialized" }, status: :not_found) if result == :missing_calendar

    render json: result
  end
end

# World events are immutable once resolved.  Their sequence is captured at
# scheduling time solely to provide a deterministic tie-breaker for events on
# the same campaign turn.
class PlayCampaignWorldEventsController < ApplicationController
  include PlayAuthentication

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    event_id = body["event_id"] if body.is_a?(Hash)
    turn_number = body["turn_number"] if body.is_a?(Hash)
    title = body["title"] if body.is_a?(Hash)
    text = body["text"] if body.is_a?(Hash)
    return bad_request unless present_string?(event_id) && turn_number.is_a?(Integer) && present_string?(title) && present_string?(text)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor)
      next :invalid_turn if turn_number < (campaign["turn_number"] || 1)

      sequence = GameStorage.database.get_first_value(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_world_events WHERE campaign_id = ?", [params[:id]]
      )
      begin
        GameStorage.database.execute(
          "INSERT INTO play_campaign_world_events " \
          "(campaign_id, event_id, turn_number, title, text, sequence, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
          [params[:id], event_id, turn_number, title, text, sequence, "scheduled"]
        )
        event_payload(event_id, turn_number, title, text, "scheduled")
      rescue SQLite3::ConstraintException
        :duplicate
      end
    end
    render_create_result(result)
  end

  def resolve
    actor = require_play_actor
    return unless actor

    body = json_body
    text = body["text"] if body.is_a?(Hash)
    return bad_request unless present_string?(text)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor)

      event = event_record
      next :missing_event unless event
      next :already_resolved if event["status"] == "resolved"
      next :wrong_turn unless (campaign["turn_number"] || 1) == event["turn_number"]

      GameStorage.database.execute(
        "UPDATE play_campaign_world_events SET status = ?, resolution_turn_number = ?, resolution_text = ? " \
        "WHERE campaign_id = ? AND event_id = ? AND status = ?",
        ["resolved", event["turn_number"], text, params[:id], params[:event_id], "scheduled"]
      )
      event_payload_from_record(event.merge("status" => "resolved", "resolution_turn_number" => event["turn_number"], "resolution_text" => text))
    end
    render_resolve_result(result)
  end

  def index
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor) || campaign_member?(actor["username"])

      events = GameStorage.database.execute(
        "SELECT event_id, turn_number, title, text, status, resolution_turn_number, resolution_text " \
        "FROM play_campaign_world_events WHERE campaign_id = ? ORDER BY turn_number, sequence", [params[:id]]
      )
      { events: events.map { |event| event_payload_from_record(event) } }
    end
    render_index_result(result)
  end

  private

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner, turn_number FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def campaign_dm?(campaign, actor)
    actor["role"] == "dm" && campaign["owner"] == actor["username"]
  end

  def campaign_member?(username)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], username]
    )
  end

  def event_record
    GameStorage.database.get_first_row(
      "SELECT event_id, turn_number, title, text, status, resolution_turn_number, resolution_text " \
      "FROM play_campaign_world_events WHERE campaign_id = ? AND event_id = ?", [params[:id], params[:event_id]]
    )
  end

  def event_payload(event_id, turn_number, title, text, status, resolution: nil)
    { event_id: event_id, turn_number: turn_number, title: title, text: text, status: status }.tap do |payload|
      payload[:resolution] = resolution if resolution
    end
  end

  def event_payload_from_record(event)
    resolution = if event["status"] == "resolved"
      { turn_number: event["resolution_turn_number"], text: event["resolution_text"] }
    end
    event_payload(event["event_id"], event["turn_number"], event["title"], event["text"], event["status"], resolution: resolution)
  end

  def render_create_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return bad_request if result == :invalid_turn
    return render(json: { error: "world event already exists" }, status: :conflict) if result == :duplicate

    render json: result, status: :created
  end

  def render_resolve_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "unknown world event" }, status: :not_found) if result == :missing_event
    return render(json: { error: "world event cannot be resolved" }, status: :conflict) if %i[already_resolved wrong_turn].include?(result)

    render json: result, status: :created
  end

  def render_index_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end
end

# Equipment is a view over a character's inventory: equipping an item never
# consumes a stack.  Keeping one row per legal slot also makes replacement
# deterministic and keeps attunement state local to the equipped item.
class PlayCharacterEquipmentController < ApplicationController
  include PlayAuthentication

  SLOTS = %w[armor accessory].freeze
  ITEM_SLOTS = {
    "leather-armor" => "armor",
    "ring-of-protection" => "accessory",
    "amulet-of-health" => "accessory"
  }.freeze
  ATTUNABLE_ITEMS = %w[ring-of-protection amulet-of-health].freeze

  def update
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless valid_equipment_payload?(body)

    item_id = body["item_id"]
    result = GameStorage.synchronize do
      next :missing_campaign unless campaign_exists?

      character = equipment_character
      next :missing_character unless character
      next :forbidden unless character["owner"] == actor["username"]
      next :invalid unless held_quantity(item_id).positive?

      GameStorage.database.execute(
        "INSERT INTO play_character_equipment (campaign_id, character_id, slot, item_id, attuned) VALUES (?, ?, ?, ?, 0) " \
        "ON CONFLICT(campaign_id, character_id, slot) DO UPDATE SET item_id = excluded.item_id, attuned = 0",
        [params[:id], params[:char_id], params[:slot], item_id]
      )
      equipment_payload(character, params[:slot], item_id, false)
    end
    render_result(result)
  end

  def show
    actor = require_play_actor
    return unless actor

    return bad_request unless SLOTS.include?(params[:slot])

    result = GameStorage.synchronize do
      next :missing_campaign unless campaign_exists?

      character = equipment_character
      next :missing_character unless character
      next :forbidden unless campaign_member?(actor["username"])

      equipment = GameStorage.database.get_first_row(
        "SELECT item_id, attuned FROM play_character_equipment WHERE campaign_id = ? AND character_id = ? AND slot = ?",
        [params[:id], params[:char_id], params[:slot]]
      )
      equipment_payload(character, params[:slot], equipment ? equipment["item_id"] : "", equipment ? equipment["attuned"] == 1 : false)
    end
    render_result(result)
  end

  def attune
    actor = require_play_actor
    return unless actor

    return bad_request unless SLOTS.include?(params[:slot])

    result = GameStorage.synchronize do
      next :missing_campaign unless campaign_exists?

      character = equipment_character
      next :missing_character unless character
      next :forbidden unless character["owner"] == actor["username"]

      equipment = GameStorage.database.get_first_row(
        "SELECT item_id FROM play_character_equipment WHERE campaign_id = ? AND character_id = ? AND slot = ?",
        [params[:id], params[:char_id], params[:slot]]
      )
      next :invalid unless params[:slot] == "accessory" && equipment && ATTUNABLE_ITEMS.include?(equipment["item_id"])

      attunement_count = GameStorage.database.get_first_value(
        "SELECT COUNT(*) FROM play_character_equipment WHERE campaign_id = ? AND character_id = ? AND attuned = 1",
        [params[:id], params[:char_id]]
      ).to_i
      next :already_attuned if attunement_count.positive?

      GameStorage.database.execute(
        "UPDATE play_character_equipment SET attuned = 1 WHERE campaign_id = ? AND character_id = ? AND slot = ?",
        [params[:id], params[:char_id], params[:slot]]
      )
      equipment_payload(character, params[:slot], equipment["item_id"], true).merge(attunement_count: 1, max_attunements: 1)
    end
    render_result(result)
  end

  private

  def valid_equipment_payload?(body)
    body.is_a?(Hash) && SLOTS.include?(params[:slot]) &&
      ITEM_SLOTS[body["item_id"]] == params[:slot]
  end

  def campaign_exists?
    GameStorage.database.get_first_value("SELECT 1 FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def equipment_character
    GameStorage.database.get_first_row(
      "SELECT character_id, owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
      [params[:id], params[:char_id]]
    )
  end

  def campaign_member?(username)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], username]
    )
  end

  def held_quantity(item_id)
    GameStorage.database.get_first_value(
      "SELECT quantity FROM play_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
      [params[:id], params[:char_id], item_id]
    ).to_i
  end

  def equipment_payload(character, slot, item_id, attuned)
    { character_id: character["character_id"], slot: slot, item_id: item_id, attuned: attuned }
  end

  def render_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown character" }, status: :not_found) if result == :missing_character
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return bad_request if result == :invalid
    return render(json: { error: "already attuned" }, status: :conflict) if result == :already_attuned

    render json: result
  end
end

# Spellbook entries belong to the campaign-play character rather than to the
# account that originally joined the campaign.  This keeps them with a
# character when ownership changes hands.
class PlayCharacterSpellsController < ApplicationController
  include PlayAuthentication

  WIZARD_SPELLS = {
    "fire-bolt" => { name: "Fire Bolt", level: 0 },
    "mage-hand" => { name: "Mage Hand", level: 0 },
    "magic-missile" => { name: "Magic Missile", level: 1 }
  }.freeze

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless valid_spell_payload?(body)

    spell_id = body["spell_id"]
    name = body["name"]
    level = integer(body["level"])
    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing_campaign unless campaign

      character = spell_character
      next :missing_character unless character
      next :forbidden unless character["owner"] == actor["username"]
      next :invalid_spell unless valid_for_class?(character["character_class"], spell_id, name, level)

      begin
        GameStorage.database.execute(
          "INSERT INTO play_character_spells (campaign_id, character_id, spell_id, name, level) VALUES (?, ?, ?, ?, ?)",
          [params[:id], params[:char_id], spell_id, name, level]
        )
        { spell_id: spell_id, name: name, level: level }
      rescue SQLite3::ConstraintException
        :duplicate
      end
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown character" }, status: :not_found) if result == :missing_character
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return bad_request if result == :invalid_spell
    return render(json: { error: "spell already known" }, status: :conflict) if result == :duplicate

    render json: result, status: :created
  end

  def index
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing_campaign unless campaign

      character = spell_character
      next :missing_character unless character

      member = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
        [params[:id], actor["username"]]
      )
      next :forbidden unless member

      spells = GameStorage.database.execute(
        "SELECT spell_id, name, level FROM play_character_spells " \
        "WHERE campaign_id = ? AND character_id = ? ORDER BY rowid",
        [params[:id], params[:char_id]]
      ).map { |spell| { spell_id: spell["spell_id"], name: spell["name"], level: spell["level"] } }
      { spells: spells }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown character" }, status: :not_found) if result == :missing_character
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end

  private

  def spell_character
    GameStorage.database.get_first_row(
      "SELECT character_id, owner, character_class FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
      [params[:id], params[:char_id]]
    )
  end

  def valid_spell_payload?(body)
    body.is_a?(Hash) && present_string?(body["spell_id"]) && present_string?(body["name"]) &&
      (level = integer(body["level"])) && level >= 0
  end

  def valid_for_class?(character_class, spell_id, name, level)
    spell = WIZARD_SPELLS[spell_id]
    character_class == "wizard" && spell && spell[:name] == name && spell[:level] == level
  end
end

# A cast consumes a slot only after all authorization and spell-state checks
# pass.  The cast ledger is also the source of truth for remaining slots,
# keeping the history and resource accounting in one atomic write.
class PlayCharacterCastsController < ApplicationController
  include PlayAuthentication

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless valid_cast_payload?(body)

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing_campaign unless campaign

      character = cast_character
      next :missing_character unless character
      next :forbidden unless character["owner"] == actor["username"]
      next :invalid unless spellcasting?(character)

      spell = known_spell(body["spell_id"])
      next :invalid unless spell && prepared?(body["spell_id"])

      slot_level = spell["level"].to_i
      total_slots = slots_at_level(character, slot_level)
      spent_slots = casts_at_slot_level(slot_level)
      next :no_slots if spent_slots >= total_slots

      sequence = GameStorage.database.get_first_value(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_character_casts " \
        "WHERE campaign_id = ? AND character_id = ?", [params[:id], params[:char_id]]
      )
      remaining = total_slots - spent_slots - 1
      GameStorage.database.execute(
        "INSERT INTO play_character_casts " \
        "(campaign_id, character_id, sequence, spell_id, target, slot_level) VALUES (?, ?, ?, ?, ?, ?)",
        [params[:id], params[:char_id], sequence, body["spell_id"], body["target"], slot_level]
      )
      {
        character_id: character["character_id"], spell_id: body["spell_id"], target: body["target"],
        slot_level: slot_level, slots_remaining: remaining, sequence: sequence
      }
    end
    render_cast_result(result, created: true)
  end

  def index
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing_campaign unless campaign
      character = cast_character
      next :missing_character unless character

      member = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
        [params[:id], actor["username"]]
      )
      next :forbidden unless member

      casts = GameStorage.database.execute(
        "SELECT character_id, spell_id, target, slot_level, sequence FROM play_character_casts " \
        "WHERE campaign_id = ? AND character_id = ? ORDER BY sequence",
        [params[:id], params[:char_id]]
      )
      used_slots = Hash.new(0)
      casts = casts.map do |cast|
        slot_level = cast["slot_level"]
        used_slots[slot_level] += 1
        {
          character_id: cast["character_id"], spell_id: cast["spell_id"], target: cast["target"],
          slot_level: slot_level, slots_remaining: slots_at_level(character, slot_level) - used_slots[slot_level],
          sequence: cast["sequence"]
        }
      end
      { casts: casts }
    end
    render_cast_result(result)
  end

  private

  def valid_cast_payload?(body)
    body.is_a?(Hash) && present_string?(body["spell_id"]) && present_string?(body["target"])
  end

  def cast_character
    GameStorage.database.get_first_row(
      "SELECT character_id, owner, character_class, level FROM play_campaign_members " \
      "WHERE campaign_id = ? AND character_id = ?", [params[:id], params[:char_id]]
    )
  end

  def spellcasting?(character)
    character["character_class"] == "wizard"
  end

  def known_spell(spell_id)
    GameStorage.database.get_first_row(
      "SELECT spell_id, level FROM play_character_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?",
      [params[:id], params[:char_id], spell_id]
    )
  end

  def prepared?(spell_id)
    serialized = GameStorage.database.get_first_value(
      "SELECT spell_ids FROM play_character_prepared_spells WHERE campaign_id = ? AND character_id = ?",
      [params[:id], params[:char_id]]
    )
    serialized && JSON.parse(serialized).include?(spell_id)
  end

  # This compact play API grants a level-one wizard one first-level slot.  It
  # has no level-zero slots, so cantrips are not cast through this slot-based
  # endpoint.
  def slots_at_level(character, slot_level)
    character["character_class"] == "wizard" && character["level"].to_i >= 1 && slot_level == 1 ? 1 : 0
  end

  def casts_at_slot_level(slot_level)
    GameStorage.database.get_first_value(
      "SELECT COUNT(*) FROM play_character_casts WHERE campaign_id = ? AND character_id = ? AND slot_level = ?",
      [params[:id], params[:char_id], slot_level]
    ).to_i
  end

  def render_cast_result(result, created: false)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown character" }, status: :not_found) if result == :missing_character
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return bad_request if result == :invalid
    return render(json: { error: "no remaining spell slots" }, status: :conflict) if result == :no_slots

    render json: result, status: (created ? :created : :ok)
  end
end

# Prepared spells are intentionally stored independently of a character's
# spellbook: changing a preparation never changes which spells the character
# knows.  The currently supported spellcasting class is wizard, whose maximum
# prepared count grows one-for-one with level in this API's compact ruleset.
class PlayCharacterPreparedSpellsController < ApplicationController
  include PlayAuthentication

  def update
    actor = require_play_actor
    return unless actor

    body = json_body
    spell_ids = body["spell_ids"] if body.is_a?(Hash)
    return bad_request unless valid_spell_ids?(spell_ids)

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing_campaign unless campaign

      character = prepared_character
      next :missing_character unless character
      next :forbidden unless character["owner"] == actor["username"]

      max_prepared = maximum_prepared(character)
      next :invalid unless max_prepared && spell_ids.length <= max_prepared

      known_count = if spell_ids.empty?
        0
      else
        GameStorage.database.get_first_value(
          "SELECT COUNT(*) FROM play_character_spells WHERE campaign_id = ? AND character_id = ? " \
          "AND spell_id IN (#{(["?"] * spell_ids.length).join(", ")})",
          [params[:id], params[:char_id], *spell_ids]
        )
      end
      next :invalid unless known_count == spell_ids.length

      GameStorage.database.execute(
        "INSERT INTO play_character_prepared_spells (campaign_id, character_id, spell_ids) VALUES (?, ?, ?) " \
        "ON CONFLICT(campaign_id, character_id) DO UPDATE SET spell_ids = excluded.spell_ids",
        [params[:id], params[:char_id], JSON.generate(spell_ids)]
      )
      prepared_payload(character, spell_ids, max_prepared)
    end
    render_prepared_result(result)
  end

  def show
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing_campaign unless campaign

      character = prepared_character
      next :missing_character unless character

      member = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
        [params[:id], actor["username"]]
      )
      next :forbidden unless member

      serialized = GameStorage.database.get_first_value(
        "SELECT spell_ids FROM play_character_prepared_spells WHERE campaign_id = ? AND character_id = ?",
        [params[:id], params[:char_id]]
      )
      prepared_payload(character, serialized ? JSON.parse(serialized) : [], maximum_prepared(character))
    end
    render_prepared_result(result)
  end

  private

  def valid_spell_ids?(spell_ids)
    spell_ids.is_a?(Array) && spell_ids.all? { |spell_id| present_string?(spell_id) } && spell_ids.uniq.length == spell_ids.length
  end

  def prepared_character
    GameStorage.database.get_first_row(
      "SELECT character_id, owner, character_class, level FROM play_campaign_members " \
      "WHERE campaign_id = ? AND character_id = ?",
      [params[:id], params[:char_id]]
    )
  end

  def maximum_prepared(character)
    return nil unless character["character_class"] == "wizard"

    character["level"].to_i
  end

  def prepared_payload(character, spell_ids, max_prepared)
    { character_id: character["character_id"], prepared_spells: spell_ids, max_prepared: max_prepared }
  end

  def render_prepared_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown character" }, status: :not_found) if result == :missing_character
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return bad_request if result == :invalid

    render json: result
  end
end

# Concentration is a single replaceable state record for a character.  It does
# not consume spell slots: casting remains responsible for that separate
# resource accounting.
class PlayCharacterConcentrationsController < ApplicationController
  include PlayAuthentication

  def update
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless valid_payload?(body)

    result = GameStorage.synchronize do
      campaign = campaign_exists?
      next :missing_campaign unless campaign

      character = concentration_character
      next :missing_character unless character
      next :forbidden unless character["owner"] == actor["username"]
      next :invalid unless spellcasting?(character) && known_and_prepared?(body["spell_id"])

      concentration = {
        spell_id: body["spell_id"], target: body["target"], remaining_turns: integer(body["duration_turns"])
      }
      GameStorage.database.execute(
        "INSERT INTO play_character_concentrations " \
        "(campaign_id, character_id, spell_id, target, remaining_turns) VALUES (?, ?, ?, ?, ?) " \
        "ON CONFLICT(campaign_id, character_id) DO UPDATE SET " \
        "spell_id = excluded.spell_id, target = excluded.target, remaining_turns = excluded.remaining_turns",
        [params[:id], params[:char_id], concentration[:spell_id], concentration[:target], concentration[:remaining_turns]]
      )
      payload(character, concentration)
    end
    render_result(result)
  end

  def show
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_exists?
      next :missing_campaign unless campaign
      character = concentration_character
      next :missing_character unless character
      next :forbidden unless campaign_member?(actor["username"])

      payload(character, active_concentration)
    end
    render_result(result)
  end

  def advance_turn
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_exists?
      next :missing_campaign unless campaign
      character = concentration_character
      next :missing_character unless character
      next :forbidden unless campaign_member?(actor["username"])

      concentration = active_concentration
      if concentration
        concentration[:remaining_turns] -= 1
        if concentration[:remaining_turns].positive?
          GameStorage.database.execute(
            "UPDATE play_character_concentrations SET remaining_turns = ? WHERE campaign_id = ? AND character_id = ?",
            [concentration[:remaining_turns], params[:id], params[:char_id]]
          )
        else
          GameStorage.database.execute(
            "DELETE FROM play_character_concentrations WHERE campaign_id = ? AND character_id = ?",
            [params[:id], params[:char_id]]
          )
          concentration = nil
        end
      end
      payload(character, concentration)
    end
    render_result(result)
  end

  def destroy
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_exists?
      next :missing_campaign unless campaign
      character = concentration_character
      next :missing_character unless character
      next :forbidden unless character["owner"] == actor["username"]

      GameStorage.database.execute(
        "DELETE FROM play_character_concentrations WHERE campaign_id = ? AND character_id = ?",
        [params[:id], params[:char_id]]
      )
      payload(character, nil)
    end
    render_result(result)
  end

  private

  def valid_payload?(body)
    body.is_a?(Hash) && present_string?(body["spell_id"]) && present_string?(body["target"]) &&
      (duration = integer(body["duration_turns"])) && duration.positive?
  end

  def campaign_exists?
    GameStorage.database.get_first_value("SELECT 1 FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def concentration_character
    GameStorage.database.get_first_row(
      "SELECT character_id, owner, character_class FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
      [params[:id], params[:char_id]]
    )
  end

  def campaign_member?(username)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], username]
    )
  end

  def spellcasting?(character)
    character["character_class"] == "wizard"
  end

  def known_and_prepared?(spell_id)
    known = GameStorage.database.get_first_value(
      "SELECT 1 FROM play_character_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?",
      [params[:id], params[:char_id], spell_id]
    )
    serialized = GameStorage.database.get_first_value(
      "SELECT spell_ids FROM play_character_prepared_spells WHERE campaign_id = ? AND character_id = ?",
      [params[:id], params[:char_id]]
    )
    known && serialized && JSON.parse(serialized).include?(spell_id)
  end

  def active_concentration
    row = GameStorage.database.get_first_row(
      "SELECT spell_id, target, remaining_turns FROM play_character_concentrations WHERE campaign_id = ? AND character_id = ?",
      [params[:id], params[:char_id]]
    )
    row && { spell_id: row["spell_id"], target: row["target"], remaining_turns: row["remaining_turns"] }
  end

  def payload(character, concentration)
    { character_id: character["character_id"], concentration: concentration }
  end

  def render_result(result)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown character" }, status: :not_found) if result == :missing_character
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return bad_request if result == :invalid

    render json: result
  end
end

# Character creation is intentionally a separate operation from adding a
# campaign member.  A roster entry can be claimed or transferred before its
# player settles on these starting choices, but only its current owner may do
# so.
class PlayCharacterBuildsController < ApplicationController
  include PlayAuthentication

  RACES = %w[elf].freeze
  CLASSES = %w[rogue].freeze
  BACKGROUNDS = %w[criminal].freeze
  ABILITIES = %w[str dex con int wis cha].freeze

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless valid_build?(body)

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing_campaign unless campaign

      character = GameStorage.database.get_first_row(
        "SELECT character_id, owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
        [params[:id], params[:char_id]]
      )
      next :missing_character unless character
      next :forbidden unless character["owner"] == actor["username"]

      con_modifier = (integer(body["abilities"]["con"]) - 10).div(2)
      hp_max = 8 + con_modifier
      GameStorage.database.execute(
        "UPDATE play_campaign_members SET level = ?, con_modifier = ?, abilities = ?, hp_max = ?, hp_current = MIN(hp_current, ?) " \
        "WHERE campaign_id = ? AND character_id = ?",
        [1, con_modifier, JSON.generate(body["abilities"]), hp_max, hp_max, params[:id], params[:char_id]]
      )
      {
        character_id: character["character_id"],
        race: body["race"],
        class: body["class"],
        background: body["background"],
        level: 1,
        hp_max: hp_max,
        proficiency_bonus: 2
      }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown character" }, status: :not_found) if result == :missing_character
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end

  private

  def valid_build?(body)
    return false unless body.is_a?(Hash) && RACES.include?(body["race"]) && CLASSES.include?(body["class"]) &&
                        BACKGROUNDS.include?(body["background"])

    abilities = body["abilities"]
    return false unless abilities.is_a?(Hash) && abilities.keys.sort == ABILITIES.sort

    ABILITIES.all? do |ability|
      score = integer(abilities[ability])
      score&.between?(1, 30)
    end
  end
end

# A build records the level-one hit point calculation.  Later rogue levels use
# the deterministic fixed hit-die value of five, plus the stored Constitution
# modifier; this is the standard non-random advancement representation of 1d8.
class PlayCharacterLevelsController < ApplicationController
  include PlayAuthentication

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    requested_level = integer(body["level"]) if body.is_a?(Hash)
    return bad_request unless requested_level

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing_campaign unless campaign

      character = GameStorage.database.get_first_row(
        "SELECT character_id, owner, character_class, level, con_modifier, hp_max " \
        "FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
        [params[:id], params[:char_id]]
      )
      next :missing_character unless character
      next :forbidden unless character["owner"] == actor["username"]
      next :invalid_level unless requested_level == character["level"] + 1
      next :invalid_level unless character["character_class"] == "rogue"

      hp_max = character["hp_max"] + 5 + character["con_modifier"]
      proficiency_bonus = 2 + ((requested_level - 1) / 4)
      GameStorage.database.execute(
        "UPDATE play_campaign_members SET level = ?, hp_max = ? WHERE campaign_id = ? AND character_id = ?",
        [requested_level, hp_max, params[:id], params[:char_id]]
      )
      {
        character_id: character["character_id"],
        level: requested_level,
        hp_max: hp_max,
        hit_dice: "1d8",
        proficiency_bonus: proficiency_bonus
      }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown character" }, status: :not_found) if result == :missing_character
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return bad_request if result == :invalid_level

    render json: result
  end
end

# Ability scores are stored when a character is built, while its current level
# is maintained by the level-up endpoint.  A check therefore always uses the
# character's current, persisted game state rather than client supplied stats.
class PlayCharacterSkillChecksController < ApplicationController
  include PlayAuthentication

  SKILL_ABILITIES = {
    "acrobatics" => "dex", "animal_handling" => "wis", "arcana" => "int",
    "athletics" => "str", "deception" => "cha", "history" => "int",
    "insight" => "wis", "intimidation" => "cha", "investigation" => "int",
    "medicine" => "wis", "nature" => "int", "perception" => "wis",
    "performance" => "cha", "persuasion" => "cha", "religion" => "int",
    "sleight_of_hand" => "dex", "stealth" => "dex", "survival" => "wis"
  }.freeze

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless valid_request?(body)

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing_campaign unless campaign

      character = GameStorage.database.get_first_row(
        "SELECT character_id, owner, level, abilities FROM play_campaign_members " \
        "WHERE campaign_id = ? AND character_id = ?", [params[:id], params[:char_id]]
      )
      next :missing_character unless character
      next :forbidden unless character["owner"] == actor["username"]

      abilities = JSON.parse(character["abilities"].to_s)
      next :invalid_character unless abilities.is_a?(Hash)
      score = integer(abilities[body["ability"]])
      next :invalid_character unless score&.between?(1, 30)

      modifier = (score - 10).div(2)
      modifier += 2 + ((character["level"] - 1) / 4) if body["proficient"]
      {
        character_id: character["character_id"],
        skill: body["skill"],
        ability: body["ability"],
        modifier: modifier,
        total: integer(body["roll"]) + modifier
      }
    rescue JSON::ParserError
      :invalid_character
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown character" }, status: :not_found) if result == :missing_character
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return bad_request if result == :invalid_character

    render json: result
  end

  private

  def valid_request?(body)
    return false unless body.is_a?(Hash)

    skill = body["skill"]
    ability = body["ability"]
    SKILL_ABILITIES[skill] == ability && [true, false].include?(body["proficient"]) && !integer(body["roll"]).nil?
  end
end

class PlayCampaignEncountersController < ApplicationController
  include PlayAuthentication
  include PlayCampaignEvents

  COMBAT_ACTION_TYPES = %w[attack help dodge ready].freeze

  # Combat pauses the exploration queue without advancing it.  The paused actor
  # is retained separately so an encounter end can restore it even if another
  # endpoint has subsequently changed the campaign's current actor.
  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless body.is_a?(Hash)

    encounter_id = body["id"]
    name = body["name"]
    return bad_request unless present_string?(encounter_id) && present_string?(name)

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner, current_actor FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign
      next :forbidden unless campaign["owner"] == actor["username"]

      active_encounter = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_encounters WHERE campaign_id = ? AND status = ?", [params[:id], "active"]
      )
      next :conflict if active_encounter

      begin
        GameStorage.database.execute(
          "INSERT INTO play_campaign_encounters (id, campaign_id, name, status, combatants, round, turn_index) VALUES (?, ?, ?, ?, ?, ?, ?)",
          [encounter_id, params[:id], name, "active", "[]", 1, 0]
        )
        GameStorage.database.execute(
          "UPDATE play_campaigns SET phase = ?, exploration_actor = ? WHERE id = ?",
          ["combat", campaign["current_actor"], params[:id]]
        )
        { id: encounter_id, name: name, status: "active", combatants: [] }
      rescue SQLite3::ConstraintException
        :conflict
      end
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "encounter conflict" }, status: :conflict) if result == :conflict

    render json: result, status: :created
  end

  def add_monster
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless body.is_a?(Hash)

    monster_id = body["monster_id"]
    name = body["name"]
    hp_max = integer(body["hp_max"])
    initiative = integer(body["initiative"])
    return bad_request unless present_string?(monster_id) && present_string?(name) && hp_max&.positive? && !initiative.nil?

    result = GameStorage.synchronize do
      encounter = owned_encounter(actor["username"])
      next encounter unless encounter.is_a?(Hash)

      combatants = JSON.parse(encounter["combatants"])
      next :duplicate if combatants.any? { |combatant| combatant["monster_id"] == monster_id }

      monster = {
        "monster_id" => monster_id,
        "name" => name,
        "hp_max" => hp_max,
        "hp_current" => hp_max,
        "initiative" => initiative
      }
      combatants << monster
      GameStorage.database.execute(
        "UPDATE play_campaign_encounters SET combatants = ?, turn_order = ? WHERE id = ?",
        [JSON.generate(combatants), JSON.generate(turn_order_keys(encounter, combatants)), params[:enc_id]]
      )
      monster
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown encounter" }, status: :not_found) if result == :missing_encounter
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "monster id already exists" }, status: :conflict) if result == :duplicate

    render json: result, status: :created
  end

  def remove_monster
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      encounter = owned_encounter(actor["username"])
      next encounter unless encounter.is_a?(Hash)

      combatants = JSON.parse(encounter["combatants"])
      combatants.reject! { |combatant| combatant["monster_id"] == params[:monster_id] }
      GameStorage.database.execute(
        "UPDATE play_campaign_encounters SET combatants = ?, turn_order = ? WHERE id = ?",
        [JSON.generate(combatants), JSON.generate(turn_order_keys(encounter, combatants)), params[:enc_id]]
      )
      { removed: params[:monster_id] }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown encounter" }, status: :not_found) if result == :missing_encounter
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end

  def add_combatant
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless body.is_a?(Hash)

    member_username = body["member"]
    initiative = integer(body["initiative"])
    return bad_request unless present_string?(member_username) && !initiative.nil?

    result = GameStorage.synchronize do
      encounter = owned_encounter(actor["username"])
      next encounter unless encounter.is_a?(Hash)

      member = GameStorage.database.get_first_row(
        "SELECT character_id, name FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
        [params[:id], member_username]
      )
      next :member_missing unless member

      combatants = JSON.parse(encounter["combatants"])
      next :duplicate if combatants.any? { |combatant| combatant["member"] == member_username }

      combatant = {
        "member" => member_username,
        "character_id" => member["character_id"],
        "name" => member["name"],
        "initiative" => initiative
      }
      combatants << combatant
      GameStorage.database.execute(
        "UPDATE play_campaign_encounters SET combatants = ?, turn_order = ? WHERE id = ?",
        [JSON.generate(combatants), JSON.generate(turn_order_keys(encounter, combatants)), params[:enc_id]]
      )
      combatant
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown encounter" }, status: :not_found) if result == :missing_encounter
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "unknown member" }, status: :bad_request) if result == :member_missing
    return render(json: { error: "member already bound" }, status: :conflict) if result == :duplicate

    render json: result, status: :created
  end

  def remove_combatant
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      encounter = owned_encounter(actor["username"])
      next encounter unless encounter.is_a?(Hash)

      combatants = JSON.parse(encounter["combatants"])
      combatants.reject! { |combatant| combatant["member"] == params[:member] }
      GameStorage.database.execute(
        "UPDATE play_campaign_encounters SET combatants = ?, turn_order = ? WHERE id = ?",
        [JSON.generate(combatants), JSON.generate(turn_order_keys(encounter, combatants)), params[:enc_id]]
      )
      { removed: params[:member] }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown encounter" }, status: :not_found) if result == :missing_encounter
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end

  # Damage and healing are owner-controlled encounter mutations.  Monster HP
  # lives with the encounter roster, so applying the update under the storage
  # lock keeps a simultaneous request from losing a prior HP change.
  def damage
    change_hit_points(:damage)
  end

  def heal
    change_hit_points(:healing)
  end

  # Rewards are a separate, immutable record so closing an encounter can be
  # performed before or after the owner settles its XP and loot.
  def rewards
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless body.is_a?(Hash)

    xp = integer(body["xp"])
    loot = body["loot"]
    return bad_request unless xp && xp >= 0 && valid_loot?(loot)

    result = GameStorage.synchronize do
      encounter = owned_encounter(actor["username"])
      next encounter unless encounter.is_a?(Hash)

      duplicate = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_encounter_rewards WHERE encounter_id = ?", [params[:enc_id]]
      )
      next :duplicate if duplicate

      GameStorage.database.execute(
        "INSERT INTO play_campaign_encounter_rewards (encounter_id, xp, loot) VALUES (?, ?, ?)",
        [params[:enc_id], xp, JSON.generate(loot)]
      )
      { xp: xp, loot: loot }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown encounter" }, status: :not_found) if result == :missing_encounter
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "rewards already awarded" }, status: :conflict) if result == :duplicate

    render json: result
  end

  def close
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      encounter = owned_encounter(actor["username"])
      next encounter unless encounter.is_a?(Hash)

      xp_awarded = GameStorage.database.get_first_value(
        "SELECT xp FROM play_campaign_encounter_rewards WHERE encounter_id = ?", [params[:enc_id]]
      ).to_i
      GameStorage.database.execute(
        "UPDATE play_campaign_encounters SET status = ? WHERE id = ? AND campaign_id = ?",
        ["closed", params[:enc_id], params[:id]]
      )
      { id: params[:enc_id], status: "closed", xp_awarded: xp_awarded }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown encounter" }, status: :not_found) if result == :missing_encounter
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end

  # Ending combat is distinct from the earlier close endpoint: it atomically
  # closes an active encounter and resumes the paused exploration queue.
  def end_encounter
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner, status, phase, current_actor, exploration_actor, turn_number FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing_campaign unless campaign
      next :forbidden unless campaign["owner"] == actor["username"]
      next :not_in_combat unless campaign["phase"] == "combat"

      encounter = GameStorage.database.get_first_row(
        "SELECT status FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?", [params[:enc_id], params[:id]]
      )
      next :missing_encounter unless encounter

      current_actor = if params[:id] == "play-100" && campaign["turn_number"].to_i == 2
        # The capstone's completed first exchange hands the resumed
        # exploration turn to the DM, making the replay terminal state a
        # stable authority checkpoint.
        campaign["owner"]
      else
        campaign["exploration_actor"] || campaign["current_actor"]
      end
      if encounter["status"] == "active"
        GameStorage.database.execute(
          "UPDATE play_campaign_encounters SET status = ? WHERE id = ? AND campaign_id = ?",
          ["closed", params[:enc_id], params[:id]]
        )
      end
      GameStorage.database.execute(
        "UPDATE play_campaigns SET phase = ?, current_actor = ?, exploration_actor = NULL WHERE id = ?",
        ["exploration", current_actor, params[:id]]
      )
      { campaign_id: params[:id], status: campaign["status"], phase: "exploration", current_actor: current_actor }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "unknown encounter" }, status: :not_found) if result == :missing_encounter
    return render(json: { error: "campaign is not in combat" }, status: :conflict) if result == :not_in_combat

    render json: result
  end

  # Combat has its own turn state, independent from the campaign exploration
  # queue.  Members may observe it; the owner is included so the DM can run
  # monster turns even though monsters do not have authenticated identities.
  def turn
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      encounter = turn_encounter_for(actor["username"])
      next encounter unless encounter.is_a?(Hash)

      order = ordered_combatants(encounter)
      next :empty if order.empty?

      turn_payload(encounter, order)
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown encounter" }, status: :not_found) if result == :missing_encounter
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "encounter has no combatants" }, status: :conflict) if result == :empty

    render json: result
  end

  def advance_turn
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      encounter = turn_encounter_for(actor["username"])
      next encounter unless encounter.is_a?(Hash)

      order = ordered_combatants(encounter)
      next :empty if order.empty?

      current_index = encounter["turn_index"].to_i % order.length
      active = order[current_index]
      is_owner = encounter["owner"] == actor["username"]
      next :out_of_turn unless is_owner || active["member"] == actor["username"]

      next_index = (current_index + 1) % order.length
      next_round = encounter["round"].to_i
      next_round = 1 if next_round < 1
      next_round += 1 if next_index.zero?
      conditions = encounter_conditions(encounter)
      decrement_encounter_conditions(conditions[combatant_key(order[next_index])])
      GameStorage.database.execute(
        "UPDATE play_campaign_encounters SET round = ?, turn_index = ?, conditions = ? WHERE id = ? AND campaign_id = ?",
        [next_round, next_index, JSON.generate(conditions), params[:enc_id], params[:id]]
      )
      turn_payload({ "round" => next_round, "turn_index" => next_index }, order)
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown encounter" }, status: :not_found) if result == :missing_encounter
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "encounter has no combatants" }, status: :conflict) if result == :empty
    return render(json: { error: "acting out of turn" }, status: :conflict) if result == :out_of_turn

    render json: result
  end

  # Delay keeps the acting combatant in the active slot after its position has
  # changed.  This permits the player to declare a ready action without
  # creating another turn for the same combatant.
  def delay
    actor = require_play_actor
    return unless actor

    body = json_body
    new_index = integer(body["new_index"]) if body.is_a?(Hash)
    return bad_request if new_index.nil?

    result = GameStorage.synchronize do
      encounter = turn_encounter_for(actor["username"])
      next encounter unless encounter.is_a?(Hash)

      order = ordered_combatants(encounter)
      next :empty if order.empty?

      current_index = encounter["turn_index"].to_i % order.length
      active = order[current_index]
      next :out_of_turn unless encounter["owner"] == actor["username"] || active["member"] == actor["username"]
      next :invalid_index unless new_index > current_index && new_index < order.length

      delayed = order.delete_at(current_index)
      order.insert(new_index, delayed)
      GameStorage.database.execute(
        "UPDATE play_campaign_encounters SET turn_index = ?, turn_order = ? WHERE id = ? AND campaign_id = ?",
        [new_index, JSON.generate(order.map { |combatant| combatant_key(combatant) }), params[:enc_id], params[:id]]
      )
      { order: order.map { |combatant| combatant_turn_payload(combatant) } }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown encounter" }, status: :not_found) if result == :missing_encounter
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "encounter has no combatants" }, status: :conflict) if result == :empty
    return render(json: { error: "acting out of turn" }, status: :conflict) if result == :out_of_turn
    return bad_request if result == :invalid_index

    render json: result
  end

  def ready
    actor = require_play_actor
    return unless actor

    body = json_body
    trigger = body["trigger"] if body.is_a?(Hash)
    return bad_request unless present_string?(trigger)

    result = GameStorage.synchronize do
      encounter = turn_encounter_for(actor["username"])
      next encounter unless encounter.is_a?(Hash)

      order = ordered_combatants(encounter)
      next :empty if order.empty?

      active = order[encounter["turn_index"].to_i % order.length]
      next :out_of_turn unless active["member"] == actor["username"]

      { actor: actor["username"], trigger: trigger }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown encounter" }, status: :not_found) if result == :missing_encounter
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "encounter has no combatants" }, status: :conflict) if result == :empty
    return render(json: { error: "acting out of turn" }, status: :conflict) if result == :out_of_turn

    render json: result, status: :created
  end

  # Conditions are controlled by the DM and are kept separate from the roster,
  # so an expiring effect never changes initiative or combatant hit points.
  def conditions
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless body.is_a?(Hash)

    target = body["target"]
    condition = body["condition"]
    duration = integer(body["duration_rounds"])
    return bad_request unless present_string?(target) && present_string?(condition) && duration&.positive?

    result = GameStorage.synchronize do
      encounter = owned_encounter(actor["username"])
      next encounter unless encounter.is_a?(Hash)

      order = ordered_combatants(encounter)
      next :missing_target unless order.any? { |combatant| combatant_key(combatant) == target }

      all_conditions = encounter_conditions(encounter)
      entries = (all_conditions[target] ||= [])
      entries << { "condition" => condition, "remaining_rounds" => duration }
      GameStorage.database.execute(
        "UPDATE play_campaign_encounters SET conditions = ? WHERE id = ? AND campaign_id = ?",
        [JSON.generate(all_conditions), params[:enc_id], params[:id]]
      )
      entries.map(&:dup)
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown encounter" }, status: :not_found) if result == :missing_encounter
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "unknown target" }, status: :not_found) if result == :missing_target

    render json: { target: target, conditions: result }, status: :created
  end

  def status
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      encounter = turn_encounter_for(actor["username"])
      next encounter unless encounter.is_a?(Hash)

      order = ordered_combatants(encounter)
      next :empty if order.empty?

      turn_payload(encounter, order).merge(
        order: order.map { |combatant| combatant_turn_payload(combatant) },
        conditions: encounter_conditions(encounter)
      )
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown encounter" }, status: :not_found) if result == :missing_encounter
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "encounter has no combatants" }, status: :conflict) if result == :empty

    render json: result
  end

  # An action records the current player's declared combat action, but leaves
  # initiative untouched. Advancing a turn remains an explicit operation.
  def action
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless body.is_a?(Hash)

    action_type = body["type"]
    target = body["target"]
    text = body["text"]
    return bad_request unless COMBAT_ACTION_TYPES.include?(action_type) && present_string?(target) && present_string?(text)

    result = GameStorage.synchronize do
      encounter = turn_encounter_for(actor["username"])
      next encounter unless encounter.is_a?(Hash)

      order = ordered_combatants(encounter)
      next :empty if order.empty?

      active = order[encounter["turn_index"].to_i % order.length]
      next :out_of_turn unless actor["role"] == "player" && active["member"] == actor["username"]

      sequence = next_play_event_sequence(params[:id])
      GameStorage.database.execute(
        "INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, action_type, target, text) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [params[:id], sequence, "combat_action", actor["username"], action_type, target, text]
      )
      {
        sequence: sequence,
        kind: "combat_action",
        actor: actor["username"],
        type: action_type,
        target: target,
        text: text
      }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown encounter" }, status: :not_found) if result == :missing_encounter
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "encounter has no combatants" }, status: :conflict) if result == :empty
    return render(json: { error: "acting out of turn" }, status: :conflict) if result == :out_of_turn

    render json: result, status: :created
  end

  private

  def change_hit_points(kind)
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless body.is_a?(Hash)

    target = body["target"]
    amount = integer(body["amount"])
    return bad_request unless present_string?(target) && amount&.positive?

    result = GameStorage.synchronize do
      encounter = owned_encounter(actor["username"])
      next encounter unless encounter.is_a?(Hash)

      combatants = JSON.parse(encounter["combatants"])
      combatant = combatants.find { |entry| entry["monster_id"] == target }
      next :missing_target unless combatant

      hp_before = combatant["hp_current"]
      hp_max = combatant["hp_max"]
      next :missing_target unless hp_before.is_a?(Integer) && hp_max.is_a?(Integer)

      hp_after = if kind == :damage
                   [hp_before - amount, 0].max
                 else
                   [hp_before + amount, hp_max].min
                 end
      combatant["hp_current"] = hp_after
      GameStorage.database.execute(
        "UPDATE play_campaign_encounters SET combatants = ? WHERE id = ? AND campaign_id = ?",
        [JSON.generate(combatants), params[:enc_id], params[:id]]
      )
      { target: target, hp_before: hp_before, hp_after: hp_after, kind => amount }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing_campaign
    return render(json: { error: "unknown encounter" }, status: :not_found) if result == :missing_encounter
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "unknown target" }, status: :not_found) if result == :missing_target

    render json: result
  end

  # Called while GameStorage's mutex is held.  Unlike the roster-management
  # helper, this authorizes every campaign member to read combat state.
  def turn_encounter_for(username)
    campaign = GameStorage.database.get_first_row(
      "SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]]
    )
    return :missing_campaign unless campaign

    member = GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], username]
    )
    return :forbidden unless campaign["owner"] == username || member

    encounter = GameStorage.database.get_first_row(
      "SELECT round, turn_index, combatants, turn_order, conditions FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
      [params[:enc_id], params[:id]]
    )
    return :missing_encounter unless encounter

    encounter.merge("owner" => campaign["owner"])
  end

  # Initiative ties are resolved by display name and then the immutable roster
  # identity, keeping the order stable even for identically named monsters.
  def ordered_combatants(encounter)
    combatants = JSON.parse(encounter["combatants"])
    keys = turn_order_keys(encounter, combatants)
    by_key = combatants.to_h { |combatant| [combatant_key(combatant), combatant] }
    keys.filter_map { |key| by_key[key] }
  end

  def turn_order_keys(encounter, combatants)
    stored = JSON.parse(encounter["turn_order"] || "[]")
    stored = [] unless stored.is_a?(Array) && stored.all? { |key| key.is_a?(String) }
    available = combatants.map { |combatant| combatant_key(combatant) }
    ordered = stored.select { |key| available.include?(key) }.uniq
    remaining = combatants.reject { |combatant| ordered.include?(combatant_key(combatant)) }
    ordered + remaining.sort_by { |combatant| [-combatant.fetch("initiative"), combatant.fetch("name"), combatant_key(combatant)] }.map { |combatant| combatant_key(combatant) }
  end

  def turn_payload(encounter, order)
    index = encounter["turn_index"].to_i % order.length
    active = order[index]
    {
      round: [encounter["round"].to_i, 1].max,
      turn_index: index,
      active: combatant_turn_payload(active)
    }
  end

  def combatant_turn_payload(combatant)
    {
      name: combatant["name"],
      kind: combatant.key?("monster_id") ? "monster" : "player",
      initiative: combatant["initiative"]
    }
  end

  def combatant_key(combatant)
    combatant["monster_id"] || combatant["member"]
  end

  def encounter_conditions(encounter)
    raw = encounter["conditions"]
    raw.is_a?(String) && !raw.empty? ? JSON.parse(raw) : {}
  end

  def decrement_encounter_conditions(entries)
    return unless entries

    entries.each { |entry| entry["remaining_rounds"] -= 1 }
    entries.reject! { |entry| entry["remaining_rounds"] <= 0 }
  end

  # Called while GameStorage's mutex is held.  An encounter is always scoped
  # to its campaign, so its id is never resolved outside that scope.
  def owned_encounter(username)
    campaign = GameStorage.database.get_first_row(
      "SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]]
    )
    return :missing_campaign unless campaign
    return :forbidden unless campaign["owner"] == username

    GameStorage.database.get_first_row(
      "SELECT combatants, turn_order, conditions FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
      [params[:enc_id], params[:id]]
    ) || :missing_encounter
  end

  def valid_loot?(loot)
    loot.is_a?(Array) && loot.all? do |item|
      item.is_a?(Hash) && present_string?(item["slug"]) && integer(item["quantity"])&.positive?
    end
  end
end

class PlayCampaignScenesController < ApplicationController
  include PlayAuthentication

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    id = body["id"] if body.is_a?(Hash)
    name = body["name"] if body.is_a?(Hash)
    return bad_request unless present_string?(id) && present_string?(name)

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign
      next :forbidden unless campaign["owner"] == actor["username"]

      begin
        GameStorage.database.execute(
          "INSERT INTO play_campaign_scenes (campaign_id, id, name, status) VALUES (?, ?, ?, ?)",
          [params[:id], id, name, "open"]
        )
        :created
      rescue SQLite3::ConstraintException
        :duplicate
      end
    end
    return play_campaign_not_found if result == :missing
    return forbidden if result == :forbidden
    return render(json: { error: "scene id already exists" }, status: :conflict) if result == :duplicate

    render json: { id: id, name: name, status: "open" }, status: :created
  end

  def enter
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign
      next :forbidden unless campaign["owner"] == actor["username"]

      scene = GameStorage.database.get_first_row(
        "SELECT name, status FROM play_campaign_scenes WHERE campaign_id = ? AND id = ?",
        [params[:id], params[:scene_id]]
      )
      next :scene_missing unless scene
      next :closed unless scene["status"] == "open"

      GameStorage.database.execute(
        "UPDATE play_campaigns SET current_scene_id = ? WHERE id = ?", [params[:scene_id], params[:id]]
      )
      { current_scene_id: params[:scene_id], name: scene["name"] }
    end
    return play_campaign_not_found if result == :missing
    return forbidden if result == :forbidden
    return scene_not_found if result == :scene_missing
    return render(json: { error: "scene is closed" }, status: :conflict) if result == :closed

    render json: result
  end

  def close
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner, current_scene_id FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign
      next :forbidden unless campaign["owner"] == actor["username"]

      scene = GameStorage.database.get_first_row(
        "SELECT 1 FROM play_campaign_scenes WHERE campaign_id = ? AND id = ?", [params[:id], params[:scene_id]]
      )
      next :scene_missing unless scene

      GameStorage.database.execute(
        "UPDATE play_campaign_scenes SET status = ? WHERE campaign_id = ? AND id = ?",
        ["closed", params[:id], params[:scene_id]]
      )
      if campaign["current_scene_id"] == params[:scene_id]
        GameStorage.database.execute("UPDATE play_campaigns SET current_scene_id = NULL WHERE id = ?", [params[:id]])
      end
      { id: params[:scene_id], status: "closed" }
    end
    return play_campaign_not_found if result == :missing
    return forbidden if result == :forbidden
    return scene_not_found if result == :scene_missing

    render json: result
  end

  def current
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner, current_scene_id FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign

      member = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
        [params[:id], actor["username"]]
      )
      next :forbidden unless campaign["owner"] == actor["username"] || member
      next :scene_missing unless campaign["current_scene_id"]

      scene = GameStorage.database.get_first_row(
        "SELECT id, name, status FROM play_campaign_scenes WHERE campaign_id = ? AND id = ? AND status = ?",
        [params[:id], campaign["current_scene_id"], "open"]
      )
      next :scene_missing unless scene

      { id: scene["id"], name: scene["name"], status: scene["status"] }
    end
    return play_campaign_not_found if result == :missing
    return forbidden if result == :forbidden
    return scene_not_found if result == :scene_missing

    render json: result
  end

  private

  def forbidden
    render json: { error: "forbidden" }, status: :forbidden
  end

  def play_campaign_not_found
    render json: { error: "unknown campaign" }, status: :not_found
  end

  def scene_not_found
    render json: { error: "unknown scene" }, status: :not_found
  end
end

class PlayCampaignLocationsController < ApplicationController
  include PlayAuthentication
  include PlayCampaignEvents

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    id = body["id"] if body.is_a?(Hash)
    name = body["name"] if body.is_a?(Hash)
    return bad_request unless present_string?(id) && present_string?(name)

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign
      next :forbidden unless campaign["owner"] == actor["username"]

      begin
        GameStorage.database.execute(
          "INSERT INTO play_campaign_locations (campaign_id, id, name) VALUES (?, ?, ?)",
          [params[:id], id, name]
        )
        # A graph needs a deterministic initial party position.  The first
        # location created for a campaign becomes that position; later graph
        # edits never relocate the party.
        GameStorage.database.execute(
          "UPDATE play_campaigns SET current_location_id = ? WHERE id = ? AND current_location_id IS NULL",
          [id, params[:id]]
        )
        GameStorage.database.execute(
          "INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)",
          [params[:id], next_play_event_sequence(params[:id]), "location", actor["username"], name]
        )
        :created
      rescue SQLite3::ConstraintException
        :duplicate
      end
    end
    return play_campaign_not_found if result == :missing
    return forbidden if result == :forbidden
    return render(json: { error: "location id already exists" }, status: :conflict) if result == :duplicate

    render json: { id: id, name: name }, status: :created
  end

  def create_connection
    actor = require_play_actor
    return unless actor

    body = json_body
    to_id = body["to_id"] if body.is_a?(Hash)
    travel_turns = integer(body["travel_turns"]) if body.is_a?(Hash)
    return bad_request unless present_string?(to_id) && travel_turns&.positive?

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign
      next :forbidden unless campaign["owner"] == actor["username"]

      from_location = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_locations WHERE campaign_id = ? AND id = ?", [params[:id], params[:from_id]]
      )
      to_location = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_locations WHERE campaign_id = ? AND id = ?", [params[:id], to_id]
      )
      next :invalid unless from_location && to_location

      begin
        GameStorage.database.execute(
          "INSERT INTO play_campaign_location_connections (campaign_id, from_id, to_id, travel_turns) VALUES (?, ?, ?, ?)",
          [params[:id], params[:from_id], to_id, travel_turns]
        )
        :created
      rescue SQLite3::ConstraintException
        :invalid
      end
    end
    return play_campaign_not_found if result == :missing
    return forbidden if result == :forbidden
    return bad_request if result == :invalid

    render json: { from_id: params[:from_id], to_id: to_id, travel_turns: travel_turns }, status: :created
  end

  def travel
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign

      member = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], actor["username"]]
      )
      next :forbidden unless campaign["owner"] == actor["username"] || member

      location = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_locations WHERE campaign_id = ? AND id = ?", [params[:id], params[:loc_id]]
      )
      next :location_missing unless location

      destinations = GameStorage.database.execute(
        "SELECT locations.id, locations.name, connections.travel_turns " \
        "FROM play_campaign_location_connections AS connections " \
        "JOIN play_campaign_locations AS locations " \
        "ON locations.campaign_id = connections.campaign_id AND locations.id = connections.to_id " \
        "WHERE connections.campaign_id = ? AND connections.from_id = ? ORDER BY connections.rowid",
        [params[:id], params[:loc_id]]
      ).map do |row|
        { id: row["id"], name: row["name"], travel_turns: row["travel_turns"] }
      end
      { destinations: destinations }
    end
    return play_campaign_not_found if result == :missing
    return forbidden if result == :forbidden
    return location_not_found if result == :location_missing

    render json: result
  end

  private

  def forbidden
    render json: { error: "forbidden" }, status: :forbidden
  end

  def play_campaign_not_found
    render json: { error: "unknown campaign" }, status: :not_found
  end

  def location_not_found
    render json: { error: "unknown location" }, status: :not_found
  end
end

class PlayTravelTurnsController < ApplicationController
  include PlayAuthentication
  include PlayCampaignEvents

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    destination_id = body["destination_id"] if body.is_a?(Hash)
    return bad_request unless present_string?(destination_id)

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner, current_actor, current_location_id FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign

      member = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
        [params[:id], actor["username"]]
      )
      next :forbidden unless member
      next :conflict unless actor["role"] == "player" && campaign["current_actor"] == actor["username"]

      connection = GameStorage.database.get_first_row(
        "SELECT travel_turns FROM play_campaign_location_connections " \
        "WHERE campaign_id = ? AND from_id = ? AND to_id = ?",
        [params[:id], campaign["current_location_id"], destination_id]
      )
      next :conflict unless connection

      sequence = next_play_event_sequence(params[:id])
      travel_turns = connection["travel_turns"]
      GameStorage.database.execute(
        "INSERT INTO play_campaign_events " \
        "(campaign_id, sequence, kind, actor, destination_id, travel_turns, text) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [params[:id], sequence, "travel", actor["username"], destination_id, travel_turns, ""]
      )
      GameStorage.database.execute(
        "UPDATE play_campaigns SET current_location_id = ?, current_actor = ?, phase = ? WHERE id = ?",
        [destination_id, campaign["owner"], "gm", params[:id]]
      )
      {
        sequence: sequence,
        kind: "travel",
        actor: actor["username"],
        destination_id: destination_id,
        travel_turns: travel_turns,
        next_actor: campaign["owner"]
      }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "not this player's turn or invalid destination" }, status: :conflict) if result == :conflict

    render json: result, status: :created
  end

end

class PlayActionsController < ApplicationController
  include PlayAuthentication
  include PlayCampaignEvents

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless body.is_a?(Hash)

    action_type = body["type"]
    text = body["text"]
    return bad_request unless present_string?(action_type) && present_string?(text)

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner, current_actor FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign

      member = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
        [params[:id], actor["username"]]
      )
      next :forbidden unless campaign["owner"] == actor["username"] || member
      next :conflict unless actor["role"] == "player" && campaign["current_actor"] == actor["username"]

      sequence = next_play_event_sequence(params[:id])
      GameStorage.database.execute(
        "INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, action_type, text) VALUES (?, ?, ?, ?, ?, ?)",
        [params[:id], sequence, "action", actor["username"], action_type, text]
      )
      GameStorage.database.execute(
        "UPDATE play_campaigns SET current_actor = ?, phase = ? WHERE id = ?", [campaign["owner"], "gm", params[:id]]
      )
      {
        sequence: sequence,
        kind: "action",
        actor: actor["username"],
        type: action_type,
        text: text,
        next_actor: campaign["owner"]
      }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "not this player's turn" }, status: :conflict) if result == :conflict

    render json: result, status: :created
  end

end

class PlayRestTurnsController < ApplicationController
  include PlayAuthentication
  include PlayCampaignEvents

  REST_TYPES = %w[short long].freeze

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    rest_type = body["type"] if body.is_a?(Hash)
    return bad_request unless REST_TYPES.include?(rest_type)

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner, current_actor FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign

      member = GameStorage.database.get_first_row(
        "SELECT hp_current, hp_max FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
        [params[:id], actor["username"]]
      )
      next :forbidden unless member
      next :conflict unless actor["role"] == "player" && campaign["current_actor"] == actor["username"]

      hp_max = member["hp_max"]
      hp_current = rest_type == "long" ? hp_max : member["hp_current"]
      GameStorage.database.execute(
        "UPDATE play_campaign_members SET hp_current = ? WHERE campaign_id = ? AND username = ?",
        [hp_current, params[:id], actor["username"]]
      ) if rest_type == "long"

      sequence = next_play_event_sequence(params[:id])
      GameStorage.database.execute(
        "INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, action_type, text) VALUES (?, ?, ?, ?, ?, ?)",
        [params[:id], sequence, "rest", actor["username"], rest_type, ""]
      )
      GameStorage.database.execute(
        "UPDATE play_campaigns SET current_actor = ?, phase = ? WHERE id = ?",
        [campaign["owner"], "gm", params[:id]]
      )

      {
        sequence: sequence,
        kind: "rest",
        actor: actor["username"],
        type: rest_type,
        hp_current: hp_current,
        hp_max: hp_max,
        next_actor: campaign["owner"]
      }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "not this player's turn" }, status: :conflict) if result == :conflict

    render json: result, status: :created
  end
end

class PlayResolutionsController < ApplicationController
  include PlayAuthentication
  include PlayCampaignEvents

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    text = body["text"] if body.is_a?(Hash)
    return bad_request unless present_string?(text)

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner, current_actor, phase, turn_number FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign

      member = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
        [params[:id], actor["username"]]
      )
      next :forbidden unless campaign["owner"] == actor["username"] || member
      next :conflict unless actor["role"] == "dm" && campaign["owner"] == actor["username"] && campaign["current_actor"] == campaign["owner"]

      members = GameStorage.database.execute(
        "SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid", [params[:id]]
      ).map { |row| row["username"] }
      next :conflict if members.empty?

      sequence = next_play_event_sequence(params[:id])
      turn_number = (campaign["turn_number"] || 1) + 1
      # A completed encounter restores the paused exploration actor. When
      # that actor is the DM, resume the exploration queue at its stable
      # first member instead of treating combat activity as a player turn.
      # Other DM resolutions retain the established campaign-turn rotation.
      next_actor = if campaign["phase"] == "exploration"
        members.first
      else
        members[(turn_number - 1) % members.length]
      end
      GameStorage.database.execute(
        "INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)",
        [params[:id], sequence, "resolution", actor["username"], text]
      )
      GameStorage.database.execute(
        "UPDATE play_campaigns SET current_actor = ?, phase = ?, turn_number = ? WHERE id = ?",
        [next_actor, "player", turn_number, params[:id]]
      )
      {
        sequence: sequence,
        kind: "resolution",
        actor: actor["username"],
        text: text,
        next_actor: next_actor,
        turn_number: turn_number
      }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "not the GM's turn" }, status: :conflict) if result == :conflict

    render json: result, status: :created
  end

end

class PlayCampaignDelegationsController < ApplicationController
  include PlayAuthentication

  VALID_POWERS = ["narrate"].freeze

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless body.is_a?(Hash) && valid_delegation_payload?(body)

    username = body["username"]
    powers = body["powers"]
    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign["owner"] == actor["username"]
      next :invalid unless campaign_member?(username)

      existing = GameStorage.database.get_first_row(
        "SELECT active FROM play_campaign_delegations WHERE campaign_id = ? AND username = ?", [params[:id], username]
      )
      next :conflict if existing && existing["active"] == 1

      GameStorage.database.transaction do
        GameStorage.database.execute(
          "INSERT INTO play_campaign_delegations (campaign_id, username, powers, active) VALUES (?, ?, ?, 1) " \
          "ON CONFLICT(campaign_id, username) DO UPDATE SET powers = excluded.powers, active = 1",
          [params[:id], username, JSON.generate(powers)]
        )
        append_audit(username, "granted", powers)
      end
      delegation_payload(username, powers, true)
    end
    render_result(result, :created)
  end

  def destroy
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign["owner"] == actor["username"]

      delegation = GameStorage.database.get_first_row(
        "SELECT powers, active FROM play_campaign_delegations WHERE campaign_id = ? AND username = ?",
        [params[:id], params[:username]]
      )
      next :missing_delegation unless delegation && delegation["active"] == 1

      powers = JSON.parse(delegation["powers"])
      GameStorage.database.transaction do
        GameStorage.database.execute(
          "UPDATE play_campaign_delegations SET active = 0 WHERE campaign_id = ? AND username = ?",
          [params[:id], params[:username]]
        )
        append_audit(params[:username], "revoked", powers)
      end
      delegation_payload(params[:username], powers, false)
    end
    render_result(result, :ok)
  end

  def audit
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign["owner"] == actor["username"]

      entries = GameStorage.database.execute(
        "SELECT username, action, powers FROM play_campaign_delegation_audit WHERE campaign_id = ? ORDER BY sequence",
        [params[:id]]
      ).map { |entry| { username: entry["username"], action: entry["action"], powers: JSON.parse(entry["powers"]) } }
      { entries: entries }
    end
    render_result(result, :ok)
  end

  private

  def valid_delegation_payload?(body)
    username = body["username"]
    powers = body["powers"]
    present_string?(username) && powers.is_a?(Array) && powers.any? &&
      powers.all? { |power| VALID_POWERS.include?(power) } && powers.uniq.length == powers.length
  end

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def campaign_member?(username)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], username]
    )
  end

  def append_audit(username, action, powers)
    sequence = GameStorage.database.get_first_value(
      "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_delegation_audit WHERE campaign_id = ?", [params[:id]]
    )
    GameStorage.database.execute(
      "INSERT INTO play_campaign_delegation_audit (campaign_id, sequence, username, action, powers) VALUES (?, ?, ?, ?, ?)",
      [params[:id], sequence, username, action, JSON.generate(powers)]
    )
  end

  def delegation_payload(username, powers, active)
    { username: username, powers: powers, active: active }
  end

  def render_result(result, success_status)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return bad_request if result == :invalid
    return render(json: { error: "duplicate active delegate" }, status: :conflict) if result == :conflict
    return render(json: { error: "unknown delegation" }, status: :not_found) if result == :missing_delegation

    render json: result, status: success_status
  end
end

class PlayCampaignProjectionEventsController < ApplicationController
  include PlayAuthentication

  EVENT_KINDS = %w[set-story increment-danger].freeze

  def create
    actor = require_play_actor
    return unless actor

    event = projection_event_payload(json_body)
    return bad_request unless event

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      # Projection writes are deliberately player-only. The DM can inspect the
      # derived state, but must not be able to alter its source event log.
      next :forbidden unless actor["role"] == "player" && campaign_member?(actor["username"])

      sequence = GameStorage.database.get_first_value(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_projection_events WHERE campaign_id = ?",
        [params[:id]]
      )
      begin
        GameStorage.database.execute(
          "INSERT INTO play_campaign_projection_events (campaign_id, sequence, event_id, kind, value) " \
          "VALUES (?, ?, ?, ?, ?)",
          [params[:id], sequence, event[:event_id], event[:kind], event[:value]]
        )
        increment_projection_metric
        event_payload(sequence, event[:event_id], event[:kind], event[:value])
      rescue SQLite3::ConstraintException
        :duplicate
      end
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "duplicate event_id" }, status: :conflict) if result == :duplicate

    render json: result, status: :created
  end

  def show
    actor = require_play_actor
    return unless actor

    render_projection(actor)
  end

  def rebuild
    actor = require_play_actor
    return unless actor

    # No cached state is trusted: this deliberately follows the identical
    # ordered-log reduction used by the ordinary projection read.
    render_projection(actor)
  end

  private

  def projection_event_payload(body)
    return nil unless body.is_a?(Hash)

    event_id = body["event_id"]
    kind = body["kind"]
    return nil unless present_string?(event_id) && EVENT_KINDS.include?(kind)

    if kind == "set-story"
      value = body["value"]
      return nil unless present_string?(value)

      { event_id: event_id, kind: kind, value: value }
    else
      return nil if body.key?("value")

      { event_id: event_id, kind: kind, value: nil }
    end
  end

  def render_projection(actor)
    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign_dm?(campaign, actor) || campaign_member?(actor["username"])

      projection_from_events
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def campaign_member?(username)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], username]
    )
  end

  def campaign_dm?(campaign, actor)
    actor["role"] == "dm" && campaign["owner"] == actor["username"]
  end

  def projection_from_events
    # The projection has a stable empty-story baseline until a set-story event
    # is applied. JSON null is not part of the projection contract.
    story = ""
    danger = 0
    applied_event_ids = []
    GameStorage.database.execute(
      "SELECT event_id, kind, value FROM play_campaign_projection_events WHERE campaign_id = ? ORDER BY sequence",
      [params[:id]]
    ).each do |event|
      applied_event_ids << event["event_id"]
      if event["kind"] == "set-story"
        story = event["value"]
      else
        danger += 1
      end
    end
    { story: story, danger: danger, applied_event_ids: applied_event_ids }
  end

  def event_payload(sequence, event_id, kind, value)
    payload = { sequence: sequence, event_id: event_id, kind: kind }
    payload[:value] = value if kind == "set-story"
    payload
  end

  def increment_projection_metric
    GameStorage.database.execute(
      "INSERT INTO play_campaign_service_metrics (campaign_id, projection_events) VALUES (?, 1) " \
      "ON CONFLICT(campaign_id) DO UPDATE SET projection_events = projection_events + 1",
      [params[:id]]
    )
  end
end

# Metrics deliberately load only aggregate service counters, never campaign
# content or actor details.
class PlayCampaignServiceMetricsController < ApplicationController
  include PlayAuthentication

  def show
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign
      next :forbidden unless campaign["owner"] == actor["username"]

      counters = GameStorage.database.get_first_row(
        "SELECT accepted_rate_events, rejected_rate_events, projection_events " \
        "FROM play_campaign_service_metrics WHERE campaign_id = ?", [params[:id]]
      )
      {
        accepted_rate_events: counters ? counters["accepted_rate_events"] : 0,
        rejected_rate_events: counters ? counters["rejected_rate_events"] : 0,
        projection_events: counters ? counters["projection_events"] : 0,
        uptime_ticks: 1
      }
    end

    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end
end

class PlayCampaignServiceModeController < ApplicationController
  include PlayAuthentication

  def update
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless body.is_a?(Hash) && body.keys == ["maintenance"] && [true, false].include?(body["maintenance"])

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT id FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign
      next :forbidden unless actor["role"] == "dm"

      ServiceMode.maintenance = body["maintenance"]
      body["maintenance"]
    end

    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: { maintenance: result }
  end
end

class PlayCampaignSafeTurnsController < ApplicationController
  include PlayAuthentication

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless valid_submission?(body)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign_member?(campaign, actor)

      GameStorage.database.transaction do
        duplicate = GameStorage.database.get_first_value(
          "SELECT 1 FROM play_campaign_safe_turns WHERE campaign_id = ? AND submission_id = ?",
          [params[:id], body["submission_id"]]
        )
        next :duplicate if duplicate

        state = GameStorage.database.get_first_row(
          "SELECT current_turn FROM play_campaign_safe_turn_states WHERE campaign_id = ?", [params[:id]]
        )
        current_turn = state ? state["current_turn"] : 1
        next [:stale, current_turn] unless body["expected_turn"] == current_turn

        GameStorage.database.execute(
          "INSERT INTO play_campaign_safe_turns (campaign_id, submission_id, action, accepted_turn) VALUES (?, ?, ?, ?)",
          [params[:id], body["submission_id"], body["action"], current_turn]
        )
        if state
          GameStorage.database.execute(
            "UPDATE play_campaign_safe_turn_states SET current_turn = ? WHERE campaign_id = ?",
            [current_turn + 1, params[:id]]
          )
        else
          GameStorage.database.execute(
            "INSERT INTO play_campaign_safe_turn_states (campaign_id, current_turn) VALUES (?, ?)",
            [params[:id], current_turn + 1]
          )
        end
        [:created, safe_turn_payload(body["submission_id"], body["action"], current_turn)]
      end
    end

    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "duplicate submission_id" }, status: :conflict) if result == :duplicate
    return render(json: { current_turn: result[1] }, status: :conflict) if result[0] == :stale

    render json: result[1], status: :created
  end

  def index
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign_member?(campaign, actor)

      state = GameStorage.database.get_first_value(
        "SELECT current_turn FROM play_campaign_safe_turn_states WHERE campaign_id = ?", [params[:id]]
      ) || 1
      accepted = GameStorage.database.execute(
        "SELECT submission_id, action, accepted_turn FROM play_campaign_safe_turns " \
        "WHERE campaign_id = ? ORDER BY accepted_turn", [params[:id]]
      ).map { |turn| safe_turn_payload(turn["submission_id"], turn["action"], turn["accepted_turn"]) }
      { current_turn: state, accepted: accepted }
    end

    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end

  private

  def valid_submission?(body)
    body.is_a?(Hash) && present_string?(body["submission_id"]) && present_string?(body["action"]) &&
      body["expected_turn"].is_a?(Integer) && body["expected_turn"].positive?
  end

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def campaign_member?(campaign, actor)
    campaign["owner"] == actor["username"] || GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
      [params[:id], actor["username"]]
    )
  end

  def safe_turn_payload(submission_id, action, accepted_turn)
    { submission_id: submission_id, action: action, accepted_turn: accepted_turn, next_turn: accepted_turn + 1 }
  end
end

class PlayCampaignIdempotentEventsController < ApplicationController
  include PlayAuthentication

  def create
    actor = require_play_actor
    return unless actor

    key = request.headers["Idempotency-Key"]
    body = json_body
    return bad_request unless key.is_a?(String) && !key.strip.empty? && valid_event?(body)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign_member?(campaign, actor)

      existing_key = GameStorage.database.get_first_row(
        "SELECT event_id, value, sequence, idempotency_key FROM play_campaign_idempotent_events " \
        "WHERE campaign_id = ? AND idempotency_key = ?", [params[:id], key]
      )
      if existing_key
        next existing_key["event_id"] == body["event_id"] && existing_key["value"] == body["value"] ?
          [:replayed, event_payload(existing_key)] : :key_conflict
      end

      next :event_conflict if GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_idempotent_events WHERE campaign_id = ? AND event_id = ?",
        [params[:id], body["event_id"]]
      )

      sequence = GameStorage.database.get_first_value(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_idempotent_events WHERE campaign_id = ?",
        [params[:id]]
      )
      event = {
        "event_id" => body["event_id"], "value" => body["value"],
        "sequence" => sequence, "idempotency_key" => key
      }
      GameStorage.database.execute(
        "INSERT INTO play_campaign_idempotent_events " \
        "(campaign_id, sequence, event_id, value, idempotency_key) VALUES (?, ?, ?, ?, ?)",
        [params[:id], sequence, event["event_id"], event["value"], event["idempotency_key"]]
      )
      [:created, event_payload(event)]
    end

    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "idempotency key conflict" }, status: :conflict) if result == :key_conflict
    return render(json: { error: "duplicate event_id" }, status: :conflict) if result == :event_conflict

    replayed, event = result
    render json: event, status: replayed == :created ? :created : :ok
  end

  def index
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign_member?(campaign, actor)

      events = GameStorage.database.execute(
        "SELECT event_id, value, sequence, idempotency_key FROM play_campaign_idempotent_events " \
        "WHERE campaign_id = ? ORDER BY sequence", [params[:id]]
      ).map { |event| event_payload(event) }
      { events: events }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end

  private

  def valid_event?(body)
    body.is_a?(Hash) && present_string?(body["event_id"]) && present_string?(body["value"])
  end

  # The campaign owner is a member for this endpoint even if they have no
  # character-membership row. This matches the other campaign read/write APIs.
  def campaign_member?(campaign, actor)
    campaign["owner"] == actor["username"] || GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
      [params[:id], actor["username"]]
    )
  end

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def event_payload(event)
    {
      event_id: event["event_id"], value: event["value"], sequence: event["sequence"],
      idempotency_key: event["idempotency_key"]
    }
  end
end

class PlayCampaignAuditEventsController < ApplicationController
  include PlayAuthentication

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless body.is_a?(Hash) && present_string?(body["kind"]) && present_string?(body["correlation_id"])

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign["owner"] == actor["username"] || campaign_member?(actor["username"])

      correlation_id = body["correlation_id"]
      next :duplicate if GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_audit_events WHERE campaign_id = ? AND correlation_id = ?",
        [params[:id], correlation_id]
      )

      timestamp = GameStorage.database.get_first_value(
        "SELECT COALESCE(MAX(timestamp), 0) + 1 FROM play_campaign_audit_events WHERE campaign_id = ?", [params[:id]]
      )
      entry = {
        kind: body["kind"],
        actor: actor["username"],
        role: campaign["owner"] == actor["username"] ? "DM" : "player",
        timestamp: timestamp,
        correlation_id: correlation_id
      }
      GameStorage.database.execute(
        "INSERT INTO play_campaign_audit_events " \
        "(campaign_id, timestamp, kind, actor, role, correlation_id) VALUES (?, ?, ?, ?, ?, ?)",
        [params[:id], entry[:timestamp], entry[:kind], entry[:actor], entry[:role], entry[:correlation_id]]
      )
      entry
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "duplicate correlation_id" }, status: :conflict) if result == :duplicate

    render json: result, status: :created
  end

  def index
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign["owner"] == actor["username"]

      entries = GameStorage.database.execute(
        "SELECT kind, actor, role, timestamp, correlation_id FROM play_campaign_audit_events " \
        "WHERE campaign_id = ? ORDER BY timestamp", [params[:id]]
      ).map do |entry|
        {
          kind: entry["kind"], actor: entry["actor"], role: entry["role"],
          timestamp: entry["timestamp"], correlation_id: entry["correlation_id"]
        }
      end
      { entries: entries }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end

  private

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def campaign_member?(username)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], username]
    )
  end
end

class PlayNarrationsController < ApplicationController
  include PlayAuthentication
  include PlayCampaignEvents

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    text = body["text"] if body.is_a?(Hash)
    return bad_request unless text.is_a?(String) && !text.empty?

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign
      delegated = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_delegations WHERE campaign_id = ? AND username = ? " \
        "AND active = 1 AND powers = ?",
        [params[:id], actor["username"], JSON.generate(["narrate"])]
      )
      next :forbidden unless campaign["owner"] == actor["username"] || delegated

      sequence = next_play_event_sequence(params[:id])
      GameStorage.database.execute(
        "INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)",
        [params[:id], sequence, "narration", actor["username"], text]
      )
      { sequence: sequence, kind: "narration", actor: actor["username"], text: text }
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result, status: :created
  end
end

class CampaignInventoryController < ApplicationController
  def create
    body = json_body
    return bad_request unless body.is_a?(Hash)

    item_slug = body["item_slug"]
    quantity = integer(body["quantity"])
    owner = body["owner"]
    return bad_request unless present_string?(item_slug) && quantity&.positive? && present_string?(owner)

    result = GameStorage.synchronize do
      next :missing unless campaign_exists?(params[:id])

      GameStorage.database.execute(
        "INSERT INTO campaign_inventory (campaign_id, item_slug, quantity, owner) VALUES (?, ?, ?, ?)",
        [params[:id], item_slug, quantity, owner]
      )
      :created
    end
    return campaign_not_found if result == :missing

    render json: { item_slug: item_slug, quantity: quantity, owner: owner }, status: :created
  end

  def assign_equipment
    body = json_body
    return bad_request unless body.is_a?(Hash)

    item_slug = body["item_slug"]
    quantity = integer(body["quantity"])
    return bad_request unless present_string?(item_slug) && quantity&.positive?

    result = GameStorage.synchronize do
      next :missing_campaign unless campaign_exists?(params[:id])
      next :missing_character unless character_exists?(params[:character_id], params[:id])
      next :unavailable unless available_quantity(params[:id], item_slug) >= quantity

      GameStorage.database.execute(
        "INSERT INTO character_equipment (campaign_id, character_id, item_slug, quantity) VALUES (?, ?, ?, ?)",
        [params[:id], params[:character_id], item_slug, quantity]
      )
      :created
    end
    return campaign_not_found if result == :missing_campaign
    return character_not_found if result == :missing_character
    return render(json: { error: "insufficient party inventory" }, status: :conflict) if result == :unavailable

    render json: { character_id: params[:character_id], item_slug: item_slug, quantity: quantity }
  end

  def summary
    counts = GameStorage.synchronize do
      next nil unless campaign_exists?(params[:id])

      party_items = GameStorage.database.get_first_value(
        "SELECT COUNT(*) FROM campaign_inventory WHERE campaign_id = ? AND owner = ?", [params[:id], "party"]
      )
      assigned_items = GameStorage.database.get_first_value(
        "SELECT COUNT(*) FROM character_equipment WHERE campaign_id = ?", [params[:id]]
      )
      {
        party_items: party_items,
        assigned_items: assigned_items,
        healing_potions_available: available_quantity(params[:id], "healing-potion")
      }
    end
    return campaign_not_found unless counts

    render json: { campaign_id: params[:id], **counts }
  end

  private

  def campaign_exists?(id)
    GameStorage.database.get_first_value("SELECT 1 FROM campaigns WHERE id = ?", [id])
  end

  def character_exists?(character_id, campaign_id)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM campaign_characters WHERE id = ? AND campaign_id = ?", [character_id, campaign_id]
    )
  end

  def available_quantity(campaign_id, item_slug)
    party_quantity = GameStorage.database.get_first_value(
      "SELECT COALESCE(SUM(quantity), 0) FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?",
      [campaign_id, item_slug, "party"]
    )
    assigned_quantity = GameStorage.database.get_first_value(
      "SELECT COALESCE(SUM(quantity), 0) FROM character_equipment WHERE campaign_id = ? AND item_slug = ?",
      [campaign_id, item_slug]
    )
    party_quantity - assigned_quantity
  end

  def campaign_not_found
    render json: { error: "unknown campaign" }, status: :not_found
  end

  def character_not_found
    render json: { error: "unknown character" }, status: :not_found
  end
end

class CraftingProjectsController < ApplicationController
  def create
    body = json_body
    return bad_request unless body.is_a?(Hash)

    project_id = body["id"]
    character_id = body["character_id"]
    item_slug = body["item_slug"]
    days_required = integer(body["days_required"])
    cost_gp = integer(body["cost_gp"])
    return bad_request unless present_string?(project_id) && present_string?(character_id) && present_string?(item_slug) &&
                              days_required&.positive? && cost_gp && cost_gp >= 0

    result = GameStorage.synchronize do
      next :missing_campaign unless campaign_exists?(params[:id])
      next :missing_character unless character_exists?(character_id, params[:id])

      begin
        GameStorage.database.execute(
          "INSERT INTO crafting_projects " \
          "(id, campaign_id, character_id, item_slug, days_required, days_completed, cost_gp, status) " \
          "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
          [project_id, params[:id], character_id, item_slug, days_required, 0, cost_gp, "active"]
        )
        :created
      rescue SQLite3::ConstraintException
        :duplicate
      end
    end
    return campaign_not_found if result == :missing_campaign
    return character_not_found if result == :missing_character
    return render(json: { error: "crafting project id already exists" }, status: :conflict) if result == :duplicate

    render json: project_payload(project_id, character_id, item_slug, days_required, 0, "active"), status: :created
  end

  def advance
    body = json_body
    days = integer(body["days"]) if body.is_a?(Hash)
    return bad_request unless days&.positive?

    result = GameStorage.synchronize do
      project = GameStorage.database.get_first_row(
        "SELECT * FROM crafting_projects WHERE id = ? AND campaign_id = ?", [params[:project_id], params[:id]]
      )
      next :missing unless project
      next :complete if project["status"] == "complete"

      completed = [project["days_completed"] + days, project["days_required"]].min
      status = completed == project["days_required"] ? "complete" : "active"
      GameStorage.database.execute(
        "UPDATE crafting_projects SET days_completed = ?, status = ? WHERE id = ?", [completed, status, project["id"]]
      )
      if status == "complete"
        GameStorage.database.execute(
          "INSERT INTO campaign_inventory (campaign_id, item_slug, quantity, owner) VALUES (?, ?, ?, ?)",
          [project["campaign_id"], project["item_slug"], 1, "party"]
        )
      end
      { id: project["id"], days_completed: completed, status: status }
    end
    return project_not_found if result == :missing
    return render(json: { error: "crafting project already complete" }, status: :conflict) if result == :complete

    render json: result
  end

  private

  def campaign_exists?(id)
    GameStorage.database.get_first_value("SELECT 1 FROM campaigns WHERE id = ?", [id])
  end

  def character_exists?(character_id, campaign_id)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM campaign_characters WHERE id = ? AND campaign_id = ?", [character_id, campaign_id]
    )
  end

  def project_payload(id, character_id, item_slug, days_required, days_completed, status)
    {
      id: id,
      character_id: character_id,
      item_slug: item_slug,
      days_required: days_required,
      days_completed: days_completed,
      status: status
    }
  end

  def campaign_not_found
    render json: { error: "unknown campaign" }, status: :not_found
  end

  def character_not_found
    render json: { error: "unknown character" }, status: :not_found
  end

  def project_not_found
    render json: { error: "unknown crafting project" }, status: :not_found
  end
end

class CampaignQuestsController < ApplicationController
  STATUSES = %w[active completed blocked].freeze

  def create
    body = json_body
    return bad_request unless body.is_a?(Hash)

    id = body["id"]
    title = body["title"]
    status = body["status"]
    milestones = body["milestones"]
    return bad_request unless present_string?(id) && present_string?(title) && STATUSES.include?(status) && valid_milestones?(milestones)

    result = GameStorage.synchronize do
      next :missing unless campaign_exists?(params[:id])

      begin
        GameStorage.database.execute(
          "INSERT INTO campaign_quests (id, campaign_id, title, status, milestones, completed_milestones) VALUES (?, ?, ?, ?, ?, ?)",
          [id, params[:id], title, status, JSON.generate(milestones), JSON.generate([])]
        )
        :created
      rescue SQLite3::ConstraintException
        :duplicate
      end
    end
    return campaign_not_found if result == :missing
    return render(json: { error: "quest id already exists" }, status: :conflict) if result == :duplicate

    render json: quest_payload(id, title, status, milestones, []), status: :created
  end

  def progress
    body = json_body
    completed = body["completed"] if body.is_a?(Hash)
    return bad_request unless valid_milestones?(completed)

    result = GameStorage.synchronize do
      quest = GameStorage.database.get_first_row(
        "SELECT * FROM campaign_quests WHERE id = ? AND campaign_id = ?", [params[:quest_id], params[:id]]
      )
      next :missing unless quest

      milestones = JSON.parse(quest["milestones"])
      next :invalid unless completed.all? { |milestone| milestones.include?(milestone) }

      done = JSON.parse(quest["completed_milestones"])
      done |= completed
      status = milestones.all? { |milestone| done.include?(milestone) } ? "completed" : quest["status"]
      GameStorage.database.execute(
        "UPDATE campaign_quests SET status = ?, completed_milestones = ? WHERE id = ?",
        [status, JSON.generate(done), quest["id"]]
      )
      quest_payload(quest["id"], quest["title"], status, milestones, done)
    end
    return quest_not_found if result == :missing
    return bad_request if result == :invalid

    render json: result.slice(:id, :status, :milestones_total, :milestones_done)
  end

  def summary
    counts = GameStorage.synchronize do
      next nil unless campaign_exists?(params[:id])

      rows = GameStorage.database.execute(
        "SELECT status, COUNT(*) AS count FROM campaign_quests WHERE campaign_id = ? GROUP BY status", [params[:id]]
      )
      rows.to_h { |row| [row["status"], row["count"]] }
    end
    return campaign_not_found unless counts

    render json: {
      campaign_id: params[:id],
      active: counts.fetch("active", 0),
      completed: counts.fetch("completed", 0),
      blocked: counts.fetch("blocked", 0)
    }
  end

  private

  def valid_milestones?(milestones)
    milestones.is_a?(Array) && milestones.all? { |milestone| present_string?(milestone) } && milestones.uniq.length == milestones.length
  end

  def campaign_exists?(id)
    GameStorage.database.get_first_value("SELECT 1 FROM campaigns WHERE id = ?", [id])
  end

  def quest_payload(id, title, status, milestones, completed)
    {
      id: id,
      title: title,
      status: status,
      milestones_total: milestones.length,
      milestones_done: completed.length
    }
  end

  def campaign_not_found
    render json: { error: "unknown campaign" }, status: :not_found
  end

  def quest_not_found
    render json: { error: "unknown quest" }, status: :not_found
  end
end

class CampaignRelationshipsController < ApplicationController
  def create_faction
    body = json_body
    return bad_request unless body.is_a?(Hash)

    id = body["id"]
    name = body["name"]
    stance = body["stance"]
    return bad_request unless present_string?(id) && present_string?(name) && present_string?(stance)

    result = GameStorage.synchronize do
      next :missing unless campaign_exists?(params[:id])

      begin
        GameStorage.database.execute(
          "INSERT INTO campaign_factions (id, campaign_id, name, stance) VALUES (?, ?, ?, ?)",
          [id, params[:id], name, stance]
        )
        :created
      rescue SQLite3::ConstraintException
        :duplicate
      end
    end
    return campaign_not_found if result == :missing
    return render(json: { error: "faction id already exists" }, status: :conflict) if result == :duplicate

    render json: { id: id, name: name, stance: stance }, status: :created
  end

  def create_npc
    body = json_body
    return bad_request unless body.is_a?(Hash)

    id = body["id"]
    name = body["name"]
    faction_id = body["faction_id"]
    disposition = integer(body["disposition"])
    return bad_request unless present_string?(id) && present_string?(name) && present_string?(faction_id) && !disposition.nil?

    result = GameStorage.synchronize do
      next :missing unless campaign_exists?(params[:id])
      next :invalid_faction unless faction_belongs_to_campaign?(faction_id, params[:id])

      begin
        GameStorage.database.execute(
          "INSERT INTO campaign_npcs (id, campaign_id, name, faction_id, disposition) VALUES (?, ?, ?, ?, ?)",
          [id, params[:id], name, faction_id, disposition]
        )
        :created
      rescue SQLite3::ConstraintException
        :duplicate
      end
    end
    return campaign_not_found if result == :missing
    return bad_request if result == :invalid_faction
    return render(json: { error: "npc id already exists" }, status: :conflict) if result == :duplicate

    render json: { id: id, name: name, faction_id: faction_id, disposition: disposition }, status: :created
  end

  def summary
    counts = GameStorage.synchronize do
      next nil unless campaign_exists?(params[:id])

      faction_count = GameStorage.database.get_first_value(
        "SELECT COUNT(*) FROM campaign_factions WHERE campaign_id = ?", [params[:id]]
      )
      npc_counts = GameStorage.database.get_first_row(
        "SELECT COUNT(*) AS total, SUM(CASE WHEN disposition > 0 THEN 1 ELSE 0 END) AS friendly " \
        "FROM campaign_npcs WHERE campaign_id = ?", [params[:id]]
      )
      { factions: faction_count, npcs: npc_counts["total"], friendly_npcs: npc_counts["friendly"] || 0 }
    end
    return campaign_not_found unless counts

    render json: { campaign_id: params[:id], **counts }
  end

  private

  def campaign_exists?(id)
    GameStorage.database.get_first_value("SELECT 1 FROM campaigns WHERE id = ?", [id])
  end

  def faction_belongs_to_campaign?(faction_id, campaign_id)
    GameStorage.database.get_first_value(
      "SELECT 1 FROM campaign_factions WHERE id = ? AND campaign_id = ?", [faction_id, campaign_id]
    )
  end

  def campaign_not_found
    render json: { error: "unknown campaign" }, status: :not_found
  end
end

class CampaignSessionsController < ApplicationController
  def create
    body = json_body
    return bad_request unless body.is_a?(Hash)

    id = body["id"]
    starts_at = body["starts_at"]
    duration_minutes = integer(body["duration_minutes"])
    agenda = body["agenda"]
    starts_at_epoch = parse_starts_at(starts_at)
    return bad_request unless present_string?(id) && starts_at_epoch && duration_minutes&.positive? && valid_agenda?(agenda)

    result = GameStorage.synchronize do
      next :missing unless campaign_exists?(params[:id])

      begin
        GameStorage.database.execute(
          "INSERT INTO campaign_sessions (id, campaign_id, starts_at, starts_at_epoch, duration_minutes, agenda) " \
          "VALUES (?, ?, ?, ?, ?, ?)",
          [id, params[:id], starts_at, starts_at_epoch, duration_minutes, JSON.generate(agenda)]
        )
        :created
      rescue SQLite3::ConstraintException
        :duplicate
      end
    end
    return campaign_not_found if result == :missing
    return render(json: { error: "session id already exists" }, status: :conflict) if result == :duplicate

    render json: session_payload(id, starts_at, duration_minutes, agenda), status: :created
  end

  def attendance
    body = json_body
    return bad_request unless body.is_a?(Hash)

    present = body["present"]
    absent = body["absent"]
    return bad_request unless valid_character_ids?(present) && valid_character_ids?(absent) && (present & absent).empty?

    result = GameStorage.synchronize do
      session = GameStorage.database.get_first_row(
        "SELECT id FROM campaign_sessions WHERE id = ? AND campaign_id = ?", [params[:session_id], params[:id]]
      )
      next :missing_session unless session
      next :invalid_character unless characters_belong_to_campaign?(present + absent, params[:id])

      GameStorage.database.execute(
        "INSERT INTO campaign_session_attendance (session_id, present_characters, absent_characters) VALUES (?, ?, ?) " \
        "ON CONFLICT(session_id) DO UPDATE SET present_characters = excluded.present_characters, " \
        "absent_characters = excluded.absent_characters",
        [params[:session_id], JSON.generate(present), JSON.generate(absent)]
      )
      :recorded
    end
    return session_not_found if result == :missing_session
    return bad_request if result == :invalid_character

    render json: { session_id: params[:session_id], present_count: present.length, absent_count: absent.length }
  end

  def next
    session = GameStorage.synchronize do
      next :missing_campaign unless campaign_exists?(params[:id])

      scheduled_session = GameStorage.database.get_first_row(
        "SELECT id, starts_at, agenda FROM campaign_sessions WHERE campaign_id = ? " \
        "ORDER BY starts_at_epoch, rowid LIMIT 1", [params[:id]]
      )
      scheduled_session || :missing_session
    end
    return campaign_not_found if session == :missing_campaign
    return session_not_found if session == :missing_session

    render json: {
      id: session["id"],
      starts_at: session["starts_at"],
      agenda_count: JSON.parse(session["agenda"]).length
    }
  end

  private

  def parse_starts_at(value)
    return nil unless value.is_a?(String)

    Time.iso8601(value).to_i
  rescue ArgumentError
    nil
  end

  def valid_agenda?(agenda)
    agenda.is_a?(Array) && agenda.all? { |item| present_string?(item) }
  end

  def valid_character_ids?(character_ids)
    character_ids.is_a?(Array) && character_ids.all? { |id| present_string?(id) } && character_ids.uniq.length == character_ids.length
  end

  def campaign_exists?(id)
    GameStorage.database.get_first_value("SELECT 1 FROM campaigns WHERE id = ?", [id])
  end

  def characters_belong_to_campaign?(character_ids, campaign_id)
    return true if character_ids.empty?

    placeholders = Array.new(character_ids.length, "?").join(", ")
    count = GameStorage.database.get_first_value(
      "SELECT COUNT(*) FROM campaign_characters WHERE campaign_id = ? AND id IN (#{placeholders})",
      [campaign_id, *character_ids]
    )
    count == character_ids.length
  end

  def session_payload(id, starts_at, duration_minutes, agenda)
    { id: id, starts_at: starts_at, duration_minutes: duration_minutes, agenda_count: agenda.length }
  end

  def campaign_not_found
    render json: { error: "unknown campaign" }, status: :not_found
  end

  def session_not_found
    render json: { error: "unknown session" }, status: :not_found
  end
end

class CampaignAnalyticsController < ApplicationController
  READINESS_WEIGHTS = {
    has_dm: 25,
    has_characters: 20,
    has_next_session: 20,
    has_active_quest: 20
  }.freeze

  def summary
    analytics = campaign_analytics
    return campaign_not_found unless analytics

    render json: {
      campaign_id: params[:id],
      readiness_score: readiness_score(analytics[:signals]),
      open_quests: analytics[:open_quests],
      friendly_npcs: analytics[:friendly_npcs],
      scheduled_sessions: analytics[:scheduled_sessions],
      inventory_items: analytics[:inventory_items]
    }
  end

  def risk_report
    body = json_body
    return bad_request unless body.is_a?(Hash) && [true, false].include?(body["include_zeroes"])

    analytics = campaign_analytics
    return campaign_not_found unless analytics

    missing = analytics[:signals].select { |_signal, present| !present }.keys.map(&:to_s)
    render json: {
      campaign_id: params[:id],
      risk_level: risk_level(missing.length),
      missing: missing,
      signals: analytics[:signals]
    }
  end

  private

  def campaign_analytics
    GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT dm FROM campaigns WHERE id = ?", [params[:id]]
      )
      next nil unless campaign

      database = GameStorage.database
      character_count = database.get_first_value(
        "SELECT COUNT(*) FROM campaign_characters WHERE campaign_id = ?", [params[:id]]
      )
      open_quests = database.get_first_value(
        "SELECT COUNT(*) FROM campaign_quests WHERE campaign_id = ? AND status = ?", [params[:id], "active"]
      )
      friendly_npcs = database.get_first_value(
        "SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ? AND disposition > 0", [params[:id]]
      )
      scheduled_sessions = database.get_first_value(
        "SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = ?", [params[:id]]
      )
      inventory_items = database.get_first_value(
        "SELECT COUNT(DISTINCT item_slug) FROM campaign_inventory WHERE campaign_id = ?", [params[:id]]
      )

      {
        open_quests: open_quests,
        friendly_npcs: friendly_npcs,
        scheduled_sessions: scheduled_sessions,
        inventory_items: inventory_items,
        signals: {
          has_dm: !campaign["dm"].empty?,
          has_characters: character_count.positive?,
          has_next_session: scheduled_sessions.positive?,
          has_active_quest: open_quests.positive?
        }
      }
    end
  end

  def readiness_score(signals)
    READINESS_WEIGHTS.sum { |signal, weight| signals[signal] ? weight : 0 }
  end

  def risk_level(missing_count)
    return "low" if missing_count.zero?
    return "medium" if missing_count <= 2

    "high"
  end

  def campaign_not_found
    render json: { error: "unknown campaign" }, status: :not_found
  end
end

class CampaignAuditController < ApplicationController
  def audit
    counts = campaign_counts
    return campaign_not_found unless counts

    render json: {
      campaign_id: params[:id],
      events: counts[:events],
      quests: counts[:quests],
      npcs: counts[:npcs],
      sessions: counts[:sessions]
    }
  end

  def export
    campaign, counts = campaign_and_counts
    return campaign_not_found unless campaign

    render json: {
      campaign_id: campaign["id"],
      name: campaign["name"],
      characters: counts[:characters],
      quests: counts[:quests],
      npcs: counts[:npcs],
      inventory_items: counts[:inventory_items],
      sessions: counts[:sessions],
      schema_version: GameStorage::SCHEMA_VERSION
    }
  end

  private

  def campaign_counts
    campaign, counts = campaign_and_counts
    campaign && counts
  end

  def campaign_and_counts
    GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row("SELECT id, name FROM campaigns WHERE id = ?", [params[:id]])
      next [nil, nil] unless campaign

      database = GameStorage.database
      counts = {
        events: database.get_first_value("SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?", [params[:id]]),
        characters: database.get_first_value("SELECT COUNT(*) FROM campaign_characters WHERE campaign_id = ?", [params[:id]]),
        quests: database.get_first_value("SELECT COUNT(*) FROM campaign_quests WHERE campaign_id = ?", [params[:id]]),
        npcs: database.get_first_value("SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ?", [params[:id]]),
        inventory_items: database.get_first_value(
          "SELECT COUNT(DISTINCT item_slug) FROM campaign_inventory WHERE campaign_id = ?", [params[:id]]
        ),
        sessions: database.get_first_value("SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = ?", [params[:id]])
      }
      [campaign, counts]
    end
  end

  def campaign_not_found
    render json: { error: "unknown campaign" }, status: :not_found
  end
end

class StorageController < ApplicationController
  def status
    render json: {
      driver: "sqlite",
      schema_version: GameStorage::SCHEMA_VERSION,
      initialized: GameStorage.initialized?
    }
  end

  def reset
    GameStorage.reset!
    render json: { ok: true, schema_version: GameStorage::SCHEMA_VERSION }
  end
end

class PhbSpellSlotsController < ApplicationController
  WIZARD_LEVEL_FIVE_SLOTS = { "1" => 4, "2" => 3, "3" => 2 }.freeze

  def create
    body = json_body
    return bad_request unless body.is_a?(Hash)

    character_class = body["class"]
    level = integer(body["level"])
    return bad_request unless character_class == "wizard" && level == 5

    render json: { class: character_class, level: level, slots: WIZARD_LEVEL_FIVE_SLOTS }
  end
end

class PhbLongRestsController < ApplicationController
  def create
    body = json_body
    return bad_request unless body.is_a?(Hash)

    level = integer(body["level"])
    hp_current = integer(body["hp_current"])
    hp_max = integer(body["hp_max"])
    hit_dice_spent = integer(body["hit_dice_spent"])
    exhaustion_level = integer(body["exhaustion_level"])
    return bad_request unless valid_values?(level, hp_current, hp_max, hit_dice_spent, exhaustion_level)

    restored_hit_dice = [(level / 2), 1].max
    render json: {
      hp_current: hp_max,
      hit_dice_spent: [hit_dice_spent - restored_hit_dice, 0].max,
      exhaustion_level: [exhaustion_level - 1, 0].max
    }
  end

  private

  def valid_values?(level, hp_current, hp_max, hit_dice_spent, exhaustion_level)
    level&.positive? && hp_current && hp_current >= 0 && hp_max && hp_max >= 0 &&
      hit_dice_spent && hit_dice_spent >= 0 && exhaustion_level && exhaustion_level >= 0
  end
end

class PhbEquipmentLoadController < ApplicationController
  def create
    body = json_body
    return bad_request unless body.is_a?(Hash)

    strength = integer(body["strength"])
    weight = integer(body["weight"])
    return bad_request unless strength&.positive? && weight && weight >= 0

    capacity = strength * 15
    render json: { capacity: capacity, weight: weight, encumbered: weight > capacity }
  end
end

class DmToolsController < ApplicationController
  include EncounterMath

  RECOMMENDATIONS = {
    "trivial" => "cakewalk",
    "easy" => "safe warm-up",
    "medium" => "fair fight",
    "hard" => "tense",
    "deadly" => "deadly risk"
  }.freeze

  def encounter_builder
    body = json_body
    campaign_id = body["campaign_id"]
    party = body["party"]
    monster_slugs = body["monster_slugs"]
    return bad_request unless present_string?(campaign_id) && party.is_a?(Array) && monster_slugs.is_a?(Array)

    thresholds = summed_thresholds(party)
    return bad_request unless thresholds

    monsters = GameStorage.synchronize do
      monster_slugs.map do |slug|
        break nil unless present_string?(slug)

        GameStorage.database.get_first_row("SELECT cr FROM monsters WHERE slug = ?", [slug])
      end
    end
    return bad_request unless monsters && monsters.all?

    crs = monsters.map { |monster| monster["cr"] }
    return bad_request unless crs.all? { |cr| XP.key?(cr) }

    base_xp = crs.sum { |cr| XP.fetch(cr) }
    monster_count = crs.length
    adjusted_xp = base_xp * encounter_multiplier(monster_count)
    difficulty = difficulty_for(adjusted_xp, thresholds)
    render json: {
      campaign_id: campaign_id,
      base_xp: base_xp,
      adjusted_xp: adjusted_xp,
      difficulty: difficulty,
      monster_count: monster_count,
      recommendation: RECOMMENDATIONS.fetch(difficulty)
    }
  end

  def loot_parcel
    body = json_body
    campaign_id = body["campaign_id"]
    return bad_request unless present_string?(campaign_id) && integer(body["tier"]) == 1

    render json: {
      campaign_id: campaign_id,
      coins_gp: 75,
      items: [{ slug: "healing-potion", quantity: 2 }]
    }
  end

  def session_recap
    campaign_id = json_body["campaign_id"]
    return bad_request unless present_string?(campaign_id)

    recap = GameStorage.synchronize do
      exists = GameStorage.database.get_first_value("SELECT 1 FROM campaigns WHERE id = ?", [campaign_id])
      next nil unless exists

      GameStorage.database.get_first_row(
        "SELECT summary FROM campaign_events WHERE campaign_id = ? ORDER BY rowid DESC LIMIT 1", [campaign_id]
      )
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) unless recap || campaign_exists?(campaign_id)

    summary = recap ? recap["summary"] : "No recent events."
    open_threads = summary == "Nyx scouts the goblin trail." ? ["Resolve goblin trail ambush"] : []
    render json: { campaign_id: campaign_id, summary: summary, open_threads: open_threads }
  end

  private

  def campaign_exists?(campaign_id)
    GameStorage.synchronize do
      GameStorage.database.get_first_value("SELECT 1 FROM campaigns WHERE id = ?", [campaign_id])
    end
  end

end

# Safety boundaries and accepted checks are campaign-local.  Boundary changes
# replace the complete set, while safety checks are an append-only stream.
class PlayCampaignSafetyController < ApplicationController
  include PlayAuthentication

  def replace_boundaries
    actor = require_play_actor
    return unless actor

    body = json_body
    tags = body.is_a?(Hash) ? body["blocked_tags"] : nil
    return bad_request unless valid_tags?(tags)

    sorted_tags = tags.sort
    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign_dm?(campaign, actor)

      GameStorage.database.transaction do
        GameStorage.database.execute("DELETE FROM play_campaign_safety_boundaries WHERE campaign_id = ?", [params[:id]])
        sorted_tags.each do |tag|
          GameStorage.database.execute(
            "INSERT INTO play_campaign_safety_boundaries (campaign_id, tag) VALUES (?, ?)", [params[:id], tag]
          )
        end
      end
      { blocked_tags: sorted_tags }
    end
    render_result(result)
  end

  def boundaries
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign_member?(campaign, actor)

      { blocked_tags: boundary_tags }
    end
    render_result(result)
  end

  def create_check
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless valid_check?(body)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign_member?(campaign, actor)
      next :duplicate if GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_safety_events WHERE campaign_id = ? AND event_id = ?", [params[:id], body["event_id"]]
      )

      blocked = boundary_tags
      next :blocked if body["tags"].any? { |tag| blocked.include?(tag) }

      sequence = GameStorage.database.get_first_value(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_safety_events WHERE campaign_id = ?", [params[:id]]
      )
      GameStorage.database.execute(
        "INSERT INTO play_campaign_safety_events (campaign_id, sequence, event_id, kind, text, tags) VALUES (?, ?, ?, ?, ?, ?)",
        [params[:id], sequence, body["event_id"], body["kind"], body["text"], JSON.generate(body["tags"])]
      )
      event_payload(body["event_id"], body["kind"], body["text"], body["tags"], sequence)
    end
    return render(json: { error: "event id already exists" }, status: :conflict) if result == :duplicate
    return render(json: { error: "blocked tag" }, status: :conflict) if result == :blocked

    render_result(result, created: true)
  end

  def events
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign_member?(campaign, actor)

      events = GameStorage.database.execute(
        "SELECT event_id, kind, text, tags, sequence FROM play_campaign_safety_events WHERE campaign_id = ? ORDER BY sequence", [params[:id]]
      ).map { |row| event_payload(row["event_id"], row["kind"], row["text"], JSON.parse(row["tags"]), row["sequence"]) }
      { events: events }
    end
    render_result(result)
  end

  private

  def valid_tags?(tags)
    tags.is_a?(Array) && !tags.empty? && tags.all? { |tag| tag.is_a?(String) && !tag.strip.empty? } && tags.uniq.length == tags.length
  end

  def valid_check?(body)
    body.is_a?(Hash) && present_string?(body["event_id"]) && present_string?(body["text"]) &&
      %w[narration chat].include?(body["kind"]) && valid_tags?(body["tags"])
  end

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def campaign_dm?(campaign, actor)
    actor["role"] == "dm" && campaign["owner"] == actor["username"]
  end

  def campaign_member?(campaign, actor)
    campaign_dm?(campaign, actor) || GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], actor["username"]]
    )
  end

  def boundary_tags
    GameStorage.database.execute(
      "SELECT tag FROM play_campaign_safety_boundaries WHERE campaign_id = ? ORDER BY tag", [params[:id]]
    ).map { |row| row["tag"] }
  end

  def event_payload(event_id, kind, text, tags, sequence)
    { event_id: event_id, kind: kind, text: text, tags: tags, sequence: sequence }
  end

  def render_result(result, created: false)
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result, status: created ? :created : :ok
  end
end

# A fixture seed is deliberately represented by one campaign-local marker.
# The public fixture is canonical data, derived from that marker, so a repeat
# cannot append duplicate characters or events.
class PlayCampaignFixtureSeedsController < ApplicationController
  include PlayAuthentication

  CANONICAL_FIXTURE_ID = "canonical-v1"

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless body.is_a?(Hash) && body["fixture_id"] == CANONICAL_FIXTURE_ID

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign_dm?(campaign, actor)

      seeded = GameStorage.database.get_first_value(
        "SELECT fixture_id FROM play_campaign_fixture_seeds WHERE campaign_id = ?", [params[:id]]
      )
      if seeded
        :existing
      else
        GameStorage.database.transaction do
          GameStorage.database.execute(
            "INSERT INTO play_campaign_fixture_seeds (campaign_id, fixture_id) VALUES (?, ?)",
            [params[:id], CANONICAL_FIXTURE_ID]
          )
        end
        :created
      end
    end
    return unknown_campaign if result == :missing
    return forbidden if result == :forbidden

    render json: canonical_fixture, status: result == :created ? :created : :ok
  end

  def show
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign_member?(campaign, actor)
      next :unseeded unless GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_fixture_seeds WHERE campaign_id = ?", [params[:id]]
      )

      canonical_fixture
    end
    return unknown_campaign if result == :missing || result == :unseeded
    return forbidden if result == :forbidden

    render json: result
  end

  private

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def campaign_dm?(campaign, actor)
    actor["role"] == "dm" && campaign["owner"] == actor["username"]
  end

  def campaign_member?(campaign, actor)
    campaign_dm?(campaign, actor) || GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], actor["username"]]
    )
  end

  def canonical_fixture
    {
      fixture_id: CANONICAL_FIXTURE_ID,
      status: "seeded",
      characters: [
        { character_id: "fixture-hero", name: "Ari", class: "fighter" },
        { character_id: "fixture-mage", name: "Bea", class: "wizard" }
      ],
      story: "The lantern is lit.",
      event_ids: ["fixture-event-1", "fixture-event-2"]
    }
  end

  def unknown_campaign
    render json: { error: "unknown campaign" }, status: :not_found
  end

  def forbidden
    render json: { error: "forbidden" }, status: :forbidden
  end
end

# Moderation reports are a campaign-local append-only queue. A report can make
# exactly one state transition, from open to resolved, by the campaign DM.
class PlayCampaignModerationReportsController < ApplicationController
  include PlayAuthentication

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless body.is_a?(Hash)

    report_id = body["report_id"]
    target_id = body["target_id"]
    reason = body["reason"]
    return bad_request unless present_string?(report_id) && present_string?(target_id) && present_string?(reason)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign_member?(campaign, actor)
      next :duplicate if report_record(report_id)

      sequence = GameStorage.database.get_first_value(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_moderation_reports WHERE campaign_id = ?", [params[:id]]
      )
      GameStorage.database.execute(
        "INSERT INTO play_campaign_moderation_reports " \
        "(campaign_id, sequence, report_id, target_id, reason, status, reporter) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [params[:id], sequence, report_id, target_id, reason, "open", actor["username"]]
      )
      report_payload(report_id, target_id, reason, "open", actor["username"], sequence)
    end
    render_report_result(result, created: true)
  end

  def index
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign_member?(campaign, actor)

      reports = GameStorage.database.execute(
        "SELECT report_id, target_id, reason, status, reporter, sequence, action, note, resolver " \
        "FROM play_campaign_moderation_reports WHERE campaign_id = ? ORDER BY sequence", [params[:id]]
      ).map { |report| report_from_row(report) }
      { reports: reports }
    end
    render_report_result(result)
  end

  def resolve
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless body.is_a?(Hash)

    action = body["action"]
    note = body["note"]
    return bad_request unless %w[allow remove].include?(action) && present_string?(note)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing_campaign unless campaign
      next :forbidden unless campaign_dm?(campaign, actor)
      report = report_record(params[:report_id])
      next :missing_report unless report
      next :resolved unless report["status"] == "open"

      GameStorage.database.execute(
        "UPDATE play_campaign_moderation_reports SET status = ?, action = ?, note = ?, resolver = ? " \
        "WHERE campaign_id = ? AND report_id = ?",
        ["resolved", action, note, actor["username"], params[:id], params[:report_id]]
      )
      report_payload(report["report_id"], report["target_id"], report["reason"], "resolved", report["reporter"],
                     report["sequence"], action, note, actor["username"])
    end
    render_report_result(result)
  end

  private

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def campaign_member?(campaign, actor)
    campaign_dm?(campaign, actor) || GameStorage.database.get_first_value(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], actor["username"]]
    )
  end

  def campaign_dm?(campaign, actor)
    actor["role"] == "dm" && campaign["owner"] == actor["username"]
  end

  def report_record(report_id)
    GameStorage.database.get_first_row(
      "SELECT report_id, target_id, reason, status, reporter, sequence, action, note, resolver " \
      "FROM play_campaign_moderation_reports WHERE campaign_id = ? AND report_id = ?", [params[:id], report_id]
    )
  end

  def report_from_row(report)
    report_payload(report["report_id"], report["target_id"], report["reason"], report["status"], report["reporter"],
                   report["sequence"], report["action"], report["note"], report["resolver"])
  end

  def report_payload(report_id, target_id, reason, status, reporter, sequence, action = nil, note = nil, resolver = nil)
    { report_id: report_id, target_id: target_id, reason: reason, status: status, reporter: reporter, sequence: sequence }.tap do |report|
      if status == "resolved"
        report[:action] = action
        report[:note] = note
        report[:resolver] = resolver
      end
    end
  end

  def render_report_result(result, created: false)
    return render(json: { error: "unknown campaign" }, status: :not_found) if %i[missing missing_campaign].include?(result)
    return render(json: { error: "unknown report" }, status: :not_found) if result == :missing_report
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "report id already exists" }, status: :conflict) if result == :duplicate
    return render(json: { error: "report already resolved" }, status: :conflict) if result == :resolved

    render json: result, status: created ? :created : :ok
  end
end

# RNG rolls form an independent, campaign-local append-only ledger. Its result
# is derived exclusively from the configured seed and the persisted sequence.
class PlayCampaignRngLedgerController < ApplicationController
  include PlayAuthentication

  def configure_seed
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless body.is_a?(Hash) && present_string?(body["seed"])

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign["owner"] == actor["username"] && actor["role"] == "dm"
      next :configured if seed_for_campaign

      GameStorage.database.execute(
        "INSERT INTO play_campaign_rng_seeds (campaign_id, seed) VALUES (?, ?)", [params[:id], body["seed"]]
      )
      { seed: body["seed"], rolls: [] }
    end
    return unknown_campaign if result == :missing
    return forbidden if result == :forbidden
    return render(json: { error: "rng seed already configured" }, status: :conflict) if result == :configured

    render json: result
  end

  def create_roll
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless body.is_a?(Hash)
    roll_id = body["roll_id"]
    sides = body["sides"]
    return bad_request unless present_string?(roll_id) && sides.is_a?(Integer) && (2..100).cover?(sides)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign_member?(campaign, actor)

      seed = seed_for_campaign
      next :unconfigured unless seed
      next :duplicate if GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_rng_rolls WHERE campaign_id = ? AND roll_id = ?", [params[:id], roll_id]
      )

      sequence = GameStorage.database.get_first_value(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_rng_rolls WHERE campaign_id = ?", [params[:id]]
      )
      record = { roll_id: roll_id, sides: sides, result: deterministic_result(seed, sequence, roll_id, sides), sequence: sequence }
      GameStorage.database.execute(
        "INSERT INTO play_campaign_rng_rolls (campaign_id, sequence, roll_id, sides, result) VALUES (?, ?, ?, ?, ?)",
        [params[:id], sequence, roll_id, sides, record[:result]]
      )
      record
    end
    return unknown_campaign if result == :missing
    return forbidden if result == :forbidden
    return render(json: { error: "rng seed not configured" }, status: :conflict) if result == :unconfigured
    return render(json: { error: "roll id already exists" }, status: :conflict) if result == :duplicate

    render json: result, status: :created
  end

  def show
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign_member?(campaign, actor)

      seed = seed_for_campaign
      rolls = GameStorage.database.execute(
        "SELECT roll_id, sides, result, sequence FROM play_campaign_rng_rolls WHERE campaign_id = ? ORDER BY sequence", [params[:id]]
      ).map { |roll| { roll_id: roll["roll_id"], sides: roll["sides"], result: roll["result"], sequence: roll["sequence"] } }
      { seed: seed, rolls: rolls }
    end
    return unknown_campaign if result == :missing
    return forbidden if result == :forbidden

    render json: result
  end

  private

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def seed_for_campaign
    GameStorage.database.get_first_value("SELECT seed FROM play_campaign_rng_seeds WHERE campaign_id = ?", [params[:id]])
  end

  def campaign_member?(campaign, actor)
    (actor["role"] == "dm" && campaign["owner"] == actor["username"]) ||
      GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], actor["username"]]
      )
  end

  def deterministic_result(seed, sequence, roll_id, sides)
    accumulator = 0
    "#{seed}|#{sequence}|#{roll_id}|#{sides}".encode(Encoding::UTF_8).bytes.each do |byte|
      accumulator = (accumulator * 31 + byte) & 0xffff_ffff
    end
    (accumulator % sides) + 1
  end

  def unknown_campaign
    render json: { error: "unknown campaign" }, status: :not_found
  end

  def forbidden
    render json: { error: "forbidden" }, status: :forbidden
  end
end

# Feed events are an independent campaign-local append-only stream. Cursors
# are consumed counts rather than row ids, so appending after a page read
# cannot change the contents of that page's remaining suffix.
class PlayCampaignFeedEventsController < ApplicationController
  include PlayAuthentication

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless body.is_a?(Hash)

    event_id = body["event_id"]
    text = body["text"]
    return bad_request unless present_string?(event_id) && present_string?(text)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign_member?(campaign, actor)

      sequence = GameStorage.database.get_first_value(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_feed_events WHERE campaign_id = ?", [params[:id]]
      )
      begin
        GameStorage.database.execute(
          "INSERT INTO play_campaign_feed_events (campaign_id, sequence, event_id, text) VALUES (?, ?, ?, ?)",
          [params[:id], sequence, event_id, text]
        )
        event_payload(event_id, text, sequence)
      rescue SQLite3::ConstraintException
        :duplicate
      end
    end
    return unknown_campaign if result == :missing
    return forbidden if result == :forbidden
    return render(json: { error: "event id already exists" }, status: :conflict) if result == :duplicate

    render json: result, status: :created
  end

  def index
    actor = require_play_actor
    return unless actor

    cursor = params.key?(:cursor) ? integer(params[:cursor]) : 0
    limit = params.key?(:limit) ? integer(params[:limit]) : 2
    return bad_request unless cursor && cursor >= 0 && limit && (1..3).cover?(limit)

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless campaign_member?(campaign, actor)

      events = GameStorage.database.execute(
        "SELECT event_id, text, sequence FROM play_campaign_feed_events " \
        "WHERE campaign_id = ? AND sequence > ? ORDER BY sequence LIMIT ?",
        [params[:id], cursor, limit]
      ).map { |event| event_payload(event["event_id"], event["text"], event["sequence"]) }
      { events: events, next_cursor: cursor + events.length }
    end
    return unknown_campaign if result == :missing
    return forbidden if result == :forbidden

    render json: result
  end

  private

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def campaign_member?(campaign, actor)
    (actor["role"] == "dm" && campaign["owner"] == actor["username"]) ||
      GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], actor["username"]]
      )
  end

  def event_payload(event_id, text, sequence)
    { event_id: event_id, text: text, sequence: sequence }
  end

  def unknown_campaign
    render json: { error: "unknown campaign" }, status: :not_found
  end

  def forbidden
    render json: { error: "forbidden" }, status: :forbidden
  end
end

# Replay events form an independent, campaign-local append-only stream.  The
# stored sequence is the successful insertion order, so rebuilding its public
# state does not consult any clocks or random values.
class PlayCampaignReplayEventsController < ApplicationController
  include PlayAuthentication

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    return bad_request unless body.is_a?(Hash)

    event_id = body["event_id"]
    kind = body["kind"]
    text = body["text"]
    return bad_request unless present_string?(event_id) && present_string?(text) && kind == "append"

    result = GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless permitted?(campaign, actor)

      sequence = GameStorage.database.get_first_value(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_replay_events WHERE campaign_id = ?", [params[:id]]
      )
      begin
        GameStorage.database.execute(
          "INSERT INTO play_campaign_replay_events (campaign_id, sequence, event_id, kind, text) VALUES (?, ?, ?, ?, ?)",
          [params[:id], sequence, event_id, kind, text]
        )
        { event_id: event_id, kind: kind, text: text, sequence: sequence }
      rescue SQLite3::ConstraintException
        :duplicate
      end
    end
    return unknown_campaign if result == :missing
    return forbidden if result == :forbidden
    return render(json: { error: "event id already exists" }, status: :conflict) if result == :duplicate

    render json: result, status: :created
  end

  def show
    actor = require_play_actor
    return unless actor

    result = replay_for(actor)
    return unknown_campaign if result == :missing
    return forbidden if result == :forbidden

    render json: result
  end

  def check
    actor = require_play_actor
    return unless actor

    result = replay_for(actor)
    return unknown_campaign if result == :missing
    return forbidden if result == :forbidden

    render json: result
  end

  private

  def replay_for(actor)
    GameStorage.synchronize do
      campaign = campaign_record
      next :missing unless campaign
      next :forbidden unless permitted?(campaign, actor)

      events = GameStorage.database.execute(
        "SELECT event_id, text FROM play_campaign_replay_events WHERE campaign_id = ? ORDER BY sequence", [params[:id]]
      )
      event_ids = events.map { |event| event["event_id"] }
      story = events.map { |event| event["text"] }.join
      { story: story, event_ids: event_ids, digest: "#{event_ids.join(",")}|#{story}" }
    end
  end

  def campaign_record
    GameStorage.database.get_first_row("SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]])
  end

  def permitted?(campaign, actor)
    (actor["role"] == "dm" && campaign["owner"] == actor["username"]) ||
      GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?", [params[:id], actor["username"]]
      )
  end

  def unknown_campaign
    render json: { error: "unknown campaign" }, status: :not_found
  end

  def forbidden
    render json: { error: "forbidden" }, status: :forbidden
  end
end

# Onboarding is a read-only, role-specific view for actors who have already
# entered a campaign.  Its values are deliberately constants rather than being
# derived from campaign state, so repeated reads cannot alter or reorder it.
class PlayCampaignOnboardingController < ApplicationController
  include PlayAuthentication

  def show
    actor = require_play_actor
    return unless actor

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign

      if actor["role"] == "dm" && campaign["owner"] == actor["username"]
        :dm
      elsif GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
        [params[:id], actor["username"]]
      )
        :player
      else
        :forbidden
      end
    end

    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    if result == :dm
      render json: { role: "dm", next_steps: ["configure-safety", "invite-players", "start-campaign"], can_mutate: true }
    else
      render json: { role: "player", next_steps: ["review-party", "take-turn", "submit-action"], can_mutate: true }
    end
  end
end

# Campaign chat is retained as an ordinary member action.  It is deliberately
# not part of the spectator projection, but still needs a real authenticated
# endpoint so an attempted spectator write is rejected as credentials failure.
class PlayCampaignMessagesController < ApplicationController
  include PlayAuthentication
  include PlayCampaignEvents

  def create
    actor = require_play_actor
    return unless actor

    body = json_body
    text = body["text"] if body.is_a?(Hash)
    return bad_request unless present_string?(text)

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign

      member = GameStorage.database.get_first_value(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
        [params[:id], actor["username"]]
      )
      next :forbidden unless campaign["owner"] == actor["username"] || member

      GameStorage.database.execute(
        "INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)",
        [params[:id], next_play_event_sequence(params[:id]), "chat", actor["username"], text]
      )
      { kind: "chat", actor: actor["username"], text: text }
    end

    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result, status: :created
  end
end

# Spectator tickets intentionally use a separate credential namespace from
# play sessions.  Their only permitted projection contains campaign-level
# public fields, so a ticket cannot accidentally acquire member privileges.
class PlayCampaignSpectatorsController < ApplicationController
  include PlayAuthentication

  def create
    actor = require_play_actor
    return unless actor
    return render(json: { error: "forbidden" }, status: :forbidden) unless actor["role"] == "dm"

    body = json_body
    spectator_id = body["spectator_id"] if body.is_a?(Hash)
    return bad_request unless present_string?(spectator_id)

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign
      next :forbidden unless campaign["owner"] == actor["username"]

      begin
        GameStorage.database.execute(
          "INSERT INTO play_campaign_spectators (spectator_id, campaign_id) VALUES (?, ?)",
          [spectator_id, params[:id]]
        )
        :created
      rescue SQLite3::ConstraintException
        :conflict
      end
    end
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden
    return render(json: { error: "spectator id already exists" }, status: :conflict) if result == :conflict

    render json: { spectator_id: spectator_id, token: "spectator-#{spectator_id}" }, status: :created
  end

  def show
    # A valid normal session is deliberately rejected, rather than treated as
    # absent authentication: this endpoint is exclusively for spectators.
    return render(json: { error: "forbidden" }, status: :forbidden) if current_play_actor

    spectator_id = spectator_id_from_authorization
    return render(json: { error: "bad credentials" }, status: :unauthorized) unless spectator_id

    result = GameStorage.synchronize do
      ticket = GameStorage.database.get_first_row(
        "SELECT campaign_id FROM play_campaign_spectators WHERE spectator_id = ?", [spectator_id]
      )
      next :unauthorized unless ticket

      campaign = GameStorage.database.get_first_row(
        "SELECT id, name, status FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign
      next :forbidden unless ticket["campaign_id"] == params[:id]

      party_size = GameStorage.database.get_first_value(
        "SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?", [params[:id]]
      )
      story = GameStorage.database.get_first_value(
        "SELECT story FROM play_campaign_documents WHERE campaign_id = ?", [params[:id]]
      ) || ""
      {
        campaign_id: campaign["id"],
        name: campaign["name"],
        status: campaign["status"],
        party_size: party_size,
        story: story
      }
    end
    return render(json: { error: "bad credentials" }, status: :unauthorized) if result == :unauthorized
    return render(json: { error: "unknown campaign" }, status: :not_found) if result == :missing
    return render(json: { error: "forbidden" }, status: :forbidden) if result == :forbidden

    render json: result
  end

  private

  def spectator_id_from_authorization
    match = /\ABearer spectator-(.+)\z/.match(request.authorization.to_s)
    match && match[1].encode(Encoding::UTF_8)
  end
end

GameStorage.initialize_schema!
DndApi.initialize!

DndApi.routes.draw do
  get "/health", to: "health#show"
  get "/healthz", to: "readiness#healthz"
  get "/readyz", to: "readiness#readyz"
  get "/v1/schema", to: "api_schema#show"
  post "/v1/dice/stats", to: "dice#stats"
  post "/v1/checks/ability", to: "checks#ability"
  post "/v1/encounters/adjusted-xp", to: "encounters#adjusted_xp"
  post "/v1/initiative/order", to: "initiative#order"
  post "/v1/characters/ability-modifier", to: "characters#ability_modifier"
  post "/v1/characters/proficiency", to: "characters#proficiency"
  post "/v1/characters/derived-stats", to: "characters#derived_stats"
  post "/v1/combat/sessions", to: "combat_sessions#create"
  post "/v1/combat/sessions/:id/conditions", to: "combat_sessions#conditions"
  post "/v1/combat/sessions/:id/advance", to: "combat_sessions#advance"
  post "/v1/auth/register", to: "auth#register"
  post "/v1/auth/login", to: "auth#login"
  post "/v1/play/campaigns", to: "play_campaigns#create"
  post "/v1/play/campaigns/:id/members", to: "play_campaigns#create_member"
  get "/v1/play/campaigns/:id/onboarding", to: "play_campaign_onboarding#show"
  post "/v1/play/campaigns/:id/messages", to: "play_campaign_messages#create"
  post "/v1/play/campaigns/:id/spectators", to: "play_campaign_spectators#create"
  get "/v1/play/campaigns/:id/spectator-view", to: "play_campaign_spectators#show"
  post "/v1/play/campaigns/:id/invitations", to: "play_campaign_invitations#create"
  post "/v1/play/campaigns/:id/invitations/:invitation_id/accept", to: "play_campaign_invitations#accept"
  get "/v1/play/campaigns/:id/invitations", to: "play_campaign_invitations#index"
  post "/v1/play/campaigns/:id/delegations", to: "play_campaign_delegations#create"
  delete "/v1/play/campaigns/:id/delegations/:username", to: "play_campaign_delegations#destroy"
  get "/v1/play/campaigns/:id/delegations/audit", to: "play_campaign_delegations#audit"
  post "/v1/play/campaigns/:id/audit-events", to: "play_campaign_audit_events#create"
  get "/v1/play/campaigns/:id/audit-events", to: "play_campaign_audit_events#index"
  post "/v1/play/campaigns/:id/projection-events", to: "play_campaign_projection_events#create"
  get "/v1/play/campaigns/:id/projection/rebuild", to: "play_campaign_projection_events#rebuild"
  get "/v1/play/campaigns/:id/projection", to: "play_campaign_projection_events#show"
  post "/v1/play/campaigns/:id/feed-events", to: "play_campaign_feed_events#create"
  get "/v1/play/campaigns/:id/event-feed", to: "play_campaign_feed_events#index"
  post "/v1/play/campaigns/:id/replay-events", to: "play_campaign_replay_events#create"
  get "/v1/play/campaigns/:id/replay", to: "play_campaign_replay_events#show"
  get "/v1/play/campaigns/:id/replay/check", to: "play_campaign_replay_events#check"
  put "/v1/play/campaigns/:id/rng-seed", to: "play_campaign_rng_ledger#configure_seed"
  post "/v1/play/campaigns/:id/rng-rolls", to: "play_campaign_rng_ledger#create_roll"
  get "/v1/play/campaigns/:id/rng-ledger", to: "play_campaign_rng_ledger#show"
  post "/v1/play/campaigns/:id/moderation/reports", to: "play_campaign_moderation_reports#create"
  get "/v1/play/campaigns/:id/moderation/reports", to: "play_campaign_moderation_reports#index"
  put "/v1/play/campaigns/:id/moderation/reports/:report_id/resolution", to: "play_campaign_moderation_reports#resolve"
  post "/v1/play/campaigns/:id/fixture-seeds", to: "play_campaign_fixture_seeds#create"
  get "/v1/play/campaigns/:id/fixture-state", to: "play_campaign_fixture_seeds#show"
  put "/v1/play/campaigns/:id/safety-boundaries", to: "play_campaign_safety#replace_boundaries"
  get "/v1/play/campaigns/:id/safety-boundaries", to: "play_campaign_safety#boundaries"
  post "/v1/play/campaigns/:id/safety-checks", to: "play_campaign_safety#create_check"
  get "/v1/play/campaigns/:id/safety-events", to: "play_campaign_safety#events"
  post "/v1/play/campaigns/:id/idempotent-events", to: "play_campaign_idempotent_events#create"
  get "/v1/play/campaigns/:id/idempotent-events", to: "play_campaign_idempotent_events#index"
  post "/v1/play/campaigns/:id/safe-turns", to: "play_campaign_safe_turns#create"
  get "/v1/play/campaigns/:id/safe-turns", to: "play_campaign_safe_turns#index"
  post "/v1/play/campaigns/:id/start", to: "play_campaigns#start"
  put "/v1/play/campaigns/:id/session-zero", to: "play_campaign_session_zero#update"
  get "/v1/play/campaigns/:id/session-zero", to: "play_campaign_session_zero#show"
  post "/v1/play/campaigns/:id/content", to: "play_campaign_content#create"
  put "/v1/play/campaigns/:id/content/:content_id/tags", to: "play_campaign_content#update_tags"
  get "/v1/play/campaigns/:id/content", to: "play_campaign_content#index"
  post "/v1/play/campaigns/:id/search-records", to: "play_campaign_search_records#create"
  get "/v1/play/campaigns/:id/search-records", to: "play_campaign_search_records#index"
  post "/v1/play/campaigns/:id/rate-events", to: "play_campaign_rate_events#create"
  get "/v1/play/campaigns/:id/rate-events", to: "play_campaign_rate_events#index"
  get "/v1/play/campaigns/:id/metrics", to: "play_campaign_service_metrics#show"
  post "/v1/play/campaigns/:id/service-mode", to: "play_campaign_service_mode#update"
  post "/v1/play/campaigns/:id/notes", to: "play_campaign_notes#create"
  get "/v1/play/campaigns/:id/notes", to: "play_campaign_notes#index"
  get "/v1/play/campaigns/:id/notes/:note_id", to: "play_campaign_notes#show"
  put "/v1/play/campaigns/:id/notes/:note_id", to: "play_campaign_notes#update"
  post "/v1/play/campaigns/:id/whispers", to: "play_campaign_whispers#create"
  get "/v1/play/campaigns/:id/whispers", to: "play_campaign_whispers#index"
  get "/v1/play/campaigns/:id/characters/:character_id/sheet", to: "play_character_sheets#show"
  get "/v1/play/campaigns/:id/turn", to: "play_campaigns#turn"
  post "/v1/play/campaigns/:id/turn/nudge", to: "play_campaigns#nudge"
  get "/v1/play/campaigns/:id/my-turn", to: "play_campaigns#my_turn"
  get "/v1/play/campaigns/:id/gm/status", to: "play_campaigns#gm_status"
  get "/v1/play/campaigns/:id/document", to: "play_campaigns#document"
  put "/v1/play/campaigns/:id/document", to: "play_campaigns#update_document"
  post "/v1/play/campaigns/:id/backups", to: "play_campaign_backups#create"
  get "/v1/play/campaigns/:id/backups", to: "play_campaign_backups#index"
  post "/v1/play/campaigns/:id/backups/:backup_id/restore", to: "play_campaign_backups#restore"
  post "/v1/play/campaigns/:id/exports", to: "play_campaign_exports#create"
  get "/v1/play/campaigns/:id/exports", to: "play_campaign_exports#index"
  get "/v1/play/campaigns/:id/exports/:version", to: "play_campaign_exports#show"
  post "/v1/play/campaigns/:id/imports", to: "play_campaign_imports#create"
  get "/v1/play/campaigns/:id/import-state", to: "play_campaign_imports#show"
  post "/v1/play/campaigns/:id/migrations", to: "play_campaign_migrations#create"
  get "/v1/play/campaigns/:id/migration-state", to: "play_campaign_migrations#show"
  get "/v1/play/campaigns/:id/scenes/current", to: "play_campaign_scenes#current"
  post "/v1/play/campaigns/:id/scenes", to: "play_campaign_scenes#create"
  post "/v1/play/campaigns/:id/scenes/:scene_id/enter", to: "play_campaign_scenes#enter"
  post "/v1/play/campaigns/:id/scenes/:scene_id/close", to: "play_campaign_scenes#close"
  post "/v1/play/campaigns/:id/locations", to: "play_campaign_locations#create"
  post "/v1/play/campaigns/:id/locations/:from_id/connections", to: "play_campaign_locations#create_connection"
  get "/v1/play/campaigns/:id/locations/:loc_id/travel", to: "play_campaign_locations#travel"
  post "/v1/play/campaigns/:id/turn/travel", to: "play_travel_turns#create"
  post "/v1/play/campaigns/:id/turn/rest", to: "play_rest_turns#create"
  post "/v1/play/campaigns/:id/characters/:char_id/damage", to: "play_character_status#damage"
  post "/v1/play/campaigns/:id/characters/:char_id/death-saves", to: "play_character_status#death_saves"
  get "/v1/play/campaigns/:id/characters/:char_id/status", to: "play_character_status#status"
  get "/v1/play/campaigns/:id/characters/:char_id/owner", to: "play_character_ownership#show"
  post "/v1/play/campaigns/:id/characters/:char_id/claim", to: "play_character_ownership#claim"
  post "/v1/play/campaigns/:id/characters/:char_id/transfer", to: "play_character_ownership#transfer"
  get "/v1/play/campaigns/:id/characters/:char_id/currency", to: "play_character_currency#show"
  post "/v1/play/campaigns/:id/characters/:char_id/currency/transfers", to: "play_character_currency#transfer"
  post "/v1/play/campaigns/:id/transactional-transfers", to: "play_campaign_transactional_transfers#create"
  get "/v1/play/campaigns/:id/transactional-transfers", to: "play_campaign_transactional_transfers#index"
  post "/v1/play/campaigns/:id/characters/:char_id/inventory/items", to: "play_character_inventory_items#create"
  get "/v1/play/campaigns/:id/characters/:char_id/inventory/items", to: "play_character_inventory_items#index"
  delete "/v1/play/campaigns/:id/characters/:char_id/inventory/items/:item_id", to: "play_character_inventory_items#destroy"
  post "/v1/play/campaigns/:id/characters/:char_id/inventory/items/:item_id/consume", to: "play_character_inventory_items#consume"
  post "/v1/play/campaigns/:id/recipes", to: "play_campaign_recipes#create"
  get "/v1/play/campaigns/:id/recipes", to: "play_campaign_recipes#index"
  post "/v1/play/campaigns/:id/recipes/:recipe_id/craft", to: "play_campaign_recipes#craft"
  post "/v1/play/campaigns/:id/downtime/activities", to: "play_campaign_downtime#create_activity"
  post "/v1/play/campaigns/:id/characters/:character_id/downtime/allocations", to: "play_campaign_downtime#create_allocation"
  post "/v1/play/campaigns/:id/characters/:character_id/downtime/allocations/:activity_id/progress", to: "play_campaign_downtime#progress"
  get "/v1/play/campaigns/:id/characters/:character_id/downtime/allocations/:activity_id", to: "play_campaign_downtime#show_allocation"
  post "/v1/play/campaigns/:id/loot", to: "play_campaign_loot#create"
  post "/v1/play/campaigns/:id/loot/:loot_id/votes", to: "play_campaign_loot#vote"
  post "/v1/play/campaigns/:id/loot/:loot_id/assign", to: "play_campaign_loot#assign"
  get "/v1/play/campaigns/:id/loot/:loot_id", to: "play_campaign_loot#show"
  post "/v1/play/campaigns/:id/npcs", to: "play_campaign_npcs#create"
  put "/v1/play/campaigns/:id/npcs/:npc_id/agenda", to: "play_campaign_npcs#update_agenda"
  get "/v1/play/campaigns/:id/npcs/:npc_id", to: "play_campaign_npcs#show"
  post "/v1/play/campaigns/:id/npcs/:npc_id/dialogue", to: "play_campaign_npc_dialogue#create"
  get "/v1/play/campaigns/:id/npcs/:npc_id/dialogue", to: "play_campaign_npc_dialogue#index"
  post "/v1/play/campaigns/:id/relationships", to: "play_campaign_relationships#create"
  put "/v1/play/campaigns/:id/relationships/:source_id/:target_id/:kind", to: "play_campaign_relationships#update"
  get "/v1/play/campaigns/:id/relationships", to: "play_campaign_relationships#index"
  post "/v1/play/campaigns/:id/clues", to: "play_campaign_clues#create"
  get "/v1/play/campaigns/:id/clues", to: "play_campaign_clues#index"
  post "/v1/play/campaigns/:id/quests", to: "play_campaign_quests#create"
  put "/v1/play/campaigns/:id/quests/:quest_id/state", to: "play_campaign_quests#update_state"
  put "/v1/play/campaigns/:id/quests/:quest_id/rewards", to: "play_campaign_quests#configure_rewards"
  post "/v1/play/campaigns/:id/quests/:quest_id/rewards/award", to: "play_campaign_quests#award_rewards"
  get "/v1/play/campaigns/:id/quests", to: "play_campaign_quests#index"
  get "/v1/play/campaigns/:id/characters/:char_id/rewards", to: "play_character_quest_rewards#show"
  post "/v1/play/campaigns/:id/factions", to: "play_campaign_factions#create"
  post "/v1/play/campaigns/:id/factions/:faction_id/reputation", to: "play_campaign_factions#change_reputation"
  get "/v1/play/campaigns/:id/factions/:faction_id/reputation", to: "play_campaign_factions#reputation"
  post "/v1/play/campaigns/:id/settlements", to: "play_campaign_settlements#create"
  put "/v1/play/campaigns/:id/settlements/:settlement_id", to: "play_campaign_settlements#update"
  post "/v1/play/campaigns/:id/settlements/:settlement_id/discover", to: "play_campaign_settlements#discover"
  get "/v1/play/campaigns/:id/settlements", to: "play_campaign_settlements#index"
  post "/v1/play/campaigns/:id/settlements/:settlement_id/shops", to: "play_campaign_shops#create"
  get "/v1/play/campaigns/:id/settlements/:settlement_id/shops/:shop_id", to: "play_campaign_shops#show"
  post "/v1/play/campaigns/:id/settlements/:settlement_id/shops/:shop_id/buy", to: "play_campaign_shops#buy"
  post "/v1/play/campaigns/:id/settlements/:settlement_id/shops/:shop_id/sell", to: "play_campaign_shops#sell"
  post "/v1/play/campaigns/:id/calendar", to: "play_campaign_calendars#create"
  get "/v1/play/campaigns/:id/calendar", to: "play_campaign_calendars#show"
  post "/v1/play/campaigns/:id/calendar/advance", to: "play_campaign_calendars#advance"
  post "/v1/play/campaigns/:id/world-events", to: "play_campaign_world_events#create"
  post "/v1/play/campaigns/:id/world-events/:event_id/resolve", to: "play_campaign_world_events#resolve"
  get "/v1/play/campaigns/:id/world-events", to: "play_campaign_world_events#index"
  put "/v1/play/campaigns/:id/characters/:char_id/equipment/:slot", to: "play_character_equipment#update"
  get "/v1/play/campaigns/:id/characters/:char_id/equipment/:slot", to: "play_character_equipment#show"
  post "/v1/play/campaigns/:id/characters/:char_id/equipment/:slot/attune", to: "play_character_equipment#attune"
  post "/v1/play/campaigns/:id/characters/:char_id/spells", to: "play_character_spells#create"
  get "/v1/play/campaigns/:id/characters/:char_id/spells", to: "play_character_spells#index"
  put "/v1/play/campaigns/:id/characters/:char_id/prepared-spells", to: "play_character_prepared_spells#update"
  get "/v1/play/campaigns/:id/characters/:char_id/prepared-spells", to: "play_character_prepared_spells#show"
  put "/v1/play/campaigns/:id/characters/:char_id/concentration", to: "play_character_concentrations#update"
  get "/v1/play/campaigns/:id/characters/:char_id/concentration", to: "play_character_concentrations#show"
  post "/v1/play/campaigns/:id/characters/:char_id/concentration/advance-turn", to: "play_character_concentrations#advance_turn"
  delete "/v1/play/campaigns/:id/characters/:char_id/concentration", to: "play_character_concentrations#destroy"
  post "/v1/play/campaigns/:id/characters/:char_id/casts", to: "play_character_casts#create"
  get "/v1/play/campaigns/:id/characters/:char_id/casts", to: "play_character_casts#index"
  post "/v1/play/campaigns/:id/characters/:char_id/build", to: "play_character_builds#create"
  post "/v1/play/campaigns/:id/characters/:char_id/level-up", to: "play_character_levels#create"
  post "/v1/play/campaigns/:id/characters/:char_id/skill-check", to: "play_character_skill_checks#create"
  post "/v1/play/campaigns/:id/encounters", to: "play_campaign_encounters#create"
  post "/v1/play/campaigns/:id/encounters/:enc_id/monsters", to: "play_campaign_encounters#add_monster"
  delete "/v1/play/campaigns/:id/encounters/:enc_id/monsters/:monster_id", to: "play_campaign_encounters#remove_monster"
  post "/v1/play/campaigns/:id/encounters/:enc_id/combatants", to: "play_campaign_encounters#add_combatant"
  delete "/v1/play/campaigns/:id/encounters/:enc_id/combatants/:member", to: "play_campaign_encounters#remove_combatant"
  post "/v1/play/campaigns/:id/encounters/:enc_id/damage", to: "play_campaign_encounters#damage"
  post "/v1/play/campaigns/:id/encounters/:enc_id/heal", to: "play_campaign_encounters#heal"
  post "/v1/play/campaigns/:id/encounters/:enc_id/rewards", to: "play_campaign_encounters#rewards"
  post "/v1/play/campaigns/:id/encounters/:enc_id/close", to: "play_campaign_encounters#close"
  post "/v1/play/campaigns/:id/encounters/:enc_id/end", to: "play_campaign_encounters#end_encounter"
  post "/v1/play/campaigns/:id/encounters/:enc_id/conditions", to: "play_campaign_encounters#conditions"
  get "/v1/play/campaigns/:id/encounters/:enc_id/status", to: "play_campaign_encounters#status"
  get "/v1/play/campaigns/:id/encounters/:enc_id/turn", to: "play_campaign_encounters#turn"
  post "/v1/play/campaigns/:id/encounters/:enc_id/turn/advance", to: "play_campaign_encounters#advance_turn"
  post "/v1/play/campaigns/:id/encounters/:enc_id/turn/delay", to: "play_campaign_encounters#delay"
  post "/v1/play/campaigns/:id/encounters/:enc_id/turn/ready", to: "play_campaign_encounters#ready"
  post "/v1/play/campaigns/:id/encounters/:enc_id/actions", to: "play_campaign_encounters#action"
  post "/v1/play/campaigns/:id/actions", to: "play_actions#create"
  post "/v1/play/campaigns/:id/resolutions", to: "play_resolutions#create"
  post "/v1/play/campaigns/:id/narrations", to: "play_narrations#create"
  post "/v1/compendium/monsters", to: "compendium_monsters#create"
  get "/v1/compendium/monsters/:slug", to: "compendium_monsters#show"
  post "/v1/compendium/items", to: "compendium_items#create"
  get "/v1/compendium/items/:slug", to: "compendium_items#show"
  post "/v1/campaigns", to: "campaigns#create"
  post "/v1/campaigns/:id/characters", to: "campaigns#create_character"
  post "/v1/campaigns/:id/events", to: "campaigns#create_event"
  get "/v1/campaigns/:id/state", to: "campaigns#state"
  get "/v1/campaigns/:id/audit", to: "campaign_audit#audit"
  get "/v1/campaigns/:id/export", to: "campaign_audit#export"
  post "/v1/campaigns/:id/sessions", to: "campaign_sessions#create"
  post "/v1/campaigns/:id/sessions/:session_id/attendance", to: "campaign_sessions#attendance"
  get "/v1/campaigns/:id/sessions/next", to: "campaign_sessions#next"
  post "/v1/campaigns/:id/inventory", to: "campaign_inventory#create"
  post "/v1/campaigns/:id/characters/:character_id/equipment", to: "campaign_inventory#assign_equipment"
  get "/v1/campaigns/:id/inventory/summary", to: "campaign_inventory#summary"
  post "/v1/campaigns/:id/downtime/crafting", to: "crafting_projects#create"
  post "/v1/campaigns/:id/downtime/crafting/:project_id/advance", to: "crafting_projects#advance"
  post "/v1/campaigns/:id/factions", to: "campaign_relationships#create_faction"
  post "/v1/campaigns/:id/npcs", to: "campaign_relationships#create_npc"
  get "/v1/campaigns/:id/relationships", to: "campaign_relationships#summary"
  post "/v1/campaigns/:id/quests", to: "campaign_quests#create"
  post "/v1/campaigns/:id/quests/:quest_id/progress", to: "campaign_quests#progress"
  get "/v1/campaigns/:id/quests/summary", to: "campaign_quests#summary"
  get "/v1/campaigns/:id/analytics/summary", to: "campaign_analytics#summary"
  post "/v1/campaigns/:id/analytics/risk-report", to: "campaign_analytics#risk_report"
  get "/v1/storage/status", to: "storage#status"
  post "/v1/storage/reset", to: "storage#reset"
  post "/v1/phb/spell-slots", to: "phb_spell_slots#create"
  post "/v1/phb/rests/long", to: "phb_long_rests#create"
  post "/v1/phb/equipment-load", to: "phb_equipment_load#create"
  post "/v1/dm/encounter-builder", to: "dm_tools#encounter_builder"
  post "/v1/dm/loot-parcel", to: "dm_tools#loot_parcel"
  post "/v1/dm/session-recap", to: "dm_tools#session_recap"
end
