require 'json'

# Each PersistentXxx class is a Hash-like, write-through cache in front of
# one GameStorage table: reads hit the in-memory @cache (populated once at
# boot from SQLite), writes update @cache and immediately persist to SQLite.
# This keeps request handling free of SQL while still surviving restarts.

class PersistentUsers
  def initialize
    @cache = {}
    GameStorage.execute('SELECT username, role, password_digest FROM users').each do |row|
      @cache[row['username']] = { role: row['role'], password_digest: row['password_digest'] }
    end
  end

  def key?(username)
    @cache.key?(username)
  end

  def [](username)
    @cache[username]
  end

  def []=(username, value)
    @cache[username] = value
    GameStorage.execute(
      'INSERT OR REPLACE INTO users (username, role, password_digest) VALUES (?, ?, ?)',
      [username, value[:role], value[:password_digest]]
    )
  end

  def clear
    @cache.clear
  end
end

# Common shape for tables of the form `(id_column TEXT PRIMARY KEY, data
# TEXT)` where `data` is a JSON-serialized hash: load every row into
# @cache at boot, keyed by id_column, and write straight through to SQLite
# on every mutation. PersistentCombatSessions, PersistentCompendium,
# PersistentCampaigns, and PersistentPlayCampaigns all follow this shape;
# PersistentUsers does not (it has typed, non-JSON columns) and stays
# separate above.
class PersistentJsonTable
  def initialize(table, id_column: 'id')
    @table = table
    @id_column = id_column
    @cache = {}
    load_cache
  end

  def key?(id)
    @cache.key?(id)
  end

  def [](id)
    @cache[id]
  end

  def []=(id, value)
    @cache[id] = value
    persist(id)
  end

  # Call after mutating a cached value in place (e.g. appending an event
  # or advancing a turn) so the change is written to SQLite without
  # reassigning via []=.
  def persist(id)
    GameStorage.execute(
      "INSERT OR REPLACE INTO #{@table} (#{@id_column}, data) VALUES (?, ?)",
      [id, JSON.generate(@cache[id])]
    )
  end

  def clear
    @cache.clear
  end

  private

  def load_cache
    GameStorage.execute("SELECT #{@id_column}, data FROM #{@table}").each do |row|
      @cache[row[@id_column]] = JSON.parse(row['data'], symbolize_names: true)
    end
  end
end

class PersistentCombatSessions < PersistentJsonTable
  def initialize
    super('combat_sessions')
  end

  private

  # Combat sessions store nested hashes (order entries, condition lists)
  # whose keys must be symbols to match the shape callers get from a
  # session created fresh in-process; JSON round-trips them as strings, so
  # rows loaded from disk need rebuilding rather than a plain symbolized
  # parse.
  def load_cache
    GameStorage.execute('SELECT id, data FROM combat_sessions').each do |row|
      @cache[row['id']] = deserialize(JSON.parse(row['data']))
    end
  end

  def deserialize(raw)
    {
      order: raw['order'].map { |e| { name: e['name'], dex: e['dex'], score: e['score'] } },
      round: raw['round'],
      turn_index: raw['turn_index'],
      conditions: raw['conditions'].transform_values do |entries|
        entries.map { |c| { condition: c['condition'], remaining_rounds: c['remaining_rounds'] } }
      end
    }
  end
end

# Backs both the monsters and items compendium tables; `table` selects
# which one a given instance reads/writes.
class PersistentCompendium < PersistentJsonTable
  def initialize(table)
    super(table, id_column: 'slug')
  end
end

class PersistentCampaigns < PersistentJsonTable
  def initialize
    super('campaigns')
  end
end

# Backs the DM-owned campaign-play surface under /v1/play, kept in a
# separate table from the legacy `campaigns` collection above.
class PersistentPlayCampaigns < PersistentJsonTable
  def initialize
    super('play_campaigns')
  end
end
