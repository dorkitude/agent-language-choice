require 'rails'
require 'action_controller/railtie'
require 'sqlite3'
require 'json'

# Durable SQLite-backed storage for game-world (users) and game-state (combat
# sessions) data. An in-memory cache fronts the database so request-handling
# logic keeps its exact prior behavior while every mutation is written through
# to SQLite for durability. Reset clears the benchmark data and recreates the
# schema without disturbing process health.
module Storage
  SCHEMA_VERSION = 1
  DB_PATH = File.expand_path('game.db', __dir__)

  @mutex = Mutex.new
  @db = nil
  @initialized = false

  # In-memory working caches (symbol-keyed) rebuilt from the database on init.
  USERS = {}     # username => { password_hash:, role: }
  SESSIONS = {}  # id => { order:, round:, turn_index:, conditions: }
  MONSTERS = {}  # slug => { slug:, name:, cr:, armor_class:, hit_points:, tags: }
  ITEMS = {}     # slug => { slug:, name:, type:, rarity:, cost_gp: }

  module_function

  def db
    @db
  end

  def initialized?
    @initialized
  end

  def schema_version
    SCHEMA_VERSION
  end

  def setup
    @mutex.synchronize do
      @db ||= SQLite3::Database.new(DB_PATH)
      @db.busy_timeout = 5000
      create_schema
      load_caches
      @initialized = true
    end
  end

  def reset
    @mutex.synchronize do
      @db ||= SQLite3::Database.new(DB_PATH)
      @db.execute('DROP TABLE IF EXISTS users')
      @db.execute('DROP TABLE IF EXISTS combat_sessions')
      @db.execute('DROP TABLE IF EXISTS monsters')
      @db.execute('DROP TABLE IF EXISTS items')
      @db.execute('DROP TABLE IF EXISTS meta')
      create_schema
      USERS.clear
      SESSIONS.clear
      MONSTERS.clear
      ITEMS.clear
      @initialized = true
    end
  end

  def save_user(username, record)
    @mutex.synchronize do
      @db.execute(
        'INSERT OR REPLACE INTO users (username, password_hash, role) VALUES (?, ?, ?)',
        [username, record[:password_hash], record[:role]]
      )
    end
  end

  def save_session(id, session)
    @mutex.synchronize do
      @db.execute(
        'INSERT OR REPLACE INTO combat_sessions (id, data) VALUES (?, ?)',
        [id, JSON.generate(session)]
      )
    end
  end

  def save_monster(slug, record)
    @mutex.synchronize do
      @db.execute(
        'INSERT OR REPLACE INTO monsters (slug, data) VALUES (?, ?)',
        [slug, JSON.generate(record)]
      )
    end
  end

  def save_item(slug, record)
    @mutex.synchronize do
      @db.execute(
        'INSERT OR REPLACE INTO items (slug, data) VALUES (?, ?)',
        [slug, JSON.generate(record)]
      )
    end
  end

  # --- private helpers -----------------------------------------------------

  def create_schema
    @db.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)')
    @db.execute('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password_hash TEXT, role TEXT)')
    @db.execute('CREATE TABLE IF NOT EXISTS combat_sessions (id TEXT PRIMARY KEY, data TEXT)')
    @db.execute('CREATE TABLE IF NOT EXISTS monsters (slug TEXT PRIMARY KEY, data TEXT)')
    @db.execute('CREATE TABLE IF NOT EXISTS items (slug TEXT PRIMARY KEY, data TEXT)')
    @db.execute(
      'INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)',
      ['schema_version', SCHEMA_VERSION.to_s]
    )
  end

  def load_caches
    USERS.clear
    SESSIONS.clear
    @db.execute('SELECT username, password_hash, role FROM users') do |username, hash, role|
      USERS[username] = { password_hash: hash, role: role }
    end
    @db.execute('SELECT id, data FROM combat_sessions') do |id, data|
      SESSIONS[id] = symbolize(JSON.parse(data))
    end
    @db.execute('SELECT slug, data FROM monsters') do |slug, data|
      MONSTERS[slug] = symbolize(JSON.parse(data))
    end
    @db.execute('SELECT slug, data FROM items') do |slug, data|
      ITEMS[slug] = symbolize(JSON.parse(data))
    end
  end

  # Recursively convert parsed-JSON string keys back to the symbol keys the
  # request handlers expect, so cached state round-trips identically.
  def symbolize(value)
    case value
    when Hash
      value.each_with_object({}) { |(k, v), acc| acc[k.to_sym] = symbolize(v) }
    when Array
      value.map { |v| symbolize(v) }
    else
      value
    end
  end
end

# Minimal single-file Rails API application implementing the Core D&D REST engine.
class App < Rails::Application
  config.eager_load = false
  config.consider_all_requests_local = true
  config.secret_key_base = 'dnd-core-benchmark-secret-key-base'
  config.hosts.clear
  config.logger = Logger.new($stdout)
  config.log_level = :warn
  config.api_only = true

  routes.append do
    get  '/health',                 to: 'engine#health'
    post '/v1/dice/stats',          to: 'engine#dice_stats'
    post '/v1/checks/ability',      to: 'engine#ability_check'
    post '/v1/encounters/adjusted-xp', to: 'engine#adjusted_xp'
    post '/v1/initiative/order',    to: 'engine#initiative_order'
    post '/v1/characters/ability-modifier', to: 'engine#ability_modifier'
    post '/v1/characters/proficiency',      to: 'engine#proficiency'
    post '/v1/characters/derived-stats',    to: 'engine#derived_stats'
    post '/v1/combat/sessions',                    to: 'combat#create_session'
    post '/v1/combat/sessions/:id/conditions',     to: 'combat#add_condition'
    post '/v1/combat/sessions/:id/advance',        to: 'combat#advance'
    post '/v1/auth/register',                      to: 'auth#register'
    post '/v1/auth/login',                         to: 'auth#login'
    get  '/v1/storage/status',                     to: 'storage#status'
    post '/v1/storage/reset',                       to: 'storage#reset'
    post '/v1/compendium/monsters',                to: 'compendium#create_monster'
    get  '/v1/compendium/monsters/:slug',          to: 'compendium#read_monster'
    post '/v1/compendium/items',                   to: 'compendium#create_item'
    get  '/v1/compendium/items/:slug',             to: 'compendium#read_item'
  end
end

App.initialize!

# Create game.db and initialize the schema on server startup.
Storage.setup

# Emit a number as an integer when it is whole (e.g. 10 rather than 10.0).
def numeric(value)
  return value if value.is_a?(Integer)
  value == value.to_i ? value.to_i : value
end

CR_XP = {
  '0' => 10, '1/8' => 25, '1/4' => 50, '1/2' => 100,
  '1' => 200, '2' => 450, '3' => 700, '4' => 1100, '5' => 1800
}.freeze

# Level => [easy, medium, hard, deadly] thresholds.
LEVEL_THRESHOLDS = {
  3 => { easy: 75, medium: 150, hard: 225, deadly: 400 }
}.freeze

def encounter_multiplier(count)
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

class EngineController < ActionController::API
  def health
    render json: { ok: true }
  end

  def dice_stats
    expr = params[:expression]
    unless expr.is_a?(String) && (m = expr.match(/\A(\d+)d(\d+)([+-]\d+)?\z/))
      return render json: { error: 'invalid expression' }, status: :bad_request
    end

    count = m[1].to_i
    sides = m[2].to_i
    modifier = m[3] ? m[3].to_i : 0

    if count <= 0 || sides <= 0
      return render json: { error: 'invalid expression' }, status: :bad_request
    end

    min = count * 1 + modifier
    max = count * sides + modifier
    average = (min + max) / 2.0

    render json: {
      dice_count: count,
      sides: sides,
      modifier: modifier,
      min: min,
      max: max,
      average: numeric(average)
    }
  end

  def ability_check
    roll = params[:roll]
    modifier = params[:modifier]
    dc = params[:dc]

    unless roll.is_a?(Integer) && modifier.is_a?(Integer) && dc.is_a?(Integer)
      return render json: { error: 'invalid request' }, status: :bad_request
    end

    total = roll + modifier
    render json: {
      total: total,
      success: total >= dc,
      margin: total - dc
    }
  end

  def adjusted_xp
    party = params[:party]
    monsters = params[:monsters]

    unless party.is_a?(Array) && monsters.is_a?(Array)
      return render json: { error: 'invalid request' }, status: :bad_request
    end

    base_xp = 0
    monster_count = 0
    monsters.each do |mon|
      cr = mon[:cr].to_s
      xp = CR_XP[cr]
      return render json: { error: 'unknown cr' }, status: :bad_request unless xp
      cnt = mon[:count].to_i
      base_xp += xp * cnt
      monster_count += cnt
    end

    multiplier = encounter_multiplier(monster_count)
    adjusted = base_xp * multiplier

    thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 }
    party.each do |member|
      level = member[:level].to_i
      lvl = LEVEL_THRESHOLDS[level]
      return render json: { error: 'unknown level' }, status: :bad_request unless lvl
      thresholds[:easy] += lvl[:easy]
      thresholds[:medium] += lvl[:medium]
      thresholds[:hard] += lvl[:hard]
      thresholds[:deadly] += lvl[:deadly]
    end

    difficulty =
      if adjusted >= thresholds[:deadly] then 'deadly'
      elsif adjusted >= thresholds[:hard] then 'hard'
      elsif adjusted >= thresholds[:medium] then 'medium'
      elsif adjusted >= thresholds[:easy] then 'easy'
      else 'trivial'
      end

    render json: {
      base_xp: base_xp,
      monster_count: monster_count,
      multiplier: numeric(multiplier),
      adjusted_xp: numeric(adjusted),
      difficulty: difficulty,
      thresholds: thresholds
    }
  end

  def initiative_order
    combatants = params[:combatants]
    unless combatants.is_a?(Array)
      return render json: { error: 'invalid request' }, status: :bad_request
    end

    entries = combatants.map do |c|
      name = c[:name].to_s
      dex = c[:dex].to_i
      roll = c[:roll].to_i
      { name: name, dex: dex, score: roll + dex }
    end

    ordered = entries.sort_by.with_index { |e, i| [-e[:score], -e[:dex], e[:name], i] }

    render json: {
      order: ordered.map { |e| { name: e[:name], score: e[:score] } }
    }
  end

  def ability_modifier
    score = params[:score]
    unless score.is_a?(Integer) && score >= 1 && score <= 30
      return render json: { error: 'invalid request' }, status: :bad_request
    end

    render json: { score: score, modifier: ability_mod(score) }
  end

  def proficiency
    level = params[:level]
    unless level.is_a?(Integer) && level >= 1 && level <= 20
      return render json: { error: 'invalid request' }, status: :bad_request
    end

    render json: { level: level, proficiency_bonus: proficiency_bonus(level) }
  end

  def derived_stats
    level = params[:level]
    abilities = params[:abilities]
    armor = params[:armor]

    unless level.is_a?(Integer) && level >= 1 && level <= 20 &&
           abilities.respond_to?(:[]) && armor.respond_to?(:[])
      return render json: { error: 'invalid request' }, status: :bad_request
    end

    keys = %w[str dex con int wis cha]
    scores = {}
    keys.each do |k|
      s = abilities[k]
      unless s.is_a?(Integer) && s >= 1 && s <= 30
        return render json: { error: 'invalid request' }, status: :bad_request
      end
      scores[k] = s
    end

    base = armor[:base]
    dex_cap = armor[:dex_cap]
    shield = armor[:shield]
    unless base.is_a?(Integer) && dex_cap.is_a?(Integer)
      return render json: { error: 'invalid request' }, status: :bad_request
    end

    modifiers = {}
    keys.each { |k| modifiers[k] = ability_mod(scores[k]) }

    con_mod = modifiers['con']
    dex_mod = modifiers['dex']
    shield_bonus = shield == true ? 2 : 0

    render json: {
      level: level,
      proficiency_bonus: proficiency_bonus(level),
      hp_max: level * (6 + con_mod),
      armor_class: base + [dex_mod, dex_cap].min + shield_bonus,
      modifiers: {
        str: modifiers['str'],
        dex: modifiers['dex'],
        con: modifiers['con'],
        int: modifiers['int'],
        wis: modifiers['wis'],
        cha: modifiers['cha']
      }
    }
  end

  private

  def ability_mod(score)
    (score - 10).fdiv(2).floor
  end

  def proficiency_bonus(level)
    2 + (level - 1) / 4
  end
end

# Stateful combat engine backed by durable SQLite storage. The working state
# lives in Storage::SESSIONS (session id => { order:, round:, turn_index:,
# conditions: }) and every mutation is written through to SQLite.
class CombatController < ActionController::API
  SESSIONS = Storage::SESSIONS

  def create_session
    id = params[:id]
    combatants = params[:combatants]

    unless id.is_a?(String) && !id.empty? && combatants.is_a?(Array) && !combatants.empty?
      return render json: { error: 'invalid request' }, status: :bad_request
    end
    if SESSIONS.key?(id)
      return render json: { error: 'session already exists' }, status: :bad_request
    end

    entries = []
    combatants.each do |c|
      name = c[:name]
      dex = c[:dex]
      roll = c[:roll]
      unless name.is_a?(String) && !name.empty? && dex.is_a?(Integer) && roll.is_a?(Integer)
        return render json: { error: 'invalid combatant' }, status: :bad_request
      end
      entries << { name: name, dex: dex, score: roll + dex }
    end

    order = entries.sort_by.with_index { |e, i| [-e[:score], -e[:dex], e[:name], i] }

    SESSIONS[id] = {
      order: order,
      round: 1,
      turn_index: 0,
      conditions: {}
    }
    Storage.save_session(id, SESSIONS[id])

    session = SESSIONS[id]
    render json: {
      id: id,
      round: session[:round],
      turn_index: session[:turn_index],
      active: active_view(session),
      order: session[:order].map { |e| { name: e[:name], score: e[:score] } }
    }
  end

  def add_condition
    session = SESSIONS[params[:id]]
    return render json: { error: 'unknown session' }, status: :not_found unless session

    target = params[:target]
    condition = params[:condition]
    duration = params[:duration_rounds]

    unless target.is_a?(String) && condition.is_a?(String) &&
           duration.is_a?(Integer) && duration > 0
      return render json: { error: 'invalid request' }, status: :bad_request
    end
    unless session[:order].any? { |e| e[:name] == target }
      return render json: { error: 'unknown target' }, status: :bad_request
    end

    list = (session[:conditions][target] ||= [])
    list << { condition: condition, remaining_rounds: duration }
    Storage.save_session(params[:id], session)

    render json: {
      target: target,
      conditions: list.map { |c| { condition: c[:condition], remaining_rounds: c[:remaining_rounds] } }
    }
  end

  def advance
    session = SESSIONS[params[:id]]
    return render json: { error: 'unknown session' }, status: :not_found unless session

    count = session[:order].length
    session[:turn_index] += 1
    if session[:turn_index] >= count
      session[:turn_index] = 0
      session[:round] += 1
    end

    active = session[:order][session[:turn_index]]
    if (list = session[:conditions][active[:name]])
      list.each { |c| c[:remaining_rounds] -= 1 }
      list.reject! { |c| c[:remaining_rounds] <= 0 }
    end
    Storage.save_session(params[:id], session)

    render json: {
      id: params[:id],
      round: session[:round],
      turn_index: session[:turn_index],
      active: active_view(session),
      conditions: conditions_view(session)
    }
  end

  private

  def active_view(session)
    e = session[:order][session[:turn_index]]
    { name: e[:name], score: e[:score] }
  end

  def conditions_view(session)
    out = {}
    session[:conditions].each do |name, list|
      out[name] = list.map { |c| { condition: c[:condition], remaining_rounds: c[:remaining_rounds] } }
    end
    out
  end
end

# Password hashing isolated behind a small helper so a production hash can
# replace it without touching the controller. Uses PBKDF2-HMAC-SHA256, a real
# key-derivation function available in Ruby's standard OpenSSL library.
module PasswordHash
  require 'openssl'
  require 'securerandom'

  ITERATIONS = 100_000
  KEY_LEN = 32

  module_function

  def hash(password)
    salt = SecureRandom.hex(16)
    digest = derive(password, salt)
    "pbkdf2$#{ITERATIONS}$#{salt}$#{digest}"
  end

  def verify(password, stored)
    return false unless stored.is_a?(String)
    _algo, iters, salt, digest = stored.split('$')
    return false unless iters && salt && digest
    expected = derive(password, salt, iters.to_i)
    OpenSSL.secure_compare(expected, digest)
  end

  def derive(password, salt, iterations = ITERATIONS)
    OpenSSL::KDF.pbkdf2_hmac(
      password.to_s,
      salt: salt,
      iterations: iterations,
      length: KEY_LEN,
      hash: 'sha256'
    ).unpack1('H*')
  end
end

# Username/password authentication backed by durable SQLite storage. The
# working set lives in Storage::USERS (username => { password_hash:, role: })
# and registrations are written through to SQLite.
class AuthController < ActionController::API
  USERS = Storage::USERS

  USERNAME_RE = /\A[a-z0-9_-]{2,32}\z/

  def register
    username = params[:username]
    password = params[:password]
    role = params[:role]

    unless username.is_a?(String) && username.match?(USERNAME_RE) &&
           password.is_a?(String) && password.length >= 8 &&
           (role == 'dm' || role == 'player')
      return render json: { error: 'invalid request' }, status: :bad_request
    end

    if USERS.key?(username)
      return render json: { error: 'username already exists' }, status: :conflict
    end

    record = { password_hash: PasswordHash.hash(password), role: role }
    USERS[username] = record
    Storage.save_user(username, record)

    render json: { username: username, role: role }, status: :created
  end

  def login
    username = params[:username]
    password = params[:password]

    unless username.is_a?(String) && password.is_a?(String)
      return render json: { error: 'invalid request' }, status: :bad_request
    end

    user = USERS[username]
    unless user && PasswordHash.verify(password, user[:password_hash])
      return render json: { error: 'invalid credentials' }, status: :unauthorized
    end

    render json: { username: username, token: "session-#{username}" }
  end
end

# Game-world compendium of monsters and items backed by durable SQLite storage.
# Working sets live in Storage::MONSTERS / Storage::ITEMS (slug => record) and
# every create is written through to SQLite. Slugs are unique per collection.
class CompendiumController < ActionController::API
  MONSTERS = Storage::MONSTERS
  ITEMS = Storage::ITEMS

  SLUG_RE = /\A[a-z0-9]+(?:-[a-z0-9]+)*\z/

  def create_monster
    slug = params[:slug]
    name = params[:name]
    cr = params[:cr]
    armor_class = params[:armor_class]
    hit_points = params[:hit_points]
    tags = params.key?(:tags) ? params[:tags] : []

    unless valid_slug?(slug) && nonempty_string?(name) && nonempty_string?(cr) &&
           armor_class.is_a?(Integer) && hit_points.is_a?(Integer) &&
           valid_tags?(tags)
      return render json: { error: 'invalid request' }, status: :bad_request
    end
    if MONSTERS.key?(slug)
      return render json: { error: 'monster already exists' }, status: :conflict
    end

    record = {
      slug: slug,
      name: name,
      cr: cr,
      armor_class: armor_class,
      hit_points: hit_points,
      tags: tags
    }
    MONSTERS[slug] = record
    Storage.save_monster(slug, record)

    render json: {
      slug: slug,
      name: name,
      cr: cr,
      armor_class: armor_class,
      hit_points: hit_points
    }
  end

  def read_monster
    record = MONSTERS[params[:slug]]
    return render json: { error: 'unknown monster' }, status: :not_found unless record

    render json: {
      slug: record[:slug],
      name: record[:name],
      cr: record[:cr],
      armor_class: record[:armor_class],
      hit_points: record[:hit_points],
      tags: record[:tags]
    }
  end

  def create_item
    slug = params[:slug]
    name = params[:name]
    type = params[:type]
    rarity = params[:rarity]
    cost_gp = params[:cost_gp]

    unless valid_slug?(slug) && nonempty_string?(name) && nonempty_string?(type) &&
           nonempty_string?(rarity) && cost_gp.is_a?(Integer)
      return render json: { error: 'invalid request' }, status: :bad_request
    end
    if ITEMS.key?(slug)
      return render json: { error: 'item already exists' }, status: :conflict
    end

    record = {
      slug: slug,
      name: name,
      type: type,
      rarity: rarity,
      cost_gp: cost_gp
    }
    ITEMS[slug] = record
    Storage.save_item(slug, record)

    render json: record
  end

  def read_item
    record = ITEMS[params[:slug]]
    return render json: { error: 'unknown item' }, status: :not_found unless record

    render json: {
      slug: record[:slug],
      name: record[:name],
      type: record[:type],
      rarity: record[:rarity],
      cost_gp: record[:cost_gp]
    }
  end

  private

  def nonempty_string?(value)
    value.is_a?(String) && !value.empty?
  end

  def valid_slug?(value)
    value.is_a?(String) && value.match?(SLUG_RE)
  end

  def valid_tags?(tags)
    tags.is_a?(Array) && tags.all? { |t| t.is_a?(String) }
  end
end

# Reports and manages the durable SQLite storage layer.
class StorageController < ActionController::API
  def status
    render json: {
      driver: 'sqlite',
      schema_version: Storage.schema_version,
      initialized: Storage.initialized?
    }
  end

  def reset
    Storage.reset
    render json: { ok: true, schema_version: Storage.schema_version }
  end
end
