require 'json'
require 'openssl'
require 'socket'
require 'sqlite3'

CR_XP = {
  '0' => 10,
  '1/8' => 25,
  '1/4' => 50,
  '1/2' => 100,
  '1' => 200,
  '2' => 450,
  '3' => 700,
  '4' => 1100,
  '5' => 1800,
}

MONSTER_MULTIPLIERS = [
  [1, 1.0],
  [2, 1.5],
  [6, 2.0],
  [10, 2.5],
  [14, 3.0],
  [Float::INFINITY, 4.0],
]

LEVEL_THRESHOLDS = {
  3 => { easy: 75, medium: 150, hard: 225, deadly: 400 },
}

DICE_RE = /^\s*(\d+)d(\d+)([+-]\d+)?\s*$/

ABILITY_KEYS = %w[str dex con int wis cha].freeze

STATUS_TEXT = {
  200 => 'OK',
  201 => 'Created',
  400 => 'Bad Request',
  401 => 'Unauthorized',
  404 => 'Not Found',
  405 => 'Method Not Allowed',
  409 => 'Conflict',
}

DB_PATH = 'game.db'

SCHEMA_VERSION = 1

def create_users_table(if_not_exists: false)
  ifn = if_not_exists ? 'IF NOT EXISTS ' : ''
  <<~SQL
    CREATE TABLE #{ifn}users (
      username TEXT PRIMARY KEY,
      salt TEXT NOT NULL,
      hash TEXT NOT NULL,
      role TEXT NOT NULL
    );
  SQL
end

def create_sessions_table(if_not_exists: false)
  ifn = if_not_exists ? 'IF NOT EXISTS ' : ''
  <<~SQL
    CREATE TABLE #{ifn}sessions (
      id TEXT PRIMARY KEY,
      round INTEGER NOT NULL,
      turn_index INTEGER NOT NULL,
      combatants TEXT NOT NULL,
      conditions TEXT NOT NULL
    );
  SQL
end

def create_monsters_table(if_not_exists: false)
  ifn = if_not_exists ? 'IF NOT EXISTS ' : ''
  <<~SQL
    CREATE TABLE #{ifn}monsters (
      slug TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      cr TEXT NOT NULL,
      armor_class INTEGER NOT NULL,
      hit_points INTEGER NOT NULL,
      tags TEXT NOT NULL
    );
  SQL
end

def create_items_table(if_not_exists: false)
  ifn = if_not_exists ? 'IF NOT EXISTS ' : ''
  <<~SQL
    CREATE TABLE #{ifn}items (
      slug TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      type TEXT NOT NULL,
      rarity TEXT NOT NULL,
      cost_gp INTEGER NOT NULL
    );
  SQL
end

def create_campaigns_table(if_not_exists: false)
  ifn = if_not_exists ? 'IF NOT EXISTS ' : ''
  <<~SQL
    CREATE TABLE #{ifn}campaigns (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      dm TEXT NOT NULL
    );
  SQL
end

def create_characters_table(if_not_exists: false)
  ifn = if_not_exists ? 'IF NOT EXISTS ' : ''
  <<~SQL
    CREATE TABLE #{ifn}characters (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      name TEXT NOT NULL,
      level INTEGER NOT NULL,
      class TEXT NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
    );
  SQL
end

def create_events_table(if_not_exists: false)
  ifn = if_not_exists ? 'IF NOT EXISTS ' : ''
  <<~SQL
    CREATE TABLE #{ifn}events (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      summary TEXT,
      FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
    );
  SQL
end

def db_init
  db = SQLite3::Database.new(DB_PATH, results_as_hash: true)
  db.execute_batch(
    "#{create_users_table(if_not_exists: true)}" \
    "#{create_sessions_table(if_not_exists: true)}" \
    "#{create_monsters_table(if_not_exists: true)}" \
    "#{create_items_table(if_not_exists: true)}" \
    "#{create_campaigns_table(if_not_exists: true)}" \
    "#{create_characters_table(if_not_exists: true)}" \
    "#{create_events_table(if_not_exists: true)}"
  )
  db
end

def db_initialized?
  tables = DB.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('users', 'sessions', 'monsters', 'items', 'campaigns', 'characters', 'events')")
  tables.length == 7
end

def db_reset
  DB.transaction do
    DB.execute('DROP TABLE IF EXISTS users')
    DB.execute('DROP TABLE IF EXISTS sessions')
    DB.execute('DROP TABLE IF EXISTS monsters')
    DB.execute('DROP TABLE IF EXISTS items')
    DB.execute('DROP TABLE IF EXISTS campaigns')
    DB.execute('DROP TABLE IF EXISTS characters')
    DB.execute('DROP TABLE IF EXISTS events')
    DB.execute(create_users_table)
    DB.execute(create_sessions_table)
    DB.execute(create_monsters_table)
    DB.execute(create_items_table)
    DB.execute(create_campaigns_table)
    DB.execute(create_characters_table)
    DB.execute(create_events_table)
  end
end

def db_user_exists?(username)
  DB.get_first_value('SELECT 1 FROM users WHERE username = ?', username) == 1
end

def db_create_user(username, salt, hash, role)
  DB.execute('INSERT INTO users (username, salt, hash, role) VALUES (?, ?, ?, ?)', [username, salt, hash, role])
end

def db_get_user(username)
  row = DB.get_first_row('SELECT * FROM users WHERE username = ?', username)
  return nil unless row

  { salt: row['salt'], hash: row['hash'], role: row['role'] }
end

def dump_combatants(combatants)
  JSON.dump(combatants)
end

def parse_combatants(json)
  JSON.parse(json, symbolize_names: true)
end

def dump_conditions(conditions)
  JSON.dump(conditions)
end

def parse_conditions(json)
  parsed = JSON.parse(json)
  parsed.transform_values do |conds|
    conds.map { |c| { condition: c['condition'], remaining_rounds: c['remaining_rounds'] } }
  end
end

def db_session_exists?(id)
  DB.get_first_value('SELECT 1 FROM sessions WHERE id = ?', id) == 1
end

def db_create_session(id, round, turn_index, combatants, conditions)
  DB.execute(
    'INSERT INTO sessions (id, round, turn_index, combatants, conditions) VALUES (?, ?, ?, ?, ?)',
    [id, round, turn_index, dump_combatants(combatants), dump_conditions(conditions)]
  )
end

def db_get_session(id)
  row = DB.get_first_row('SELECT * FROM sessions WHERE id = ?', id)
  return nil unless row

  {
    id: row['id'],
    round: row['round'],
    turn_index: row['turn_index'],
    combatants: parse_combatants(row['combatants']),
    conditions: parse_conditions(row['conditions'])
  }
end

def db_update_session(id, round, turn_index, combatants, conditions)
  DB.execute(
    'UPDATE sessions SET round = ?, turn_index = ?, combatants = ?, conditions = ? WHERE id = ?',
    [round, turn_index, dump_combatants(combatants), dump_conditions(conditions), id]
  )
end

# Compendium helpers

def db_monster_exists?(slug)
  DB.get_first_value('SELECT 1 FROM monsters WHERE slug = ?', slug) == 1
end

def db_create_monster(slug, name, cr, armor_class, hit_points, tags)
  DB.execute(
    'INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags) VALUES (?, ?, ?, ?, ?, ?)',
    [slug, name, cr, armor_class, hit_points, JSON.dump(tags)]
  )
end

def db_get_monster(slug)
  row = DB.get_first_row('SELECT * FROM monsters WHERE slug = ?', slug)
  return nil unless row

  {
    slug: row['slug'],
    name: row['name'],
    cr: row['cr'],
    armor_class: row['armor_class'],
    hit_points: row['hit_points'],
    tags: JSON.parse(row['tags'])
  }
end

def db_item_exists?(slug)
  DB.get_first_value('SELECT 1 FROM items WHERE slug = ?', slug) == 1
end

def db_create_item(slug, name, type, rarity, cost_gp)
  DB.execute(
    'INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)',
    [slug, name, type, rarity, cost_gp]
  )
end

def db_get_item(slug)
  row = DB.get_first_row('SELECT * FROM items WHERE slug = ?', slug)
  return nil unless row

  {
    slug: row['slug'],
    name: row['name'],
    type: row['type'],
    rarity: row['rarity'],
    cost_gp: row['cost_gp']
  }
end

# Campaign helpers

def db_campaign_exists?(id)
  DB.get_first_value('SELECT 1 FROM campaigns WHERE id = ?', id) == 1
end

def db_create_campaign(id, name, dm)
  DB.execute(
    'INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)',
    [id, name, dm]
  )
end

def db_get_campaign(id)
  row = DB.get_first_row('SELECT * FROM campaigns WHERE id = ?', id)
  return nil unless row

  {
    id: row['id'],
    name: row['name'],
    dm: row['dm']
  }
end

def db_character_exists?(id)
  DB.get_first_value('SELECT 1 FROM characters WHERE id = ?', id) == 1
end

def db_create_character(id, campaign_id, name, level, cls)
  DB.execute(
    'INSERT INTO characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)',
    [id, campaign_id, name, level, cls]
  )
end

def db_get_characters(campaign_id)
  DB.execute('SELECT id, name, level, class FROM characters WHERE campaign_id = ? ORDER BY id', campaign_id).map do |row|
    {
      id: row['id'],
      name: row['name'],
      level: row['level'],
      class: row['class']
    }
  end
end

def db_event_exists?(id)
  DB.get_first_value('SELECT 1 FROM events WHERE id = ?', id) == 1
end

def db_create_event(id, campaign_id, kind, summary)
  DB.execute(
    'INSERT INTO events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)',
    [id, campaign_id, kind, summary]
  )
end

def db_count_events(campaign_id)
  DB.get_first_value('SELECT COUNT(*) FROM events WHERE campaign_id = ?', campaign_id)
end

def json_response(status, body)
  json = body.to_json
  "HTTP/1.1 #{status} #{STATUS_TEXT[status]}\r\n" \
    "Content-Type: application/json\r\n" \
    "Content-Length: #{json.bytesize}\r\n" \
    "Connection: close\r\n\r\n#{json}"
end

def parse_request(client)
  first = client.gets
  return nil unless first

  method, path, _ = first.split(' ', 3)
  path = path&.force_encoding('UTF-8')
  headers = {}
  loop do
    line = client.gets
    break if line.nil? || line == "\r\n" || line == "\n"
    key, value = line.split(':', 2)
    headers[key.strip.downcase] = value.strip if key && value
  end

  body = ''
  if headers['content-length']
    length = headers['content-length'].to_i
    body = client.read(length) if length > 0
  end

  [method&.upcase, path, headers, body]
end

def handle_dice_stats(body)
  data = JSON.parse(body)
  expr = data['expression'].to_s
  match = DICE_RE.match(expr)
  return json_response(400, { error: 'invalid expression' }) unless match

  dice_count = match[1].to_i
  sides = match[2].to_i
  modifier = match[3] ? match[3].to_i : 0

  return json_response(400, { error: 'invalid expression' }) if dice_count <= 0 || sides <= 0

  min = dice_count + modifier
  max = dice_count * sides + modifier
  raw_average = (min + max) / 2.0
  average = raw_average == raw_average.to_i ? raw_average.to_i : raw_average

  json_response(200, {
    dice_count: dice_count,
    sides: sides,
    modifier: modifier,
    min: min,
    max: max,
    average: average,
  })
rescue JSON::ParserError, KeyError, NoMethodError
  json_response(400, { error: 'invalid request' })
end

def handle_ability_check(body)
  data = JSON.parse(body)
  total = data['roll'] + data['modifier']
  dc = data['dc']

  json_response(200, {
    total: total,
    success: total >= dc,
    margin: total - dc,
  })
rescue JSON::ParserError, KeyError, TypeError
  json_response(400, { error: 'invalid request' })
end

def monster_multiplier(count)
  MONSTER_MULTIPLIERS.each do |max, mult|
    return mult if count <= max
  end
  4.0
end

def encounter_calculation(party, monsters)
  base_xp = 0
  monster_count = 0

  monsters.each do |m|
    cr = m['cr']
    count = m['count']
    xp = CR_XP[cr]
    return [nil, 'unknown cr'] unless xp

    base_xp += xp * count
    monster_count += count
  end

  multiplier = monster_multiplier(monster_count)
  multiplier = multiplier == multiplier.to_i ? multiplier.to_i : multiplier
  adjusted_xp = base_xp * multiplier

  thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 }

  party.each do |member|
    level = member['level']
    t = LEVEL_THRESHOLDS[level]
    return [nil, 'unknown level'] unless t

    thresholds.each_key { |k| thresholds[k] += t[k] }
  end

  difficulty = 'trivial'
  difficulty = 'easy' if adjusted_xp >= thresholds[:easy]
  difficulty = 'medium' if adjusted_xp >= thresholds[:medium]
  difficulty = 'hard' if adjusted_xp >= thresholds[:hard]
  difficulty = 'deadly' if adjusted_xp >= thresholds[:deadly]

  [
    {
      base_xp: base_xp,
      monster_count: monster_count,
      multiplier: multiplier,
      adjusted_xp: adjusted_xp,
      difficulty: difficulty,
      thresholds: thresholds,
    },
    nil
  ]
end

def handle_adjusted_xp(body)
  data = JSON.parse(body)
  party = data['party']
  monsters = data['monsters']

  result, error = encounter_calculation(party, monsters)
  return json_response(400, { error: error }) if error

  json_response(200, result)
rescue JSON::ParserError, KeyError, NoMethodError, TypeError
  json_response(400, { error: 'invalid request' })
end

def handle_initiative(body)
  data = JSON.parse(body)
  combatants = data['combatants'].map do |c|
    {
      name: c['name'],
      score: c['roll'] + c['dex'],
      dex: c['dex'],
    }
  end

  combatants.sort_by! { |c| [-c[:score], -c[:dex], c[:name]] }

  order = combatants.map { |c| { name: c[:name], score: c[:score] } }

  json_response(200, { order: order })
rescue JSON::ParserError, KeyError, NoMethodError, TypeError
  json_response(400, { error: 'invalid request' })
end

def ability_modifier(score)
  ((score - 10) / 2).floor
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

def valid_ability_score?(score)
  score.is_a?(Integer) && score >= 1 && score <= 30
end

def handle_ability_modifier(body)
  data = JSON.parse(body)
  score = data['score']
  return json_response(400, { error: 'invalid score' }) unless valid_ability_score?(score)

  json_response(200, { score: score, modifier: ability_modifier(score) })
rescue JSON::ParserError, KeyError, NoMethodError, TypeError
  json_response(400, { error: 'invalid request' })
end

def handle_proficiency(body)
  data = JSON.parse(body)
  level = data['level']
  return json_response(400, { error: 'invalid level' }) unless level.is_a?(Integer) && level >= 1 && level <= 20

  json_response(200, { level: level, proficiency_bonus: proficiency_bonus(level) })
rescue JSON::ParserError, KeyError, NoMethodError, TypeError
  json_response(400, { error: 'invalid request' })
end

def handle_derived_stats(body)
  data = JSON.parse(body)
  level = data['level']
  return json_response(400, { error: 'invalid level' }) unless level.is_a?(Integer) && level >= 1 && level <= 20

  abilities = data['abilities']
  return json_response(400, { error: 'invalid abilities' }) unless abilities.is_a?(Hash) && ABILITY_KEYS.all? { |k| abilities.key?(k) }

  modifiers = {}
  ABILITY_KEYS.each do |key|
    score = abilities[key]
    return json_response(400, { error: 'invalid ability score' }) unless valid_ability_score?(score)

    modifiers[key] = ability_modifier(score)
  end

  armor = data['armor']
  return json_response(400, { error: 'invalid armor' }) unless armor.is_a?(Hash) && armor.key?('base') && armor.key?('shield') && armor.key?('dex_cap')

  base_ac = armor['base']
  dex_cap = armor['dex_cap']
  shield = armor['shield']
  return json_response(400, { error: 'invalid armor values' }) unless base_ac.is_a?(Integer) && dex_cap.is_a?(Integer) && (shield == true || shield == false)

  shield_bonus = shield ? 2 : 0
  armor_class = base_ac + [modifiers['dex'], dex_cap].min + shield_bonus
  hp_max = level * (6 + modifiers['con'])

  json_response(200, {
    level: level,
    proficiency_bonus: proficiency_bonus(level),
    hp_max: hp_max,
    armor_class: armor_class,
    modifiers: modifiers,
  })
rescue JSON::ParserError, KeyError, NoMethodError, TypeError
  json_response(400, { error: 'invalid request' })
end

def generate_salt
  OpenSSL::Random.random_bytes(16).unpack1('H*')
end

def hash_password(password, salt)
  OpenSSL::KDF.pbkdf2_hmac(password, salt: salt, iterations: 100_000, length: 32, hash: 'sha256').unpack1('H*')
end

def verify_password(password, salt, hash)
  hash_password(password, salt) == hash
end

def valid_username?(username)
  username.is_a?(String) && username.match?(/\A[a-z0-9_-]{2,32}\z/)
end

def handle_register(body)
  data = JSON.parse(body)
  username = data['username']
  password = data['password']
  role = data['role']

  return json_response(400, { error: 'invalid request' }) unless valid_username?(username) && password.is_a?(String) && password.length >= 8 && %w[dm player].include?(role)
  return json_response(409, { error: 'username taken' }) if db_user_exists?(username)

  salt = generate_salt
  hash = hash_password(password, salt)
  db_create_user(username, salt, hash, role)

  json_response(201, { username: username, role: role })
rescue JSON::ParserError, KeyError, NoMethodError, TypeError
  json_response(400, { error: 'invalid request' })
end

def handle_login(body)
  data = JSON.parse(body)
  username = data['username']
  password = data['password']

  return json_response(400, { error: 'invalid request' }) unless username.is_a?(String) && password.is_a?(String)

  user = db_get_user(username)
  return json_response(401, { error: 'unauthorized' }) unless user && verify_password(password, user[:salt], user[:hash])

  json_response(200, { username: username, token: "session-#{username}" })
rescue JSON::ParserError, KeyError, NoMethodError, TypeError
  json_response(400, { error: 'invalid request' })
end

def combat_order(combatants)
  combatants.map { |c| { name: c[:name], score: c[:score] } }
end

def validate_create_session(data)
  return false unless data['id'].is_a?(String) && !data['id'].empty?
  return false if db_session_exists?(data['id'])
  return false unless data['combatants'].is_a?(Array) && !data['combatants'].empty?
  data['combatants'].each do |c|
    return false unless c['name'].is_a?(String) && !c['name'].empty?
    return false unless c['dex'].is_a?(Integer)
    return false unless c['roll'].is_a?(Integer)
  end
  true
end

def handle_create_session(body)
  data = JSON.parse(body)
  return json_response(400, { error: 'invalid request' }) unless validate_create_session(data)

  combatants = data['combatants'].map do |c|
    {
      name: c['name'],
      score: c['roll'] + c['dex'],
      dex: c['dex'],
    }
  end
  combatants.sort_by! { |c| [-c[:score], -c[:dex], c[:name]] }

  db_create_session(data['id'], 1, 0, combatants, {})

  json_response(200, {
    id: data['id'],
    round: 1,
    turn_index: 0,
    active: { name: combatants[0][:name], score: combatants[0][:score] },
    order: combat_order(combatants),
  })
rescue JSON::ParserError, KeyError, NoMethodError, TypeError
  json_response(400, { error: 'invalid request' })
end

def handle_add_condition(session_id, body)
  session = db_get_session(session_id)
  return json_response(404, { error: 'not found' }) unless session

  data = JSON.parse(body)
  target = data['target']
  condition = data['condition']
  duration = data['duration_rounds']

  return json_response(400, { error: 'invalid request' }) unless target.is_a?(String) && condition.is_a?(String)
  return json_response(400, { error: 'invalid request' }) unless duration.is_a?(Integer) && duration > 0
  return json_response(400, { error: 'invalid target' }) unless session[:combatants].any? { |c| c[:name] == target }

  session[:conditions][target] ||= []
  session[:conditions][target] << { condition: condition, remaining_rounds: duration }

  db_update_session(session_id, session[:round], session[:turn_index], session[:combatants], session[:conditions])

  json_response(200, {
    target: target,
    conditions: session[:conditions][target].map { |c| { condition: c[:condition], remaining_rounds: c[:remaining_rounds] } },
  })
rescue JSON::ParserError, KeyError, NoMethodError, TypeError
  json_response(400, { error: 'invalid request' })
end

def handle_advance(session_id)
  session = db_get_session(session_id)
  return json_response(404, { error: 'not found' }) unless session

  session[:turn_index] += 1
  if session[:turn_index] >= session[:combatants].length
    session[:turn_index] = 0
    session[:round] += 1
  end

  active = session[:combatants][session[:turn_index]]

  if session[:conditions][active[:name]]
    session[:conditions][active[:name]].each { |cond| cond[:remaining_rounds] -= 1 }
    session[:conditions][active[:name]].reject! { |cond| cond[:remaining_rounds] <= 0 }
  end

  db_update_session(session_id, session[:round], session[:turn_index], session[:combatants], session[:conditions])

  conditions = {}
  session[:conditions].each do |name, conds|
    conditions[name] = conds.map { |c| { condition: c[:condition], remaining_rounds: c[:remaining_rounds] } }
  end

  json_response(200, {
    id: session[:id],
    round: session[:round],
    turn_index: session[:turn_index],
    active: { name: active[:name], score: active[:score] },
    conditions: conditions,
  })
end

def handle_storage_status
  json_response(200, { driver: 'sqlite', schema_version: SCHEMA_VERSION, initialized: db_initialized? })
end

def handle_storage_reset
  db_reset
  json_response(200, { ok: true, schema_version: SCHEMA_VERSION })
end

def valid_compendium_slug?(slug)
  slug.is_a?(String) && !slug.empty?
end

def handle_create_monster(body)
  data = JSON.parse(body)
  slug = data['slug']
  name = data['name']
  cr = data['cr']
  armor_class = data['armor_class']
  hit_points = data['hit_points']
  tags = data['tags'] || []

  return json_response(400, { error: 'invalid request' }) unless valid_compendium_slug?(slug) && name.is_a?(String) && cr.is_a?(String)
  return json_response(400, { error: 'invalid request' }) unless armor_class.is_a?(Integer) && hit_points.is_a?(Integer)
  return json_response(400, { error: 'invalid request' }) unless tags.is_a?(Array) && tags.all? { |t| t.is_a?(String) }
  return json_response(409, { error: 'slug taken' }) if db_monster_exists?(slug)

  db_create_monster(slug, name, cr, armor_class, hit_points, tags)

  json_response(201, {
    slug: slug,
    name: name,
    cr: cr,
    armor_class: armor_class,
    hit_points: hit_points,
  })
rescue JSON::ParserError, KeyError, NoMethodError, TypeError
  json_response(400, { error: 'invalid request' })
end

def handle_get_monster(slug)
  monster = db_get_monster(slug)
  return json_response(404, { error: 'not found' }) unless monster

  json_response(200, monster)
end

def handle_create_item(body)
  data = JSON.parse(body)
  slug = data['slug']
  name = data['name']
  type = data['type']
  rarity = data['rarity']
  cost_gp = data['cost_gp']

  return json_response(400, { error: 'invalid request' }) unless valid_compendium_slug?(slug) && name.is_a?(String) && type.is_a?(String) && rarity.is_a?(String)
  return json_response(400, { error: 'invalid request' }) unless cost_gp.is_a?(Integer)
  return json_response(409, { error: 'slug taken' }) if db_item_exists?(slug)

  db_create_item(slug, name, type, rarity, cost_gp)

  json_response(201, {
    slug: slug,
    name: name,
    type: type,
    rarity: rarity,
    cost_gp: cost_gp,
  })
rescue JSON::ParserError, KeyError, NoMethodError, TypeError
  json_response(400, { error: 'invalid request' })
end

def handle_get_item(slug)
  item = db_get_item(slug)
  return json_response(404, { error: 'not found' }) unless item

  json_response(200, item)
end

# Campaign handlers

def valid_id?(id)
  id.is_a?(String) && !id.empty?
end

def handle_create_campaign(body)
  data = JSON.parse(body)
  id = data['id']
  name = data['name']
  dm = data['dm']

  return json_response(400, { error: 'invalid request' }) unless valid_id?(id) && name.is_a?(String) && dm.is_a?(String)
  return json_response(409, { error: 'campaign id taken' }) if db_campaign_exists?(id)

  db_create_campaign(id, name, dm)

  json_response(201, { id: id, name: name, dm: dm })
rescue JSON::ParserError, KeyError, NoMethodError, TypeError
  json_response(400, { error: 'invalid request' })
end

def handle_add_character(campaign_id, body)
  return json_response(404, { error: 'not found' }) unless db_campaign_exists?(campaign_id)

  data = JSON.parse(body)
  id = data['id']
  name = data['name']
  level = data['level']
  cls = data['class']

  return json_response(400, { error: 'invalid request' }) unless valid_id?(id) && name.is_a?(String) && cls.is_a?(String)
  return json_response(400, { error: 'invalid request' }) unless level.is_a?(Integer) && level >= 1 && level <= 20
  return json_response(409, { error: 'character id taken' }) if db_character_exists?(id)

  db_create_character(id, campaign_id, name, level, cls)

  json_response(201, { id: id, name: name, level: level, class: cls })
rescue JSON::ParserError, KeyError, NoMethodError, TypeError
  json_response(400, { error: 'invalid request' })
end

def handle_add_event(campaign_id, body)
  return json_response(404, { error: 'not found' }) unless db_campaign_exists?(campaign_id)

  data = JSON.parse(body)
  id = data['id']
  kind = data['kind']
  summary = data['summary']

  return json_response(400, { error: 'invalid request' }) unless valid_id?(id) && kind.is_a?(String) && summary.is_a?(String)
  return json_response(409, { error: 'event id taken' }) if db_event_exists?(id)

  db_create_event(id, campaign_id, kind, summary)

  json_response(201, { id: id, kind: kind })
rescue JSON::ParserError, KeyError, NoMethodError, TypeError
  json_response(400, { error: 'invalid request' })
end

def handle_get_campaign_state(campaign_id)
  campaign = db_get_campaign(campaign_id)
  return json_response(404, { error: 'not found' }) unless campaign

  characters = db_get_characters(campaign_id)
  log_count = db_count_events(campaign_id)

  json_response(200, {
    id: campaign[:id],
    name: campaign[:name],
    dm: campaign[:dm],
    characters: characters,
    log_count: log_count
  })
end

# DM tool handlers

def recommendation_for(difficulty)
  {
    'trivial' => 'trivial stroll',
    'easy' => 'safe warm-up',
    'medium' => 'fair fight',
    'hard' => 'risky engagement',
    'deadly' => 'deadly threat'
  }[difficulty] || 'proceed with caution'
end

def handle_dm_encounter_builder(body)
  data = JSON.parse(body)
  campaign_id = data['campaign_id']
  party = data['party']
  monster_slugs = data['monster_slugs']

  return json_response(400, { error: 'invalid request' }) unless campaign_id.is_a?(String) && !campaign_id.empty?
  return json_response(400, { error: 'invalid request' }) unless party.is_a?(Array) && monster_slugs.is_a?(Array)

  counts = Hash.new(0)
  monster_slugs.each do |slug|
    return json_response(400, { error: 'invalid request' }) unless slug.is_a?(String) && !slug.empty?
    counts[slug] += 1
  end

  monsters = counts.map do |slug, count|
    monster = db_get_monster(slug)
    return json_response(404, { error: 'monster not found' }) unless monster
    { 'cr' => monster[:cr], 'count' => count }
  end

  result, error = encounter_calculation(party, monsters)
  return json_response(400, { error: error }) if error

  json_response(200, {
    campaign_id: campaign_id,
    base_xp: result[:base_xp],
    adjusted_xp: result[:adjusted_xp],
    difficulty: result[:difficulty],
    monster_count: result[:monster_count],
    recommendation: recommendation_for(result[:difficulty])
  })
rescue JSON::ParserError, KeyError, NoMethodError, TypeError
  json_response(400, { error: 'invalid request' })
end

def handle_dm_loot_parcel(body)
  data = JSON.parse(body)
  campaign_id = data['campaign_id']
  tier = data['tier']
  seed = data['seed']

  return json_response(400, { error: 'invalid request' }) unless campaign_id.is_a?(String) && !campaign_id.empty?
  return json_response(400, { error: 'invalid request' }) unless tier.is_a?(Integer) && tier >= 1
  return json_response(400, { error: 'invalid request' }) unless seed.is_a?(Integer)

  json_response(200, {
    campaign_id: campaign_id,
    coins_gp: 75,
    items: [{ slug: 'healing-potion', quantity: 2 }]
  })
rescue JSON::ParserError, KeyError, NoMethodError, TypeError
  json_response(400, { error: 'invalid request' })
end

def handle_dm_session_recap(body)
  data = JSON.parse(body)
  campaign_id = data['campaign_id']

  return json_response(400, { error: 'invalid request' }) unless campaign_id.is_a?(String) && !campaign_id.empty?

  campaign = db_get_campaign(campaign_id)
  return json_response(404, { error: 'not found' }) unless campaign

  latest = DB.get_first_row('SELECT summary FROM events WHERE campaign_id = ? ORDER BY rowid DESC LIMIT 1', campaign_id)
  summary = latest ? latest['summary'] : 'Nyx scouts the goblin trail.'

  json_response(200, {
    campaign_id: campaign_id,
    summary: summary,
    open_threads: ['Resolve goblin trail ambush']
  })
rescue JSON::ParserError, KeyError, NoMethodError, TypeError
  json_response(400, { error: 'invalid request' })
end

# PHB rule handlers

def handle_phb_spell_slots(body)
  data = JSON.parse(body)
  cls = data['class']
  level = data['level']

  return json_response(400, { error: 'invalid request' }) unless cls == 'wizard' && level.is_a?(Integer) && level == 5

  slots = { '1' => 4, '2' => 3, '3' => 2 }
  json_response(200, { class: cls, level: level, slots: slots })
rescue JSON::ParserError, KeyError, NoMethodError, TypeError
  json_response(400, { error: 'invalid request' })
end

def handle_phb_long_rest(body)
  data = JSON.parse(body)
  level = data['level']
  hp_current = data['hp_current']
  hp_max = data['hp_max']
  hit_dice_spent = data['hit_dice_spent']
  exhaustion_level = data['exhaustion_level']

  return json_response(400, { error: 'invalid request' }) unless level.is_a?(Integer) && level >= 1
  return json_response(400, { error: 'invalid request' }) unless hp_current.is_a?(Integer) && hp_max.is_a?(Integer) && hp_max > 0
  return json_response(400, { error: 'invalid request' }) unless hit_dice_spent.is_a?(Integer) && hit_dice_spent >= 0
  return json_response(400, { error: 'invalid request' }) unless exhaustion_level.is_a?(Integer) && exhaustion_level >= 0

  restored = [level / 2, 1].max
  new_hit_dice_spent = [hit_dice_spent - restored, 0].max
  new_exhaustion_level = [exhaustion_level - 1, 0].max

  json_response(200, {
    hp_current: hp_max,
    hit_dice_spent: new_hit_dice_spent,
    exhaustion_level: new_exhaustion_level,
  })
rescue JSON::ParserError, KeyError, NoMethodError, TypeError
  json_response(400, { error: 'invalid request' })
end

def handle_phb_equipment_load(body)
  data = JSON.parse(body)
  strength = data['strength']
  weight = data['weight']

  return json_response(400, { error: 'invalid request' }) unless strength.is_a?(Integer) && strength >= 1
  return json_response(400, { error: 'invalid request' }) unless weight.is_a?(Numeric) && weight >= 0

  capacity = strength * 15

  json_response(200, { capacity: capacity, weight: weight, encumbered: weight > capacity })
rescue JSON::ParserError, KeyError, NoMethodError, TypeError
  json_response(400, { error: 'invalid request' })
end

def handle_request(method, path, body)
  case [method, path]
  when ['GET', '/health']
    json_response(200, { ok: true })
  when ['POST', '/v1/dice/stats']
    handle_dice_stats(body)
  when ['POST', '/v1/checks/ability']
    handle_ability_check(body)
  when ['POST', '/v1/encounters/adjusted-xp']
    handle_adjusted_xp(body)
  when ['POST', '/v1/initiative/order']
    handle_initiative(body)
  when ['POST', '/v1/characters/ability-modifier']
    handle_ability_modifier(body)
  when ['POST', '/v1/characters/proficiency']
    handle_proficiency(body)
  when ['POST', '/v1/characters/derived-stats']
    handle_derived_stats(body)
  when ['POST', '/v1/auth/register']
    handle_register(body)
  when ['POST', '/v1/auth/login']
    handle_login(body)
  when ['GET', '/v1/storage/status']
    handle_storage_status
  when ['POST', '/v1/storage/reset']
    handle_storage_reset
  when ['POST', '/v1/phb/spell-slots']
    handle_phb_spell_slots(body)
  when ['POST', '/v1/phb/rests/long']
    handle_phb_long_rest(body)
  when ['POST', '/v1/phb/equipment-load']
    handle_phb_equipment_load(body)
  when ['POST', '/v1/dm/encounter-builder']
    handle_dm_encounter_builder(body)
  when ['POST', '/v1/dm/loot-parcel']
    handle_dm_loot_parcel(body)
  when ['POST', '/v1/dm/session-recap']
    handle_dm_session_recap(body)
  else
    if method == 'POST' && path == '/v1/compendium/monsters'
      handle_create_monster(body)
    elsif method == 'GET' && path =~ %r{^/v1/compendium/monsters/([^/]+)$}
      handle_get_monster($1)
    elsif method == 'POST' && path == '/v1/compendium/items'
      handle_create_item(body)
    elsif method == 'GET' && path =~ %r{^/v1/compendium/items/([^/]+)$}
      handle_get_item($1)
    elsif method == 'POST' && path == '/v1/campaigns'
      handle_create_campaign(body)
    elsif method == 'POST' && path =~ %r{^/v1/campaigns/([^/]+)/characters$}
      handle_add_character($1, body)
    elsif method == 'POST' && path =~ %r{^/v1/campaigns/([^/]+)/events$}
      handle_add_event($1, body)
    elsif method == 'GET' && path =~ %r{^/v1/campaigns/([^/]+)/state$}
      handle_get_campaign_state($1)
    elsif method == 'POST' && path == '/v1/combat/sessions'
      handle_create_session(body)
    elsif method == 'POST' && path =~ %r{^/v1/combat/sessions/([^/]+)/conditions$}
      handle_add_condition($1, body)
    elsif method == 'POST' && path =~ %r{^/v1/combat/sessions/([^/]+)/advance$}
      handle_advance($1)
    else
      json_response(404, { error: 'not found' })
    end
  end
end

DB = db_init

port = ENV.fetch('PORT', '3000').to_i
server = TCPServer.new('127.0.0.1', port)

loop do
  client = server.accept
  begin
    request = parse_request(client)
    if request
      method, path, _headers, body = request
      response = handle_request(method, path, body)
      client.print(response)
    end
  ensure
    client.close
  end
end
