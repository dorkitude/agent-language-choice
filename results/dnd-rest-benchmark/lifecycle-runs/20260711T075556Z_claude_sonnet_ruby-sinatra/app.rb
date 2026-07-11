require 'sinatra'
require 'json'
require 'openssl'
require 'securerandom'
require 'sqlite3'

set :bind, '127.0.0.1'

SCHEMA_VERSION = 1
DB_PATH = File.join(__dir__, 'game.db')

def init_schema(db)
  db.execute_batch(<<~SQL)
    CREATE TABLE IF NOT EXISTS users (
      username TEXT PRIMARY KEY,
      role TEXT NOT NULL,
      salt TEXT NOT NULL,
      digest TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS combat_sessions (
      id TEXT PRIMARY KEY,
      round INTEGER NOT NULL,
      turn_index INTEGER NOT NULL,
      order_json TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS storage_meta (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS monsters (
      slug TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      cr TEXT NOT NULL,
      armor_class INTEGER NOT NULL,
      hit_points INTEGER NOT NULL,
      tags_json TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS items (
      slug TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      type TEXT NOT NULL,
      rarity TEXT NOT NULL,
      cost_gp INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS campaigns (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      dm TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS campaign_characters (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      name TEXT NOT NULL,
      level INTEGER NOT NULL,
      class TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );

    CREATE TABLE IF NOT EXISTS campaign_events (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      kind TEXT NOT NULL,
      summary TEXT,
      PRIMARY KEY (campaign_id, id)
    );
  SQL
  db.execute(
    'INSERT OR REPLACE INTO storage_meta (key, value) VALUES (?, ?)',
    ['schema_version', SCHEMA_VERSION.to_s]
  )
  db.execute(
    'INSERT OR REPLACE INTO storage_meta (key, value) VALUES (?, ?)',
    ['initialized', 'true']
  )
end

def open_db
  db = SQLite3::Database.new(DB_PATH)
  db.results_as_hash = true
  db
end

DB = open_db
init_schema(DB)

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
  when 1 then 1
  when 2 then 1.5
  when 3..6 then 2
  when 7..10 then 2.5
  when 11..14 then 3
  else 4
  end
end

before do
  content_type :json
end

def json_body
  request.body.rewind
  JSON.parse(request.body.read)
rescue JSON::ParserError
  halt 400, { error: 'invalid json' }.to_json
end

get '/health' do
  { ok: true }.to_json
end

def ability_modifier(score)
  ((score - 10).to_f / 2).floor
end

def proficiency_bonus(level)
  case level
  when 1..4 then 2
  when 5..8 then 3
  when 9..12 then 4
  when 13..16 then 5
  when 17..20 then 6
  end
end

post '/v1/characters/ability-modifier' do
  body = json_body
  score = body['score']
  halt 400, { error: 'invalid score' }.to_json unless score.is_a?(Integer) && score >= 1 && score <= 30

  { score: score, modifier: ability_modifier(score) }.to_json
end

post '/v1/characters/proficiency' do
  body = json_body
  level = body['level']
  halt 400, { error: 'invalid level' }.to_json unless level.is_a?(Integer) && level >= 1 && level <= 20

  { level: level, proficiency_bonus: proficiency_bonus(level) }.to_json
end

post '/v1/characters/derived-stats' do
  body = json_body
  level = body['level']
  abilities = body['abilities']
  armor = body['armor']

  halt 400, { error: 'invalid parameters' }.to_json unless level.is_a?(Integer) && level >= 1 && level <= 20
  halt 400, { error: 'invalid parameters' }.to_json unless abilities.is_a?(Hash) && armor.is_a?(Hash)

  %w[str dex con int wis cha].each do |key|
    halt 400, { error: 'invalid abilities' }.to_json unless abilities[key].is_a?(Integer)
  end

  base = armor['base']
  shield = armor['shield']
  dex_cap = armor['dex_cap']
  halt 400, { error: 'invalid armor' }.to_json unless base.is_a?(Integer) && dex_cap.is_a?(Integer)

  modifiers = {}
  %w[str dex con int wis cha].each do |key|
    modifiers[key.to_sym] = ability_modifier(abilities[key])
  end

  prof = proficiency_bonus(level)
  hp_max = level * (6 + modifiers[:con])
  shield_bonus = shield == true ? 2 : 0
  armor_class = base + [modifiers[:dex], dex_cap].min + shield_bonus

  {
    level: level,
    proficiency_bonus: prof,
    hp_max: hp_max,
    armor_class: armor_class,
    modifiers: modifiers
  }.to_json
end

post '/v1/dice/stats' do
  body = json_body
  expression = body['expression']
  halt 400, { error: 'invalid expression' }.to_json unless expression.is_a?(String)

  match = /\A(\d+)d(\d+)([+-]\d+)?\z/.match(expression)
  halt 400, { error: 'invalid expression' }.to_json unless match

  count = match[1].to_i
  sides = match[2].to_i
  modifier = match[3] ? match[3].to_i : 0

  halt 400, { error: 'invalid expression' }.to_json if count <= 0 || sides <= 0

  min = count * 1 + modifier
  max = count * sides + modifier
  average_raw = (count * (sides + 1) / 2.0) + modifier
  average = average_raw == average_raw.to_i ? average_raw.to_i : average_raw

  {
    dice_count: count,
    sides: sides,
    modifier: modifier,
    min: min,
    max: max,
    average: average
  }.to_json
end

post '/v1/checks/ability' do
  body = json_body
  roll = body['roll']
  modifier = body['modifier']
  dc = body['dc']

  halt 400, { error: 'invalid parameters' }.to_json unless roll.is_a?(Numeric) && modifier.is_a?(Numeric) && dc.is_a?(Numeric)

  total = roll + modifier
  success = total >= dc
  margin = total - dc

  { total: total, success: success, margin: margin }.to_json
end

post '/v1/encounters/adjusted-xp' do
  body = json_body
  party = body['party']
  monsters = body['monsters']

  halt 400, { error: 'invalid parameters' }.to_json unless party.is_a?(Array) && monsters.is_a?(Array)

  base_xp = 0
  monster_count = 0
  monsters.each do |m|
    cr = m['cr'].to_s
    count = m['count']
    halt 400, { error: 'unknown cr' }.to_json unless CR_XP.key?(cr)
    base_xp += CR_XP[cr] * count
    monster_count += count
  end

  mult = multiplier_for(monster_count)
  adjusted_xp = (base_xp * mult).to_i

  levels = party.map { |p| p['level'] }
  thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 }
  levels.each do |lvl|
    lvl_thresholds = LEVEL_THRESHOLDS[lvl]
    halt 400, { error: 'unsupported level' }.to_json unless lvl_thresholds
    thresholds[:easy] += lvl_thresholds[:easy]
    thresholds[:medium] += lvl_thresholds[:medium]
    thresholds[:hard] += lvl_thresholds[:hard]
    thresholds[:deadly] += lvl_thresholds[:deadly]
  end

  difficulty = if adjusted_xp >= thresholds[:deadly]
                 'deadly'
               elsif adjusted_xp >= thresholds[:hard]
                 'hard'
               elsif adjusted_xp >= thresholds[:medium]
                 'medium'
               elsif adjusted_xp >= thresholds[:easy]
                 'easy'
               else
                 'trivial'
               end

  {
    base_xp: base_xp,
    monster_count: monster_count,
    multiplier: mult,
    adjusted_xp: adjusted_xp,
    difficulty: difficulty,
    thresholds: thresholds
  }.to_json
end

post '/v1/initiative/order' do
  body = json_body
  combatants = body['combatants']
  halt 400, { error: 'invalid parameters' }.to_json unless combatants.is_a?(Array)

  scored = combatants.map do |c|
    { name: c['name'], score: c['roll'] + c['dex'], dex: c['dex'] }
  end

  ordered = scored.sort_by { |c| [-c[:score], -c[:dex], c[:name]] }
             .map { |c| { name: c[:name], score: c[:score] } }

  { order: ordered }.to_json
end

COMBAT_SESSIONS = {}

def persist_session(session)
  DB.execute(
    'INSERT OR REPLACE INTO combat_sessions (id, round, turn_index, order_json) VALUES (?, ?, ?, ?)',
    [session[:id], session[:round], session[:turn_index], JSON.generate(session[:order])]
  )
end

def load_sessions_from_db
  COMBAT_SESSIONS.clear
  DB.execute('SELECT id, round, turn_index, order_json FROM combat_sessions').each do |row|
    order = JSON.parse(row['order_json']).map do |c|
      { name: c['name'], dex: c['dex'], score: c['score'],
        conditions: c['conditions'].map { |cond| { condition: cond['condition'], remaining_rounds: cond['remaining_rounds'] } } }
    end
    COMBAT_SESSIONS[row['id']] = {
      id: row['id'],
      order: order,
      round: row['round'],
      turn_index: row['turn_index']
    }
  end
end

def combat_active(session)
  order = session[:order]
  order[session[:turn_index]]
end

def combat_response(session)
  active = combat_active(session)
  {
    id: session[:id],
    round: session[:round],
    turn_index: session[:turn_index],
    active: { name: active[:name], score: active[:score] },
    order: session[:order].map { |c| { name: c[:name], score: c[:score] } }
  }
end

def find_session!(id)
  session = COMBAT_SESSIONS[id]
  halt 404, { error: 'unknown session' }.to_json unless session
  session
end

post '/v1/combat/sessions' do
  body = json_body
  id = body['id']
  combatants = body['combatants']

  halt 400, { error: 'invalid parameters' }.to_json unless id.is_a?(String) && !id.empty?
  halt 400, { error: 'invalid parameters' }.to_json unless combatants.is_a?(Array) && !combatants.empty?
  halt 400, { error: 'duplicate session id' }.to_json if COMBAT_SESSIONS.key?(id)

  combatants.each do |c|
    unless c.is_a?(Hash) && c['name'].is_a?(String) && c['dex'].is_a?(Numeric) && c['roll'].is_a?(Numeric)
      halt 400, { error: 'invalid combatant' }.to_json
    end
  end

  scored = combatants.map do |c|
    { name: c['name'], dex: c['dex'], score: c['roll'] + c['dex'], conditions: [] }
  end

  order = scored.sort_by { |c| [-c[:score], -c[:dex], c[:name]] }

  session = {
    id: id,
    order: order,
    round: 1,
    turn_index: 0
  }
  COMBAT_SESSIONS[id] = session
  persist_session(session)

  combat_response(session).to_json
end

post '/v1/combat/sessions/:id/conditions' do
  session = find_session!(params[:id])
  body = json_body
  target = body['target']
  condition = body['condition']
  duration_rounds = body['duration_rounds']

  halt 400, { error: 'invalid parameters' }.to_json unless target.is_a?(String)
  halt 400, { error: 'invalid parameters' }.to_json unless condition.is_a?(String)
  halt 400, { error: 'invalid parameters' }.to_json unless duration_rounds.is_a?(Integer) && duration_rounds > 0

  combatant = session[:order].find { |c| c[:name] == target }
  halt 400, { error: 'unknown target' }.to_json unless combatant

  combatant[:conditions] << { condition: condition, remaining_rounds: duration_rounds }
  persist_session(session)

  {
    target: target,
    conditions: combatant[:conditions]
  }.to_json
end

post '/v1/combat/sessions/:id/advance' do
  session = find_session!(params[:id])
  order = session[:order]

  session[:turn_index] += 1
  if session[:turn_index] >= order.length
    session[:turn_index] = 0
    session[:round] += 1
  end

  active = combat_active(session)
  active[:conditions] = active[:conditions].filter_map do |cond|
    remaining = cond[:remaining_rounds] - 1
    remaining <= 0 ? nil : { condition: cond[:condition], remaining_rounds: remaining }
  end

  conditions = {}
  order.each { |c| conditions[c[:name]] = c[:conditions] }

  persist_session(session)

  {
    id: session[:id],
    round: session[:round],
    turn_index: session[:turn_index],
    active: { name: active[:name], score: active[:score] },
    conditions: conditions
  }.to_json
end

USERS = {}

def persist_user(username, data)
  DB.execute(
    'INSERT OR REPLACE INTO users (username, role, salt, digest) VALUES (?, ?, ?, ?)',
    [username, data[:role], data[:salt], data[:digest]]
  )
end

def load_users_from_db
  USERS.clear
  DB.execute('SELECT username, role, salt, digest FROM users').each do |row|
    USERS[row['username']] = { role: row['role'], salt: row['salt'], digest: row['digest'] }
  end
end

module PasswordHasher
  ITERATIONS = 200_000
  KEY_LEN = 32
  DIGEST = OpenSSL::Digest.new('SHA256')

  def self.hash(password, salt = SecureRandom.hex(16))
    digest = OpenSSL::KDF.pbkdf2_hmac(
      password, salt: salt, iterations: ITERATIONS, length: KEY_LEN, hash: DIGEST
    ).unpack1('H*')
    { salt: salt, digest: digest }
  end

  def self.verify(password, salt, expected_digest)
    computed = hash(password, salt)[:digest]
    secure_compare(computed, expected_digest)
  end

  def self.secure_compare(a, b)
    return false unless a.bytesize == b.bytesize

    l = a.unpack('C*')
    r = b.unpack('C*')
    result = 0
    l.zip(r) { |x, y| result |= x ^ y }
    result.zero?
  end
end

USERNAME_RE = /\A[a-z0-9_-]{2,32}\z/

post '/v1/auth/register' do
  body = json_body
  username = body['username']
  password = body['password']
  role = body['role']

  halt 400, { error: 'invalid username' }.to_json unless username.is_a?(String) && USERNAME_RE.match?(username)
  halt 400, { error: 'invalid password' }.to_json unless password.is_a?(String) && password.length >= 8
  halt 400, { error: 'invalid role' }.to_json unless %w[dm player].include?(role)
  halt 409, { error: 'duplicate username' }.to_json if USERS.key?(username)

  hashed = PasswordHasher.hash(password)
  USERS[username] = { role: role, salt: hashed[:salt], digest: hashed[:digest] }
  persist_user(username, USERS[username])

  status 201
  { username: username, role: role }.to_json
end

post '/v1/auth/login' do
  body = json_body
  username = body['username']
  password = body['password']

  halt 401, { error: 'invalid credentials' }.to_json unless username.is_a?(String) && password.is_a?(String)

  user = USERS[username]
  halt 401, { error: 'invalid credentials' }.to_json unless user
  halt 401, { error: 'invalid credentials' }.to_json unless PasswordHasher.verify(password, user[:salt], user[:digest])

  { username: username, token: "session-#{username}" }.to_json
end

get '/v1/storage/status' do
  {
    driver: 'sqlite',
    schema_version: SCHEMA_VERSION,
    initialized: true
  }.to_json
end

post '/v1/storage/reset' do
  DB.execute('DELETE FROM users')
  DB.execute('DELETE FROM combat_sessions')
  init_schema(DB)
  load_users_from_db
  load_sessions_from_db

  { ok: true, schema_version: SCHEMA_VERSION }.to_json
end

SLUG_RE = /\A[a-z0-9]+(?:-[a-z0-9]+)*\z/

post '/v1/compendium/monsters' do
  body = json_body
  slug = body['slug']
  name = body['name']
  cr = body['cr']
  armor_class = body['armor_class']
  hit_points = body['hit_points']
  tags = body['tags']

  halt 400, { error: 'invalid slug' }.to_json unless slug.is_a?(String) && SLUG_RE.match?(slug)
  halt 400, { error: 'invalid name' }.to_json unless name.is_a?(String) && !name.empty?
  halt 400, { error: 'invalid cr' }.to_json unless cr.is_a?(String) && !cr.empty?
  halt 400, { error: 'invalid armor_class' }.to_json unless armor_class.is_a?(Integer)
  halt 400, { error: 'invalid hit_points' }.to_json unless hit_points.is_a?(Integer)
  halt 400, { error: 'invalid tags' }.to_json unless tags.nil? || (tags.is_a?(Array) && tags.all? { |t| t.is_a?(String) })

  tags ||= []

  existing = DB.execute('SELECT slug FROM monsters WHERE slug = ?', [slug]).first
  halt 409, { error: 'duplicate slug' }.to_json if existing

  DB.execute(
    'INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags_json) VALUES (?, ?, ?, ?, ?, ?)',
    [slug, name, cr, armor_class, hit_points, JSON.generate(tags)]
  )

  status 201
  {
    slug: slug,
    name: name,
    cr: cr,
    armor_class: armor_class,
    hit_points: hit_points
  }.to_json
end

get '/v1/compendium/monsters/:slug' do
  row = DB.execute('SELECT * FROM monsters WHERE slug = ?', [params[:slug]]).first
  halt 404, { error: 'unknown monster' }.to_json unless row

  {
    slug: row['slug'],
    name: row['name'],
    cr: row['cr'],
    armor_class: row['armor_class'],
    hit_points: row['hit_points'],
    tags: JSON.parse(row['tags_json'])
  }.to_json
end

post '/v1/compendium/items' do
  body = json_body
  slug = body['slug']
  name = body['name']
  type = body['type']
  rarity = body['rarity']
  cost_gp = body['cost_gp']

  halt 400, { error: 'invalid slug' }.to_json unless slug.is_a?(String) && SLUG_RE.match?(slug)
  halt 400, { error: 'invalid name' }.to_json unless name.is_a?(String) && !name.empty?
  halt 400, { error: 'invalid type' }.to_json unless type.is_a?(String) && !type.empty?
  halt 400, { error: 'invalid rarity' }.to_json unless rarity.is_a?(String) && !rarity.empty?
  halt 400, { error: 'invalid cost_gp' }.to_json unless cost_gp.is_a?(Integer)

  existing = DB.execute('SELECT slug FROM items WHERE slug = ?', [slug]).first
  halt 409, { error: 'duplicate slug' }.to_json if existing

  DB.execute(
    'INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)',
    [slug, name, type, rarity, cost_gp]
  )

  status 201
  {
    slug: slug,
    name: name,
    type: type,
    rarity: rarity,
    cost_gp: cost_gp
  }.to_json
end

get '/v1/compendium/items/:slug' do
  row = DB.execute('SELECT * FROM items WHERE slug = ?', [params[:slug]]).first
  halt 404, { error: 'unknown item' }.to_json unless row

  {
    slug: row['slug'],
    name: row['name'],
    type: row['type'],
    rarity: row['rarity'],
    cost_gp: row['cost_gp']
  }.to_json
end

post '/v1/campaigns' do
  body = json_body
  id = body['id']
  name = body['name']
  dm = body['dm']

  halt 400, { error: 'invalid id' }.to_json unless id.is_a?(String) && !id.empty?
  halt 400, { error: 'invalid name' }.to_json unless name.is_a?(String) && !name.empty?
  halt 400, { error: 'invalid dm' }.to_json unless dm.is_a?(String) && !dm.empty?

  existing = DB.execute('SELECT id FROM campaigns WHERE id = ?', [id]).first
  halt 409, { error: 'duplicate id' }.to_json if existing

  DB.execute('INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)', [id, name, dm])

  status 201
  { id: id, name: name, dm: dm }.to_json
end

post '/v1/campaigns/:id/characters' do
  campaign = DB.execute('SELECT id FROM campaigns WHERE id = ?', [params[:id]]).first
  halt 404, { error: 'unknown campaign' }.to_json unless campaign

  body = json_body
  id = body['id']
  name = body['name']
  level = body['level']
  klass = body['class']

  halt 400, { error: 'invalid id' }.to_json unless id.is_a?(String) && !id.empty?
  halt 400, { error: 'invalid name' }.to_json unless name.is_a?(String) && !name.empty?
  halt 400, { error: 'invalid level' }.to_json unless level.is_a?(Integer)
  halt 400, { error: 'invalid class' }.to_json unless klass.is_a?(String) && !klass.empty?

  existing = DB.execute(
    'SELECT id FROM campaign_characters WHERE campaign_id = ? AND id = ?',
    [params[:id], id]
  ).first
  halt 409, { error: 'duplicate id' }.to_json if existing

  DB.execute(
    'INSERT INTO campaign_characters (campaign_id, id, name, level, class) VALUES (?, ?, ?, ?, ?)',
    [params[:id], id, name, level, klass]
  )

  status 201
  { id: id, name: name, level: level, class: klass }.to_json
end

post '/v1/campaigns/:id/events' do
  campaign = DB.execute('SELECT id FROM campaigns WHERE id = ?', [params[:id]]).first
  halt 404, { error: 'unknown campaign' }.to_json unless campaign

  body = json_body
  id = body['id']
  kind = body['kind']
  summary = body['summary']

  halt 400, { error: 'invalid id' }.to_json unless id.is_a?(String) && !id.empty?
  halt 400, { error: 'invalid kind' }.to_json unless kind.is_a?(String) && !kind.empty?
  halt 400, { error: 'invalid summary' }.to_json unless summary.nil? || summary.is_a?(String)

  existing = DB.execute(
    'SELECT id FROM campaign_events WHERE campaign_id = ? AND id = ?',
    [params[:id], id]
  ).first
  halt 409, { error: 'duplicate id' }.to_json if existing

  DB.execute(
    'INSERT INTO campaign_events (campaign_id, id, kind, summary) VALUES (?, ?, ?, ?)',
    [params[:id], id, kind, summary]
  )

  status 201
  { id: id, kind: kind }.to_json
end

get '/v1/campaigns/:id/state' do
  campaign = DB.execute('SELECT id, name, dm FROM campaigns WHERE id = ?', [params[:id]]).first
  halt 404, { error: 'unknown campaign' }.to_json unless campaign

  characters = DB.execute(
    'SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY rowid',
    [params[:id]]
  ).map do |row|
    { id: row['id'], name: row['name'], level: row['level'], class: row['class'] }
  end

  log_count = DB.execute(
    'SELECT COUNT(*) AS cnt FROM campaign_events WHERE campaign_id = ?',
    [params[:id]]
  ).first['cnt']

  {
    id: campaign['id'],
    name: campaign['name'],
    dm: campaign['dm'],
    characters: characters,
    log_count: log_count
  }.to_json
end

load_users_from_db
load_sessions_from_db
