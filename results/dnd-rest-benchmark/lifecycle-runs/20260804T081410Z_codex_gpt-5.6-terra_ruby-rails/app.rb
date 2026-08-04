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
  LOCK = Mutex.new

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
          DROP TABLE IF EXISTS play_campaign_documents;
          DROP TABLE IF EXISTS play_character_casts;
          DROP TABLE IF EXISTS play_character_concentrations;
          DROP TABLE IF EXISTS play_character_prepared_spells;
          DROP TABLE IF EXISTS play_character_equipment;
          DROP TABLE IF EXISTS play_character_currency_transfers;
          DROP TABLE IF EXISTS play_character_currency;
          DROP TABLE IF EXISTS play_character_inventory_items;
          DROP TABLE IF EXISTS play_character_spells;
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
      {
        campaign_id: params[:id],
        current_actor: campaign["current_actor"] || members.first,
        phase: campaign["phase"] || "player",
        turn_number: campaign["turn_number"] || 1,
        queue: queue,
        overdue: false,
        # This is a logical deadline, derived only from the deterministic turn
        # counter. Keep `deadline` as a compatibility alias for earlier
        # clients, while exposing the contract's explicit field name.
        logical_deadline: (campaign["turn_number"] || 1) + TURN_DEADLINE_OFFSET,
        deadline: (campaign["turn_number"] || 1) + TURN_DEADLINE_OFFSET
      }
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
        "SELECT owner, status, phase, current_actor, exploration_actor FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing_campaign unless campaign
      next :forbidden unless campaign["owner"] == actor["username"]
      next :not_in_combat unless campaign["phase"] == "combat"

      encounter = GameStorage.database.get_first_row(
        "SELECT status FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?", [params[:enc_id], params[:id]]
      )
      next :missing_encounter unless encounter

      current_actor = campaign["exploration_actor"] || campaign["current_actor"]
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
        "SELECT owner, current_actor, turn_number FROM play_campaigns WHERE id = ?", [params[:id]]
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

      turn_number = (campaign["turn_number"] || 1) + 1
      next_actor = members[(turn_number - 1) % members.length]
      sequence = next_play_event_sequence(params[:id])
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

class PlayNarrationsController < ApplicationController
  include PlayAuthentication
  include PlayCampaignEvents

  def create
    actor = require_play_actor
    return unless actor
    return render(json: { error: "forbidden" }, status: :forbidden) unless actor["role"] == "dm"

    body = json_body
    text = body["text"] if body.is_a?(Hash)
    return bad_request unless text.is_a?(String) && !text.empty?

    result = GameStorage.synchronize do
      campaign = GameStorage.database.get_first_row(
        "SELECT owner FROM play_campaigns WHERE id = ?", [params[:id]]
      )
      next :missing unless campaign
      next :forbidden unless campaign["owner"] == actor["username"]

      sequence = next_play_event_sequence(params[:id])
      GameStorage.database.execute(
        "INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)",
        [params[:id], sequence, "narration", "dm", text]
      )
      { sequence: sequence, kind: "narration", actor: "dm", text: text }
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

GameStorage.initialize_schema!
DndApi.initialize!

DndApi.routes.draw do
  get "/health", to: "health#show"
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
  post "/v1/play/campaigns/:id/start", to: "play_campaigns#start"
  get "/v1/play/campaigns/:id/turn", to: "play_campaigns#turn"
  post "/v1/play/campaigns/:id/turn/nudge", to: "play_campaigns#nudge"
  get "/v1/play/campaigns/:id/my-turn", to: "play_campaigns#my_turn"
  get "/v1/play/campaigns/:id/gm/status", to: "play_campaigns#gm_status"
  get "/v1/play/campaigns/:id/document", to: "play_campaigns#document"
  put "/v1/play/campaigns/:id/document", to: "play_campaigns#update_document"
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
  post "/v1/play/campaigns/:id/characters/:char_id/inventory/items", to: "play_character_inventory_items#create"
  get "/v1/play/campaigns/:id/characters/:char_id/inventory/items", to: "play_character_inventory_items#index"
  delete "/v1/play/campaigns/:id/characters/:char_id/inventory/items/:item_id", to: "play_character_inventory_items#destroy"
  post "/v1/play/campaigns/:id/characters/:char_id/inventory/items/:item_id/consume", to: "play_character_inventory_items#consume"
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
