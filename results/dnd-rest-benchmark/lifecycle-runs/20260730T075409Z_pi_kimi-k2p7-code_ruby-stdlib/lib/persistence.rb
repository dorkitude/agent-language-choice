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
      current_location_id TEXT
    );

    CREATE TABLE IF NOT EXISTS play_campaign_members (
      campaign_id TEXT NOT NULL,
      username TEXT NOT NULL,
      character_id TEXT NOT NULL,
      name TEXT NOT NULL,
      class TEXT NOT NULL,
      PRIMARY KEY (campaign_id, username),
      UNIQUE (campaign_id, character_id)
    );

    CREATE INDEX IF NOT EXISTS idx_play_campaign_members_campaign ON play_campaign_members(campaign_id);

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

  # Drops every application table, including users, and recreates the schema.
  # Used on server startup to guarantee a clean state.
  def self.reset!
    db do |d|
      %w[users combat_conditions combat_sessions compendium_monsters compendium_items
         campaigns campaign_characters campaign_events campaign_quests campaign_factions campaign_npcs campaign_inventory campaign_crafting_projects
         campaign_sessions session_attendance play_campaigns play_campaign_members play_narrations play_campaign_documents play_campaign_scenes
         play_locations play_location_connections schema_meta].each do |table|
        d.execute("DROP TABLE IF EXISTS #{table}")
      end
      d.execute_batch(SCHEMA_SQL)
    end
  end

  # Drops every application table except users, then recreates the schema.
  # Used by the /v1/storage/reset endpoint so authentication remains usable.
  def self.soft_reset!
    db do |d|
      %w[combat_conditions combat_sessions compendium_monsters compendium_items
         campaigns campaign_characters campaign_events campaign_quests campaign_factions campaign_npcs campaign_inventory campaign_crafting_projects
         campaign_sessions session_attendance play_campaigns play_campaign_members play_narrations play_campaign_documents play_campaign_scenes
         play_locations play_location_connections schema_meta].each do |table|
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
