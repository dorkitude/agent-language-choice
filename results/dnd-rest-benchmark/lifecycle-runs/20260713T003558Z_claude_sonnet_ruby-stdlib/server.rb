#!/usr/bin/env ruby
# frozen_string_literal: true

require 'socket'
require 'json'
require 'openssl'
require 'securerandom'
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

def json_response(status, body)
  payload = JSON.generate(body)
  [status, payload]
end

def parse_dice_expression(expr)
  return nil unless expr.is_a?(String)

  m = /\A(\d+)d(\d+)([+-]\d+)?\z/.match(expr)
  return nil unless m

  count = m[1].to_i
  sides = m[2].to_i
  modifier = m[3] ? m[3].to_i : 0

  return nil if count <= 0 || sides <= 0

  { count: count, sides: sides, modifier: modifier }
end

def handle_health(_req_body)
  json_response(200, { ok: true })
end

def handle_dice_stats(req_body)
  data = JSON.parse(req_body)
  parsed = parse_dice_expression(data['expression'])
  return json_response(400, { error: 'invalid expression' }) unless parsed

  count = parsed[:count]
  sides = parsed[:sides]
  modifier = parsed[:modifier]

  min = count * 1 + modifier
  max = count * sides + modifier
  average_raw = (count * (sides + 1) / 2.0) + modifier
  average = average_raw == average_raw.to_i ? average_raw.to_i : average_raw

  json_response(200, {
                   dice_count: count,
                   sides: sides,
                   modifier: modifier,
                   min: min,
                   max: max,
                   average: average
                 })
rescue JSON::ParserError, TypeError
  json_response(400, { error: 'invalid json' })
end

def handle_ability_check(req_body)
  data = JSON.parse(req_body)
  roll = data['roll']
  modifier = data['modifier']
  dc = data['dc']
  return json_response(400, { error: 'invalid payload' }) unless roll.is_a?(Numeric) && modifier.is_a?(Numeric) && dc.is_a?(Numeric)

  total = roll + modifier
  success = total >= dc
  margin = total - dc

  json_response(200, { total: total, success: success, margin: margin })
rescue JSON::ParserError, TypeError
  json_response(400, { error: 'invalid json' })
end

def handle_adjusted_xp(req_body)
  data = JSON.parse(req_body)
  party = data['party']
  monsters = data['monsters']
  return json_response(400, { error: 'invalid payload' }) unless party.is_a?(Array) && monsters.is_a?(Array)

  base_xp = 0
  monster_count = 0

  monsters.each do |monster|
    cr = monster['cr'].to_s
    count = monster['count']
    xp = CR_XP[cr]
    return json_response(400, { error: 'unsupported cr' }) unless xp
    return json_response(400, { error: 'invalid count' }) unless count.is_a?(Integer) && count.positive?

    base_xp += xp * count
    monster_count += count
  end

  mult = multiplier_for(monster_count)
  adjusted_xp = (base_xp * mult).to_i

  thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 }
  party.each do |member|
    level = member['level']
    lt = LEVEL_THRESHOLDS[level]
    return json_response(400, { error: 'unsupported level' }) unless lt

    thresholds.each_key { |k| thresholds[k] += lt[k] }
  end

  difficulty = 'trivial'
  difficulty = 'easy' if adjusted_xp >= thresholds[:easy]
  difficulty = 'medium' if adjusted_xp >= thresholds[:medium]
  difficulty = 'hard' if adjusted_xp >= thresholds[:hard]
  difficulty = 'deadly' if adjusted_xp >= thresholds[:deadly]

  json_response(200, {
                   base_xp: base_xp,
                   monster_count: monster_count,
                   multiplier: mult,
                   adjusted_xp: adjusted_xp,
                   difficulty: difficulty,
                   thresholds: thresholds
                 })
rescue JSON::ParserError, TypeError
  json_response(400, { error: 'invalid json' })
end

def handle_initiative_order(req_body)
  data = JSON.parse(req_body)
  combatants = data['combatants']
  return json_response(400, { error: 'invalid payload' }) unless combatants.is_a?(Array)

  scored = combatants.map do |c|
    name = c['name']
    dex = c['dex']
    roll = c['roll']
    return json_response(400, { error: 'invalid combatant' }) unless name.is_a?(String) && dex.is_a?(Numeric) && roll.is_a?(Numeric)

    { name: name, dex: dex, score: roll + dex }
  end

  ordered = scored.sort do |a, b|
    cmp = b[:score] <=> a[:score]
    next cmp unless cmp.zero?

    cmp = b[:dex] <=> a[:dex]
    next cmp unless cmp.zero?

    a[:name] <=> b[:name]
  end

  json_response(200, { order: ordered.map { |c| { name: c[:name], score: c[:score] } } })
rescue JSON::ParserError, TypeError
  json_response(400, { error: 'invalid json' })
end

PROFICIENCY_BY_LEVEL = {
  (1..4) => 2,
  (5..8) => 3,
  (9..12) => 4,
  (13..16) => 5,
  (17..20) => 6
}.freeze

def ability_modifier(score)
  ((score - 10) / 2.0).floor
end

def proficiency_bonus_for(level)
  PROFICIENCY_BY_LEVEL.each do |range, bonus|
    return bonus if range.cover?(level)
  end
  nil
end

def handle_ability_modifier(req_body)
  data = JSON.parse(req_body)
  score = data['score']
  return json_response(400, { error: 'invalid score' }) unless score.is_a?(Integer) && score.between?(1, 30)

  json_response(200, { score: score, modifier: ability_modifier(score) })
rescue JSON::ParserError, TypeError
  json_response(400, { error: 'invalid json' })
end

def handle_proficiency(req_body)
  data = JSON.parse(req_body)
  level = data['level']
  return json_response(400, { error: 'invalid level' }) unless level.is_a?(Integer) && level.between?(1, 20)

  json_response(200, { level: level, proficiency_bonus: proficiency_bonus_for(level) })
rescue JSON::ParserError, TypeError
  json_response(400, { error: 'invalid json' })
end

def handle_derived_stats(req_body)
  data = JSON.parse(req_body)
  level = data['level']
  abilities = data['abilities']
  armor = data['armor']
  return json_response(400, { error: 'invalid payload' }) unless level.is_a?(Integer) && level.between?(1, 20)
  return json_response(400, { error: 'invalid abilities' }) unless abilities.is_a?(Hash)
  return json_response(400, { error: 'invalid armor' }) unless armor.is_a?(Hash)

  %w[str dex con int wis cha].each do |key|
    score = abilities[key]
    return json_response(400, { error: 'invalid abilities' }) unless score.is_a?(Integer) && score.between?(1, 30)
  end

  base = armor['base']
  shield = armor['shield']
  dex_cap = armor['dex_cap']
  return json_response(400, { error: 'invalid armor' }) unless base.is_a?(Numeric) && [true, false].include?(shield) && dex_cap.is_a?(Numeric)

  modifiers = {}
  %w[str dex con int wis cha].each { |key| modifiers[key.to_sym] = ability_modifier(abilities[key]) }

  proficiency_bonus = proficiency_bonus_for(level)
  hp_max = level * (6 + modifiers[:con])
  shield_bonus = shield ? 2 : 0
  armor_class = base + [modifiers[:dex], dex_cap].min + shield_bonus

  json_response(200, {
                   level: level,
                   proficiency_bonus: proficiency_bonus,
                   hp_max: hp_max,
                   armor_class: armor_class,
                   modifiers: modifiers
                 })
rescue JSON::ParserError, TypeError
  json_response(400, { error: 'invalid json' })
end

DB_PATH = File.join(__dir__, 'game.db')
SCHEMA_VERSION = 1

$db = nil
$db_initialized = false

def init_db!
  File.delete(DB_PATH) if File.exist?(DB_PATH)
  $db = SQLite3::Database.new(DB_PATH)
  $db.execute('PRAGMA journal_mode = WAL')
  create_schema!
  $db_initialized = true
end

def create_schema!
  $db.execute(<<~SQL)
    CREATE TABLE IF NOT EXISTS users (
      username TEXT PRIMARY KEY,
      role TEXT NOT NULL,
      salt BLOB NOT NULL,
      password_hash TEXT NOT NULL
    )
  SQL
  $db.execute(<<~SQL)
    CREATE TABLE IF NOT EXISTS combat_sessions (
      id TEXT PRIMARY KEY,
      data TEXT NOT NULL
    )
  SQL
  $db.execute(<<~SQL)
    CREATE TABLE IF NOT EXISTS monsters (
      slug TEXT PRIMARY KEY,
      data TEXT NOT NULL
    )
  SQL
  $db.execute(<<~SQL)
    CREATE TABLE IF NOT EXISTS items (
      slug TEXT PRIMARY KEY,
      data TEXT NOT NULL
    )
  SQL
end

def reset_storage!
  $db.execute('DROP TABLE IF EXISTS users')
  $db.execute('DROP TABLE IF EXISTS combat_sessions')
  $db.execute('DROP TABLE IF EXISTS monsters')
  $db.execute('DROP TABLE IF EXISTS items')
  create_schema!
  USERS.clear
  COMBAT_SESSIONS.clear
  MONSTERS.clear
  ITEMS.clear
end

def persist_user(user)
  $db.execute(
    'INSERT OR REPLACE INTO users (username, role, salt, password_hash) VALUES (?, ?, ?, ?)',
    [user[:username], user[:role], SQLite3::Blob.new(user[:salt]), user[:password_hash]]
  )
end

def persist_combat_session(session)
  $db.execute(
    'INSERT OR REPLACE INTO combat_sessions (id, data) VALUES (?, ?)',
    [session[:id], JSON.generate(session)]
  )
end

def persist_monster(monster)
  $db.execute(
    'INSERT OR REPLACE INTO monsters (slug, data) VALUES (?, ?)',
    [monster[:slug], JSON.generate(monster)]
  )
end

def persist_item(item)
  $db.execute(
    'INSERT OR REPLACE INTO items (slug, data) VALUES (?, ?)',
    [item[:slug], JSON.generate(item)]
  )
end

COMBAT_SESSIONS = {}
USERS = {}
MONSTERS = {}
ITEMS = {}

SLUG_RE = /\A[a-z0-9-]{1,64}\z/.freeze

def handle_create_monster(req_body)
  data = JSON.parse(req_body)
  slug = data['slug']
  name = data['name']
  cr = data['cr']
  armor_class = data['armor_class']
  hit_points = data['hit_points']
  tags = data['tags']

  return json_response(400, { error: 'invalid slug' }) unless slug.is_a?(String) && SLUG_RE.match?(slug)
  return json_response(400, { error: 'invalid name' }) unless name.is_a?(String) && !name.empty?
  return json_response(400, { error: 'invalid cr' }) unless cr.is_a?(String) && !cr.empty?
  return json_response(400, { error: 'invalid armor_class' }) unless armor_class.is_a?(Integer)
  return json_response(400, { error: 'invalid hit_points' }) unless hit_points.is_a?(Integer)
  return json_response(400, { error: 'invalid tags' }) unless tags.nil? || (tags.is_a?(Array) && tags.all? { |t| t.is_a?(String) })
  return json_response(409, { error: 'duplicate slug' }) if MONSTERS.key?(slug)

  monster = {
    slug: slug,
    name: name,
    cr: cr,
    armor_class: armor_class,
    hit_points: hit_points,
    tags: tags || []
  }
  MONSTERS[slug] = monster
  persist_monster(monster)

  json_response(200, {
                   slug: slug,
                   name: name,
                   cr: cr,
                   armor_class: armor_class,
                   hit_points: hit_points
                 })
rescue JSON::ParserError, TypeError
  json_response(400, { error: 'invalid json' })
end

def handle_get_monster(_req_body, slug)
  monster = MONSTERS[slug]
  return json_response(404, { error: 'monster not found' }) unless monster

  json_response(200, {
                   slug: monster[:slug],
                   name: monster[:name],
                   cr: monster[:cr],
                   armor_class: monster[:armor_class],
                   hit_points: monster[:hit_points],
                   tags: monster[:tags]
                 })
end

def handle_create_item(req_body)
  data = JSON.parse(req_body)
  slug = data['slug']
  name = data['name']
  type = data['type']
  rarity = data['rarity']
  cost_gp = data['cost_gp']

  return json_response(400, { error: 'invalid slug' }) unless slug.is_a?(String) && SLUG_RE.match?(slug)
  return json_response(400, { error: 'invalid name' }) unless name.is_a?(String) && !name.empty?
  return json_response(400, { error: 'invalid type' }) unless type.is_a?(String) && !type.empty?
  return json_response(400, { error: 'invalid rarity' }) unless rarity.is_a?(String) && !rarity.empty?
  return json_response(400, { error: 'invalid cost_gp' }) unless cost_gp.is_a?(Numeric)
  return json_response(409, { error: 'duplicate slug' }) if ITEMS.key?(slug)

  item = {
    slug: slug,
    name: name,
    type: type,
    rarity: rarity,
    cost_gp: cost_gp
  }
  ITEMS[slug] = item
  persist_item(item)

  json_response(200, item)
rescue JSON::ParserError, TypeError
  json_response(400, { error: 'invalid json' })
end

def handle_get_item(_req_body, slug)
  item = ITEMS[slug]
  return json_response(404, { error: 'item not found' }) unless item

  json_response(200, item)
end

def condition_snapshot(combatant)
  combatant[:conditions].map { |c| { condition: c[:condition], remaining_rounds: c[:remaining_rounds] } }
end

def session_snapshot(session)
  order = session[:order]
  active = order[session[:turn_index]]
  {
    id: session[:id],
    round: session[:round],
    turn_index: session[:turn_index],
    active: { name: active[:name], score: active[:score] },
    order: order.map { |c| { name: c[:name], score: c[:score] } }
  }
end

def handle_create_combat_session(req_body)
  data = JSON.parse(req_body)
  id = data['id']
  combatants = data['combatants']
  return json_response(400, { error: 'invalid id' }) unless id.is_a?(String) && !id.empty?
  return json_response(400, { error: 'invalid payload' }) unless combatants.is_a?(Array) && !combatants.empty?
  return json_response(400, { error: 'duplicate id' }) if COMBAT_SESSIONS.key?(id)

  scored = combatants.map do |c|
    name = c['name']
    dex = c['dex']
    roll = c['roll']
    return json_response(400, { error: 'invalid combatant' }) unless name.is_a?(String) && dex.is_a?(Numeric) && roll.is_a?(Numeric)

    { name: name, dex: dex, score: roll + dex, conditions: [] }
  end

  ordered = scored.sort do |a, b|
    cmp = b[:score] <=> a[:score]
    next cmp unless cmp.zero?

    cmp = b[:dex] <=> a[:dex]
    next cmp unless cmp.zero?

    a[:name] <=> b[:name]
  end

  session = { id: id, round: 1, turn_index: 0, order: ordered }
  COMBAT_SESSIONS[id] = session
  persist_combat_session(session)

  json_response(200, session_snapshot(session))
rescue JSON::ParserError, TypeError
  json_response(400, { error: 'invalid json' })
end

def handle_add_condition(req_body, id)
  session = COMBAT_SESSIONS[id]
  return json_response(404, { error: 'session not found' }) unless session

  data = JSON.parse(req_body)
  target = data['target']
  condition = data['condition']
  duration_rounds = data['duration_rounds']
  return json_response(400, { error: 'invalid payload' }) unless target.is_a?(String) && condition.is_a?(String)
  return json_response(400, { error: 'invalid duration_rounds' }) unless duration_rounds.is_a?(Integer) && duration_rounds.positive?

  combatant = session[:order].find { |c| c[:name] == target }
  return json_response(400, { error: 'unknown target' }) unless combatant

  combatant[:conditions] << { condition: condition, remaining_rounds: duration_rounds }
  persist_combat_session(session)

  json_response(200, { target: target, conditions: condition_snapshot(combatant) })
rescue JSON::ParserError, TypeError
  json_response(400, { error: 'invalid json' })
end

def handle_advance_turn(_req_body, id)
  session = COMBAT_SESSIONS[id]
  return json_response(404, { error: 'session not found' }) unless session

  order = session[:order]
  session[:turn_index] += 1
  if session[:turn_index] >= order.length
    session[:turn_index] = 0
    session[:round] += 1
  end

  active = order[session[:turn_index]]
  active[:conditions].each { |c| c[:remaining_rounds] -= 1 }
  active[:conditions].reject! { |c| c[:remaining_rounds] <= 0 }
  persist_combat_session(session)

  conditions = {}
  order.each do |c|
    conditions[c[:name]] = condition_snapshot(c) if c == active || !c[:conditions].empty?
  end

  json_response(200, {
                   id: session[:id],
                   round: session[:round],
                   turn_index: session[:turn_index],
                   active: { name: active[:name], score: active[:score] },
                   conditions: conditions
                 })
rescue JSON::ParserError, TypeError
  json_response(400, { error: 'invalid json' })
end

PBKDF2_ITERATIONS = 20_000
PBKDF2_KEY_LEN = 32
PBKDF2_DIGEST = OpenSSL::Digest::SHA256.new

def hash_password(password, salt)
  OpenSSL::PKCS5.pbkdf2_hmac(password, salt, PBKDF2_ITERATIONS, PBKDF2_KEY_LEN, PBKDF2_DIGEST).unpack1('H*')
end

def password_matches?(user, password)
  hash_password(password, user[:salt]) == user[:password_hash]
end

USERNAME_RE = /\A[a-z0-9_-]{2,32}\z/.freeze

def handle_register(req_body)
  data = JSON.parse(req_body)
  username = data['username']
  password = data['password']
  role = data['role']

  return json_response(400, { error: 'invalid username' }) unless username.is_a?(String) && USERNAME_RE.match?(username)
  return json_response(400, { error: 'invalid password' }) unless password.is_a?(String) && password.length >= 8
  return json_response(400, { error: 'invalid role' }) unless %w[dm player].include?(role)
  return json_response(409, { error: 'duplicate username' }) if USERS.key?(username)

  salt = SecureRandom.random_bytes(16)
  user = { username: username, role: role, salt: salt, password_hash: hash_password(password, salt) }
  USERS[username] = user
  persist_user(user)

  json_response(201, { username: username, role: role })
rescue JSON::ParserError, TypeError
  json_response(400, { error: 'invalid json' })
end

def handle_login(req_body)
  data = JSON.parse(req_body)
  username = data['username']
  password = data['password']
  return json_response(400, { error: 'invalid payload' }) unless username.is_a?(String) && password.is_a?(String)

  user = USERS[username]
  return json_response(401, { error: 'invalid credentials' }) unless user && password_matches?(user, password)

  json_response(200, { username: username, token: "session-#{username}" })
rescue JSON::ParserError, TypeError
  json_response(400, { error: 'invalid json' })
end

def handle_storage_status(_req_body)
  json_response(200, { driver: 'sqlite', schema_version: SCHEMA_VERSION, initialized: $db_initialized })
end

def handle_storage_reset(_req_body)
  reset_storage!
  json_response(200, { ok: true, schema_version: SCHEMA_VERSION })
end

ROUTES = {
  ['GET', '/health'] => method(:handle_health),
  ['GET', '/v1/storage/status'] => method(:handle_storage_status),
  ['POST', '/v1/storage/reset'] => method(:handle_storage_reset),
  ['POST', '/v1/dice/stats'] => method(:handle_dice_stats),
  ['POST', '/v1/checks/ability'] => method(:handle_ability_check),
  ['POST', '/v1/encounters/adjusted-xp'] => method(:handle_adjusted_xp),
  ['POST', '/v1/initiative/order'] => method(:handle_initiative_order),
  ['POST', '/v1/characters/ability-modifier'] => method(:handle_ability_modifier),
  ['POST', '/v1/characters/proficiency'] => method(:handle_proficiency),
  ['POST', '/v1/characters/derived-stats'] => method(:handle_derived_stats),
  ['POST', '/v1/combat/sessions'] => method(:handle_create_combat_session),
  ['POST', '/v1/auth/register'] => method(:handle_register),
  ['POST', '/v1/auth/login'] => method(:handle_login),
  ['POST', '/v1/compendium/monsters'] => method(:handle_create_monster),
  ['POST', '/v1/compendium/items'] => method(:handle_create_item)
}.freeze

PARAM_ROUTES = [
  [%r{\A/v1/combat/sessions/([^/]+)/conditions\z}, 'POST', method(:handle_add_condition)],
  [%r{\A/v1/combat/sessions/([^/]+)/advance\z}, 'POST', method(:handle_advance_turn)],
  [%r{\A/v1/compendium/monsters/([^/]+)\z}, 'GET', method(:handle_get_monster)],
  [%r{\A/v1/compendium/items/([^/]+)\z}, 'GET', method(:handle_get_item)]
].freeze

def read_request(client)
  request_line = client.gets
  return nil if request_line.nil?

  method_name, path, = request_line.split(' ')
  headers = {}
  loop do
    line = client.gets
    break if line.nil? || line == "\r\n" || line == "\n"

    key, value = line.split(':', 2)
    headers[key.strip.downcase] = value.strip if key && value
  end

  body = ''
  content_length = headers['content-length'].to_i
  body = client.read(content_length) if content_length.positive?

  { method: method_name, path: path, headers: headers, body: body }
end

def write_response(client, status, body)
  status_text = { 200 => 'OK', 400 => 'Bad Request', 404 => 'Not Found', 500 => 'Internal Server Error' }[status] || 'OK'
  client.write("HTTP/1.1 #{status} #{status_text}\r\n")
  client.write("Content-Type: application/json\r\n")
  client.write("Content-Length: #{body.bytesize}\r\n")
  client.write("Connection: close\r\n")
  client.write("\r\n")
  client.write(body)
end

def handle_client(client)
  req = read_request(client)
  if req.nil?
    client.close
    return
  end

  path_only = req[:path].split('?').first
  handler = ROUTES[[req[:method], path_only]]

  status, body =
    if handler
      handler.call(req[:body])
    else
      param_match = PARAM_ROUTES.find { |(regex, method_name, _)| method_name == req[:method] && regex.match(path_only) }
      if param_match
        regex, _, param_handler = param_match
        id = regex.match(path_only)[1]
        param_handler.call(req[:body], id)
      else
        json_response(404, { error: 'not found' })
      end
    end

  write_response(client, status, body)
rescue StandardError => e
  write_response(client, 500, JSON.generate({ error: e.message }))
ensure
  client.close
end

init_db!

port = (ENV['PORT'] || 8080).to_i
server = TCPServer.new('127.0.0.1', port)
warn "Listening on 127.0.0.1:#{port}"

loop do
  client = server.accept
  handle_client(client)
end
