# Minimal single-file Rails API application for the D&D REST engine.
require 'rails'
require 'action_controller/railtie'
require 'json'
require 'digest'
require 'securerandom'
require 'openssl'
require 'sqlite3'

class DndApp < Rails::Application
  config.eager_load = false
  config.consider_all_requests_local = true
  config.hosts.clear
  config.secret_key_base = 'dnd-rest-benchmark-secret-key-base'
  config.logger = Logger.new($stdout)
  config.log_level = :warn
  config.api_only = true

  routes.append do
    get  '/health',                  to: 'dnd#health'
    post '/v1/dice/stats',           to: 'dnd#dice_stats'
    post '/v1/checks/ability',       to: 'dnd#ability_check'
    post '/v1/encounters/adjusted-xp', to: 'dnd#adjusted_xp'
    post '/v1/initiative/order',     to: 'dnd#initiative_order'
    post '/v1/characters/ability-modifier', to: 'dnd#ability_modifier'
    post '/v1/characters/proficiency',      to: 'dnd#proficiency'
    post '/v1/characters/derived-stats',    to: 'dnd#derived_stats'
    post '/v1/combat/sessions',                   to: 'dnd#create_combat_session'
    post '/v1/combat/sessions/:id/conditions',    to: 'dnd#add_condition'
    post '/v1/combat/sessions/:id/advance',       to: 'dnd#advance_turn'
    post '/v1/auth/register',                      to: 'dnd#register'
    post '/v1/auth/login',                         to: 'dnd#login'
    get  '/v1/storage/status',                     to: 'dnd#storage_status'
    post '/v1/storage/reset',                       to: 'dnd#storage_reset'
    post '/v1/compendium/monsters',                 to: 'dnd#create_monster'
    get  '/v1/compendium/monsters/:slug',           to: 'dnd#read_monster'
    post '/v1/compendium/items',                    to: 'dnd#create_item'
    get  '/v1/compendium/items/:slug',              to: 'dnd#read_item'
    post '/v1/campaigns',                           to: 'dnd#create_campaign'
    post '/v1/campaigns/:id/characters',            to: 'dnd#add_character'
    post '/v1/campaigns/:id/events',                to: 'dnd#add_event'
    get  '/v1/campaigns/:id/state',                 to: 'dnd#campaign_state'
    post '/v1/phb/spell-slots',                      to: 'dnd#phb_spell_slots'
    post '/v1/phb/rests/long',                       to: 'dnd#phb_long_rest'
    post '/v1/phb/equipment-load',                   to: 'dnd#phb_equipment_load'
    post '/v1/dm/encounter-builder',                 to: 'dnd#dm_encounter_builder'
    post '/v1/dm/loot-parcel',                       to: 'dnd#dm_loot_parcel'
    post '/v1/dm/session-recap',                     to: 'dnd#dm_session_recap'
  end
end

# --- Selected Player's Handbook rules -------------------------------------

# Deterministic implementations of a small selection of PHB-style rules used by
# maintenance stage 7. Each method validates its inputs and raises ArgumentError
# on anything it cannot compute.
module Phb
  # Spell slot tables keyed by class and character level. Only the values
  # required by this benchmark are provided.
  SPELL_SLOTS = {
    'wizard' => {
      5 => { '1' => 4, '2' => 3, '3' => 2 }
    }
  }.freeze

  module_function

  def spell_slots(klass, level)
    klass = String(klass).downcase
    level = Integer(level)
    table = SPELL_SLOTS[klass]
    raise ArgumentError, 'unsupported class' unless table
    slots = table[level]
    raise ArgumentError, 'unsupported level' unless slots
    { 'class' => klass, 'level' => level, 'slots' => slots }
  end

  def long_rest(level:, hp_current:, hp_max:, hit_dice_spent:, exhaustion_level:)
    level = Integer(level)
    hp_max = Integer(hp_max)
    hit_dice_spent = Integer(hit_dice_spent)
    exhaustion_level = Integer(exhaustion_level)
    Integer(hp_current)
    raise ArgumentError, 'invalid level' if level < 1
    raise ArgumentError, 'invalid hit dice' if hit_dice_spent < 0
    raise ArgumentError, 'invalid exhaustion' if exhaustion_level < 0

    recovered = [level / 2, 1].max
    remaining_spent = [hit_dice_spent - recovered, 0].max
    {
      'hp_current' => hp_max,
      'hit_dice_spent' => remaining_spent,
      'exhaustion_level' => [exhaustion_level - 1, 0].max
    }
  end

  def equipment_load(strength:, weight:)
    strength = Integer(strength)
    weight = Integer(weight)
    raise ArgumentError, 'invalid strength' if strength < 0
    capacity = strength * 15
    { 'capacity' => capacity, 'weight' => weight, 'encumbered' => weight > capacity }
  end
end

# --- Durable storage (SQLite) ---------------------------------------------

# Durable, SQLite-backed store for game-world and game-state data. A single
# connection is guarded by a mutex so concurrent Puma threads serialize their
# access. The schema is initialized on server startup and can be recreated via
# the storage reset endpoint.
module Store
  SCHEMA_VERSION = 1
  DB_PATH = File.expand_path('game.db', __dir__)

  MUTEX = Mutex.new
  DB = SQLite3::Database.new(DB_PATH)
  DB.busy_timeout = 5000

  module_function

  def with_db
    MUTEX.synchronize { yield DB }
  end

  # Create tables if they do not already exist.
  def init_schema!
    with_db do |db|
      db.execute_batch(<<~SQL)
        CREATE TABLE IF NOT EXISTS users (
          username TEXT PRIMARY KEY,
          role     TEXT NOT NULL,
          password TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS combat_sessions (
          id   TEXT PRIMARY KEY,
          data TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS monsters (
          slug        TEXT PRIMARY KEY,
          name        TEXT NOT NULL,
          cr          TEXT NOT NULL,
          armor_class INTEGER NOT NULL,
          hit_points  INTEGER NOT NULL,
          tags        TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS items (
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
          campaign_id TEXT NOT NULL,
          id          TEXT NOT NULL,
          name        TEXT NOT NULL,
          level       INTEGER NOT NULL,
          class       TEXT NOT NULL,
          seq         INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, id)
        );
        CREATE TABLE IF NOT EXISTS campaign_events (
          campaign_id TEXT NOT NULL,
          id          TEXT NOT NULL,
          kind        TEXT NOT NULL,
          summary     TEXT NOT NULL,
          seq         INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, id)
        );
      SQL
    end
    self
  end

  # Drop and recreate benchmark-created durable data.
  def reset!
    with_db do |db|
      db.execute_batch(<<~SQL)
        DROP TABLE IF EXISTS users;
        DROP TABLE IF EXISTS combat_sessions;
        DROP TABLE IF EXISTS monsters;
        DROP TABLE IF EXISTS items;
        DROP TABLE IF EXISTS campaigns;
        DROP TABLE IF EXISTS campaign_characters;
        DROP TABLE IF EXISTS campaign_events;
      SQL
    end
    init_schema!
  end

  def initialized?
    with_db do |db|
      names = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('users','combat_sessions')"
      ).flatten
      names.include?('users') && names.include?('combat_sessions')
    end
  end
end

Store.init_schema!

# --- Domain logic ---------------------------------------------------------

module Dnd
  DICE_RE = /\A(\d+)d(\d+)([+-]\d+)?\z/

  CR_XP = {
    '0'   => 10,
    '1/8' => 25,
    '1/4' => 50,
    '1/2' => 100,
    '1'   => 200,
    '2'   => 450,
    '3'   => 700,
    '4'   => 1100,
    '5'   => 1800,
  }.freeze

  LEVEL_THRESHOLDS = {
    3 => { 'easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400 },
  }.freeze

  module_function

  def dice_stats(expression)
    raise ArgumentError unless expression.is_a?(String)
    m = DICE_RE.match(expression)
    raise ArgumentError unless m

    count = Integer(m[1], 10)
    sides = Integer(m[2], 10)
    modifier = m[3] ? Integer(m[3], 10) : 0
    raise ArgumentError unless count.positive? && sides.positive?

    min = count + modifier
    max = count * sides + modifier
    {
      dice_count: count,
      sides: sides,
      modifier: modifier,
      min: min,
      max: max,
      average: numify((min + max) / 2.0),
    }
  end

  def multiplier_for(monster_count)
    case monster_count
    when 0 then 1
    when 1 then 1
    when 2 then 1.5
    when 3..6 then 2
    when 7..10 then 2.5
    when 11..14 then 3
    else 4
    end
  end

  def adjusted_xp(party, monsters)
    base_xp = 0
    monster_count = 0
    monsters.each do |mon|
      cr = mon['cr'].to_s
      count = Integer(mon['count'])
      xp = CR_XP.fetch(cr)
      base_xp += xp * count
      monster_count += count
    end

    multiplier = multiplier_for(monster_count)
    adjusted = base_xp * multiplier

    thresholds = { 'easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0 }
    party.each do |member|
      level = Integer(member['level'])
      per = LEVEL_THRESHOLDS.fetch(level)
      thresholds.each_key { |k| thresholds[k] += per[k] }
    end

    difficulty = 'trivial'
    difficulty = 'easy'   if adjusted >= thresholds['easy']
    difficulty = 'medium' if adjusted >= thresholds['medium']
    difficulty = 'hard'   if adjusted >= thresholds['hard']
    difficulty = 'deadly' if adjusted >= thresholds['deadly']

    {
      base_xp: base_xp,
      monster_count: monster_count,
      multiplier: numify(multiplier),
      adjusted_xp: numify(adjusted),
      difficulty: difficulty,
      thresholds: thresholds,
    }
  end

  def initiative_order(combatants)
    scored = combatants.map do |c|
      dex = Integer(c['dex'])
      roll = Integer(c['roll'])
      name = c['name'].to_s
      { name: name, dex: dex, score: roll + dex }
    end
    scored.sort_by! { |c| [-c[:score], -c[:dex], c[:name]] }
    scored.map { |c| { name: c[:name], score: c[:score] } }
  end

  def require_integer(value)
    raise ArgumentError unless value.is_a?(Integer)
    value
  end

  def ability_modifier(score)
    score = require_integer(score)
    raise ArgumentError unless score >= 1 && score <= 30
    (score - 10).fdiv(2).floor
  end

  def proficiency_bonus(level)
    level = require_integer(level)
    raise ArgumentError unless level >= 1 && level <= 20
    (level - 1) / 4 + 2
  end

  def derived_stats(level, abilities, armor)
    level = require_integer(level)
    raise ArgumentError unless level >= 1 && level <= 20
    raise ArgumentError unless abilities.is_a?(Hash) && armor.is_a?(Hash)

    modifiers = {}
    %w[str dex con int wis cha].each do |key|
      raise ArgumentError unless abilities.key?(key)
      modifiers[key] = ability_modifier(abilities[key])
    end

    base = require_integer(armor['base'])
    dex_cap = require_integer(armor['dex_cap'])
    shield = armor['shield']
    raise ArgumentError unless [true, false].include?(shield)

    shield_bonus = shield ? 2 : 0
    hp_max = level * (6 + modifiers['con'])
    armor_class = base + [modifiers['dex'], dex_cap].min + shield_bonus

    {
      level: level,
      proficiency_bonus: proficiency_bonus(level),
      hp_max: hp_max,
      armor_class: armor_class,
      modifiers: modifiers,
    }
  end

  # --- Combat sessions (durable, SQLite-backed) ---------------------------

  # Load a session hash (symbol keys) from durable storage, or nil.
  def load_session(db, id)
    row = db.execute('SELECT data FROM combat_sessions WHERE id = ?', [id]).first
    return nil unless row
    JSON.parse(row[0], symbolize_names: true)
  end

  def save_session(db, session)
    db.execute(
      'INSERT OR REPLACE INTO combat_sessions (id, data) VALUES (?, ?)',
      [session[:id], JSON.generate(session)]
    )
  end

  def create_combat_session(id, combatants)
    raise ArgumentError unless id.is_a?(String) && !id.empty?
    raise ArgumentError unless combatants.is_a?(Array) && !combatants.empty?

    order = combatants.map do |c|
      raise ArgumentError unless c.is_a?(Hash)
      name = c['name']
      raise ArgumentError unless name.is_a?(String) && !name.empty?
      dex = require_integer(c['dex'])
      roll = require_integer(c['roll'])
      { name: name, dex: dex, score: roll + dex, conditions: [], had_conditions: false }
    end
    order.sort_by! { |c| [-c[:score], -c[:dex], c[:name]] }

    session = { id: id, round: 1, turn_index: 0, order: order }

    Store.with_db do |db|
      raise ArgumentError if load_session(db, id)
      save_session(db, session)
    end

    session_summary(session)
  end

  def add_condition(id, target, condition, duration_rounds)
    raise ArgumentError unless condition.is_a?(String) && !condition.empty?
    duration = require_integer(duration_rounds)
    raise ArgumentError unless duration.positive?

    Store.with_db do |db|
      session = load_session(db, id)
      raise KeyError unless session
      combatant = session[:order].find { |c| c[:name] == target }
      raise ArgumentError unless combatant

      combatant[:conditions] << { condition: condition, remaining_rounds: duration }
      combatant[:had_conditions] = true
      save_session(db, session)
      {
        target: target,
        conditions: combatant[:conditions].map do |cond|
          { condition: cond[:condition], remaining_rounds: cond[:remaining_rounds] }
        end,
      }
    end
  end

  def advance_turn(id)
    Store.with_db do |db|
      session = load_session(db, id)
      raise KeyError unless session

      order = session[:order]
      session[:turn_index] += 1
      if session[:turn_index] >= order.length
        session[:turn_index] = 0
        session[:round] += 1
      end

      active = order[session[:turn_index]]
      active[:conditions].each { |cond| cond[:remaining_rounds] -= 1 }
      active[:conditions].reject! { |cond| cond[:remaining_rounds] <= 0 }

      save_session(db, session)

      conditions = {}
      order.each do |c|
        next unless c[:had_conditions]
        conditions[c[:name]] = c[:conditions].map do |cond|
          { condition: cond[:condition], remaining_rounds: cond[:remaining_rounds] }
        end
      end

      {
        id: session[:id],
        round: session[:round],
        turn_index: session[:turn_index],
        active: { name: active[:name], score: active[:score] },
        conditions: conditions,
      }
    end
  end

  def session_summary(session)
    active = session[:order][session[:turn_index]]
    {
      id: session[:id],
      round: session[:round],
      turn_index: session[:turn_index],
      active: { name: active[:name], score: active[:score] },
      order: session[:order].map { |c| { name: c[:name], score: c[:score] } },
    }
  end

  # Return an Integer when the value is whole, else a Float.
  def numify(value)
    if value.is_a?(Float) && value == value.to_i
      value.to_i
    else
      value
    end
  end
end

# --- Users / authentication (in-memory, process-lifetime state) -----------

module Auth
  USERNAME_RE = /\A[a-z0-9_-]{2,32}\z/
  ROLES = %w[dm player].freeze

  # Raised when a validation rule fails (maps to HTTP 400).
  class InvalidInput < StandardError; end
  # Raised when a username is already taken (maps to HTTP 409).
  class Duplicate < StandardError; end
  # Raised when credentials do not match (maps to HTTP 401).
  class BadCredentials < StandardError; end

  module_function

  # Real password hashing, isolated behind this helper so a production hash
  # (e.g. bcrypt/argon2) can drop in without touching call sites. Uses a
  # per-user random salt with PBKDF2-HMAC-SHA256 from the standard library.
  def hash_password(password, salt = SecureRandom.hex(16))
    digest = OpenSSL::PKCS5.pbkdf2_hmac(
      password, salt, 100_000, 32, OpenSSL::Digest::SHA256.new
    )
    "#{salt}$#{digest.unpack1('H*')}"
  end

  def password_matches?(password, stored)
    salt, = stored.split('$', 2)
    return false unless salt
    # Constant-time comparison to avoid leaking timing information.
    OpenSSL.secure_compare(hash_password(password, salt), stored)
  end

  def register(username, password, role)
    raise InvalidInput unless username.is_a?(String) && USERNAME_RE.match?(username)
    raise InvalidInput unless password.is_a?(String) && password.length >= 8
    raise InvalidInput unless ROLES.include?(role)

    Store.with_db do |db|
      exists = db.execute('SELECT 1 FROM users WHERE username = ?', [username]).first
      raise Duplicate if exists
      db.execute(
        'INSERT INTO users (username, role, password) VALUES (?, ?, ?)',
        [username, role, hash_password(password)]
      )
    end

    { username: username, role: role }
  end

  def login(username, password)
    raise InvalidInput unless username.is_a?(String) && password.is_a?(String)

    row = Store.with_db { |db| db.execute('SELECT password FROM users WHERE username = ?', [username]).first }
    raise BadCredentials unless row && password_matches?(password, row[0])

    { username: username, token: "session-#{username}" }
  end
end

# --- Compendium (durable, SQLite-backed game-world reference data) ---------

module Compendium
  # Raised when a slug already exists (maps to HTTP 409).
  class Duplicate < StandardError; end
  # Raised when a record does not exist (maps to HTTP 404).
  class NotFound < StandardError; end

  module_function

  def require_string(value)
    raise ArgumentError unless value.is_a?(String) && !value.strip.empty?
    value
  end

  def require_integer(value)
    raise ArgumentError unless value.is_a?(Integer)
    value
  end

  def create_monster(attrs)
    raise ArgumentError unless attrs.is_a?(Hash)
    slug = require_string(attrs['slug'])
    name = require_string(attrs['name'])
    cr   = require_string(attrs['cr'])
    armor_class = require_integer(attrs['armor_class'])
    hit_points  = require_integer(attrs['hit_points'])

    tags = attrs['tags'] || []
    raise ArgumentError unless tags.is_a?(Array) && tags.all? { |t| t.is_a?(String) }

    Store.with_db do |db|
      raise Duplicate if db.execute('SELECT 1 FROM monsters WHERE slug = ?', [slug]).first
      db.execute(
        'INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags) VALUES (?, ?, ?, ?, ?, ?)',
        [slug, name, cr, armor_class, hit_points, JSON.generate(tags)]
      )
    end

    { slug: slug, name: name, cr: cr, armor_class: armor_class, hit_points: hit_points }
  end

  def read_monster(slug)
    row = Store.with_db do |db|
      db.execute(
        'SELECT slug, name, cr, armor_class, hit_points, tags FROM monsters WHERE slug = ?',
        [slug]
      ).first
    end
    raise NotFound unless row

    {
      slug: row[0],
      name: row[1],
      cr: row[2],
      armor_class: row[3],
      hit_points: row[4],
      tags: JSON.parse(row[5]),
    }
  end

  def create_item(attrs)
    raise ArgumentError unless attrs.is_a?(Hash)
    slug   = require_string(attrs['slug'])
    name   = require_string(attrs['name'])
    type   = require_string(attrs['type'])
    rarity = require_string(attrs['rarity'])
    cost_gp = require_integer(attrs['cost_gp'])

    Store.with_db do |db|
      raise Duplicate if db.execute('SELECT 1 FROM items WHERE slug = ?', [slug]).first
      db.execute(
        'INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)',
        [slug, name, type, rarity, cost_gp]
      )
    end

    { slug: slug, name: name, type: type, rarity: rarity, cost_gp: cost_gp }
  end

  def read_item(slug)
    row = Store.with_db do |db|
      db.execute(
        'SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?',
        [slug]
      ).first
    end
    raise NotFound unless row

    { slug: row[0], name: row[1], type: row[2], rarity: row[3], cost_gp: row[4] }
  end
end

# --- Campaign state (durable, SQLite-backed) ------------------------------

module Campaign
  # Raised when an id already exists (maps to HTTP 409).
  class Duplicate < StandardError; end
  # Raised when a campaign does not exist (maps to HTTP 404).
  class NotFound < StandardError; end

  module_function

  def require_string(value)
    raise ArgumentError unless value.is_a?(String) && !value.strip.empty?
    value
  end

  def require_integer(value)
    raise ArgumentError unless value.is_a?(Integer)
    value
  end

  def create_campaign(attrs)
    raise ArgumentError unless attrs.is_a?(Hash)
    id   = require_string(attrs['id'])
    name = require_string(attrs['name'])
    dm   = require_string(attrs['dm'])

    Store.with_db do |db|
      raise Duplicate if db.execute('SELECT 1 FROM campaigns WHERE id = ?', [id]).first
      db.execute('INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)', [id, name, dm])
    end

    { id: id, name: name, dm: dm }
  end

  def add_character(campaign_id, attrs)
    raise ArgumentError unless attrs.is_a?(Hash)
    id    = require_string(attrs['id'])
    name  = require_string(attrs['name'])
    level = require_integer(attrs['level'])
    klass = require_string(attrs['class'])

    Store.with_db do |db|
      raise NotFound unless db.execute('SELECT 1 FROM campaigns WHERE id = ?', [campaign_id]).first
      raise Duplicate if db.execute(
        'SELECT 1 FROM campaign_characters WHERE campaign_id = ? AND id = ?', [campaign_id, id]
      ).first
      seq = db.execute(
        'SELECT COUNT(*) FROM campaign_characters WHERE campaign_id = ?', [campaign_id]
      ).first[0]
      db.execute(
        'INSERT INTO campaign_characters (campaign_id, id, name, level, class, seq) VALUES (?, ?, ?, ?, ?, ?)',
        [campaign_id, id, name, level, klass, seq]
      )
    end

    { id: id, name: name, level: level, class: klass }
  end

  def add_event(campaign_id, attrs)
    raise ArgumentError unless attrs.is_a?(Hash)
    id      = require_string(attrs['id'])
    kind    = require_string(attrs['kind'])
    summary = require_string(attrs['summary'])

    Store.with_db do |db|
      raise NotFound unless db.execute('SELECT 1 FROM campaigns WHERE id = ?', [campaign_id]).first
      raise Duplicate if db.execute(
        'SELECT 1 FROM campaign_events WHERE campaign_id = ? AND id = ?', [campaign_id, id]
      ).first
      seq = db.execute(
        'SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?', [campaign_id]
      ).first[0]
      db.execute(
        'INSERT INTO campaign_events (campaign_id, id, kind, summary, seq) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, id, kind, summary, seq]
      )
    end

    { id: id, kind: kind }
  end

  def campaign_state(campaign_id)
    Store.with_db do |db|
      row = db.execute('SELECT id, name, dm FROM campaigns WHERE id = ?', [campaign_id]).first
      raise NotFound unless row

      characters = db.execute(
        'SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY seq',
        [campaign_id]
      ).map { |c| { id: c[0], name: c[1], level: c[2], class: c[3] } }

      log_count = db.execute(
        'SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?', [campaign_id]
      ).first[0]

      { id: row[0], name: row[1], dm: row[2], characters: characters, log_count: log_count }
    end
  end
end

# --- DM tools (combine compendium + campaign state) -----------------------

# DM-facing helpers that read stored compendium and campaign data and return
# deterministic recommendations. All values are computed from durable state so
# repeated calls yield identical output.
module DmTools
  # Raised when a referenced record does not exist (maps to HTTP 404).
  class NotFound < StandardError; end

  # Difficulty -> deterministic recommendation phrasing.
  RECOMMENDATION = {
    'trivial' => 'no real threat',
    'easy'    => 'safe warm-up',
    'medium'  => 'a fair fight',
    'hard'    => 'tough battle',
    'deadly'  => 'potentially lethal',
  }.freeze

  # Deterministic loot tables keyed by tier.
  LOOT_TABLE = {
    1 => { coins_gp: 75, items: [{ slug: 'healing-potion', quantity: 2 }] },
  }.freeze

  module_function

  def encounter_builder(campaign_id, party, monster_slugs)
    raise ArgumentError unless campaign_id.is_a?(String) && !campaign_id.empty?
    raise ArgumentError unless party.is_a?(Array) && !party.empty?
    raise ArgumentError unless monster_slugs.is_a?(Array) && !monster_slugs.empty?

    counts = Hash.new(0)
    order = []
    monster_slugs.each do |slug|
      raise ArgumentError unless slug.is_a?(String) && !slug.empty?
      order << slug unless counts.key?(slug)
      counts[slug] += 1
    end

    monsters = order.map do |slug|
      row = Store.with_db { |db| db.execute('SELECT cr FROM monsters WHERE slug = ?', [slug]).first }
      raise NotFound unless row
      { 'cr' => row[0], 'count' => counts[slug] }
    end

    result = Dnd.adjusted_xp(party, monsters)
    difficulty = result[:difficulty]

    {
      campaign_id: campaign_id,
      base_xp: result[:base_xp],
      adjusted_xp: result[:adjusted_xp],
      difficulty: difficulty,
      monster_count: result[:monster_count],
      recommendation: RECOMMENDATION.fetch(difficulty),
    }
  end

  def loot_parcel(campaign_id, tier)
    raise ArgumentError unless campaign_id.is_a?(String) && !campaign_id.empty?
    tier = Integer(tier)
    parcel = LOOT_TABLE[tier]
    raise ArgumentError unless parcel

    { campaign_id: campaign_id, coins_gp: parcel[:coins_gp], items: parcel[:items] }
  end

  def session_recap(campaign_id)
    raise ArgumentError unless campaign_id.is_a?(String) && !campaign_id.empty?

    Store.with_db do |db|
      raise NotFound unless db.execute('SELECT 1 FROM campaigns WHERE id = ?', [campaign_id]).first

      summaries = db.execute(
        'SELECT summary FROM campaign_events WHERE campaign_id = ? ORDER BY seq', [campaign_id]
      ).map { |r| r[0] }

      summary = summaries.last.to_s
      open_threads = summaries.filter_map { |s| thread_for(s) }

      { campaign_id: campaign_id, summary: summary, open_threads: open_threads }
    end
  end

  # Derive an open thread from an event summary. Scouting a location leaves an
  # unresolved ambush to be dealt with later.
  def thread_for(summary)
    m = /scouts the (.+?)\.?\z/.match(summary.to_s)
    return nil unless m
    "Resolve #{m[1]} ambush"
  end
end

# --- Controller -----------------------------------------------------------

class DndController < ActionController::API
  def health
    render json: { ok: true }
  end

  def dice_stats
    result = Dnd.dice_stats(params[:expression])
    render json: result
  rescue ArgumentError, TypeError
    render json: { error: 'invalid expression' }, status: :bad_request
  end

  def ability_check
    roll = Integer(params[:roll])
    modifier = Integer(params[:modifier])
    dc = Integer(params[:dc])
    total = roll + modifier
    render json: { total: total, success: total >= dc, margin: total - dc }
  rescue ArgumentError, TypeError
    render json: { error: 'invalid request' }, status: :bad_request
  end

  def adjusted_xp
    party = Array(params[:party]).map(&:to_unsafe_h)
    monsters = Array(params[:monsters]).map(&:to_unsafe_h)
    render json: Dnd.adjusted_xp(party, monsters)
  rescue ArgumentError, TypeError, KeyError
    render json: { error: 'invalid request' }, status: :bad_request
  end

  def initiative_order
    combatants = Array(params[:combatants]).map(&:to_unsafe_h)
    render json: { order: Dnd.initiative_order(combatants) }
  rescue ArgumentError, TypeError
    render json: { error: 'invalid request' }, status: :bad_request
  end

  def ability_modifier
    score = params[:score]
    modifier = Dnd.ability_modifier(score)
    render json: { score: score, modifier: modifier }
  rescue ArgumentError, TypeError
    render json: { error: 'invalid request' }, status: :bad_request
  end

  def proficiency
    level = params[:level]
    bonus = Dnd.proficiency_bonus(level)
    render json: { level: level, proficiency_bonus: bonus }
  rescue ArgumentError, TypeError
    render json: { error: 'invalid request' }, status: :bad_request
  end

  def derived_stats
    abilities = params[:abilities]&.to_unsafe_h
    armor = params[:armor]&.to_unsafe_h
    render json: Dnd.derived_stats(params[:level], abilities, armor)
  rescue ArgumentError, TypeError
    render json: { error: 'invalid request' }, status: :bad_request
  end

  def create_combat_session
    combatants = Array(params[:combatants]).map(&:to_unsafe_h)
    render json: Dnd.create_combat_session(params[:id], combatants)
  rescue ArgumentError, TypeError
    render json: { error: 'invalid request' }, status: :bad_request
  end

  def add_condition
    result = Dnd.add_condition(
      params[:id], params[:target], params[:condition], params[:duration_rounds]
    )
    render json: result
  rescue KeyError
    render json: { error: 'unknown session' }, status: :not_found
  rescue ArgumentError, TypeError
    render json: { error: 'invalid request' }, status: :bad_request
  end

  def advance_turn
    render json: Dnd.advance_turn(params[:id])
  rescue KeyError
    render json: { error: 'unknown session' }, status: :not_found
  rescue ArgumentError, TypeError
    render json: { error: 'invalid request' }, status: :bad_request
  end

  def register
    render json: Auth.register(params[:username], params[:password], params[:role]), status: :created
  rescue Auth::Duplicate
    render json: { error: 'username already exists' }, status: :conflict
  rescue Auth::InvalidInput, ArgumentError, TypeError
    render json: { error: 'invalid request' }, status: :bad_request
  end

  def login
    render json: Auth.login(params[:username], params[:password])
  rescue Auth::BadCredentials
    render json: { error: 'invalid credentials' }, status: :unauthorized
  rescue Auth::InvalidInput, ArgumentError, TypeError
    render json: { error: 'invalid request' }, status: :bad_request
  end

  def storage_status
    render json: {
      driver: 'sqlite',
      schema_version: Store::SCHEMA_VERSION,
      initialized: Store.initialized?,
    }
  end

  def storage_reset
    Store.reset!
    render json: { ok: true, schema_version: Store::SCHEMA_VERSION }
  end

  def create_monster
    attrs = params.permit!.to_h.transform_keys(&:to_s)
    render json: Compendium.create_monster(attrs), status: :created
  rescue Compendium::Duplicate
    render json: { error: 'slug already exists' }, status: :conflict
  rescue ArgumentError, TypeError
    render json: { error: 'invalid request' }, status: :bad_request
  end

  def read_monster
    render json: Compendium.read_monster(params[:slug])
  rescue Compendium::NotFound
    render json: { error: 'unknown monster' }, status: :not_found
  end

  def create_item
    attrs = params.permit!.to_h.transform_keys(&:to_s)
    render json: Compendium.create_item(attrs), status: :created
  rescue Compendium::Duplicate
    render json: { error: 'slug already exists' }, status: :conflict
  rescue ArgumentError, TypeError
    render json: { error: 'invalid request' }, status: :bad_request
  end

  def read_item
    render json: Compendium.read_item(params[:slug])
  rescue Compendium::NotFound
    render json: { error: 'unknown item' }, status: :not_found
  end

  def create_campaign
    attrs = params.permit!.to_h.transform_keys(&:to_s)
    render json: Campaign.create_campaign(attrs), status: :created
  rescue Campaign::Duplicate
    render json: { error: 'campaign already exists' }, status: :conflict
  rescue ArgumentError, TypeError
    render json: { error: 'invalid request' }, status: :bad_request
  end

  def add_character
    attrs = request.request_parameters.to_h.transform_keys(&:to_s)
    render json: Campaign.add_character(params[:id], attrs), status: :created
  rescue Campaign::Duplicate
    render json: { error: 'character already exists' }, status: :conflict
  rescue Campaign::NotFound
    render json: { error: 'unknown campaign' }, status: :not_found
  rescue ArgumentError, TypeError
    render json: { error: 'invalid request' }, status: :bad_request
  end

  def add_event
    attrs = request.request_parameters.to_h.transform_keys(&:to_s)
    render json: Campaign.add_event(params[:id], attrs), status: :created
  rescue Campaign::Duplicate
    render json: { error: 'event already exists' }, status: :conflict
  rescue Campaign::NotFound
    render json: { error: 'unknown campaign' }, status: :not_found
  rescue ArgumentError, TypeError
    render json: { error: 'invalid request' }, status: :bad_request
  end

  def campaign_state
    render json: Campaign.campaign_state(params[:id])
  rescue Campaign::NotFound
    render json: { error: 'unknown campaign' }, status: :not_found
  end

  def phb_spell_slots
    render json: Phb.spell_slots(params[:class], params[:level])
  rescue ArgumentError, TypeError
    render json: { error: 'invalid request' }, status: :bad_request
  end

  def phb_long_rest
    render json: Phb.long_rest(
      level: params[:level],
      hp_current: params[:hp_current],
      hp_max: params[:hp_max],
      hit_dice_spent: params[:hit_dice_spent],
      exhaustion_level: params[:exhaustion_level]
    )
  rescue ArgumentError, TypeError
    render json: { error: 'invalid request' }, status: :bad_request
  end

  def phb_equipment_load
    render json: Phb.equipment_load(strength: params[:strength], weight: params[:weight])
  rescue ArgumentError, TypeError
    render json: { error: 'invalid request' }, status: :bad_request
  end

  def dm_encounter_builder
    party = Array(params[:party]).map(&:to_unsafe_h)
    monster_slugs = Array(params[:monster_slugs])
    render json: DmTools.encounter_builder(params[:campaign_id], party, monster_slugs)
  rescue DmTools::NotFound
    render json: { error: 'unknown monster' }, status: :not_found
  rescue ArgumentError, TypeError, KeyError
    render json: { error: 'invalid request' }, status: :bad_request
  end

  def dm_loot_parcel
    render json: DmTools.loot_parcel(params[:campaign_id], params[:tier])
  rescue ArgumentError, TypeError
    render json: { error: 'invalid request' }, status: :bad_request
  end

  def dm_session_recap
    render json: DmTools.session_recap(params[:campaign_id])
  rescue DmTools::NotFound
    render json: { error: 'unknown campaign' }, status: :not_found
  rescue ArgumentError, TypeError
    render json: { error: 'invalid request' }, status: :bad_request
  end
end

Rails.application.initialize!
