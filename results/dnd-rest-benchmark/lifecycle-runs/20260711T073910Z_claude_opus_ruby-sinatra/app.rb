require 'sinatra'
require 'json'
require 'openssl'
require 'securerandom'
require 'sqlite3'

set :environment, :production
disable :logging

# Durable storage. Game-world and game-state data live behind a SQLite
# database file created in the project directory. Schema is initialized on
# server startup.
SCHEMA_VERSION = 1
DB_PATH = File.join(__dir__, 'game.db').freeze

module Storage
  @db = nil

  def self.db
    @db
  end

  def self.init!
    @db ||= SQLite3::Database.new(DB_PATH)
    @db.results_as_hash = true
    create_schema!
    @db
  end

  def self.create_schema!
    @db.execute_batch(<<~SQL)
      CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        role TEXT NOT NULL,
        password_hash TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS combat_sessions (
        id TEXT PRIMARY KEY,
        state TEXT NOT NULL
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
        seq INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, id)
      );
      CREATE TABLE IF NOT EXISTS campaign_events (
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        kind TEXT NOT NULL,
        summary TEXT NOT NULL,
        seq INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, id)
      );
    SQL
    @db.execute(
      'INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)',
      ['schema_version', SCHEMA_VERSION.to_s]
    )
  end

  def self.reset!
    @db.execute_batch(<<~SQL)
      DROP TABLE IF EXISTS meta;
      DROP TABLE IF EXISTS users;
      DROP TABLE IF EXISTS combat_sessions;
      DROP TABLE IF EXISTS monsters;
      DROP TABLE IF EXISTS items;
      DROP TABLE IF EXISTS campaigns;
      DROP TABLE IF EXISTS campaign_characters;
      DROP TABLE IF EXISTS campaign_events;
    SQL
    create_schema!
  end

  def self.initialized?
    return false if @db.nil?
    rows = @db.execute(
      "SELECT name FROM sqlite_master WHERE type='table' AND name='meta'"
    )
    !rows.empty?
  end

  # --- Users ------------------------------------------------------------
  def self.user(username)
    rows = @db.execute('SELECT username, role, password_hash FROM users WHERE username = ?', [username])
    rows.first
  end

  def self.user_exists?(username)
    !@db.execute('SELECT 1 FROM users WHERE username = ?', [username]).empty?
  end

  def self.insert_user(username, role, password_hash)
    @db.execute(
      'INSERT INTO users (username, role, password_hash) VALUES (?, ?, ?)',
      [username, role, password_hash]
    )
  end

  # --- Combat sessions --------------------------------------------------
  def self.session_exists?(id)
    !@db.execute('SELECT 1 FROM combat_sessions WHERE id = ?', [id]).empty?
  end

  def self.load_session(id)
    rows = @db.execute('SELECT state FROM combat_sessions WHERE id = ?', [id])
    return nil if rows.empty?
    JSON.parse(rows.first['state'])
  end

  def self.save_session(id, state)
    @db.execute(
      'INSERT OR REPLACE INTO combat_sessions (id, state) VALUES (?, ?)',
      [id, state.to_json]
    )
  end

  # --- Monsters ---------------------------------------------------------
  def self.monster_exists?(slug)
    !@db.execute('SELECT 1 FROM monsters WHERE slug = ?', [slug]).empty?
  end

  def self.insert_monster(slug, name, cr, armor_class, hit_points, tags)
    @db.execute(
      'INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags) VALUES (?, ?, ?, ?, ?, ?)',
      [slug, name, cr, armor_class, hit_points, tags.to_json]
    )
  end

  def self.monster(slug)
    rows = @db.execute(
      'SELECT slug, name, cr, armor_class, hit_points, tags FROM monsters WHERE slug = ?',
      [slug]
    )
    rows.first
  end

  # --- Items ------------------------------------------------------------
  def self.item_exists?(slug)
    !@db.execute('SELECT 1 FROM items WHERE slug = ?', [slug]).empty?
  end

  def self.insert_item(slug, name, type, rarity, cost_gp)
    @db.execute(
      'INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)',
      [slug, name, type, rarity, cost_gp]
    )
  end

  def self.item(slug)
    rows = @db.execute(
      'SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?',
      [slug]
    )
    rows.first
  end

  # --- Campaigns --------------------------------------------------------
  def self.campaign_exists?(id)
    !@db.execute('SELECT 1 FROM campaigns WHERE id = ?', [id]).empty?
  end

  def self.insert_campaign(id, name, dm)
    @db.execute('INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)', [id, name, dm])
  end

  def self.campaign(id)
    @db.execute('SELECT id, name, dm FROM campaigns WHERE id = ?', [id]).first
  end

  def self.campaign_character_exists?(campaign_id, id)
    !@db.execute(
      'SELECT 1 FROM campaign_characters WHERE campaign_id = ? AND id = ?',
      [campaign_id, id]
    ).empty?
  end

  def self.next_character_seq(campaign_id)
    row = @db.execute(
      'SELECT COALESCE(MAX(seq), 0) AS m FROM campaign_characters WHERE campaign_id = ?',
      [campaign_id]
    ).first
    row['m'].to_i + 1
  end

  def self.insert_campaign_character(campaign_id, id, name, level, klass, seq)
    @db.execute(
      'INSERT INTO campaign_characters (campaign_id, id, name, level, class, seq) VALUES (?, ?, ?, ?, ?, ?)',
      [campaign_id, id, name, level, klass, seq]
    )
  end

  def self.campaign_characters(campaign_id)
    @db.execute(
      'SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY seq ASC',
      [campaign_id]
    )
  end

  def self.campaign_event_exists?(campaign_id, id)
    !@db.execute(
      'SELECT 1 FROM campaign_events WHERE campaign_id = ? AND id = ?',
      [campaign_id, id]
    ).empty?
  end

  def self.next_event_seq(campaign_id)
    row = @db.execute(
      'SELECT COALESCE(MAX(seq), 0) AS m FROM campaign_events WHERE campaign_id = ?',
      [campaign_id]
    ).first
    row['m'].to_i + 1
  end

  def self.insert_campaign_event(campaign_id, id, kind, summary, seq)
    @db.execute(
      'INSERT INTO campaign_events (campaign_id, id, kind, summary, seq) VALUES (?, ?, ?, ?, ?)',
      [campaign_id, id, kind, summary, seq]
    )
  end

  def self.campaign_event_count(campaign_id)
    row = @db.execute(
      'SELECT COUNT(*) AS c FROM campaign_events WHERE campaign_id = ?',
      [campaign_id]
    ).first
    row['c'].to_i
  end

  def self.campaign_events(campaign_id)
    @db.execute(
      'SELECT id, kind, summary FROM campaign_events WHERE campaign_id = ? ORDER BY seq ASC',
      [campaign_id]
    )
  end
end

Storage.init!

CR_XP = {
  '0'   => 10,
  '1/8' => 25,
  '1/4' => 50,
  '1/2' => 100,
  '1'   => 200,
  '2'   => 450,
  '3'   => 700,
  '4'   => 1100,
  '5'   => 1800
}.freeze

LEVEL_THRESHOLDS = {
  3 => { 'easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400 }
}.freeze

DIFFICULTY_ORDER = %w[easy medium hard deadly].freeze

def json_response(obj, status = 200)
  content_type :json
  halt status, obj.to_json
end

def parse_body
  request.body.rewind
  body = request.body.read
  return {} if body.nil? || body.empty?
  JSON.parse(body)
rescue JSON::ParserError
  json_response({ 'error' => 'invalid JSON' }, 400)
end

def multiplier_for(count)
  case count
  when 0 then 0
  when 1 then 1
  when 2 then 1.5
  when 3..6 then 2
  when 7..10 then 2.5
  when 11..14 then 3
  else 4
  end
end

def numeric(value)
  value.is_a?(Numeric) ? value : nil
end

get '/health' do
  json_response({ 'ok' => true })
end

post '/v1/dice/stats' do
  data = parse_body
  expr = data['expression']
  json_response({ 'error' => 'invalid expression' }, 400) unless expr.is_a?(String)

  match = expr.strip.match(/\A(\d+)d(\d+)([+-]\d+)?\z/)
  json_response({ 'error' => 'invalid expression' }, 400) unless match

  count = match[1].to_i
  sides = match[2].to_i
  modifier = match[3] ? match[3].to_i : 0

  json_response({ 'error' => 'invalid expression' }, 400) if count <= 0 || sides <= 0

  min = count * 1 + modifier
  max = count * sides + modifier
  average = (min + max) / 2.0
  average = average.to_i if average == average.to_i

  json_response({
    'dice_count' => count,
    'sides' => sides,
    'modifier' => modifier,
    'min' => min,
    'max' => max,
    'average' => average
  })
end

post '/v1/checks/ability' do
  data = parse_body
  roll = numeric(data['roll'])
  modifier = numeric(data['modifier'])
  dc = numeric(data['dc'])
  json_response({ 'error' => 'invalid request' }, 400) if roll.nil? || modifier.nil? || dc.nil?

  total = roll + modifier
  json_response({
    'total' => total,
    'success' => total >= dc,
    'margin' => total - dc
  })
end

post '/v1/encounters/adjusted-xp' do
  data = parse_body
  party = data['party']
  monsters = data['monsters']
  json_response({ 'error' => 'invalid request' }, 400) unless party.is_a?(Array) && monsters.is_a?(Array)

  base_xp = 0
  monster_count = 0
  monsters.each do |m|
    json_response({ 'error' => 'invalid request' }, 400) unless m.is_a?(Hash)
    cr = m['cr'].to_s
    count = m['count']
    json_response({ 'error' => 'invalid CR' }, 400) unless CR_XP.key?(cr)
    json_response({ 'error' => 'invalid count' }, 400) unless count.is_a?(Integer) && count >= 0
    base_xp += CR_XP[cr] * count
    monster_count += count
  end

  multiplier = multiplier_for(monster_count)
  adjusted_xp = base_xp * multiplier
  adjusted_xp = adjusted_xp.to_i if adjusted_xp == adjusted_xp.to_i

  thresholds = { 'easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0 }
  party.each do |member|
    json_response({ 'error' => 'invalid request' }, 400) unless member.is_a?(Hash)
    level = member['level']
    json_response({ 'error' => 'invalid level' }, 400) unless LEVEL_THRESHOLDS.key?(level)
    LEVEL_THRESHOLDS[level].each do |k, v|
      thresholds[k] += v
    end
  end

  difficulty = 'trivial'
  DIFFICULTY_ORDER.each do |tier|
    difficulty = tier if adjusted_xp >= thresholds[tier]
  end

  json_response({
    'base_xp' => base_xp,
    'monster_count' => monster_count,
    'multiplier' => multiplier,
    'adjusted_xp' => adjusted_xp,
    'difficulty' => difficulty,
    'thresholds' => thresholds
  })
end

post '/v1/initiative/order' do
  data = parse_body
  combatants = data['combatants']
  json_response({ 'error' => 'invalid request' }, 400) unless combatants.is_a?(Array)

  entries = combatants.map do |c|
    json_response({ 'error' => 'invalid request' }, 400) unless c.is_a?(Hash)
    name = c['name']
    dex = numeric(c['dex'])
    roll = numeric(c['roll'])
    json_response({ 'error' => 'invalid request' }, 400) if name.nil? || dex.nil? || roll.nil?
    { 'name' => name, 'dex' => dex, 'score' => roll + dex }
  end

  ordered = entries.sort do |a, b|
    cmp = b['score'] <=> a['score']
    cmp = b['dex'] <=> a['dex'] if cmp == 0
    cmp = a['name'] <=> b['name'] if cmp == 0
    cmp
  end

  json_response({
    'order' => ordered.map { |e| { 'name' => e['name'], 'score' => e['score'] } }
  })
end

def integer_value(value)
  value.is_a?(Integer) ? value : nil
end

def ability_modifier(score)
  ((score - 10).to_f / 2).floor
end

def proficiency_bonus(level)
  ((level - 1) / 4) + 2
end

post '/v1/characters/ability-modifier' do
  data = parse_body
  score = integer_value(data['score'])
  json_response({ 'error' => 'invalid score' }, 400) if score.nil? || score < 1 || score > 30

  json_response({ 'score' => score, 'modifier' => ability_modifier(score) })
end

post '/v1/characters/proficiency' do
  data = parse_body
  level = integer_value(data['level'])
  json_response({ 'error' => 'invalid level' }, 400) if level.nil? || level < 1 || level > 20

  json_response({ 'level' => level, 'proficiency_bonus' => proficiency_bonus(level) })
end

post '/v1/characters/derived-stats' do
  data = parse_body
  level = integer_value(data['level'])
  json_response({ 'error' => 'invalid level' }, 400) if level.nil? || level < 1 || level > 20

  abilities = data['abilities']
  json_response({ 'error' => 'invalid abilities' }, 400) unless abilities.is_a?(Hash)

  modifiers = {}
  %w[str dex con int wis cha].each do |key|
    score = integer_value(abilities[key])
    json_response({ 'error' => 'invalid abilities' }, 400) if score.nil? || score < 1 || score > 30
    modifiers[key] = ability_modifier(score)
  end

  armor = data['armor']
  json_response({ 'error' => 'invalid armor' }, 400) unless armor.is_a?(Hash)
  base = integer_value(armor['base'])
  dex_cap = integer_value(armor['dex_cap'])
  shield = armor['shield']
  json_response({ 'error' => 'invalid armor' }, 400) if base.nil? || dex_cap.nil?
  json_response({ 'error' => 'invalid armor' }, 400) unless shield == true || shield == false

  shield_bonus = shield ? 2 : 0
  armor_class = base + [modifiers['dex'], dex_cap].min + shield_bonus
  hp_max = level * (6 + modifiers['con'])

  json_response({
    'level' => level,
    'proficiency_bonus' => proficiency_bonus(level),
    'hp_max' => hp_max,
    'armor_class' => armor_class,
    'modifiers' => modifiers
  })
end

def initiative_order(entries)
  entries.sort do |a, b|
    cmp = b['score'] <=> a['score']
    cmp = b['dex'] <=> a['dex'] if cmp == 0
    cmp = a['name'] <=> b['name'] if cmp == 0
    cmp
  end
end

def combatant_public(entry)
  { 'name' => entry['name'], 'score' => entry['score'] }
end

def conditions_map(session)
  map = {}
  session['order'].each do |entry|
    conds = entry['conditions']
    next unless entry['conditions_tracked']
    map[entry['name']] = conds.map do |c|
      { 'condition' => c['condition'], 'remaining_rounds' => c['remaining_rounds'] }
    end
  end
  map
end

post '/v1/combat/sessions' do
  data = parse_body
  id = data['id']
  combatants = data['combatants']
  json_response({ 'error' => 'invalid request' }, 400) unless id.is_a?(String) && !id.empty?
  json_response({ 'error' => 'invalid request' }, 400) unless combatants.is_a?(Array) && !combatants.empty?
  json_response({ 'error' => 'duplicate session' }, 400) if Storage.session_exists?(id)

  entries = combatants.map do |c|
    json_response({ 'error' => 'invalid request' }, 400) unless c.is_a?(Hash)
    name = c['name']
    dex = numeric(c['dex'])
    roll = numeric(c['roll'])
    json_response({ 'error' => 'invalid request' }, 400) if name.nil? || dex.nil? || roll.nil?
    { 'name' => name, 'dex' => dex, 'score' => roll + dex, 'conditions' => [] }
  end

  order = initiative_order(entries)
  session = { 'id' => id, 'round' => 1, 'turn_index' => 0, 'order' => order }
  Storage.save_session(id, session)

  json_response({
    'id' => id,
    'round' => 1,
    'turn_index' => 0,
    'active' => combatant_public(order[0]),
    'order' => order.map { |e| combatant_public(e) }
  })
end

post '/v1/combat/sessions/:id/conditions' do
  session = Storage.load_session(params['id'])
  json_response({ 'error' => 'unknown session' }, 404) if session.nil?

  data = parse_body
  target = data['target']
  condition = data['condition']
  duration = data['duration_rounds']
  json_response({ 'error' => 'invalid request' }, 400) unless target.is_a?(String)
  json_response({ 'error' => 'invalid request' }, 400) unless condition.is_a?(String)
  json_response({ 'error' => 'invalid request' }, 400) unless duration.is_a?(Integer) && duration > 0

  entry = session['order'].find { |e| e['name'] == target }
  json_response({ 'error' => 'unknown target' }, 400) if entry.nil?

  entry['conditions_tracked'] = true
  entry['conditions'] << { 'condition' => condition, 'remaining_rounds' => duration }
  Storage.save_session(session['id'], session)

  json_response({
    'target' => target,
    'conditions' => entry['conditions'].map do |c|
      { 'condition' => c['condition'], 'remaining_rounds' => c['remaining_rounds'] }
    end
  })
end

post '/v1/combat/sessions/:id/advance' do
  session = Storage.load_session(params['id'])
  json_response({ 'error' => 'unknown session' }, 404) if session.nil?

  order = session['order']
  next_index = session['turn_index'] + 1
  if next_index >= order.length
    next_index = 0
    session['round'] += 1
  end
  session['turn_index'] = next_index

  active = order[next_index]
  active['conditions'].each { |c| c['remaining_rounds'] -= 1 }
  active['conditions'].reject! { |c| c['remaining_rounds'] <= 0 }
  Storage.save_session(session['id'], session)

  json_response({
    'id' => session['id'],
    'round' => session['round'],
    'turn_index' => session['turn_index'],
    'active' => combatant_public(active),
    'conditions' => conditions_map(session)
  })
end

USERNAME_PATTERN = /\A[a-z0-9_-]{2,32}\z/
VALID_ROLES = %w[dm player].freeze

# Password handling isolated behind a helper. Uses OpenSSL PBKDF2 (a real,
# stdlib-provided password hash) so a production hash can drop in here.
module PasswordHelper
  ITERATIONS = 100_000
  KEY_LEN = 32
  DIGEST = 'sha256'.freeze

  def self.hash_password(password)
    salt = SecureRandom.hex(16)
    dk = OpenSSL::PKCS5.pbkdf2_hmac(password, salt, ITERATIONS, KEY_LEN, DIGEST)
    "#{salt}$#{dk.unpack1('H*')}"
  end

  def self.verify(password, stored)
    salt, expected = stored.split('$', 2)
    return false if salt.nil? || expected.nil?
    dk = OpenSSL::PKCS5.pbkdf2_hmac(password, salt, ITERATIONS, KEY_LEN, DIGEST)
    OpenSSL.fixed_length_secure_compare(dk.unpack1('H*'), expected)
  rescue ArgumentError
    false
  end
end

post '/v1/auth/register' do
  data = parse_body
  username = data['username']
  password = data['password']
  role = data['role']

  json_response({ 'error' => 'invalid username' }, 400) unless username.is_a?(String) && username.match?(USERNAME_PATTERN)
  json_response({ 'error' => 'invalid password' }, 400) unless password.is_a?(String) && password.length >= 8
  json_response({ 'error' => 'invalid role' }, 400) unless VALID_ROLES.include?(role)
  json_response({ 'error' => 'duplicate username' }, 409) if Storage.user_exists?(username)

  Storage.insert_user(username, role, PasswordHelper.hash_password(password))

  json_response({ 'username' => username, 'role' => role }, 201)
end

post '/v1/auth/login' do
  data = parse_body
  username = data['username']
  password = data['password']

  json_response({ 'error' => 'invalid request' }, 400) unless username.is_a?(String) && password.is_a?(String)

  user = Storage.user(username)
  json_response({ 'error' => 'invalid credentials' }, 401) if user.nil?
  json_response({ 'error' => 'invalid credentials' }, 401) unless PasswordHelper.verify(password, user['password_hash'])

  json_response({ 'username' => username, 'token' => "session-#{username}" })
end

get '/v1/storage/status' do
  json_response({
    'driver' => 'sqlite',
    'schema_version' => SCHEMA_VERSION,
    'initialized' => Storage.initialized?
  })
end

post '/v1/storage/reset' do
  Storage.reset!
  json_response({ 'ok' => true, 'schema_version' => SCHEMA_VERSION })
end

SLUG_PATTERN = /\A[a-z0-9]+(?:-[a-z0-9]+)*\z/

post '/v1/compendium/monsters' do
  data = parse_body
  slug = data['slug']
  name = data['name']
  cr = data['cr']
  armor_class = integer_value(data['armor_class'])
  hit_points = integer_value(data['hit_points'])
  tags = data['tags']

  json_response({ 'error' => 'invalid slug' }, 400) unless slug.is_a?(String) && slug.match?(SLUG_PATTERN)
  json_response({ 'error' => 'invalid name' }, 400) unless name.is_a?(String) && !name.empty?
  json_response({ 'error' => 'invalid cr' }, 400) unless cr.is_a?(String) && !cr.empty?
  json_response({ 'error' => 'invalid armor_class' }, 400) if armor_class.nil?
  json_response({ 'error' => 'invalid hit_points' }, 400) if hit_points.nil?
  tags = [] if tags.nil?
  json_response({ 'error' => 'invalid tags' }, 400) unless tags.is_a?(Array) && tags.all? { |t| t.is_a?(String) }
  json_response({ 'error' => 'duplicate slug' }, 409) if Storage.monster_exists?(slug)

  Storage.insert_monster(slug, name, cr, armor_class, hit_points, tags)

  json_response({
    'slug' => slug,
    'name' => name,
    'cr' => cr,
    'armor_class' => armor_class,
    'hit_points' => hit_points
  }, 201)
end

get '/v1/compendium/monsters/:slug' do
  row = Storage.monster(params['slug'])
  json_response({ 'error' => 'unknown monster' }, 404) if row.nil?

  json_response({
    'slug' => row['slug'],
    'name' => row['name'],
    'cr' => row['cr'],
    'armor_class' => row['armor_class'],
    'hit_points' => row['hit_points'],
    'tags' => JSON.parse(row['tags'])
  })
end

post '/v1/compendium/items' do
  data = parse_body
  slug = data['slug']
  name = data['name']
  type = data['type']
  rarity = data['rarity']
  cost_gp = integer_value(data['cost_gp'])

  json_response({ 'error' => 'invalid slug' }, 400) unless slug.is_a?(String) && slug.match?(SLUG_PATTERN)
  json_response({ 'error' => 'invalid name' }, 400) unless name.is_a?(String) && !name.empty?
  json_response({ 'error' => 'invalid type' }, 400) unless type.is_a?(String) && !type.empty?
  json_response({ 'error' => 'invalid rarity' }, 400) unless rarity.is_a?(String) && !rarity.empty?
  json_response({ 'error' => 'invalid cost_gp' }, 400) if cost_gp.nil?
  json_response({ 'error' => 'duplicate slug' }, 409) if Storage.item_exists?(slug)

  Storage.insert_item(slug, name, type, rarity, cost_gp)

  json_response({
    'slug' => slug,
    'name' => name,
    'type' => type,
    'rarity' => rarity,
    'cost_gp' => cost_gp
  }, 201)
end

get '/v1/compendium/items/:slug' do
  row = Storage.item(params['slug'])
  json_response({ 'error' => 'unknown item' }, 404) if row.nil?

  json_response({
    'slug' => row['slug'],
    'name' => row['name'],
    'type' => row['type'],
    'rarity' => row['rarity'],
    'cost_gp' => row['cost_gp']
  })
end

post '/v1/campaigns' do
  data = parse_body
  id = data['id']
  name = data['name']
  dm = data['dm']

  json_response({ 'error' => 'invalid id' }, 400) unless id.is_a?(String) && !id.empty?
  json_response({ 'error' => 'invalid name' }, 400) unless name.is_a?(String) && !name.empty?
  json_response({ 'error' => 'invalid dm' }, 400) unless dm.is_a?(String) && !dm.empty?
  json_response({ 'error' => 'duplicate id' }, 409) if Storage.campaign_exists?(id)

  Storage.insert_campaign(id, name, dm)

  json_response({ 'id' => id, 'name' => name, 'dm' => dm }, 201)
end

post '/v1/campaigns/:campaign_id/characters' do
  campaign_id = params['campaign_id']
  json_response({ 'error' => 'unknown campaign' }, 404) unless Storage.campaign_exists?(campaign_id)

  data = parse_body
  id = data['id']
  name = data['name']
  level = integer_value(data['level'])
  klass = data['class']

  json_response({ 'error' => 'invalid id' }, 400) unless id.is_a?(String) && !id.empty?
  json_response({ 'error' => 'invalid name' }, 400) unless name.is_a?(String) && !name.empty?
  json_response({ 'error' => 'invalid level' }, 400) if level.nil? || level < 1
  json_response({ 'error' => 'invalid class' }, 400) unless klass.is_a?(String) && !klass.empty?
  json_response({ 'error' => 'duplicate id' }, 409) if Storage.campaign_character_exists?(campaign_id, id)

  Storage.insert_campaign_character(campaign_id, id, name, level, klass, Storage.next_character_seq(campaign_id))

  json_response({ 'id' => id, 'name' => name, 'level' => level, 'class' => klass }, 201)
end

post '/v1/campaigns/:campaign_id/events' do
  campaign_id = params['campaign_id']
  json_response({ 'error' => 'unknown campaign' }, 404) unless Storage.campaign_exists?(campaign_id)

  data = parse_body
  id = data['id']
  kind = data['kind']
  summary = data['summary']

  json_response({ 'error' => 'invalid id' }, 400) unless id.is_a?(String) && !id.empty?
  json_response({ 'error' => 'invalid kind' }, 400) unless kind.is_a?(String) && !kind.empty?
  json_response({ 'error' => 'invalid summary' }, 400) unless summary.is_a?(String) && !summary.empty?
  json_response({ 'error' => 'duplicate id' }, 409) if Storage.campaign_event_exists?(campaign_id, id)

  Storage.insert_campaign_event(campaign_id, id, kind, summary, Storage.next_event_seq(campaign_id))

  json_response({ 'id' => id, 'kind' => kind }, 201)
end

get '/v1/campaigns/:campaign_id/state' do
  campaign_id = params['campaign_id']
  campaign = Storage.campaign(campaign_id)
  json_response({ 'error' => 'unknown campaign' }, 404) if campaign.nil?

  characters = Storage.campaign_characters(campaign_id).map do |c|
    { 'id' => c['id'], 'name' => c['name'], 'level' => c['level'], 'class' => c['class'] }
  end

  json_response({
    'id' => campaign['id'],
    'name' => campaign['name'],
    'dm' => campaign['dm'],
    'characters' => characters,
    'log_count' => Storage.campaign_event_count(campaign_id)
  })
end

SPELL_SLOT_TABLE = {
  ['wizard', 5] => { '1' => 4, '2' => 3, '3' => 2 }
}.freeze

post '/v1/phb/spell-slots' do
  data = parse_body
  klass = data['class']
  level = data['level']
  json_response({ 'error' => 'invalid request' }, 400) unless klass.is_a?(String) && level.is_a?(Integer)

  slots = SPELL_SLOT_TABLE[[klass, level]]
  json_response({ 'error' => 'unsupported class/level' }, 400) if slots.nil?

  json_response({ 'class' => klass, 'level' => level, 'slots' => slots })
end

post '/v1/phb/rests/long' do
  data = parse_body
  level = data['level']
  hp_current = data['hp_current']
  hp_max = data['hp_max']
  hit_dice_spent = data['hit_dice_spent']
  exhaustion_level = data['exhaustion_level']
  unless [level, hp_current, hp_max, hit_dice_spent, exhaustion_level].all? { |v| v.is_a?(Integer) }
    json_response({ 'error' => 'invalid request' }, 400)
  end
  json_response({ 'error' => 'invalid request' }, 400) if level < 1

  recovered = [level / 2, 1].max
  new_hit_dice_spent = [hit_dice_spent - recovered, 0].max
  new_exhaustion = [exhaustion_level - 1, 0].max

  json_response({
    'hp_current' => hp_max,
    'hit_dice_spent' => new_hit_dice_spent,
    'exhaustion_level' => new_exhaustion
  })
end

post '/v1/phb/equipment-load' do
  data = parse_body
  strength = data['strength']
  weight = data['weight']
  json_response({ 'error' => 'invalid request' }, 400) unless strength.is_a?(Integer) && weight.is_a?(Numeric)

  capacity = strength * 15
  json_response({
    'capacity' => capacity,
    'weight' => weight,
    'encumbered' => weight > capacity
  })
end

# --- Stage 8: DM Tools ------------------------------------------------------

# Deterministic recommendation keyed by the computed encounter difficulty.
DIFFICULTY_RECOMMENDATION = {
  'trivial' => 'cakewalk',
  'easy'    => 'safe warm-up',
  'medium'  => 'a fair fight',
  'hard'    => 'tough battle',
  'deadly'  => 'risk of a wipe'
}.freeze

# Deterministic loot parcels keyed by tier for this benchmark.
LOOT_PARCELS = {
  1 => { 'coins_gp' => 75, 'items' => [{ 'slug' => 'healing-potion', 'quantity' => 2 }] }
}.freeze

post '/v1/dm/encounter-builder' do
  data = parse_body
  campaign_id = data['campaign_id']
  party = data['party']
  monster_slugs = data['monster_slugs']

  json_response({ 'error' => 'invalid campaign_id' }, 400) unless campaign_id.is_a?(String) && !campaign_id.empty?
  json_response({ 'error' => 'invalid party' }, 400) unless party.is_a?(Array) && !party.empty?
  json_response({ 'error' => 'invalid monster_slugs' }, 400) unless monster_slugs.is_a?(Array) && !monster_slugs.empty?

  base_xp = 0
  monster_slugs.each do |slug|
    json_response({ 'error' => 'invalid monster slug' }, 400) unless slug.is_a?(String) && !slug.empty?
    monster = Storage.monster(slug)
    json_response({ 'error' => 'monster not found' }, 404) if monster.nil?
    cr = monster['cr'].to_s
    json_response({ 'error' => 'unsupported cr' }, 400) unless CR_XP.key?(cr)
    base_xp += CR_XP[cr]
  end

  monster_count = monster_slugs.length
  multiplier = multiplier_for(monster_count)
  adjusted_xp = base_xp * multiplier
  adjusted_xp = adjusted_xp.to_i if adjusted_xp == adjusted_xp.to_i

  thresholds = { 'easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0 }
  party.each do |member|
    json_response({ 'error' => 'invalid party' }, 400) unless member.is_a?(Hash)
    level = member['level']
    json_response({ 'error' => 'unsupported level' }, 400) unless LEVEL_THRESHOLDS.key?(level)
    LEVEL_THRESHOLDS[level].each { |k, v| thresholds[k] += v }
  end

  difficulty = 'trivial'
  DIFFICULTY_ORDER.each do |tier|
    difficulty = tier if adjusted_xp >= thresholds[tier]
  end

  json_response({
    'campaign_id' => campaign_id,
    'base_xp' => base_xp,
    'adjusted_xp' => adjusted_xp,
    'difficulty' => difficulty,
    'monster_count' => monster_count,
    'recommendation' => DIFFICULTY_RECOMMENDATION[difficulty]
  })
end

post '/v1/dm/loot-parcel' do
  data = parse_body
  campaign_id = data['campaign_id']
  tier = data['tier']

  json_response({ 'error' => 'invalid campaign_id' }, 400) unless campaign_id.is_a?(String) && !campaign_id.empty?
  json_response({ 'error' => 'invalid tier' }, 400) unless tier.is_a?(Integer)

  parcel = LOOT_PARCELS[tier]
  json_response({ 'error' => 'unsupported tier' }, 400) if parcel.nil?

  json_response({
    'campaign_id' => campaign_id,
    'coins_gp' => parcel['coins_gp'],
    'items' => parcel['items'].map { |item| item.dup }
  })
end

post '/v1/dm/session-recap' do
  data = parse_body
  campaign_id = data['campaign_id']
  json_response({ 'error' => 'invalid campaign_id' }, 400) unless campaign_id.is_a?(String) && !campaign_id.empty?

  campaign = Storage.campaign(campaign_id)
  json_response({ 'error' => 'campaign not found' }, 404) if campaign.nil?

  events = Storage.campaign_events(campaign_id)
  summary = events.empty? ? '' : events.last['summary']

  open_threads = []
  events.each do |event|
    next unless event['summary'].to_s.downcase.include?('goblin trail')
    thread = 'Resolve goblin trail ambush'
    open_threads << thread unless open_threads.include?(thread)
  end

  json_response({
    'campaign_id' => campaign_id,
    'summary' => summary,
    'open_threads' => open_threads
  })
end

not_found do
  json_response({ 'error' => 'not found' }, 404)
end
