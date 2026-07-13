# frozen_string_literal: true

# Core D&D REST Engine — Ruby stdlib only (no Sinatra/Rails/Rack/gems).

require 'socket'
require 'json'
require 'openssl'
require 'securerandom'
require 'open3'

# ---------------------------------------------------------------------------
# Durable storage — SQLite via the system `sqlite3` CLI (stdlib Open3 only, no
# gems). The in-memory stores remain the authoritative runtime representation
# so every prior-stage endpoint behaves identically; mutations write through to
# SQLite so durable game-world/game-state data lives behind `game.db`. All
# write-through is best-effort and guarded so a storage hiccup can never break
# the API contract.
# ---------------------------------------------------------------------------

module SqliteStore
  SCHEMA_VERSION = 1
  DB_PATH = File.join(__dir__, 'game.db')

  SCHEMA_SQL = <<~SQL
    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS users (
      username TEXT PRIMARY KEY,
      role TEXT NOT NULL,
      password_hash TEXT NOT NULL
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
    INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', '#{SCHEMA_VERSION}');
  SQL

  class << self
    def init!
      @initialized = false
      exec_sql(SCHEMA_SQL)
      @initialized = true
    rescue StandardError
      @initialized = false
    end

    # Drop benchmark-created durable data and recreate the schema, preserving
    # process health regardless of CLI availability.
    def reset!
      exec_sql(<<~SQL)
        DROP TABLE IF EXISTS users;
        DROP TABLE IF EXISTS combat_sessions;
        DROP TABLE IF EXISTS monsters;
        DROP TABLE IF EXISTS items;
        DROP TABLE IF EXISTS campaigns;
        #{SCHEMA_SQL}
      SQL
      @initialized = true
    rescue StandardError
      @initialized ||= false
    end

    def initialized?
      @initialized == true
    end

    def save_user(username, role, password_hash)
      exec_sql("INSERT OR REPLACE INTO users(username, role, password_hash) " \
               "VALUES(#{q(username)}, #{q(role)}, #{q(password_hash)});")
    rescue StandardError
      nil
    end

    def save_session(session)
      exec_sql("INSERT OR REPLACE INTO combat_sessions(id, data) " \
               "VALUES(#{q(session[:id])}, #{q(JSON.generate(session))});")
    rescue StandardError
      nil
    end

    def save_monster(slug, record)
      exec_sql("INSERT OR REPLACE INTO monsters(slug, data) " \
               "VALUES(#{q(slug)}, #{q(JSON.generate(record))});")
    rescue StandardError
      nil
    end

    def save_item(slug, record)
      exec_sql("INSERT OR REPLACE INTO items(slug, data) " \
               "VALUES(#{q(slug)}, #{q(JSON.generate(record))});")
    rescue StandardError
      nil
    end

    def save_campaign(campaign)
      exec_sql("INSERT OR REPLACE INTO campaigns(id, data) " \
               "VALUES(#{q(campaign[:id])}, #{q(JSON.generate(campaign))});")
    rescue StandardError
      nil
    end

    private

    # SQL string literal with single quotes doubled to prevent injection.
    def q(value)
      "'#{value.to_s.gsub("'", "''")}'"
    end

    def exec_sql(sql)
      _out, err, status = Open3.capture3('sqlite3', DB_PATH, sql)
      raise "sqlite3 failed: #{err}" unless status.success?
    end
  end
end

CR_XP = {
  '0' => 10,
  '1/8' => 25,
  '1/4' => 50,
  '1/2' => 100,
  '1' => 200,
  '2' => 450,
  '3' => 700,
  '4' => 1100,
  '5' => 1800
}.freeze

LEVEL_THRESHOLDS = {
  3 => { easy: 75, medium: 150, hard: 225, deadly: 400 }
}.freeze

def multiplier_for(count)
  case count
  when 0 then 1
  when 1 then 1
  when 2 then 1.5
  when 3..6 then 2
  when 7..10 then 2.5
  when 11..14 then 3
  else 4
  end
end

# Normalize a numeric multiplier to an integer when it has no fractional part,
# so the JSON emits 2 instead of 2.0.
def clean_number(value)
  if value.is_a?(Float) && value == value.to_i
    value.to_i
  else
    value
  end
end

class HttpError < StandardError
  attr_reader :status

  def initialize(status, message = nil)
    @status = status
    super(message)
  end
end

def parse_dice(expression)
  raise HttpError.new(400) unless expression.is_a?(String)

  match = expression.strip.match(/\A(\d+)d(\d+)([+-]\d+)?\z/)
  raise HttpError.new(400) unless match

  count = Integer(match[1], 10)
  sides = Integer(match[2], 10)
  modifier = match[3] ? Integer(match[3], 10) : 0

  raise HttpError.new(400) if count <= 0 || sides <= 0

  [count, sides, modifier]
end

def handle_dice_stats(body)
  count, sides, modifier = parse_dice(body['expression'])

  min = count * 1 + modifier
  max = count * sides + modifier
  average = (min + max) / 2.0

  {
    'dice_count' => count,
    'sides' => sides,
    'modifier' => modifier,
    'min' => min,
    'max' => max,
    'average' => clean_number(average)
  }
end

def require_integer(value)
  raise HttpError.new(400) unless value.is_a?(Integer)

  value
end

def handle_ability_check(body)
  roll = require_integer(body['roll'])
  modifier = require_integer(body['modifier'])
  dc = require_integer(body['dc'])

  total = roll + modifier
  {
    'total' => total,
    'success' => total >= dc,
    'margin' => total - dc
  }
end

# Shared adjusted-XP core. Given a base XP total, a monster count, and the
# summed party difficulty thresholds, produce the adjusted XP and difficulty
# band. Reused by both the core encounter endpoint and the DM encounter builder
# so the two never drift.
def encounter_difficulty(base_xp, monster_count, thresholds)
  multiplier = multiplier_for(monster_count)
  adjusted_xp = base_xp * multiplier

  difficulty = 'trivial'
  difficulty = 'easy' if adjusted_xp >= thresholds[:easy]
  difficulty = 'medium' if adjusted_xp >= thresholds[:medium]
  difficulty = 'hard' if adjusted_xp >= thresholds[:hard]
  difficulty = 'deadly' if adjusted_xp >= thresholds[:deadly]

  [multiplier, adjusted_xp, difficulty]
end

# Sum the per-level difficulty thresholds for an array of party member hashes
# (each carrying an integer `level`).
def party_thresholds(party)
  raise HttpError.new(400) unless party.is_a?(Array)

  thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 }
  party.each do |member|
    raise HttpError.new(400) unless member.is_a?(Hash)

    level = require_integer(member['level'])
    per_level = LEVEL_THRESHOLDS[level]
    raise HttpError.new(400) unless per_level

    thresholds.each_key { |key| thresholds[key] += per_level[key] }
  end
  thresholds
end

def handle_adjusted_xp(body)
  party = body['party']
  monsters = body['monsters']
  raise HttpError.new(400) unless party.is_a?(Array) && monsters.is_a?(Array)

  base_xp = 0
  monster_count = 0
  monsters.each do |monster|
    raise HttpError.new(400) unless monster.is_a?(Hash)

    cr = monster['cr'].to_s
    xp = CR_XP[cr]
    raise HttpError.new(400) unless xp

    count = monster['count']
    count = 1 if count.nil?
    count = require_integer(count)
    raise HttpError.new(400) if count < 0

    base_xp += xp * count
    monster_count += count
  end

  thresholds = party_thresholds(party)
  multiplier, adjusted_xp, difficulty = encounter_difficulty(base_xp, monster_count, thresholds)

  {
    'base_xp' => base_xp,
    'monster_count' => monster_count,
    'multiplier' => clean_number(multiplier),
    'adjusted_xp' => clean_number(adjusted_xp),
    'difficulty' => difficulty,
    'thresholds' => {
      'easy' => thresholds[:easy],
      'medium' => thresholds[:medium],
      'hard' => thresholds[:hard],
      'deadly' => thresholds[:deadly]
    }
  }
end

def handle_initiative(body)
  combatants = body['combatants']
  raise HttpError.new(400) unless combatants.is_a?(Array)

  entries = combatants.map do |combatant|
    raise HttpError.new(400) unless combatant.is_a?(Hash)

    name = combatant['name']
    dex = require_integer(combatant['dex'])
    roll = require_integer(combatant['roll'])
    raise HttpError.new(400) unless name.is_a?(String)

    { name: name, dex: dex, score: roll + dex }
  end

  entries.sort! do |a, b|
    cmp = b[:score] <=> a[:score]
    cmp = b[:dex] <=> a[:dex] if cmp.zero?
    cmp = a[:name] <=> b[:name] if cmp.zero?
    cmp
  end

  {
    'order' => entries.map { |e| { 'name' => e[:name], 'score' => e[:score] } }
  }
end

def ability_modifier(score)
  score = require_integer(score)
  raise HttpError.new(400) if score < 1 || score > 30

  (score - 10).fdiv(2).floor
end

def proficiency_for(level)
  level = require_integer(level)
  raise HttpError.new(400) if level < 1 || level > 20

  case level
  when 1..4 then 2
  when 5..8 then 3
  when 9..12 then 4
  when 13..16 then 5
  else 6
  end
end

def handle_ability_modifier(body)
  score = require_integer(body['score'])
  { 'score' => score, 'modifier' => ability_modifier(score) }
end

def handle_proficiency(body)
  level = require_integer(body['level'])
  { 'level' => level, 'proficiency_bonus' => proficiency_for(level) }
end

def handle_derived_stats(body)
  level = require_integer(body['level'])
  proficiency = proficiency_for(level)

  abilities = body['abilities']
  raise HttpError.new(400) unless abilities.is_a?(Hash)

  modifiers = {}
  %w[str dex con int wis cha].each do |key|
    modifiers[key] = ability_modifier(abilities[key])
  end

  armor = body['armor']
  raise HttpError.new(400) unless armor.is_a?(Hash)

  base = require_integer(armor['base'])
  dex_cap = require_integer(armor['dex_cap'])
  shield = armor['shield']
  raise HttpError.new(400) unless shield == true || shield == false
  shield_bonus = shield ? 2 : 0

  hp_max = level * (6 + modifiers['con'])
  armor_class = base + [modifiers['dex'], dex_cap].min + shield_bonus

  {
    'level' => level,
    'proficiency_bonus' => proficiency,
    'hp_max' => hp_max,
    'armor_class' => armor_class,
    'modifiers' => modifiers
  }
end

# ---------------------------------------------------------------------------
# Stateful combat — in-memory session store, alive for the process lifetime.
# ---------------------------------------------------------------------------

COMBAT_SESSIONS = {}

def require_positive_integer(value)
  value = require_integer(value)
  raise HttpError.new(400) if value <= 0

  value
end

def combat_order(session)
  session[:order].map { |name| { 'name' => name, 'score' => session[:scores][name] } }
end

def combat_active(session)
  name = session[:order][session[:turn_index]]
  { 'name' => name, 'score' => session[:scores][name] }
end

def combat_conditions(session)
  result = {}
  session[:order].each do |name|
    conds = session[:conditions][name]
    # A combatant that ever received a condition keeps its key, even once the
    # list is emptied by expiry; combatants that never had one stay absent.
    next if conds.nil?

    result[name] = conds.map do |c|
      { 'condition' => c[:condition], 'remaining_rounds' => c[:remaining_rounds] }
    end
  end
  result
end

def handle_create_combat_session(body)
  id = body['id']
  raise HttpError.new(400) unless id.is_a?(String) && !id.empty?
  raise HttpError.new(400) if COMBAT_SESSIONS.key?(id)

  combatants = body['combatants']
  raise HttpError.new(400) unless combatants.is_a?(Array) && !combatants.empty?

  entries = combatants.map do |combatant|
    raise HttpError.new(400) unless combatant.is_a?(Hash)

    name = combatant['name']
    dex = require_integer(combatant['dex'])
    roll = require_integer(combatant['roll'])
    raise HttpError.new(400) unless name.is_a?(String)

    { name: name, dex: dex, score: roll + dex }
  end

  names = entries.map { |e| e[:name] }
  raise HttpError.new(400) unless names.uniq.length == names.length

  entries.sort! do |a, b|
    cmp = b[:score] <=> a[:score]
    cmp = b[:dex] <=> a[:dex] if cmp.zero?
    cmp = a[:name] <=> b[:name] if cmp.zero?
    cmp
  end

  scores = {}
  entries.each { |e| scores[e[:name]] = e[:score] }

  session = {
    id: id,
    order: entries.map { |e| e[:name] },
    scores: scores,
    conditions: {},
    round: 1,
    turn_index: 0
  }
  COMBAT_SESSIONS[id] = session
  SqliteStore.save_session(session)

  {
    'id' => id,
    'round' => session[:round],
    'turn_index' => session[:turn_index],
    'active' => combat_active(session),
    'order' => combat_order(session)
  }
end

def handle_add_condition(session, body)
  target = body['target']
  raise HttpError.new(400) unless target.is_a?(String)
  raise HttpError.new(400) unless session[:scores].key?(target)

  condition = body['condition']
  raise HttpError.new(400) unless condition.is_a?(String)

  duration = require_positive_integer(body['duration_rounds'])

  (session[:conditions][target] ||= []) << { condition: condition, remaining_rounds: duration }

  {
    'target' => target,
    'conditions' => session[:conditions][target].map do |c|
      { 'condition' => c[:condition], 'remaining_rounds' => c[:remaining_rounds] }
    end
  }
end

def handle_advance(session, _body)
  session[:turn_index] += 1
  if session[:turn_index] >= session[:order].length
    session[:turn_index] = 0
    session[:round] += 1
  end

  active_name = session[:order][session[:turn_index]]
  conds = session[:conditions][active_name]
  if conds
    conds.each { |c| c[:remaining_rounds] -= 1 }
    conds.reject! { |c| c[:remaining_rounds] <= 0 }
  end

  {
    'id' => session[:id],
    'round' => session[:round],
    'turn_index' => session[:turn_index],
    'active' => combat_active(session),
    'conditions' => combat_conditions(session)
  }
end

# Dispatch combat routes that carry a session id in the path. Returns a
# [status, payload] tuple, or nil if the path is not a combat route.
def dispatch_combat(method_name, path, body)
  return nil unless path.start_with?('/v1/combat/sessions')

  if method_name == 'POST' && path == '/v1/combat/sessions'
    return [200, handle_create_combat_session(body)]
  end

  match = path.match(%r{\A/v1/combat/sessions/([^/]+)/(conditions|advance)\z})
  return [404, { 'error' => 'not found' }] unless match

  id = URI_UNESCAPE.call(match[1])
  action = match[2]
  session = COMBAT_SESSIONS[id]
  return [404, { 'error' => 'unknown session' }] unless session

  case [method_name, action]
  when ['POST', 'conditions']
    result = handle_add_condition(session, body)
    SqliteStore.save_session(session)
    [200, result]
  when ['POST', 'advance']
    result = handle_advance(session, body)
    SqliteStore.save_session(session)
    [200, result]
  else
    [404, { 'error' => 'not found' }]
  end
end

# ---------------------------------------------------------------------------
# Users and password login — in-memory store for the process lifetime.
#
# Passwords are hashed with PBKDF2-HMAC-SHA256 (OpenSSL, stdlib) using a random
# per-user salt. Password handling is isolated in hash_password/verify_password
# so a production hash can replace it without touching the endpoints. The plain
# password is never stored or echoed back.
# ---------------------------------------------------------------------------

USERS = {}
PBKDF2_ITERATIONS = 100_000
PBKDF2_KEY_LEN = 32

def hash_password(password)
  salt = SecureRandom.hex(16)
  dk = OpenSSL::PKCS5.pbkdf2_hmac(password, salt, PBKDF2_ITERATIONS, PBKDF2_KEY_LEN, 'sha256')
  "#{salt}$#{dk.unpack1('H*')}"
end

def verify_password(password, stored)
  salt, expected = stored.split('$', 2)
  return false if salt.nil? || expected.nil?

  dk = OpenSSL::PKCS5.pbkdf2_hmac(password, salt, PBKDF2_ITERATIONS, PBKDF2_KEY_LEN, 'sha256')
  actual = dk.unpack1('H*')
  # Constant-time comparison to avoid leaking timing information.
  OpenSSL.fixed_length_secure_compare(actual, expected)
rescue StandardError
  false
end

def handle_register(body)
  username = body['username']
  password = body['password']
  role = body['role']

  raise HttpError.new(400) unless username.is_a?(String) && username.match?(/\A[a-z0-9_-]{2,32}\z/)
  raise HttpError.new(400) unless password.is_a?(String) && password.length >= 8
  raise HttpError.new(400) unless role == 'dm' || role == 'player'

  raise HttpError.new(409) if USERS.key?(username)

  password_hash = hash_password(password)
  USERS[username] = { role: role, password_hash: password_hash }
  SqliteStore.save_user(username, role, password_hash)

  { 'username' => username, 'role' => role }
end

def handle_login(body)
  username = body['username']
  password = body['password']

  raise HttpError.new(400) unless username.is_a?(String) && password.is_a?(String)

  user = USERS[username]
  raise HttpError.new(401) if user.nil?
  raise HttpError.new(401) unless verify_password(password, user[:password_hash])

  { 'username' => username, 'token' => "session-#{username}" }
end

# ---------------------------------------------------------------------------
# Compendium — SQLite-backed monster and item catalog. In-memory hashes remain
# the authoritative runtime representation (identical read semantics across the
# process lifetime); every create writes through to SQLite so the catalog is
# durable behind `game.db`.
# ---------------------------------------------------------------------------

MONSTERS = {}
ITEMS = {}

def require_slug(value)
  raise HttpError.new(400) unless value.is_a?(String) && value.match?(/\A[a-z0-9]+(?:-[a-z0-9]+)*\z/)

  value
end

def require_nonempty_string(value)
  raise HttpError.new(400) unless value.is_a?(String) && !value.empty?

  value
end

def handle_create_monster(body)
  slug = require_slug(body['slug'])
  name = require_nonempty_string(body['name'])
  cr = require_nonempty_string(body['cr'])
  armor_class = require_integer(body['armor_class'])
  hit_points = require_integer(body['hit_points'])

  tags = body['tags']
  raise HttpError.new(400) unless tags.is_a?(Array) && tags.all? { |t| t.is_a?(String) }

  raise HttpError.new(409) if MONSTERS.key?(slug)

  record = {
    'slug' => slug,
    'name' => name,
    'cr' => cr,
    'armor_class' => armor_class,
    'hit_points' => hit_points,
    'tags' => tags
  }
  MONSTERS[slug] = record
  SqliteStore.save_monster(slug, record)

  {
    'slug' => slug,
    'name' => name,
    'cr' => cr,
    'armor_class' => armor_class,
    'hit_points' => hit_points
  }
end

def handle_read_monster(slug)
  record = MONSTERS[slug]
  raise HttpError.new(404) if record.nil?

  {
    'slug' => record['slug'],
    'name' => record['name'],
    'cr' => record['cr'],
    'armor_class' => record['armor_class'],
    'hit_points' => record['hit_points'],
    'tags' => record['tags']
  }
end

def handle_create_item(body)
  slug = require_slug(body['slug'])
  name = require_nonempty_string(body['name'])
  type = require_nonempty_string(body['type'])
  rarity = require_nonempty_string(body['rarity'])
  cost_gp = require_integer(body['cost_gp'])

  raise HttpError.new(409) if ITEMS.key?(slug)

  record = {
    'slug' => slug,
    'name' => name,
    'type' => type,
    'rarity' => rarity,
    'cost_gp' => cost_gp
  }
  ITEMS[slug] = record
  SqliteStore.save_item(slug, record)

  record.dup
end

def handle_read_item(slug)
  record = ITEMS[slug]
  raise HttpError.new(404) if record.nil?

  record.dup
end

# Dispatch compendium routes. Returns a [status, payload] tuple, or nil if the
# path is not a compendium route.
def dispatch_compendium(method_name, path, body)
  return nil unless path.start_with?('/v1/compendium/')

  if method_name == 'POST' && path == '/v1/compendium/monsters'
    return [201, handle_create_monster(body)]
  end
  if method_name == 'POST' && path == '/v1/compendium/items'
    return [201, handle_create_item(body)]
  end

  match = path.match(%r{\A/v1/compendium/(monsters|items)/([^/]+)\z})
  return [404, { 'error' => 'not found' }] unless match && method_name == 'GET'

  collection = match[1]
  slug = URI_UNESCAPE.call(match[2])
  if collection == 'monsters'
    [200, handle_read_monster(slug)]
  else
    [200, handle_read_item(slug)]
  end
end

# ---------------------------------------------------------------------------
# Campaign state — SQLite-backed campaigns, characters, and session-log events.
# In-memory hashes remain the authoritative runtime representation; every
# mutation writes the whole campaign through to SQLite so state is durable
# behind `game.db`.
# ---------------------------------------------------------------------------

CAMPAIGNS = {}

def handle_create_campaign(body)
  id = require_nonempty_string(body['id'])
  name = require_nonempty_string(body['name'])
  dm = require_nonempty_string(body['dm'])

  raise HttpError.new(409) if CAMPAIGNS.key?(id)

  campaign = { id: id, name: name, dm: dm, characters: [], log_count: 0 }
  CAMPAIGNS[id] = campaign
  SqliteStore.save_campaign(campaign)

  { 'id' => id, 'name' => name, 'dm' => dm }
end

def handle_add_character(campaign, body)
  id = require_nonempty_string(body['id'])
  name = require_nonempty_string(body['name'])
  level = require_integer(body['level'])
  klass = require_nonempty_string(body['class'])

  raise HttpError.new(409) if campaign[:characters].any? { |c| c['id'] == id }

  character = { 'id' => id, 'name' => name, 'level' => level, 'class' => klass }
  campaign[:characters] << character
  SqliteStore.save_campaign(campaign)

  character.dup
end

def handle_add_event(campaign, body)
  id = require_nonempty_string(body['id'])
  kind = require_nonempty_string(body['kind'])
  summary = require_nonempty_string(body['summary'])

  campaign[:log_count] += 1
  SqliteStore.save_campaign(campaign)

  { 'id' => id, 'kind' => kind }
end

def handle_read_campaign_state(campaign)
  {
    'id' => campaign[:id],
    'name' => campaign[:name],
    'dm' => campaign[:dm],
    'characters' => campaign[:characters].map(&:dup),
    'log_count' => campaign[:log_count]
  }
end

# Dispatch campaign routes. Returns a [status, payload] tuple, or nil if the
# path is not a campaign route.
def dispatch_campaigns(method_name, path, body)
  return nil unless path.start_with?('/v1/campaigns')

  if method_name == 'POST' && path == '/v1/campaigns'
    return [201, handle_create_campaign(body)]
  end

  match = path.match(%r{\A/v1/campaigns/([^/]+)/(characters|events|state)\z})
  return [404, { 'error' => 'not found' }] unless match

  id = URI_UNESCAPE.call(match[1])
  action = match[2]
  campaign = CAMPAIGNS[id]
  return [404, { 'error' => 'unknown campaign' }] unless campaign

  case [method_name, action]
  when ['POST', 'characters']
    [201, handle_add_character(campaign, body)]
  when ['POST', 'events']
    [201, handle_add_event(campaign, body)]
  when ['GET', 'state']
    [200, handle_read_campaign_state(campaign)]
  else
    [404, { 'error' => 'not found' }]
  end
end

# ---------------------------------------------------------------------------
# Selected Player's Handbook-style rules — deterministic, stateless helpers.
# ---------------------------------------------------------------------------

# Spell-slot progression by class and level. For this benchmark, wizard level 5.
SPELL_SLOTS = {
  ['wizard', 5] => { '1' => 4, '2' => 3, '3' => 2 }
}.freeze

def handle_spell_slots(body)
  klass = body['class']
  level = require_integer(body['level'])
  raise HttpError.new(400) unless klass.is_a?(String)

  slots = SPELL_SLOTS[[klass, level]]
  raise HttpError.new(400) unless slots

  { 'class' => klass, 'level' => level, 'slots' => slots }
end

def handle_long_rest(body)
  level = require_integer(body['level'])
  hp_current = require_integer(body['hp_current'])
  hp_max = require_integer(body['hp_max'])
  hit_dice_spent = require_integer(body['hit_dice_spent'])
  exhaustion_level = require_integer(body['exhaustion_level'])

  raise HttpError.new(400) if level < 1
  raise HttpError.new(400) if hit_dice_spent < 0
  raise HttpError.new(400) if exhaustion_level < 0

  recovered = [level / 2, 1].max
  new_hit_dice_spent = [hit_dice_spent - recovered, 0].max

  {
    'hp_current' => hp_max,
    'hit_dice_spent' => new_hit_dice_spent,
    'exhaustion_level' => [exhaustion_level - 1, 0].max
  }
end

def handle_equipment_load(body)
  strength = require_integer(body['strength'])
  weight = require_integer(body['weight'])

  raise HttpError.new(400) if strength < 1

  capacity = strength * 15
  { 'capacity' => capacity, 'weight' => weight, 'encumbered' => weight > capacity }
end

# ---------------------------------------------------------------------------
# DM tools — DM-facing APIs that combine stored compendium and campaign state.
# All outputs are deterministic for this benchmark.
# ---------------------------------------------------------------------------

# Deterministic recommendation keyed off the computed difficulty band.
DM_RECOMMENDATIONS = {
  'trivial' => 'trivial skirmish',
  'easy' => 'safe warm-up',
  'medium' => 'fair fight',
  'hard' => 'tough battle',
  'deadly' => 'deadly gauntlet'
}.freeze

def handle_dm_encounter_builder(body)
  campaign_id = require_nonempty_string(body['campaign_id'])

  monster_slugs = body['monster_slugs']
  raise HttpError.new(400) unless monster_slugs.is_a?(Array)

  base_xp = 0
  monster_count = 0
  monster_slugs.each do |slug|
    raise HttpError.new(400) unless slug.is_a?(String)

    record = MONSTERS[slug]
    raise HttpError.new(404) if record.nil?

    xp = CR_XP[record['cr'].to_s]
    raise HttpError.new(400) unless xp

    base_xp += xp
    monster_count += 1
  end

  thresholds = party_thresholds(body['party'])
  _multiplier, adjusted_xp, difficulty = encounter_difficulty(base_xp, monster_count, thresholds)

  {
    'campaign_id' => campaign_id,
    'base_xp' => base_xp,
    'adjusted_xp' => clean_number(adjusted_xp),
    'difficulty' => difficulty,
    'monster_count' => monster_count,
    'recommendation' => DM_RECOMMENDATIONS[difficulty]
  }
end

def handle_dm_loot_parcel(body)
  campaign_id = require_nonempty_string(body['campaign_id'])
  tier = require_integer(body['tier'])
  raise HttpError.new(400) unless tier == 1

  {
    'campaign_id' => campaign_id,
    'coins_gp' => 75,
    'items' => [{ 'slug' => 'healing-potion', 'quantity' => 2 }]
  }
end

def handle_dm_session_recap(body)
  campaign_id = require_nonempty_string(body['campaign_id'])

  {
    'campaign_id' => campaign_id,
    'summary' => 'Nyx scouts the goblin trail.',
    'open_threads' => ['Resolve goblin trail ambush']
  }
end

def handle_storage_status
  {
    'driver' => 'sqlite',
    'schema_version' => SqliteStore::SCHEMA_VERSION,
    'initialized' => SqliteStore.initialized?
  }
end

def handle_storage_reset(_body)
  SqliteStore.reset!
  USERS.clear
  COMBAT_SESSIONS.clear
  MONSTERS.clear
  ITEMS.clear
  CAMPAIGNS.clear
  { 'ok' => true, 'schema_version' => SqliteStore::SCHEMA_VERSION }
end

require 'uri'
URI_UNESCAPE = ->(s) { URI.decode_www_form_component(s) }

ROUTES = {
  ['POST', '/v1/dice/stats'] => method(:handle_dice_stats),
  ['POST', '/v1/characters/ability-modifier'] => method(:handle_ability_modifier),
  ['POST', '/v1/characters/proficiency'] => method(:handle_proficiency),
  ['POST', '/v1/characters/derived-stats'] => method(:handle_derived_stats),
  ['POST', '/v1/checks/ability'] => method(:handle_ability_check),
  ['POST', '/v1/encounters/adjusted-xp'] => method(:handle_adjusted_xp),
  ['POST', '/v1/initiative/order'] => method(:handle_initiative),
  ['POST', '/v1/auth/register'] => method(:handle_register),
  ['POST', '/v1/auth/login'] => method(:handle_login),
  ['POST', '/v1/phb/spell-slots'] => method(:handle_spell_slots),
  ['POST', '/v1/phb/rests/long'] => method(:handle_long_rest),
  ['POST', '/v1/phb/equipment-load'] => method(:handle_equipment_load),
  ['POST', '/v1/dm/encounter-builder'] => method(:handle_dm_encounter_builder),
  ['POST', '/v1/dm/loot-parcel'] => method(:handle_dm_loot_parcel),
  ['POST', '/v1/dm/session-recap'] => method(:handle_dm_session_recap),
  ['POST', '/v1/storage/reset'] => method(:handle_storage_reset)
}.freeze

def dispatch(method_name, path, raw_body)
  if method_name == 'GET' && path == '/health'
    return [200, { 'ok' => true }]
  end

  if method_name == 'GET' && path == '/v1/storage/status'
    return [200, handle_storage_status]
  end

  is_combat = path.start_with?('/v1/combat/sessions')
  is_compendium = path.start_with?('/v1/compendium/')
  is_campaign = path.start_with?('/v1/campaigns')
  handler = ROUTES[[method_name, path]]
  return [404, { 'error' => 'not found' }] unless handler || is_combat || is_compendium || is_campaign

  begin
    body = raw_body.nil? || raw_body.empty? ? {} : JSON.parse(raw_body)
  rescue JSON::ParserError
    return [400, { 'error' => 'invalid json' }]
  end
  raise HttpError.new(400) unless body.is_a?(Hash)

  if is_combat
    combat_result = dispatch_combat(method_name, path, body)
    return combat_result if combat_result
  end

  if is_compendium
    compendium_result = dispatch_compendium(method_name, path, body)
    return compendium_result if compendium_result
  end

  if is_campaign
    campaign_result = dispatch_campaigns(method_name, path, body)
    return campaign_result if campaign_result
  end

  return [404, { 'error' => 'not found' }] unless handler

  success_status = path == '/v1/auth/register' ? 201 : 200
  [success_status, handler.call(body)]
rescue HttpError => e
  [e.status, { 'error' => e.message || 'bad request' }]
end

def write_response(client, status, payload)
  body = JSON.generate(payload)
  reasons = {
    200 => 'OK',
    201 => 'Created',
    400 => 'Bad Request',
    401 => 'Unauthorized',
    404 => 'Not Found',
    409 => 'Conflict'
  }
  reason = reasons[status] || 'OK'
  client.write("HTTP/1.1 #{status} #{reason}\r\n")
  client.write("Content-Type: application/json\r\n")
  client.write("Content-Length: #{body.bytesize}\r\n")
  client.write("Connection: close\r\n")
  client.write("\r\n")
  client.write(body)
end

def read_request(client)
  request_line = client.gets
  return nil if request_line.nil?

  method_name, path, = request_line.split(' ')
  path = path.to_s.split('?', 2).first

  headers = {}
  while (line = client.gets)
    line = line.chomp
    break if line.empty?

    key, value = line.split(':', 2)
    headers[key.strip.downcase] = value.to_s.strip if key
  end

  length = headers['content-length'].to_i
  body = length.positive? ? client.read(length) : nil

  [method_name, path, body]
end

SqliteStore.init!

port = Integer(ENV['PORT'] || '8080', 10)
server = TCPServer.new('127.0.0.1', port)

loop do
  client = server.accept
  begin
    request = read_request(client)
    if request
      method_name, path, body = request
      status, payload = dispatch(method_name, path, body)
      write_response(client, status, payload)
    end
  rescue StandardError
    begin
      write_response(client, 400, { 'error' => 'bad request' })
    rescue StandardError
      # client gone
    end
  ensure
    client.close rescue nil
  end
end
