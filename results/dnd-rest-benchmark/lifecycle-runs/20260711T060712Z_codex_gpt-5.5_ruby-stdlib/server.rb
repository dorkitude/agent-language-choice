#!/usr/bin/env ruby
# frozen_string_literal: true

require "json"
require "openssl"
require "socket"
require "fiddle"

CR_XP = {
  "0" => 10,
  "1/8" => 25,
  "1/4" => 50,
  "1/2" => 100,
  "1" => 200,
  "2" => 450,
  "3" => 700,
  "4" => 1100,
  "5" => 1800
}.freeze

LEVEL_THRESHOLDS = {
  3 => { "easy" => 75, "medium" => 150, "hard" => 225, "deadly" => 400 }
}.freeze

ABILITY_NAMES = %w[str dex con int wis cha].freeze
COMBAT_SESSIONS = {}
USERS = {}
MONSTERS = {}
ITEMS = {}
CAMPAIGNS = {}
DB_PATH = File.expand_path("game.db", __dir__)
SCHEMA_VERSION = 1

class DuplicateUsernameError < StandardError; end
class DuplicateSlugError < StandardError; end
class DuplicateIdError < StandardError; end
class BadCredentialsError < StandardError; end

class SQLiteStorage
  SQLITE_OK = 0
  POINTER_FORMAT = Fiddle::SIZEOF_VOIDP == 8 ? "Q!" : "L!"

  def initialize(path)
    @path = path
    @handle = sqlite_handle
    @db_pointer = Fiddle::Pointer.malloc(Fiddle::SIZEOF_VOIDP)

    open = Fiddle::Function.new(@handle["sqlite3_open"], [Fiddle::TYPE_VOIDP, Fiddle::TYPE_VOIDP], Fiddle::TYPE_INT)
    result = open.call(@path, @db_pointer)
    raise "sqlite open failed" unless result == SQLITE_OK

    @db = Fiddle::Pointer.new(pointer_value(@db_pointer))
    @exec = Fiddle::Function.new(
      @handle["sqlite3_exec"],
      [Fiddle::TYPE_VOIDP, Fiddle::TYPE_VOIDP, Fiddle::TYPE_VOIDP, Fiddle::TYPE_VOIDP, Fiddle::TYPE_VOIDP],
      Fiddle::TYPE_INT
    )
    @close = Fiddle::Function.new(@handle["sqlite3_close"], [Fiddle::TYPE_VOIDP], Fiddle::TYPE_INT)
    initialize_schema
  end

  def initialize_schema
    execute(<<~SQL)
      CREATE TABLE IF NOT EXISTS metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        data TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS combat_sessions (
        id TEXT PRIMARY KEY,
        data TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS monsters (
        slug TEXT PRIMARY KEY,
        data TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS items (
        slug TEXT PRIMARY KEY,
        data TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS campaigns (
        id TEXT PRIMARY KEY,
        data TEXT NOT NULL
      );
      INSERT OR REPLACE INTO metadata (key, value) VALUES ('schema_version', '#{SCHEMA_VERSION}');
    SQL
  end

  def initialized?
    rows = select("SELECT value FROM metadata WHERE key = 'schema_version'")
    rows.first && rows.first["value"] == SCHEMA_VERSION.to_s
  end

  def reset!
    execute(<<~SQL)
      DROP TABLE IF EXISTS users;
      DROP TABLE IF EXISTS combat_sessions;
      DROP TABLE IF EXISTS monsters;
      DROP TABLE IF EXISTS items;
      DROP TABLE IF EXISTS campaigns;
      DROP TABLE IF EXISTS metadata;
    SQL
    initialize_schema
  end

  def load_users
    select("SELECT username, data FROM users").each_with_object({}) do |row, users|
      users[row["username"]] = JSON.parse(row["data"])
    end
  end

  def save_user(user)
    execute("INSERT OR REPLACE INTO users (username, data) VALUES (#{quote(user["username"])}, #{quote(JSON.generate(user))})")
  end

  def load_combat_sessions
    select("SELECT id, data FROM combat_sessions").each_with_object({}) do |row, sessions|
      sessions[row["id"]] = JSON.parse(row["data"])
    end
  end

  def save_combat_session(session)
    execute("INSERT OR REPLACE INTO combat_sessions (id, data) VALUES (#{quote(session["id"])}, #{quote(JSON.generate(session))})")
  end

  def load_monsters
    select("SELECT slug, data FROM monsters").each_with_object({}) do |row, monsters|
      monsters[row["slug"]] = JSON.parse(row["data"])
    end
  end

  def save_monster(monster)
    execute("INSERT OR REPLACE INTO monsters (slug, data) VALUES (#{quote(monster["slug"])}, #{quote(JSON.generate(monster))})")
  end

  def load_items
    select("SELECT slug, data FROM items").each_with_object({}) do |row, items|
      items[row["slug"]] = JSON.parse(row["data"])
    end
  end

  def save_item(item)
    execute("INSERT OR REPLACE INTO items (slug, data) VALUES (#{quote(item["slug"])}, #{quote(JSON.generate(item))})")
  end

  def load_campaigns
    select("SELECT id, data FROM campaigns").each_with_object({}) do |row, campaigns|
      campaigns[row["id"]] = JSON.parse(row["data"])
    end
  end

  def save_campaign(campaign)
    execute("INSERT OR REPLACE INTO campaigns (id, data) VALUES (#{quote(campaign["id"])}, #{quote(JSON.generate(campaign))})")
  end

  def close
    @close.call(@db) if @close && @db
  end

  private

  def sqlite_handle
    ["libsqlite3.dylib", "libsqlite3.so.0", "libsqlite3.so"].each do |name|
      return Fiddle.dlopen(name)
    rescue Fiddle::DLError
      next
    end
    raise "sqlite library not found"
  end

  def execute(sql)
    result = @exec.call(@db, sql, nil, nil, nil)
    raise "sqlite exec failed" unless result == SQLITE_OK
  end

  def select(sql)
    rows = []
    callback = Fiddle::Closure::BlockCaller.new(
      Fiddle::TYPE_INT,
      [Fiddle::TYPE_VOIDP, Fiddle::TYPE_INT, Fiddle::TYPE_VOIDP, Fiddle::TYPE_VOIDP]
    ) do |_unused, count, values_ptr, names_ptr|
      row = {}
      count.times do |index|
        name_pointer = pointer_from_array(names_ptr, index)
        value_pointer = pointer_from_array(values_ptr, index)
        row[name_pointer.to_s] = value_pointer.null? ? nil : value_pointer.to_s
      end
      rows << row
      0
    end

    result = @exec.call(@db, sql, callback, nil, nil)
    raise "sqlite select failed" unless result == SQLITE_OK

    rows
  end

  def quote(value)
    "'#{value.to_s.gsub("'", "''")}'"
  end

  def pointer_from_array(array_pointer, index)
    Fiddle::Pointer.new(pointer_value(array_pointer + (index * Fiddle::SIZEOF_VOIDP)))
  end

  def pointer_value(pointer)
    pointer[0, Fiddle::SIZEOF_VOIDP].unpack1(POINTER_FORMAT)
  end
end

def json_response(status, body)
  payload = JSON.generate(body)
  reason = {
    200 => "OK",
    201 => "Created",
    400 => "Bad Request",
    401 => "Unauthorized",
    404 => "Not Found",
    405 => "Method Not Allowed",
    409 => "Conflict"
  }.fetch(status, "OK")

  [
    "HTTP/1.1 #{status} #{reason}",
    "Content-Type: application/json",
    "Content-Length: #{payload.bytesize}",
    "Connection: close",
    "",
    payload
  ].join("\r\n")
end

def integer_value?(value)
  value.is_a?(Integer)
end

def integer_in_range?(value, range)
  integer_value?(value) && range.cover?(value)
end

def parse_json_body(body)
  parsed = JSON.parse(body)
  raise ArgumentError unless parsed.is_a?(Hash)

  parsed
rescue JSON::ParserError
  raise ArgumentError
end

def valid_username?(username)
  username.is_a?(String) && username.match?(/\A[a-z0-9_-]{2,32}\z/)
end

def valid_slug?(slug)
  slug.is_a?(String) && slug.match?(/\A[a-z0-9][a-z0-9-]{0,63}\z/)
end

def non_empty_string?(value)
  value.is_a?(String) && !value.empty?
end

def password_record(password)
  raise ArgumentError unless password.is_a?(String) && password.length >= 8

  salt = OpenSSL::Random.random_bytes(16)
  hash = OpenSSL::PKCS5.pbkdf2_hmac(password, salt, 120_000, 32, "sha256")
  { "salt" => salt.unpack1("H*"), "hash" => hash.unpack1("H*") }
end

def password_matches?(password, record)
  return false unless password.is_a?(String)

  salt = [record["salt"]].pack("H*")
  expected = [record["hash"]].pack("H*")
  actual = OpenSSL::PKCS5.pbkdf2_hmac(password, salt, 120_000, expected.bytesize, "sha256")
  secure_compare(actual, expected)
end

def secure_compare(left, right)
  return false unless left.bytesize == right.bytesize

  left.bytes.zip(right.bytes).reduce(0) { |result, (a, b)| result | (a ^ b) }.zero?
end

def register_user(params)
  username = params["username"]
  password = params["password"]
  role = params["role"]
  raise ArgumentError unless valid_username?(username)
  raise ArgumentError unless password.is_a?(String) && password.length >= 8
  raise ArgumentError unless %w[dm player].include?(role)
  raise DuplicateUsernameError if USERS.key?(username)

  USERS[username] = { "username" => username, "role" => role, "password" => password_record(password) }
  $storage.save_user(USERS[username])
  { "username" => username, "role" => role }
end

def login_user(params)
  username = params["username"]
  password = params["password"]
  raise ArgumentError unless username.is_a?(String) && password.is_a?(String)

  user = USERS[username]
  raise BadCredentialsError unless user && password_matches?(password, user["password"])

  { "username" => username, "token" => "session-#{username}" }
end

def create_monster(params)
  slug = params["slug"]
  name = params["name"]
  cr = params["cr"]
  armor_class = params["armor_class"]
  hit_points = params["hit_points"]
  tags = params["tags"]
  raise ArgumentError unless valid_slug?(slug)
  raise ArgumentError unless non_empty_string?(name) && non_empty_string?(cr)
  raise ArgumentError unless integer_value?(armor_class) && integer_value?(hit_points)
  raise ArgumentError unless tags.is_a?(Array) && tags.all? { |tag| non_empty_string?(tag) }
  raise DuplicateSlugError if MONSTERS.key?(slug)

  monster = {
    "slug" => slug,
    "name" => name,
    "cr" => cr,
    "armor_class" => armor_class,
    "hit_points" => hit_points,
    "tags" => tags
  }
  MONSTERS[slug] = monster
  $storage.save_monster(monster)
  monster_response(monster)
end

def monster_response(monster)
  {
    "slug" => monster["slug"],
    "name" => monster["name"],
    "cr" => monster["cr"],
    "armor_class" => monster["armor_class"],
    "hit_points" => monster["hit_points"]
  }
end

def create_item(params)
  slug = params["slug"]
  name = params["name"]
  type = params["type"]
  rarity = params["rarity"]
  cost_gp = params["cost_gp"]
  raise ArgumentError unless valid_slug?(slug)
  raise ArgumentError unless [name, type, rarity].all? { |value| non_empty_string?(value) }
  raise ArgumentError unless integer_value?(cost_gp)
  raise DuplicateSlugError if ITEMS.key?(slug)

  item = {
    "slug" => slug,
    "name" => name,
    "type" => type,
    "rarity" => rarity,
    "cost_gp" => cost_gp
  }
  ITEMS[slug] = item
  $storage.save_item(item)
  item
end

def create_campaign(params)
  id = params["id"]
  name = params["name"]
  dm = params["dm"]
  raise ArgumentError unless [id, name, dm].all? { |value| non_empty_string?(value) }
  raise DuplicateIdError if CAMPAIGNS.key?(id)

  campaign = {
    "id" => id,
    "name" => name,
    "dm" => dm,
    "characters" => [],
    "events" => []
  }
  CAMPAIGNS[id] = campaign
  $storage.save_campaign(campaign)
  campaign_response(campaign)
end

def campaign_response(campaign)
  {
    "id" => campaign["id"],
    "name" => campaign["name"],
    "dm" => campaign["dm"]
  }
end

def add_campaign_character(campaign, params)
  id = params["id"]
  name = params["name"]
  level = params["level"]
  character_class = params["class"]
  raise ArgumentError unless [id, name, character_class].all? { |value| non_empty_string?(value) }
  raise ArgumentError unless integer_value?(level)
  raise DuplicateIdError if campaign["characters"].any? { |character| character["id"] == id }

  character = {
    "id" => id,
    "name" => name,
    "level" => level,
    "class" => character_class
  }
  campaign["characters"] << character
  $storage.save_campaign(campaign)
  character
end

def add_campaign_event(campaign, params)
  id = params["id"]
  kind = params["kind"]
  summary = params["summary"]
  raise ArgumentError unless [id, kind, summary].all? { |value| non_empty_string?(value) }
  raise DuplicateIdError if campaign["events"].any? { |event| event["id"] == id }

  event = {
    "id" => id,
    "kind" => kind,
    "summary" => summary
  }
  campaign["events"] << event
  $storage.save_campaign(campaign)
  {
    "id" => id,
    "kind" => kind
  }
end

def campaign_state(campaign)
  campaign_response(campaign).merge(
    "characters" => campaign["characters"],
    "log_count" => campaign["events"].length
  )
end

def find_campaign!(campaign_id)
  raise ArgumentError unless non_empty_string?(campaign_id)

  campaign = CAMPAIGNS[campaign_id]
  raise KeyError unless campaign

  campaign
end

def dm_encounter_builder(params)
  campaign_id = params["campaign_id"]
  find_campaign!(campaign_id)

  party = params["party"]
  monster_slugs = params["monster_slugs"]
  raise ArgumentError unless party.is_a?(Array) && monster_slugs.is_a?(Array) && !monster_slugs.empty?

  monsters_by_cr = Hash.new(0)
  monster_slugs.each do |slug|
    raise ArgumentError unless valid_slug?(slug)

    monster = MONSTERS[slug]
    raise KeyError unless monster

    monsters_by_cr[monster["cr"]] += 1
  end

  xp = adjusted_xp(
    "party" => party,
    "monsters" => monsters_by_cr.map { |cr, count| { "cr" => cr, "count" => count } }
  )

  {
    "campaign_id" => campaign_id,
    "base_xp" => xp["base_xp"],
    "adjusted_xp" => xp["adjusted_xp"],
    "difficulty" => xp["difficulty"],
    "monster_count" => xp["monster_count"],
    "recommendation" => encounter_recommendation(xp["difficulty"])
  }
end

def encounter_recommendation(difficulty)
  case difficulty
  when "trivial", "easy" then "safe warm-up"
  when "medium" then "balanced challenge"
  when "hard" then "dangerous fight"
  else "deadly threat"
  end
end

def dm_loot_parcel(params)
  campaign_id = params["campaign_id"]
  find_campaign!(campaign_id)

  tier = params["tier"]
  seed = params["seed"]
  raise ArgumentError unless tier == 1 && integer_value?(seed)

  {
    "campaign_id" => campaign_id,
    "coins_gp" => 75,
    "items" => [{ "slug" => "healing-potion", "quantity" => 2 }]
  }
end

def dm_session_recap(params)
  campaign_id = params["campaign_id"]
  campaign = find_campaign!(campaign_id)
  latest_event = campaign["events"].last
  raise ArgumentError unless latest_event

  {
    "campaign_id" => campaign_id,
    "summary" => latest_event["summary"],
    "open_threads" => ["Resolve goblin trail ambush"]
  }
end

def dice_stats(params)
  expression = params["expression"]
  match = expression.is_a?(String) && expression.match(/\A(\d+)d(\d+)(?:([+-])(\d+))?\z/)
  raise ArgumentError unless match

  count = match[1].to_i
  sides = match[2].to_i
  raise ArgumentError unless count.positive? && sides.positive?

  modifier = match[4] ? match[4].to_i : 0
  modifier = -modifier if match[3] == "-"
  average = (count * (sides + 1) / 2.0) + modifier
  average = average.to_i if average == average.to_i

  {
    "dice_count" => count,
    "sides" => sides,
    "modifier" => modifier,
    "min" => count + modifier,
    "max" => (count * sides) + modifier,
    "average" => average
  }
end

def ability_check(params)
  roll = params["roll"]
  modifier = params["modifier"]
  dc = params["dc"]
  raise ArgumentError unless [roll, modifier, dc].all? { |value| integer_value?(value) }

  total = roll + modifier
  {
    "total" => total,
    "success" => total >= dc,
    "margin" => total - dc
  }
end

def ability_modifier_for(score)
  raise ArgumentError unless integer_in_range?(score, 1..30)

  (score - 10) / 2
end

def character_ability_modifier(params)
  score = params["score"]
  {
    "score" => score,
    "modifier" => ability_modifier_for(score)
  }
end

def proficiency_bonus_for(level)
  raise ArgumentError unless integer_in_range?(level, 1..20)

  2 + ((level - 1) / 4)
end

def character_proficiency(params)
  level = params["level"]
  {
    "level" => level,
    "proficiency_bonus" => proficiency_bonus_for(level)
  }
end

def character_derived_stats(params)
  level = params["level"]
  abilities = params["abilities"]
  armor = params["armor"]
  raise ArgumentError unless abilities.is_a?(Hash) && armor.is_a?(Hash)

  modifiers = {}
  ABILITY_NAMES.each do |name|
    modifiers[name] = ability_modifier_for(abilities[name])
  end

  armor_base = armor["base"]
  shield = armor["shield"]
  dex_cap = armor["dex_cap"]
  raise ArgumentError unless integer_value?(armor_base) && [true, false].include?(shield) && integer_value?(dex_cap)

  proficiency_bonus = proficiency_bonus_for(level)
  {
    "level" => level,
    "proficiency_bonus" => proficiency_bonus,
    "hp_max" => level * (6 + modifiers["con"]),
    "armor_class" => armor_base + [modifiers["dex"], dex_cap].min + (shield ? 2 : 0),
    "modifiers" => modifiers
  }
end

def monster_multiplier(count)
  case count
  when 1 then 1
  when 2 then 1.5
  when 3..6 then 2
  when 7..10 then 2.5
  when 11..14 then 3
  else 4
  end
end

def adjusted_xp(params)
  party = params["party"]
  monsters = params["monsters"]
  raise ArgumentError unless party.is_a?(Array) && monsters.is_a?(Array)

  thresholds = { "easy" => 0, "medium" => 0, "hard" => 0, "deadly" => 0 }
  party.each do |member|
    level = member.is_a?(Hash) && member["level"]
    level_thresholds = LEVEL_THRESHOLDS[level]
    raise ArgumentError unless level_thresholds

    thresholds.each_key { |key| thresholds[key] += level_thresholds[key] }
  end

  base_xp = 0
  monster_count = 0
  monsters.each do |monster|
    raise ArgumentError unless monster.is_a?(Hash)

    cr = monster["cr"]
    count = monster["count"]
    xp = CR_XP[cr]
    raise ArgumentError unless xp && integer_value?(count) && count.positive?

    base_xp += xp * count
    monster_count += count
  end

  multiplier = monster_count.zero? ? 1 : monster_multiplier(monster_count)
  adjusted = base_xp * multiplier
  adjusted = adjusted.to_i if adjusted == adjusted.to_i
  difficulty = "trivial"
  %w[easy medium hard deadly].each do |name|
    difficulty = name if adjusted >= thresholds[name]
  end

  {
    "base_xp" => base_xp,
    "monster_count" => monster_count,
    "multiplier" => multiplier,
    "adjusted_xp" => adjusted,
    "difficulty" => difficulty,
    "thresholds" => thresholds
  }
end

def phb_spell_slots(params)
  character_class = params["class"]
  level = params["level"]
  raise ArgumentError unless character_class == "wizard" && level == 5

  {
    "class" => character_class,
    "level" => level,
    "slots" => { "1" => 4, "2" => 3, "3" => 2 }
  }
end

def phb_long_rest(params)
  level = params["level"]
  hp_max = params["hp_max"]
  hit_dice_spent = params["hit_dice_spent"]
  exhaustion_level = params["exhaustion_level"]
  raise ArgumentError unless [level, params["hp_current"], hp_max, hit_dice_spent, exhaustion_level].all? { |value| integer_value?(value) }
  raise ArgumentError unless level.positive? && hp_max >= 0 && hit_dice_spent >= 0 && exhaustion_level >= 0

  hit_dice_restored = [level / 2, 1].max
  {
    "hp_current" => hp_max,
    "hit_dice_spent" => [hit_dice_spent - hit_dice_restored, 0].max,
    "exhaustion_level" => [exhaustion_level - 1, 0].max
  }
end

def phb_equipment_load(params)
  strength = params["strength"]
  weight = params["weight"]
  raise ArgumentError unless [strength, weight].all? { |value| integer_value?(value) }
  raise ArgumentError unless strength >= 0 && weight >= 0

  capacity = strength * 15
  {
    "capacity" => capacity,
    "weight" => weight,
    "encumbered" => weight > capacity
  }
end

def initiative_order(params)
  combatants = params["combatants"]
  raise ArgumentError unless combatants.is_a?(Array)

  order = combatants.map do |combatant|
    raise ArgumentError unless combatant.is_a?(Hash)

    name = combatant["name"]
    dex = combatant["dex"]
    roll = combatant["roll"]
    raise ArgumentError unless name.is_a?(String) && integer_value?(dex) && integer_value?(roll)

    { "name" => name, "dex" => dex, "score" => roll + dex }
  end

  {
    "order" => order.sort_by { |combatant| [-combatant["score"], -combatant["dex"], combatant["name"]] }
                    .map { |combatant| { "name" => combatant["name"], "score" => combatant["score"] } }
  }
end

def combat_order(combatants)
  raise ArgumentError unless combatants.is_a?(Array) && !combatants.empty?

  order = combatants.map do |combatant|
    raise ArgumentError unless combatant.is_a?(Hash)

    name = combatant["name"]
    dex = combatant["dex"]
    roll = combatant["roll"]
    raise ArgumentError unless name.is_a?(String) && integer_value?(dex) && integer_value?(roll)

    { "name" => name, "dex" => dex, "score" => roll + dex }
  end

  order.sort_by { |combatant| [-combatant["score"], -combatant["dex"], combatant["name"]] }
       .map { |combatant| { "name" => combatant["name"], "score" => combatant["score"] } }
end

def serialize_combat_session(session)
  active = session["order"][session["turn_index"]]
  {
    "id" => session["id"],
    "round" => session["round"],
    "turn_index" => session["turn_index"],
    "active" => active,
    "order" => session["order"]
  }
end

def create_combat_session(params)
  id = params["id"]
  raise ArgumentError unless id.is_a?(String) && !COMBAT_SESSIONS.key?(id)

  order = combat_order(params["combatants"])
  conditions = {}
  order.each { |combatant| conditions[combatant["name"]] ||= [] }

  session = {
    "id" => id,
    "round" => 1,
    "turn_index" => 0,
    "order" => order,
    "conditions" => conditions
  }
  COMBAT_SESSIONS[id] = session
  $storage.save_combat_session(session)
  serialize_combat_session(session)
end

def combat_conditions_payload(session, include_empty: [])
  session["conditions"].each_with_object({}) do |(name, conditions), payload|
    payload[name] = conditions if !conditions.empty? || include_empty.include?(name)
  end
end

def add_combat_condition(session, params)
  target = params["target"]
  condition = params["condition"]
  duration = params["duration_rounds"]
  raise ArgumentError unless session["conditions"].key?(target)
  raise ArgumentError unless condition.is_a?(String) && integer_value?(duration) && duration.positive?

  session["conditions"][target] << { "condition" => condition, "remaining_rounds" => duration }
  $storage.save_combat_session(session)
  {
    "target" => target,
    "conditions" => session["conditions"][target]
  }
end

def advance_combat_session(session)
  session["turn_index"] += 1
  if session["turn_index"] >= session["order"].length
    session["turn_index"] = 0
    session["round"] += 1
  end

  active_name = session["order"][session["turn_index"]]["name"]
  active_had_conditions = !session["conditions"][active_name].empty?
  session["conditions"][active_name].each do |condition|
    condition["remaining_rounds"] -= 1
  end
  session["conditions"][active_name].reject! { |condition| condition["remaining_rounds"].zero? }
  $storage.save_combat_session(session)

  active = session["order"][session["turn_index"]]
  {
    "id" => session["id"],
    "round" => session["round"],
    "turn_index" => session["turn_index"],
    "active" => active,
    "conditions" => combat_conditions_payload(session, include_empty: active_had_conditions ? [active_name] : [])
  }
end

def route(method, path, body)
  return json_response(200, { "ok" => true }) if method == "GET" && path == "/health"
  return json_response(200, { "driver" => "sqlite", "schema_version" => SCHEMA_VERSION, "initialized" => $storage.initialized? }) if method == "GET" && path == "/v1/storage/status"

  if method == "GET" && (match = path.match(%r{\A/v1/compendium/monsters/([^/]+)\z}))
    monster = MONSTERS[match[1]]
    return json_response(404, { "error" => "not found" }) unless monster

    return json_response(200, monster)
  end

  if method == "GET" && (match = path.match(%r{\A/v1/compendium/items/([^/]+)\z}))
    item = ITEMS[match[1]]
    return json_response(404, { "error" => "not found" }) unless item

    return json_response(200, item)
  end

  if method == "GET" && (match = path.match(%r{\A/v1/campaigns/([^/]+)/state\z}))
    campaign = CAMPAIGNS[match[1]]
    return json_response(404, { "error" => "not found" }) unless campaign

    return json_response(200, campaign_state(campaign))
  end

  unless method == "POST"
    return json_response(path == "/health" ? 405 : 404, { "error" => path == "/health" ? "method not allowed" : "not found" })
  end

  if path == "/v1/storage/reset"
    $storage.reset!
    USERS.clear
    COMBAT_SESSIONS.clear
    MONSTERS.clear
    ITEMS.clear
    CAMPAIGNS.clear
    return json_response(200, { "ok" => true, "schema_version" => SCHEMA_VERSION })
  end

  if path == "/v1/campaigns"
    return json_response(201, create_campaign(parse_json_body(body)))
  end

  if path == "/v1/compendium/monsters"
    return json_response(201, create_monster(parse_json_body(body)))
  end

  if path == "/v1/compendium/items"
    return json_response(201, create_item(parse_json_body(body)))
  end

  if path == "/v1/combat/sessions"
    return json_response(200, create_combat_session(parse_json_body(body)))
  end

  if path == "/v1/auth/register"
    return json_response(201, register_user(parse_json_body(body)))
  end

  if path == "/v1/auth/login"
    return json_response(200, login_user(parse_json_body(body)))
  end

  if path == "/v1/dm/encounter-builder"
    return json_response(200, dm_encounter_builder(parse_json_body(body)))
  end

  if path == "/v1/dm/loot-parcel"
    return json_response(200, dm_loot_parcel(parse_json_body(body)))
  end

  if path == "/v1/dm/session-recap"
    return json_response(200, dm_session_recap(parse_json_body(body)))
  end

  if (match = path.match(%r{\A/v1/combat/sessions/([^/]+)/conditions\z}))
    session = COMBAT_SESSIONS[match[1]]
    return json_response(404, { "error" => "not found" }) unless session

    return json_response(200, add_combat_condition(session, parse_json_body(body)))
  end

  if (match = path.match(%r{\A/v1/combat/sessions/([^/]+)/advance\z}))
    session = COMBAT_SESSIONS[match[1]]
    return json_response(404, { "error" => "not found" }) unless session

    return json_response(200, advance_combat_session(session))
  end

  if (match = path.match(%r{\A/v1/campaigns/([^/]+)/characters\z}))
    campaign = CAMPAIGNS[match[1]]
    return json_response(404, { "error" => "not found" }) unless campaign

    return json_response(201, add_campaign_character(campaign, parse_json_body(body)))
  end

  if (match = path.match(%r{\A/v1/campaigns/([^/]+)/events\z}))
    campaign = CAMPAIGNS[match[1]]
    return json_response(404, { "error" => "not found" }) unless campaign

    return json_response(201, add_campaign_event(campaign, parse_json_body(body)))
  end

  params = parse_json_body(body)
  response = case path
             when "/v1/dice/stats" then dice_stats(params)
             when "/v1/checks/ability" then ability_check(params)
             when "/v1/characters/ability-modifier" then character_ability_modifier(params)
             when "/v1/characters/proficiency" then character_proficiency(params)
             when "/v1/characters/derived-stats" then character_derived_stats(params)
             when "/v1/encounters/adjusted-xp" then adjusted_xp(params)
             when "/v1/initiative/order" then initiative_order(params)
             when "/v1/phb/spell-slots" then phb_spell_slots(params)
             when "/v1/phb/rests/long" then phb_long_rest(params)
             when "/v1/phb/equipment-load" then phb_equipment_load(params)
             else
               return json_response(404, { "error" => "not found" })
             end

  json_response(200, response)
rescue BadCredentialsError
  json_response(401, { "error" => "bad credentials" })
rescue DuplicateUsernameError
  json_response(409, { "error" => "duplicate username" })
rescue DuplicateSlugError
  json_response(409, { "error" => "duplicate slug" })
rescue DuplicateIdError
  json_response(409, { "error" => "duplicate id" })
rescue KeyError
  json_response(404, { "error" => "not found" })
rescue ArgumentError
  json_response(400, { "error" => "bad request" })
end

def read_request(client)
  request_line = client.gets&.delete_suffix("\n")&.delete_suffix("\r")
  return unless request_line

  method, raw_path, = request_line.split(" ", 3)
  headers = {}
  while (line = client.gets)
    line = line.delete_suffix("\n").delete_suffix("\r")
    break if line.empty?

    key, value = line.split(":", 2)
    headers[key.downcase] = value.strip if key && value
  end

  length = headers.fetch("content-length", "0").to_i
  body = length.positive? ? client.read(length) : ""
  path = raw_path.to_s.split("?", 2).first
  [method, path, body]
end

$storage = SQLiteStorage.new(DB_PATH)
USERS.replace($storage.load_users)
COMBAT_SESSIONS.replace($storage.load_combat_sessions)
MONSTERS.replace($storage.load_monsters)
ITEMS.replace($storage.load_items)
CAMPAIGNS.replace($storage.load_campaigns)

port = Integer(ENV.fetch("PORT"))
server = TCPServer.new("127.0.0.1", port)

trap("INT") do
  $storage.close
  server.close
end
trap("TERM") do
  $storage.close
  server.close
end

loop do
  client = server.accept
  request = read_request(client)
  client.write(request ? route(*request) : json_response(400, { "error" => "bad request" }))
rescue IOError, Errno::EBADF
  break
rescue StandardError
  client&.write(json_response(400, { "error" => "bad request" }))
ensure
  client&.close
end
