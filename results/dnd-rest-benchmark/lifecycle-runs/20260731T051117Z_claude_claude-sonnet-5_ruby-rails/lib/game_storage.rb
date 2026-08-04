require 'sqlite3'

# Owns the raw SQLite connection and schema. All game state (users, combat
# sessions, compendium entries, campaigns) lives in one file (game.db) as
# simple key/value tables where `data` is a JSON blob; the PersistentXxx
# collection classes in persistent_collections.rb layer typed, cached access
# on top of these tables.
SCHEMA_VERSION = 1
DB_PATH = File.join(__dir__, '..', 'game.db')

module GameStorage
  class << self
    attr_accessor :db, :initialized

    # Puma serves requests from multiple threads, but the underlying
    # sqlite3 connection object is not safe for concurrent use from more
    # than one thread at a time. Every access goes through `execute`, which
    # serializes with this mutex.
    MUTEX = Mutex.new

    def connect
      # Each server process boot starts from a clean database: game.db is
      # per-run state, not state meant to survive across separate process
      # lifetimes (see CODEBASE.md).
      File.delete(DB_PATH) if File.exist?(DB_PATH)
      File.delete("#{DB_PATH}-wal") if File.exist?("#{DB_PATH}-wal")
      File.delete("#{DB_PATH}-shm") if File.exist?("#{DB_PATH}-shm")
      @db = SQLite3::Database.new(DB_PATH)
      @db.results_as_hash = true
      @db.execute('PRAGMA journal_mode = WAL')
      # NORMAL is the recommended synchronous level under WAL mode: it
      # skips the fsync on every write transaction (only WAL checkpoints
      # fsync), which avoids multi-second stalls under disk contention
      # while still keeping the database consistent if the process crashes.
      @db.execute('PRAGMA synchronous = NORMAL')
      create_schema
      @initialized = true
    end

    # Serializes access to the shared connection across Puma's threads.
    def execute(sql, params = [])
      MUTEX.synchronize { db.execute(sql, params) }
    end

    def create_schema
      execute(<<~SQL)
        CREATE TABLE IF NOT EXISTS meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        )
      SQL
      execute(<<~SQL)
        CREATE TABLE IF NOT EXISTS users (
          username TEXT PRIMARY KEY,
          role TEXT NOT NULL,
          password_digest TEXT NOT NULL
        )
      SQL
      execute(<<~SQL)
        CREATE TABLE IF NOT EXISTS combat_sessions (
          id TEXT PRIMARY KEY,
          data TEXT NOT NULL
        )
      SQL
      execute(<<~SQL)
        CREATE TABLE IF NOT EXISTS monsters (
          slug TEXT PRIMARY KEY,
          data TEXT NOT NULL
        )
      SQL
      execute(<<~SQL)
        CREATE TABLE IF NOT EXISTS items (
          slug TEXT PRIMARY KEY,
          data TEXT NOT NULL
        )
      SQL
      execute(<<~SQL)
        CREATE TABLE IF NOT EXISTS campaigns (
          id TEXT PRIMARY KEY,
          data TEXT NOT NULL
        )
      SQL
      execute(<<~SQL)
        CREATE TABLE IF NOT EXISTS play_campaigns (
          id TEXT PRIMARY KEY,
          data TEXT NOT NULL
        )
      SQL
      execute('INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)', ['schema_version', SCHEMA_VERSION.to_s])
    end

    # Drops and recreates every table, then clears the in-process caches
    # that mirror them. Used by POST /v1/storage/reset.
    def reset
      execute('DROP TABLE IF EXISTS meta')
      execute('DROP TABLE IF EXISTS users')
      execute('DROP TABLE IF EXISTS combat_sessions')
      execute('DROP TABLE IF EXISTS monsters')
      execute('DROP TABLE IF EXISTS items')
      execute('DROP TABLE IF EXISTS campaigns')
      execute('DROP TABLE IF EXISTS play_campaigns')
      create_schema
      USERS.clear
      COMBAT_SESSIONS.clear
      MONSTERS.clear
      ITEMS.clear
      CAMPAIGNS.clear
      PLAY_CAMPAIGNS.clear
    end
  end
end
