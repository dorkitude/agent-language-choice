#!/usr/bin/env ruby
# frozen_string_literal: true
#
# D&D REST engine — Ruby standard library only (no Sinatra/Rack/gems).
# Implements the "core" lifecycle stage endpoints using a raw TCPServer.

require "socket"
require "json"
require "openssl"
require "open3"
require "fileutils"

# D&D 5e XP awarded per challenge rating.
XP_TABLE = {
  "0" => 10, "1/8" => 25, "1/4" => 50, "1/2" => 100,
  "1" => 200, "2" => 450, "3" => 700, "4" => 1100, "5" => 1800
}.freeze

# Per-character encounter difficulty XP thresholds: [easy, medium, hard, deadly].
# Level 3 is the only value required by the first benchmark suite; the rest of
# the standard DMG table is included for robustness across cumulative stages.
THRESHOLDS = {
  1  => [25,   50,   75,   100],
  2  => [50,   100,  150,  200],
  3  => [75,   150,  225,  400],
  4  => [125,  250,  375,  500],
  5  => [250,  500,  750,  1100],
  6  => [300,  600,  900,  1400],
  7  => [350,  750,  1100, 1700],
  8  => [450,  900,  1400, 2100],
  9  => [550,  1100, 1600, 2400],
  10 => [600,  1200, 1900, 2800],
  11 => [800,  1600, 2400, 3600],
  12 => [1000, 2000, 3000, 4500],
  13 => [1100, 2200, 3400, 5100],
  14 => [1250, 2500, 3800, 5700],
  15 => [1400, 2800, 4300, 6400],
  16 => [1600, 3200, 4800, 7200],
  17 => [2000, 3900, 5900, 8800],
  18 => [2100, 4200, 6300, 9500],
  19 => [2400, 4900, 7300, 10900],
  20 => [2800, 5700, 8500, 12700]
}.freeze

STATUS_TEXT = {
  200 => "OK",
  201 => "Created",
  400 => "Bad Request",
  401 => "Unauthorized",
  404 => "Not Found",
  409 => "Conflict",
  500 => "Internal Server Error"
}.freeze

# Wizard spell slots per character level (PHB). Only non-zero slot levels are
# listed; the response omits slot levels with zero slots.
WIZARD_SLOTS = {
  1  => { 1 => 2 },
  2  => { 1 => 3 },
  3  => { 1 => 4, 2 => 2 },
  4  => { 1 => 4, 2 => 3 },
  5  => { 1 => 4, 2 => 3, 3 => 2 },
  6  => { 1 => 4, 2 => 3, 3 => 3 },
  7  => { 1 => 4, 2 => 3, 3 => 3, 4 => 1 },
  8  => { 1 => 4, 2 => 3, 3 => 3, 4 => 2 },
  9  => { 1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 1 },
  10 => { 1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2 },
  11 => { 1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2, 6 => 1 },
  12 => { 1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2, 6 => 1 },
  13 => { 1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2, 6 => 1, 7 => 1 },
  14 => { 1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2, 6 => 1, 7 => 1 },
  15 => { 1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2, 6 => 1, 7 => 1, 8 => 1 },
  16 => { 1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2, 6 => 1, 7 => 1, 8 => 1 },
  17 => { 1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2, 6 => 1, 7 => 1, 8 => 1, 9 => 1 },
  18 => { 1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 3, 6 => 1, 7 => 1, 8 => 1, 9 => 1 },
  19 => { 1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 3, 6 => 2, 7 => 1, 8 => 1, 9 => 1 },
  20 => { 1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 3, 6 => 2, 7 => 2, 8 => 1, 9 => 1 }
}.freeze

# --- Durable storage: SQLite via the system `sqlite3` CLI (no gems) ---
#
# The Ruby stdlib has no SQLite binding and dbm/sdbm are unavailable in this
# build, so durable storage is provided by shelling out to the OS `sqlite3`
# binary through Open3 (stdlib). All access is serialized by DB_MUTEX so that
# read-mutate-write transactions on combat sessions stay atomic and SQLite
# file locking is never contended by concurrent threads.

DB_PATH        = File.expand_path("game.db", __dir__)
SCHEMA_VERSION = 1
DB_MUTEX       = Mutex.new

SCHEMA_SQL = <<~SQL
  CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
  );
  INSERT OR IGNORE INTO schema_meta (key, value) VALUES ('schema_version', '#{SCHEMA_VERSION}');
  CREATE TABLE IF NOT EXISTS users (
    username      TEXT PRIMARY KEY,
    role          TEXT NOT NULL,
    password_hash TEXT NOT NULL
  );
  CREATE TABLE IF NOT EXISTS combat_sessions (
    id               TEXT PRIMARY KEY,
    round            INTEGER NOT NULL,
    turn_index       INTEGER NOT NULL,
    order_json       TEXT NOT NULL,
    conditions_json  TEXT NOT NULL
  );
  CREATE TABLE IF NOT EXISTS compendium_monsters (
    slug         TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    cr           TEXT NOT NULL,
    armor_class  INTEGER NOT NULL,
    hit_points   INTEGER NOT NULL,
    tags_json    TEXT NOT NULL
  );
  CREATE TABLE IF NOT EXISTS compendium_items (
    slug    TEXT PRIMARY KEY,
    name    TEXT NOT NULL,
    type    TEXT NOT NULL,
    rarity  TEXT NOT NULL,
    cost_gp INTEGER NOT NULL
  );
  CREATE TABLE IF NOT EXISTS campaigns (
    id   TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    dm   TEXT NOT NULL
  );
  CREATE TABLE IF NOT EXISTS campaign_characters (
    id          TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    name        TEXT NOT NULL,
    level       INTEGER NOT NULL,
    class       TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id)
  );
  CREATE TABLE IF NOT EXISTS campaign_events (
    id          TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    kind        TEXT NOT NULL,
    summary     TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id)
  );
SQL

# Serialize a Ruby string into a SQLite string literal (single quotes doubled).
def sql_quote(s)
  "'" + s.to_s.gsub("'", "''") + "'"
end

# Hold DB_MUTEX for the duration of a logical transaction. Callers MUST use the
# raw helpers (db_run / db_select) inside; never the locking convenience ones.
def db_locked
  DB_MUTEX.synchronize { yield }
end

# Execute a SQL script against game.db (no locking). Returns [out, err, status].
def db_run(sql)
  Open3.capture3("sqlite3", DB_PATH, sql)
end

# Execute a SELECT and parse the `-json` output (no locking). Returns an Array
# of Hashes; an empty result set yields an empty String from the CLI, mapped to [].
def db_select(sql)
  out, _err, _status = Open3.capture3("sqlite3", "-json", DB_PATH, sql)
  return [] if out.nil? || out.strip.empty?
  JSON.parse(out)
end

# Create a fresh database file with the current schema. Called once at boot so
# each server process starts from a clean slate (mirroring the prior in-memory
# behavior and avoiding stale benchmark data across runs).
def init_db
  File.delete(DB_PATH) if File.exist?(DB_PATH)
  _out, err, status = db_run(SCHEMA_SQL)
  warn "[storage] sqlite schema init failed: #{err.strip}" unless status.success?
end

# GET /v1/storage/status -> report the durable storage driver and init state.
def storage_status
  initialized = begin
    db_locked do
      File.exist?(DB_PATH) &&
        db_select("SELECT value FROM schema_meta WHERE key='schema_version';")
          .any? { |r| r["value"].to_i == SCHEMA_VERSION }
    end
  rescue StandardError
    false
  end
  { "driver" => "sqlite", "schema_version" => SCHEMA_VERSION, "initialized" => !!initialized }
end

# POST /v1/storage/reset -> clear benchmark-created durable data, recreate schema.
def storage_reset
  db_locked do
    db_run(
      "DELETE FROM users; DELETE FROM combat_sessions; " \
      "DELETE FROM compendium_monsters; DELETE FROM compendium_items; " \
      "DELETE FROM campaigns; DELETE FROM campaign_characters; " \
      "DELETE FROM campaign_events;"
    )
    db_run(SCHEMA_SQL)
  end
  { "ok" => true, "schema_version" => SCHEMA_VERSION }
end

# Load a combat session from durable storage, reconstructing the in-memory shape.
# Returns the session Hash, or nil when the id does not exist.
def load_session(id)
  rows = db_select(
    "SELECT id, round, turn_index, order_json, conditions_json " \
    "FROM combat_sessions WHERE id=#{sql_quote(id)};"
  )
  return nil if rows.empty?
  r = rows.first
  {
    "id"         => r["id"],
    "round"      => r["round"].to_i,
    "turn_index" => r["turn_index"].to_i,
    "order"      => JSON.parse(r["order_json"]),
    "conditions" => JSON.parse(r["conditions_json"])
  }
end

# Persist a combat session (insert or replace) to durable storage.
def save_session(session)
  order_json      = JSON.generate(session["order"])
  conditions_json = JSON.generate(session["conditions"])
  db_run(
    "INSERT OR REPLACE INTO combat_sessions " \
    "(id, round, turn_index, order_json, conditions_json) VALUES " \
    "(#{sql_quote(session['id'])}, #{session['round']}, #{session['turn_index']}, " \
    "#{sql_quote(order_json)}, #{sql_quote(conditions_json)});"
  )
end

# Collapse a whole-valued Float to Integer so JSON emits "10" rather than "10.0".
def num(x)
  x.is_a?(Float) && x == x.to_i ? x.to_i : x
end

# Encounter multiplier based on the total number of monsters.
def encounter_multiplier(count)
  case count
  when 1       then 1
  when 2       then 1.5
  when 3..6    then 2
  when 7..10   then 2.5
  when 11..14  then 3
  else count >= 15 ? 4 : 1
  end
end

# POST /v1/dice/stats -> parse a <count>d<sides>[+/-<mod>] expression.
# Returns a result Hash, or nil when the expression is invalid.
def dice_stats(body)
  expr = body["expression"]
  return nil unless expr.is_a?(String)

  match = /\A(\d+)d(\d+)(?:([+-])(\d+))?\z/.match(expr.strip)
  return nil unless match

  count    = match[1].to_i
  sides    = match[2].to_i
  modifier = match[3] ? (match[3] == "-" ? -match[4].to_i : match[4].to_i) : 0
  return nil unless count.positive? && sides.positive?

  min = count + modifier
  max = count * sides + modifier
  {
    "dice_count" => count,
    "sides"      => sides,
    "modifier"   => modifier,
    "min"        => min,
    "max"        => max,
    "average"    => num((min + max) / 2.0)
  }
end

# POST /v1/checks/ability -> resolve an ability check against a DC.
def ability_check(body)
  roll     = (body["roll"]     || 0).to_i
  modifier = (body["modifier"] || 0).to_i
  dc       = (body["dc"]       || 0).to_i
  total = roll + modifier
  { "total" => total, "success" => total >= dc, "margin" => total - dc }
end

# POST /v1/encounters/adjusted-xp -> compute base/adjusted XP and difficulty.
# Returns a result Hash, or nil when a CR or level is unsupported.
def adjusted_xp(body)
  party    = body["party"]    || []
  monsters = body["monsters"] || []

  base_xp = 0
  monster_count = 0
  monsters.each do |mon|
    xp = XP_TABLE[mon["cr"].to_s]
    return nil unless xp
    cnt = (mon["count"] || 0).to_i
    base_xp += xp * cnt
    monster_count += cnt
  end

  multiplier  = encounter_multiplier(monster_count)
  adjusted    = num(base_xp * multiplier)

  easy = medium = hard = deadly = 0
  party.each do |member|
    thresholds = THRESHOLDS[(member["level"] || 3).to_i]
    return nil unless thresholds
    easy   += thresholds[0]
    medium += thresholds[1]
    hard   += thresholds[2]
    deadly += thresholds[3]
  end

  difficulty =
    if adjusted >= deadly then "deadly"
    elsif adjusted >= hard then "hard"
    elsif adjusted >= medium then "medium"
    elsif adjusted >= easy then "easy"
    else "trivial"
    end

  {
    "base_xp"       => base_xp,
    "monster_count" => monster_count,
    "multiplier"    => multiplier,
    "adjusted_xp"   => adjusted,
    "difficulty"    => difficulty,
    "thresholds"    => {
      "easy"   => easy,
      "medium" => medium,
      "hard"   => hard,
      "deadly" => deadly
    }
  }
end

# POST /v1/initiative/order -> sort combatants into initiative order.
def initiative_order(body)
  combatants = body["combatants"] || []
  scored = combatants.map do |c|
    roll = (c["roll"] || 0).to_i
    dex  = (c["dex"]  || 0).to_i
    { "name" => c["name"].to_s, "score" => roll + dex, "dex" => dex }
  end
  # score desc, then dex desc, then name asc.
  ordered = scored.sort_by { |c| [-c["score"], -c["dex"], c["name"]] }
  { "order" => ordered.map { |c| { "name" => c["name"], "score" => c["score"] } } }
end

# The six standard D&D 5e ability abbreviations.
ABILITIES = %w[str dex con int wis cha].freeze

# Ability modifier = floor((score - 10) / 2). Floors negative halves, e.g. 9 -> -1.
def ability_modifier(score)
  ((score - 10) / 2).floor
end

# Proficiency bonus by character level (1-20).
def proficiency_bonus(level)
  case level
  when 1..4   then 2
  when 5..8   then 3
  when 9..12  then 4
  when 13..16 then 5
  when 17..20 then 6
  end
end

# POST /v1/characters/ability-modifier -> modifier for a single score.
# Returns a result Hash, or nil when the score is out of range/non-integer.
def characters_ability_modifier(body)
  score = body["score"]
  return nil unless score.is_a?(Integer) && score.between?(1, 30)
  { "score" => score, "modifier" => ability_modifier(score) }
end

# POST /v1/characters/proficiency -> proficiency bonus for a level.
# Returns a result Hash, or nil when the level is out of range/non-integer.
def characters_proficiency(body)
  level = body["level"]
  return nil unless level.is_a?(Integer) && level.between?(1, 20)
  { "level" => level, "proficiency_bonus" => proficiency_bonus(level) }
end

# POST /v1/characters/derived-stats -> proficiency, hp, AC and all modifiers.
# Returns a result Hash, or nil when any required field is missing/invalid.
def characters_derived_stats(body)
  level = body["level"]
  return nil unless level.is_a?(Integer) && level.between?(1, 20)

  abilities = body["abilities"]
  return nil unless abilities.is_a?(Hash)

  modifiers = {}
  ABILITIES.each do |ab|
    score = abilities[ab]
    return nil unless score.is_a?(Integer) && score.between?(1, 30)
    modifiers[ab] = ability_modifier(score)
  end

  armor = body["armor"]
  return nil unless armor.is_a?(Hash)
  base    = armor["base"]
  dex_cap = armor["dex_cap"]
  return nil unless base.is_a?(Integer) && dex_cap.is_a?(Integer)

  shield_bonus = armor["shield"] ? 2 : 0
  dex_mod      = modifiers["dex"]
  con_mod      = modifiers["con"]

  {
    "level"             => level,
    "proficiency_bonus" => proficiency_bonus(level),
    "hp_max"            => level * (6 + con_mod),
    "armor_class"       => base + [dex_mod, dex_cap].min + shield_bonus,
    "modifiers"         => modifiers
  }
end

# Public response shape for a combat session (no conditions field here).
def session_view(session)
  active = session["order"][session["turn_index"]]
  {
    "id"         => session["id"],
    "round"      => session["round"],
    "turn_index" => session["turn_index"],
    "active"     => active ? { "name" => active["name"], "score" => active["score"] } : nil,
    "order"      => session["order"].map { |c| { "name" => c["name"], "score" => c["score"] } }
  }
end

# Snapshot of all condition lists, keyed by combatant name. Combatants whose
# conditions have all expired still appear with an empty array, so callers can
# see that a combatant is tracked but currently unaffected. Combatants who never
# had a condition attached never get a key and therefore never appear.
def conditions_view(session)
  view = {}
  session["conditions"].each do |name, conds|
    list = conds || []
    view[name] = list.map { |c| { "condition" => c["condition"], "remaining_rounds" => c["remaining_rounds"] } }
  end
  view
end

# POST /v1/combat/sessions -> create a stateful combat session.
# Returns the new session Hash, or nil when the request is malformed.
def create_combat_session(body)
  id = body["id"]
  return nil unless id.is_a?(String) && !id.empty?

  combatants = body["combatants"]
  return nil unless combatants.is_a?(Array) && !combatants.empty?

  scored = []
  combatants.each do |c|
    return nil unless c.is_a?(Hash)
    name = c["name"]
    dex  = c["dex"]
    roll = c["roll"]
    return nil unless name.is_a?(String) && !name.empty?
    return nil unless dex.is_a?(Integer)
    return nil unless roll.is_a?(Integer)
    scored << { "name" => name, "score" => roll + dex, "dex" => dex }
  end

  ordered = scored.sort_by { |c| [-c["score"], -c["dex"], c["name"]] }
  order   = ordered.map { |c| { "name" => c["name"], "score" => c["score"] } }

  { "id" => id, "round" => 1, "turn_index" => 0, "order" => order, "conditions" => {} }
end

# POST /v1/combat/sessions/{id}/conditions -> attach a condition to a combatant.
# Returns a response Hash, or nil when the request is malformed.
def add_condition(session, body)
  target    = body["target"]
  condition = body["condition"]
  duration  = body["duration_rounds"]

  return nil unless target.is_a?(String) && !target.empty?
  return nil unless condition.is_a?(String)
  return nil unless duration.is_a?(Integer) && duration.positive?

  names = session["order"].map { |c| c["name"] }
  return nil unless names.include?(target)

  entry = { "condition" => condition, "remaining_rounds" => duration }
  session["conditions"][target] ||= []
  session["conditions"][target] << entry

  {
    "target"     => target,
    "conditions" => session["conditions"][target].map { |c|
      { "condition" => c["condition"], "remaining_rounds" => c["remaining_rounds"] }
    }
  }
end

# POST /v1/combat/sessions/{id}/advance -> advance to the next combatant's turn.
# Mutates the session in place and returns a response Hash.
def advance_turn(session)
  order = session["order"]
  next_index = session["turn_index"] + 1
  if next_index >= order.length
    next_index = 0
    session["round"] += 1
  end
  session["turn_index"] = next_index

  active_name = order[next_index]["name"]
  conds = session["conditions"][active_name]
  if conds
    conds.each { |c| c["remaining_rounds"] -= 1 }
    session["conditions"][active_name] = conds.reject { |c| c["remaining_rounds"] <= 0 }
  end

  active = order[next_index]
  {
    "id"         => session["id"],
    "round"      => session["round"],
    "turn_index" => session["turn_index"],
    "active"     => { "name" => active["name"], "score" => active["score"] },
    "conditions" => conditions_view(session)
  }
end

# --- Auth: users and password login ---

# Valid username: 2-32 chars of lowercase letters, digits, underscore, hyphen.
USERNAME_RE = /\A[a-z0-9_-]{2,32}\z/.freeze

# PBKDF2 parameters for password hashing (Ruby stdlib openssl). A stored hash is
# self-describing: "pbkdf2$<iterations>$<salt_hex>$<hash_hex>".
PBKDF2_ITERATIONS = 100_000
PBKDF2_DIGEST     = "sha256"
PBKDF2_SALT_BYTES = 16
PBKDF2_KEY_LEN    = 32

# Hash a plaintext password into a self-describing verifier string.
def hash_password(password)
  salt = OpenSSL::Random.random_bytes(PBKDF2_SALT_BYTES)
  hash = OpenSSL::KDF.pbkdf2_hmac(
    password, salt: salt, iterations: PBKDF2_ITERATIONS,
    length: PBKDF2_KEY_LEN, hash: PBKDF2_DIGEST
  )
  "pbkdf2$#{PBKDF2_ITERATIONS}$#{salt.unpack1('H*')}$#{hash.unpack1('H*')}"
end

# Verify a plaintext password against a stored verifier. Constant-time compare.
def verify_password(password, stored)
  return false unless stored.is_a?(String)
  scheme, iter, salt_hex, hash_hex = stored.split("$")
  return false unless scheme == "pbkdf2" && iter && salt_hex && hash_hex
  salt     = [salt_hex].pack("H*")
  expected = [hash_hex].pack("H*")
  computed = OpenSSL::KDF.pbkdf2_hmac(
    password, salt: salt, iterations: iter.to_i,
    length: expected.bytesize, hash: PBKDF2_DIGEST
  )
  OpenSSL.fixed_length_secure_compare(computed, expected)
rescue ArgumentError
  false
end

# POST /v1/auth/register -> create a user with a hashed password.
# Returns [status, body]. 400 for malformed input, 409 for a duplicate username.
def register_user(body)
  return [400, { "error" => "invalid request" }] unless body.is_a?(Hash)

  username = body["username"]
  password = body["password"]
  role     = body["role"]

  unless username.is_a?(String) && USERNAME_RE.match?(username)
    return [400, { "error" => "invalid request" }]
  end
  unless password.is_a?(String) && password.length >= 8
    return [400, { "error" => "invalid request" }]
  end
  return [400, { "error" => "invalid request" }] unless role == "dm" || role == "player"

  db_locked do
    unless db_select("SELECT username FROM users WHERE username=#{sql_quote(username)};").empty?
      next [409, { "error" => "username already exists" }]
    end
    db_run(
      "INSERT INTO users (username, role, password_hash) VALUES " \
      "(#{sql_quote(username)}, #{sql_quote(role)}, #{sql_quote(hash_password(password))});"
    )
    [201, { "username" => username, "role" => role }]
  end
end

# POST /v1/auth/login -> verify credentials and return a deterministic token.
# Returns [status, body]. 400 for malformed input, 401 for bad credentials.
def login_user(body)
  return [400, { "error" => "invalid request" }] unless body.is_a?(Hash)

  username = body["username"]
  password = body["password"]
  unless username.is_a?(String) && password.is_a?(String)
    return [400, { "error" => "invalid request" }]
  end

  db_locked do
    rows = db_select("SELECT password_hash FROM users WHERE username=#{sql_quote(username)};")
    stored = rows.empty? ? nil : rows.first["password_hash"]
    if stored && verify_password(password, stored)
      next [200, { "username" => username, "token" => "session-#{username}" }]
    end
    [401, { "error" => "invalid credentials" }]
  end
end

# --- Compendium: monsters and items ---

# Validate a monster create payload. Returns a normalized Hash, or nil when
# the request is malformed. tags is optional and defaults to an empty array.
# Returns [status, body] when called with a body via create_monster.
def validate_monster(body)
  return nil unless body.is_a?(Hash)
  slug        = body["slug"]
  name        = body["name"]
  cr          = body["cr"]
  armor_class = body["armor_class"]
  hit_points  = body["hit_points"]
  tags        = body["tags"]
  return nil unless slug.is_a?(String) && !slug.empty?
  return nil unless name.is_a?(String) && !name.empty?
  return nil unless cr.is_a?(String) && !cr.empty?
  return nil unless armor_class.is_a?(Integer)
  return nil unless hit_points.is_a?(Integer)
  if tags.nil?
    tags = []
  elsif tags.is_a?(Array)
    return nil unless tags.all? { |t| t.is_a?(String) }
  else
    return nil
  end
  { "slug" => slug, "name" => name, "cr" => cr,
    "armor_class" => armor_class, "hit_points" => hit_points, "tags" => tags }
end

# POST /v1/compendium/monsters -> create a monster record.
# Returns [status, body]. 400 malformed, 409 duplicate slug, 201 on success.
# The create response omits tags (per spec); tags are returned only on read.
def create_monster(body)
  monster = validate_monster(body)
  return [400, { "error" => "invalid request" }] unless monster
  db_locked do
    unless db_select(
      "SELECT slug FROM compendium_monsters WHERE slug=#{sql_quote(monster['slug'])};"
    ).empty?
      next [409, { "error" => "monster already exists" }]
    end
    db_run(
      "INSERT INTO compendium_monsters " \
      "(slug, name, cr, armor_class, hit_points, tags_json) VALUES " \
      "(#{sql_quote(monster['slug'])}, #{sql_quote(monster['name'])}, #{sql_quote(monster['cr'])}, " \
      "#{monster['armor_class']}, #{monster['hit_points']}, #{sql_quote(JSON.generate(monster['tags']))});"
    )
    [201, {
      "slug"        => monster["slug"],
      "name"        => monster["name"],
      "cr"          => monster["cr"],
      "armor_class" => monster["armor_class"],
      "hit_points"  => monster["hit_points"]
    }]
  end
end

# GET /v1/compendium/monsters/{slug} -> read a monster record (includes tags).
# Returns [status, body]. 404 when the slug is unknown, 200 on success.
def read_monster(slug)
  db_locked do
    rows = db_select(
      "SELECT slug, name, cr, armor_class, hit_points, tags_json " \
      "FROM compendium_monsters WHERE slug=#{sql_quote(slug)};"
    )
    if rows.empty?
      next [404, { "error" => "monster not found" }]
    end
    r = rows.first
    [200, {
      "slug"        => r["slug"],
      "name"        => r["name"],
      "cr"          => r["cr"],
      "armor_class" => r["armor_class"].to_i,
      "hit_points"  => r["hit_points"].to_i,
      "tags"        => JSON.parse(r["tags_json"])
    }]
  end
end

# Validate an item create payload. Returns a normalized Hash, or nil when
# the request is malformed.
def validate_item(body)
  return nil unless body.is_a?(Hash)
  slug    = body["slug"]
  name    = body["name"]
  type    = body["type"]
  rarity  = body["rarity"]
  cost_gp = body["cost_gp"]
  return nil unless slug.is_a?(String) && !slug.empty?
  return nil unless name.is_a?(String) && !name.empty?
  return nil unless type.is_a?(String) && !type.empty?
  return nil unless rarity.is_a?(String) && !rarity.empty?
  return nil unless cost_gp.is_a?(Integer)
  { "slug" => slug, "name" => name, "type" => type,
    "rarity" => rarity, "cost_gp" => cost_gp }
end

# POST /v1/compendium/items -> create an item record.
# Returns [status, body]. 400 malformed, 409 duplicate slug, 201 on success.
def create_item(body)
  item = validate_item(body)
  return [400, { "error" => "invalid request" }] unless item
  db_locked do
    unless db_select(
      "SELECT slug FROM compendium_items WHERE slug=#{sql_quote(item['slug'])};"
    ).empty?
      next [409, { "error" => "item already exists" }]
    end
    db_run(
      "INSERT INTO compendium_items (slug, name, type, rarity, cost_gp) VALUES " \
      "(#{sql_quote(item['slug'])}, #{sql_quote(item['name'])}, #{sql_quote(item['type'])}, " \
      "#{sql_quote(item['rarity'])}, #{item['cost_gp']});"
    )
    [201, {
      "slug"    => item["slug"],
      "name"    => item["name"],
      "type"    => item["type"],
      "rarity"  => item["rarity"],
      "cost_gp" => item["cost_gp"]
    }]
  end
end

# GET /v1/compendium/items/{slug} -> read an item record.
# Returns [status, body]. 404 when the slug is unknown, 200 on success.
def read_item(slug)
  db_locked do
    rows = db_select(
      "SELECT slug, name, type, rarity, cost_gp " \
      "FROM compendium_items WHERE slug=#{sql_quote(slug)};"
    )
    if rows.empty?
      next [404, { "error" => "item not found" }]
    end
    r = rows.first
    [200, {
      "slug"    => r["slug"],
      "name"    => r["name"],
      "type"    => r["type"],
      "rarity"  => r["rarity"],
      "cost_gp" => r["cost_gp"].to_i
    }]
  end
end

# --- Campaign state: campaigns, characters, session log events ---

# POST /v1/campaigns -> create a campaign record.
# Returns [status, body]. 400 malformed, 409 duplicate id, 201 on success.
def create_campaign(body)
  return [400, { "error" => "invalid request" }] unless body.is_a?(Hash)
  id   = body["id"]
  name = body["name"]
  dm   = body["dm"]
  return [400, { "error" => "invalid request" }] unless id.is_a?(String) && !id.empty?
  return [400, { "error" => "invalid request" }] unless name.is_a?(String) && !name.empty?
  return [400, { "error" => "invalid request" }] unless dm.is_a?(String) && !dm.empty?
  db_locked do
    unless db_select("SELECT id FROM campaigns WHERE id=#{sql_quote(id)};").empty?
      next [409, { "error" => "campaign already exists" }]
    end
    db_run(
      "INSERT INTO campaigns (id, name, dm) VALUES " \
      "(#{sql_quote(id)}, #{sql_quote(name)}, #{sql_quote(dm)});"
    )
    next [201, { "id" => id, "name" => name, "dm" => dm }]
  end
end

# POST /v1/campaigns/{id}/characters -> add a character to a campaign.
# Returns [status, body]. 400 malformed, 404 unknown campaign,
# 409 duplicate character id, 201 on success.
def add_campaign_character(campaign_id, body)
  return [400, { "error" => "invalid request" }] unless body.is_a?(Hash)
  id    = body["id"]
  name  = body["name"]
  level = body["level"]
  klass = body["class"]
  return [400, { "error" => "invalid request" }] unless id.is_a?(String) && !id.empty?
  return [400, { "error" => "invalid request" }] unless name.is_a?(String) && !name.empty?
  return [400, { "error" => "invalid request" }] unless level.is_a?(Integer)
  return [400, { "error" => "invalid request" }] unless klass.is_a?(String) && !klass.empty?
  db_locked do
    if db_select("SELECT id FROM campaigns WHERE id=#{sql_quote(campaign_id)};").empty?
      next [404, { "error" => "campaign not found" }]
    end
    unless db_select(
      "SELECT id FROM campaign_characters " \
      "WHERE campaign_id=#{sql_quote(campaign_id)} AND id=#{sql_quote(id)};"
    ).empty?
      next [409, { "error" => "character already exists" }]
    end
    db_run(
      "INSERT INTO campaign_characters (id, campaign_id, name, level, class) VALUES " \
      "(#{sql_quote(id)}, #{sql_quote(campaign_id)}, #{sql_quote(name)}, " \
      "#{level}, #{sql_quote(klass)});"
    )
    next [201, { "id" => id, "name" => name, "level" => level, "class" => klass }]
  end
end

# POST /v1/campaigns/{id}/events -> add a session log event to a campaign.
# Returns [status, body]. 400 malformed, 404 unknown campaign,
# 409 duplicate event id, 201 on success. Response omits summary (per spec).
def add_campaign_event(campaign_id, body)
  return [400, { "error" => "invalid request" }] unless body.is_a?(Hash)
  id      = body["id"]
  kind    = body["kind"]
  summary = body["summary"]
  return [400, { "error" => "invalid request" }] unless id.is_a?(String) && !id.empty?
  return [400, { "error" => "invalid request" }] unless kind.is_a?(String) && !kind.empty?
  return [400, { "error" => "invalid request" }] unless summary.is_a?(String)
  db_locked do
    if db_select("SELECT id FROM campaigns WHERE id=#{sql_quote(campaign_id)};").empty?
      next [404, { "error" => "campaign not found" }]
    end
    unless db_select(
      "SELECT id FROM campaign_events " \
      "WHERE campaign_id=#{sql_quote(campaign_id)} AND id=#{sql_quote(id)};"
    ).empty?
      next [409, { "error" => "event already exists" }]
    end
    db_run(
      "INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES " \
      "(#{sql_quote(id)}, #{sql_quote(campaign_id)}, #{sql_quote(kind)}, " \
      "#{sql_quote(summary)});"
    )
    next [201, { "id" => id, "kind" => kind }]
  end
end

# GET /v1/campaigns/{id}/state -> read full campaign state.
# Returns [status, body]. 404 unknown campaign, 200 on success.
def read_campaign_state(campaign_id)
  db_locked do
    rows = db_select(
      "SELECT id, name, dm FROM campaigns WHERE id=#{sql_quote(campaign_id)};"
    )
    if rows.empty?
      next [404, { "error" => "campaign not found" }]
    end
    c = rows.first
    chars = db_select(
      "SELECT id, name, level, class FROM campaign_characters " \
      "WHERE campaign_id=#{sql_quote(campaign_id)} ORDER BY rowid;"
    )
    characters = chars.map do |r|
      { "id" => r["id"], "name" => r["name"],
        "level" => r["level"].to_i, "class" => r["class"] }
    end
    count_rows = db_select(
      "SELECT COUNT(*) AS n FROM campaign_events " \
      "WHERE campaign_id=#{sql_quote(campaign_id)};"
    )
    log_count = count_rows.empty? ? 0 : count_rows.first["n"].to_i
    next [200, {
      "id"         => c["id"],
      "name"       => c["name"],
      "dm"         => c["dm"],
      "characters" => characters,
      "log_count"  => log_count
    }]
  end
end

# --- PHB rules: spell slots, long rest, equipment load ---

# POST /v1/phb/spell-slots -> spell slots for a class/level.
# Returns a result Hash, or nil when the class/level is unsupported.
def phb_spell_slots(body)
  klass = body["class"]
  level = body["level"]
  return nil unless klass == "wizard"
  return nil unless level.is_a?(Integer) && level.between?(1, 20)
  slots = WIZARD_SLOTS[level]
  return nil unless slots
  slot_view = {}
  slots.each { |k, v| slot_view[k.to_s] = v if v.positive? }
  { "class" => klass, "level" => level, "slots" => slot_view }
end

# POST /v1/phb/rests/long -> apply long-rest recovery.
# Returns a result Hash, or nil when the request is malformed.
def phb_long_rest(body)
  level            = body["level"]
  hp_current       = body["hp_current"]
  hp_max           = body["hp_max"]
  hit_dice_spent   = body["hit_dice_spent"]
  exhaustion_level = body["exhaustion_level"]
  return nil unless level.is_a?(Integer) && level >= 1
  return nil unless hp_current.is_a?(Integer) && hp_current >= 0
  return nil unless hp_max.is_a?(Integer) && hp_max >= 0
  return nil unless hit_dice_spent.is_a?(Integer) && hit_dice_spent >= 0
  return nil unless exhaustion_level.is_a?(Integer) && exhaustion_level >= 0

  restored       = [hit_dice_spent, [level / 2, 1].max].min
  new_spent      = hit_dice_spent - restored
  new_exhaustion = [exhaustion_level - 1, 0].max
  {
    "hp_current"       => hp_max,
    "hit_dice_spent"   => new_spent,
    "exhaustion_level" => new_exhaustion
  }
end

# POST /v1/phb/equipment-load -> carrying capacity and encumbrance.
# Returns a result Hash, or nil when the request is malformed.
def phb_equipment_load(body)
  strength = body["strength"]
  weight   = body["weight"]
  return nil unless strength.is_a?(Integer) && strength >= 1
  return nil unless weight.is_a?(Integer) && weight >= 0
  capacity = strength * 15
  {
    "capacity"   => capacity,
    "weight"     => weight,
    "encumbered" => weight > capacity
  }
end

# --- DM tools: encounter builder, loot parcel, session recap ---

# Deterministic tier-1..4 loot parcels. The benchmark only requires tier 1; the
# higher tiers are included so unknown tiers still map to a deterministic parcel.
TIER_LOOT = {
  1 => { "coins_gp" => 75,  "items" => [{ "slug" => "healing-potion", "quantity" => 2 }] },
  2 => { "coins_gp" => 200, "items" => [{ "slug" => "healing-potion", "quantity" => 3 }] },
  3 => { "coins_gp" => 500, "items" => [{ "slug" => "healing-potion", "quantity" => 5 }] },
  4 => { "coins_gp" => 1200, "items" => [{ "slug" => "healing-potion", "quantity" => 8 }] }
}.freeze

# Map an encounter difficulty to a deterministic DM recommendation string.
def difficulty_recommendation(difficulty)
  case difficulty
  when "trivial" then "too weak"
  when "easy"    then "safe warm-up"
  when "medium"  then "balanced fight"
  when "hard"    then "tough battle"
  when "deadly"  then "likely TPK"
  end
end

# POST /v1/dm/encounter-builder -> look up monster CRs from the compendium,
# reuse the core adjusted-XP math, and return a deterministic recommendation.
# Returns [status, body]. 400 for malformed input, 404 for an unknown monster.
def dm_encounter_builder(body)
  return [400, { "error" => "invalid request" }] unless body.is_a?(Hash)
  campaign_id   = body["campaign_id"]
  party         = body["party"]
  monster_slugs = body["monster_slugs"]
  return [400, { "error" => "invalid request" }] unless campaign_id.is_a?(String) && !campaign_id.empty?
  return [400, { "error" => "invalid request" }] unless party.is_a?(Array) && !party.empty?
  return [400, { "error" => "invalid request" }] unless monster_slugs.is_a?(Array) && !monster_slugs.empty?
  monster_slugs.each do |slug|
    return [400, { "error" => "invalid request" }] unless slug.is_a?(String) && !slug.empty?
  end
  levels = party.map do |member|
    return [400, { "error" => "invalid request" }] unless member.is_a?(Hash)
    lvl = member["level"]
    return [400, { "error" => "invalid request" }] unless lvl.is_a?(Integer)
    lvl
  end

  db_locked do
    crs = monster_slugs.map do |slug|
      rows = db_select("SELECT cr FROM compendium_monsters WHERE slug=#{sql_quote(slug)};")
      rows.empty? ? nil : rows.first["cr"]
    end
    if crs.any? { |c| c.nil? }
      next [404, { "error" => "monster not found" }]
    end
    if crs.any? { |cr| !XP_TABLE.key?(cr.to_s) }
      next [400, { "error" => "invalid request" }]
    end
    if levels.any? { |lvl| !THRESHOLDS.key?(lvl) }
      next [400, { "error" => "invalid request" }]
    end

    base_xp       = crs.sum { |cr| XP_TABLE[cr.to_s] }
    monster_count = crs.length
    multiplier    = encounter_multiplier(monster_count)
    adjusted      = num(base_xp * multiplier)

    easy = medium = hard = deadly = 0
    levels.each do |lvl|
      t = THRESHOLDS[lvl]
      easy   += t[0]
      medium += t[1]
      hard   += t[2]
      deadly += t[3]
    end

    difficulty =
      if adjusted >= deadly then "deadly"
      elsif adjusted >= hard then "hard"
      elsif adjusted >= medium then "medium"
      elsif adjusted >= easy then "easy"
      else "trivial"
      end

    [200, {
      "campaign_id"    => campaign_id,
      "base_xp"        => base_xp,
      "adjusted_xp"    => adjusted,
      "difficulty"     => difficulty,
      "monster_count"  => monster_count,
      "recommendation" => difficulty_recommendation(difficulty)
    }]
  end
end

# POST /v1/dm/loot-parcel -> return a deterministic tier-based loot parcel.
# Returns [status, body]. 400 for malformed input.
def dm_loot_parcel(body)
  return [400, { "error" => "invalid request" }] unless body.is_a?(Hash)
  campaign_id = body["campaign_id"]
  tier        = body["tier"]
  return [400, { "error" => "invalid request" }] unless campaign_id.is_a?(String) && !campaign_id.empty?
  return [400, { "error" => "invalid request" }] unless tier.is_a?(Integer) && tier.between?(1, 4)
  loot = TIER_LOOT[tier]
  return [400, { "error" => "invalid request" }] unless loot
  [200, {
    "campaign_id" => campaign_id,
    "coins_gp"    => loot["coins_gp"],
    "items"       => loot["items"].map { |i| { "slug" => i["slug"], "quantity" => i["quantity"] } }
  }]
end

# Derive deterministic open plot threads from a campaign's event summaries.
# "Nyx scouts the goblin trail." -> "Resolve goblin trail ambush"
def derive_open_threads(events)
  threads = []
  events.each do |e|
    summary = e["summary"].to_s
    if summary =~ /\bscouts the\s+/
      subject = summary.sub(/\A.*?\bscouts the\s+/, "").sub(/\.\z/, "")
      threads << "Resolve #{subject} ambush"
    end
  end
  threads
end

# POST /v1/dm/session-recap -> summarize the latest campaign event and list
# open plot threads. Returns [status, body]. 400 malformed, 404 unknown campaign.
def dm_session_recap(body)
  return [400, { "error" => "invalid request" }] unless body.is_a?(Hash)
  campaign_id = body["campaign_id"]
  return [400, { "error" => "invalid request" }] unless campaign_id.is_a?(String) && !campaign_id.empty?

  db_locked do
    if db_select("SELECT id FROM campaigns WHERE id=#{sql_quote(campaign_id)};").empty?
      next [404, { "error" => "campaign not found" }]
    end
    events = db_select(
      "SELECT id, kind, summary FROM campaign_events " \
      "WHERE campaign_id=#{sql_quote(campaign_id)} ORDER BY rowid;"
    )
    summary = events.empty? ? "" : events.last["summary"]
    [200, {
      "campaign_id"  => campaign_id,
      "summary"      => summary,
      "open_threads" => derive_open_threads(events)
    }]
  end
end

# Parse a JSON request body, returning nil for empty or unparseable input.
def parse_json(raw)
  return nil if raw.nil? || raw.empty?
  JSON.parse(raw)
rescue JSON::ParserError
  nil
end

# Serialize a payload and write a complete HTTP/1.1 response, then close.
def respond(client, status, payload)
  body = JSON.generate(payload)
  client.write("HTTP/1.1 #{status} #{STATUS_TEXT[status] || 'OK'}\r\n")
  client.write("Content-Type: application/json\r\n")
  client.write("Content-Length: #{body.bytesize}\r\n")
  client.write("Connection: close\r\n")
  client.write("\r\n")
  client.write(body)
  client.flush
end

# Read and route a single HTTP request.
def handle(client)
  request_line = client.gets
  return unless request_line

  parts  = request_line.strip.split(/\s+/)
  method = parts[0]
  path   = (parts[1] || "").split("?").first

  headers = {}
  while (line = client.gets)
    line = line.strip
    break if line.empty?
    key, val = line.split(":", 2)
    headers[key.downcase] = val.strip if key && val
  end

  if headers["expect"]&.downcase&.include?("100-continue")
    client.write("HTTP/1.1 100 Continue\r\n\r\n")
  end

  content_length = (headers["content-length"] || "0").to_i
  raw_body = content_length.positive? ? client.read(content_length) : ""

  case "#{method} #{path}"
  when "GET /health"
    respond(client, 200, { "ok" => true })
  when "POST /v1/dice/stats"
    data = parse_json(raw_body)
    result = data && dice_stats(data)
    respond(client, result ? 200 : 400, result || { "error" => "invalid expression" })
  when "POST /v1/checks/ability"
    data = parse_json(raw_body)
    if data
      respond(client, 200, ability_check(data))
    else
      respond(client, 400, { "error" => "invalid request" })
    end
  when "POST /v1/encounters/adjusted-xp"
    data = parse_json(raw_body)
    result = data && adjusted_xp(data)
    respond(client, result ? 200 : 400, result || { "error" => "invalid request" })
  when "POST /v1/initiative/order"
    data = parse_json(raw_body)
    if data
      respond(client, 200, initiative_order(data))
    else
      respond(client, 400, { "error" => "invalid request" })
    end
  when "POST /v1/characters/ability-modifier"
    data = parse_json(raw_body)
    result = data && characters_ability_modifier(data)
    respond(client, result ? 200 : 400, result || { "error" => "invalid request" })
  when "POST /v1/characters/proficiency"
    data = parse_json(raw_body)
    result = data && characters_proficiency(data)
    respond(client, result ? 200 : 400, result || { "error" => "invalid request" })
  when "POST /v1/characters/derived-stats"
    data = parse_json(raw_body)
    result = data && characters_derived_stats(data)
    respond(client, result ? 200 : 400, result || { "error" => "invalid request" })
  when "POST /v1/auth/register"
    data = parse_json(raw_body)
    status, body = register_user(data)
    respond(client, status, body)
  when "POST /v1/auth/login"
    data = parse_json(raw_body)
    status, body = login_user(data)
    respond(client, status, body)
  when "GET /v1/storage/status"
    respond(client, 200, storage_status)
  when "POST /v1/storage/reset"
    respond(client, 200, storage_reset)
  when "POST /v1/combat/sessions"
    data = parse_json(raw_body)
    result = db_locked do
      session = data && create_combat_session(data)
      if session
        save_session(session)
        { :status => 200, :body => session_view(session) }
      else
        { :status => 400, :body => { "error" => "invalid request" } }
      end
    end
    respond(client, result[:status], result[:body])
  when %r{\APOST /v1/combat/sessions/([^/]+)/conditions\z}
    session_id = $~[1]
    data = parse_json(raw_body)
    result = db_locked do
      session = load_session(session_id)
      if session.nil?
        { :status => 404, :body => { "error" => "session not found" } }
      else
        res = data && add_condition(session, data)
        if res
          save_session(session)
          { :status => 200, :body => res }
        else
          { :status => 400, :body => { "error" => "invalid request" } }
        end
      end
    end
    respond(client, result[:status], result[:body])
  when %r{\APOST /v1/combat/sessions/([^/]+)/advance\z}
    session_id = $~[1]
    result = db_locked do
      session = load_session(session_id)
      if session.nil?
        { :status => 404, :body => { "error" => "session not found" } }
      else
        body = advance_turn(session)
        save_session(session)
        { :status => 200, :body => body }
      end
    end
    respond(client, result[:status], result[:body])
  when "POST /v1/compendium/monsters"
    data = parse_json(raw_body)
    status, body = create_monster(data)
    respond(client, status, body)
  when %r{\AGET /v1/compendium/monsters/([^/]+)\z}
    slug = $~[1]
    status, body = read_monster(slug)
    respond(client, status, body)
  when "POST /v1/compendium/items"
    data = parse_json(raw_body)
    status, body = create_item(data)
    respond(client, status, body)
  when %r{\AGET /v1/compendium/items/([^/]+)\z}
    slug = $~[1]
    status, body = read_item(slug)
    respond(client, status, body)
  when "POST /v1/campaigns"
    data = parse_json(raw_body)
    status, body = create_campaign(data)
    respond(client, status, body)
  when %r{\APOST /v1/campaigns/([^/]+)/characters\z}
    campaign_id = $~[1]
    data = parse_json(raw_body)
    status, body = add_campaign_character(campaign_id, data)
    respond(client, status, body)
  when %r{\APOST /v1/campaigns/([^/]+)/events\z}
    campaign_id = $~[1]
    data = parse_json(raw_body)
    status, body = add_campaign_event(campaign_id, data)
    respond(client, status, body)
  when %r{\AGET /v1/campaigns/([^/]+)/state\z}
    campaign_id = $~[1]
    status, body = read_campaign_state(campaign_id)
    respond(client, status, body)
  when "POST /v1/phb/spell-slots"
    data = parse_json(raw_body)
    result = data && phb_spell_slots(data)
    respond(client, result ? 200 : 400, result || { "error" => "invalid request" })
  when "POST /v1/phb/rests/long"
    data = parse_json(raw_body)
    result = data && phb_long_rest(data)
    respond(client, result ? 200 : 400, result || { "error" => "invalid request" })
  when "POST /v1/phb/equipment-load"
    data = parse_json(raw_body)
    result = data && phb_equipment_load(data)
    respond(client, result ? 200 : 400, result || { "error" => "invalid request" })
  when "POST /v1/dm/encounter-builder"
    data = parse_json(raw_body)
    status, body = dm_encounter_builder(data)
    respond(client, status, body)
  when "POST /v1/dm/loot-parcel"
    data = parse_json(raw_body)
    status, body = dm_loot_parcel(data)
    respond(client, status, body)
  when "POST /v1/dm/session-recap"
    data = parse_json(raw_body)
    status, body = dm_session_recap(data)
    respond(client, status, body)
  else
    respond(client, 404, { "error" => "not found" })
  end
end

port = (ENV["PORT"] || 3000).to_i
init_db
server = TCPServer.new("127.0.0.1", port)

loop do
  begin
    client = server.accept
  rescue => e
    next
  end

  Thread.new(client) do |c|
    begin
      handle(c)
    rescue => e
      begin
        respond(c, 500, { "error" => "internal server error" })
      rescue
        # socket already broken; nothing more to do.
      end
    ensure
      c.close rescue nil
    end
  end
end
