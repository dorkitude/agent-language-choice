require 'sinatra'
require 'json'
require 'openssl'
require 'securerandom'

set :bind, '127.0.0.1'
set :port, ENV.fetch('PORT', '4567')
set :server, :puma

configure do
  set :show_exceptions, false
end

DICE_EXPR = /\A(\d+)d(\d+)(?:([+-])(\d+))?\z/

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
}

LEVEL_THRESHOLDS = {
  3 => { easy: 75, medium: 150, hard: 225, deadly: 400 },
}

MULTIPLIERS = [
  [1, 1],
  [2, 1.5],
  [3, 2],
  [7, 2.5],
  [11, 3],
  [15, 4],
]

VALID_USERNAME_RE = /\A[a-z0-9_-]{2,32}\z/
VALID_ROLES = %w[dm player].freeze
USERS = {}
USERS_MUTEX = Mutex.new

class PasswordHelper
  ITERATIONS = 10_000
  HASH_BYTES = 32

  def self.hash(password)
    salt = SecureRandom.hex(16)
    derived = OpenSSL::PKCS5.pbkdf2_hmac(password, salt, ITERATIONS, HASH_BYTES, OpenSSL::Digest::SHA256.new)
    "pbkdf2_sha256$#{ITERATIONS}$#{salt}$#{derived.unpack1('H*')}"
  end

  def self.verify(password, stored)
    _algo, iterations, salt, hash_hex = stored.split('$')
    expected = [hash_hex].pack('H*')
    actual = OpenSSL::PKCS5.pbkdf2_hmac(password, salt, iterations.to_i, expected.bytesize, OpenSSL::Digest::SHA256.new)
    secure_compare(expected, actual)
  rescue
    false
  end

  def self.secure_compare(a, b)
    return false unless a.bytesize == b.bytesize
    a.bytes.zip(b.bytes).reduce(0) { |memo, (x, y)| memo | (x ^ y) }.zero?
  end
end

def validate_registration(data)
  username = data['username'].to_s
  password = data['password'].to_s
  role = data['role'].to_s

  halt 400, { error: 'invalid username' }.to_json unless username.match?(VALID_USERNAME_RE)
  halt 400, { error: 'invalid password' }.to_json unless password.length >= 8
  halt 400, { error: 'invalid role' }.to_json unless VALID_ROLES.include?(role)

  [username, password, role]
end

def parse_json_body
  body = request.body.read
  JSON.parse(body)
rescue JSON::ParserError
  halt 400, { error: 'invalid json' }.to_json
end

ABILITY_NAMES = %w[str dex con int wis cha].freeze

ABILITY_MODIFIER = ->(score) { ((score - 10) / 2.0).floor }

def require_int(value, range)
  halt 400, { error: 'invalid request' }.to_json unless value.is_a?(Integer) && range.include?(value)
  value
end

def compute_proficiency_bonus(level)
  case level
  when 1..4 then 2
  when 5..8 then 3
  when 9..12 then 4
  when 13..16 then 5
  when 17..20 then 6
  end
end

get '/health' do
  content_type :json
  { ok: true }.to_json
end

post '/v1/dice/stats' do
  content_type :json
  data = parse_json_body
  expr = data['expression'].to_s

  match = DICE_EXPR.match(expr)
  halt 400, { error: 'invalid expression' }.to_json unless match

  count = match[1].to_i
  sides = match[2].to_i
  sign  = match[3]
  mod   = match[4].to_i

  modifier = sign == '-' ? -mod : mod
  halt 400, { error: 'invalid expression' }.to_json if count <= 0 || sides <= 0

  min = count + modifier
  max = count * sides + modifier
  average = (min + max) / 2.0

  {
    dice_count: count,
    sides: sides,
    modifier: modifier,
    min: min,
    max: max,
    average: average,
  }.to_json
end

post '/v1/checks/ability' do
  content_type :json
  data = parse_json_body

  roll = data['roll'].to_i
  modifier = data['modifier'].to_i
  dc = data['dc'].to_i

  total = roll + modifier

  {
    total: total,
    success: total >= dc,
    margin: total - dc,
  }.to_json
end

post '/v1/encounters/adjusted-xp' do
  content_type :json
  data = parse_json_body

  party = data['party'] || []
  monsters = data['monsters'] || []

  base_xp = 0
  monster_count = 0

  monsters.each do |m|
    cr = m['cr'].to_s
    count = m['count'].to_i
    xp = CR_XP[cr]
    halt 400, { error: 'unsupported cr' }.to_json unless xp
    halt 400, { error: 'invalid monster count' }.to_json if count <= 0

    base_xp += xp * count
    monster_count += count
  end

  multiplier = MULTIPLIERS.reverse.find { |min, _| monster_count >= min }&.last || 1
  adjusted_xp = base_xp * multiplier

  thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 }
  party.each do |p|
    level = p['level'].to_i
    th = LEVEL_THRESHOLDS[level]
    halt 400, { error: 'unsupported level' }.to_json unless th

    thresholds[:easy]   += th[:easy]
    thresholds[:medium] += th[:medium]
    thresholds[:hard]   += th[:hard]
    thresholds[:deadly] += th[:deadly]
  end

  difficulty = 'trivial'
  difficulty = 'easy'   if adjusted_xp >= thresholds[:easy]
  difficulty = 'medium' if adjusted_xp >= thresholds[:medium]
  difficulty = 'hard'   if adjusted_xp >= thresholds[:hard]
  difficulty = 'deadly' if adjusted_xp >= thresholds[:deadly]

  {
    base_xp: base_xp,
    monster_count: monster_count,
    multiplier: multiplier,
    adjusted_xp: adjusted_xp,
    difficulty: difficulty,
    thresholds: thresholds,
  }.to_json
end

post '/v1/initiative/order' do
  content_type :json
  data = parse_json_body

  combatants = data['combatants'] || []

  order = combatants.map do |c|
    {
      name: c['name'],
      score: c['roll'].to_i + c['dex'].to_i,
      dex: c['dex'].to_i,
    }
  end

  order.sort! do |a, b|
    comp = b[:score] <=> a[:score]
    comp = b[:dex] <=> a[:dex] if comp == 0
    comp = a[:name] <=> b[:name] if comp == 0
    comp
  end

  {
    order: order.map { |c| { name: c[:name], score: c[:score] } },
  }.to_json
end

post '/v1/characters/ability-modifier' do
  content_type :json
  data = parse_json_body

  score = data['score']
  require_int(score, 1..30)

  {
    score: score,
    modifier: ABILITY_MODIFIER.call(score),
  }.to_json
end

post '/v1/characters/proficiency' do
  content_type :json
  data = parse_json_body

  level = data['level']
  require_int(level, 1..20)

  {
    level: level,
    proficiency_bonus: compute_proficiency_bonus(level),
  }.to_json
end

post '/v1/characters/derived-stats' do
  content_type :json
  data = parse_json_body

  level = data['level']
  require_int(level, 1..20)

  abilities = data['abilities']
  halt 400, { error: 'invalid abilities' }.to_json unless abilities.is_a?(Hash)

  modifiers = {}
  ABILITY_NAMES.each do |name|
    score = abilities[name]
    require_int(score, 1..30)
    modifiers[name] = ABILITY_MODIFIER.call(score)
  end

  armor = data['armor']
  halt 400, { error: 'invalid armor' }.to_json unless armor.is_a?(Hash)

  base = armor['base']
  require_int(base, 0..99)

  dex_cap = armor['dex_cap']
  require_int(dex_cap, 0..99)

  shield_bonus = armor['shield'] == true ? 2 : 0

  armor_class = base + [modifiers['dex'], dex_cap].min + shield_bonus
  hp_max = level * (6 + modifiers['con'])

  {
    level: level,
    proficiency_bonus: compute_proficiency_bonus(level),
    hp_max: hp_max,
    armor_class: armor_class,
    modifiers: modifiers,
  }.to_json
end

COMBAT_SESSIONS = {}

post '/v1/combat/sessions' do
  content_type :json
  data = parse_json_body

  id = data['id']
  halt 400, { error: 'invalid session id' }.to_json unless id.is_a?(String) && !id.empty?

  combatants = data['combatants']
  halt 400, { error: 'invalid combatants' }.to_json unless combatants.is_a?(Array)

  order = combatants.map do |c|
    name = c['name']
    dex = c['dex']
    roll = c['roll']
    halt 400, { error: 'invalid combatant' }.to_json unless name.is_a?(String) && dex.is_a?(Integer) && roll.is_a?(Integer)

    {
      name: name,
      score: roll + dex,
      dex: dex,
    }
  end

  order.sort! do |a, b|
    comp = b[:score] <=> a[:score]
    comp = b[:dex] <=> a[:dex] if comp == 0
    comp = a[:name] <=> b[:name] if comp == 0
    comp
  end

  halt 400, { error: 'session already exists' }.to_json if COMBAT_SESSIONS.key?(id)

  COMBAT_SESSIONS[id] = {
    id: id,
    round: 1,
    turn_index: 0,
    order: order,
    conditions: {},
  }

  active = order[0]

  {
    id: id,
    round: 1,
    turn_index: 0,
    active: active ? { name: active[:name], score: active[:score] } : nil,
    order: order.map { |c| { name: c[:name], score: c[:score] } },
  }.to_json
end

post '/v1/combat/sessions/:id/conditions' do
  content_type :json
  session_id = params[:id]
  session = COMBAT_SESSIONS[session_id]
  halt 404, { error: 'session not found' }.to_json unless session

  data = parse_json_body
  target = data['target']
  condition_name = data['condition']
  duration = data['duration_rounds']

  combatant_names = session[:order].map { |c| c[:name] }
  halt 400, { error: 'invalid target' }.to_json unless target.is_a?(String) && combatant_names.include?(target)
  halt 400, { error: 'invalid condition' }.to_json unless condition_name.is_a?(String)
  halt 400, { error: 'invalid duration' }.to_json unless duration.is_a?(Integer) && duration > 0

  session[:conditions][target] ||= []
  session[:conditions][target] << { condition: condition_name, remaining_rounds: duration }

  {
    target: target,
    conditions: session[:conditions][target].map { |c| { condition: c[:condition], remaining_rounds: c[:remaining_rounds] } },
  }.to_json
end

post '/v1/combat/sessions/:id/advance' do
  content_type :json
  session_id = params[:id]
  session = COMBAT_SESSIONS[session_id]
  halt 404, { error: 'session not found' }.to_json unless session

  order = session[:order]
  unless order.empty?
    session[:turn_index] += 1
    if session[:turn_index] >= order.length
      session[:turn_index] = 0
      session[:round] += 1
    end
  end

  active = order[session[:turn_index]]

  if active
    active_conditions = session[:conditions][active[:name]]
    if active_conditions
      active_conditions.each { |cond| cond[:remaining_rounds] -= 1 }
      active_conditions.reject! { |cond| cond[:remaining_rounds] <= 0 }
    end
  end

  response_conditions = {}
  session[:conditions].each do |name, conds|
    response_conditions[name] = conds.map { |c| { condition: c[:condition], remaining_rounds: c[:remaining_rounds] } }
  end

  {
    id: session[:id],
    round: session[:round],
    turn_index: session[:turn_index],
    active: active ? { name: active[:name], score: active[:score] } : nil,
    conditions: response_conditions,
  }.to_json
end

post '/v1/auth/register' do
  content_type :json
  data = parse_json_body
  halt 400, { error: 'invalid request' }.to_json unless data.is_a?(Hash)

  username, password, role = validate_registration(data)

  USERS_MUTEX.synchronize do
    halt 409, { error: 'username already exists' }.to_json if USERS.key?(username)
    USERS[username] = { username: username, password_hash: PasswordHelper.hash(password), role: role }
  end

  status 201
  { username: username, role: role }.to_json
end

post '/v1/auth/login' do
  content_type :json
  data = parse_json_body
  halt 400, { error: 'invalid request' }.to_json unless data.is_a?(Hash)

  username = data['username'].to_s
  password = data['password'].to_s

  user = USERS_MUTEX.synchronize { USERS[username] }
  halt 401, { error: 'invalid credentials' }.to_json unless user && PasswordHelper.verify(password, user[:password_hash])

  { username: username, token: "session-#{username}" }.to_json
end

not_found do
  content_type :json
  { error: 'not found' }.to_json
end

error do
  content_type :json
  status 500
  { error: 'internal server error' }.to_json
end
