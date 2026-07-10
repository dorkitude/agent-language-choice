#!/usr/bin/env ruby
# frozen_string_literal: true
#
# D&D REST engine — Ruby stdlib only (socket + json).
# No Sinatra/Rails/Rack/gems.

require 'socket'
require 'json'

HOST = '127.0.0.1'
PORT = ENV.fetch('PORT', '4567').to_i

# Challenge rating -> XP
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

# Per-level encounter difficulty thresholds (first suite: level 3 only).
LEVEL_THRESHOLDS = {
  3 => { easy: 75, medium: 150, hard: 225, deadly: 400 }
}.freeze

REASON = {
  200 => 'OK',
  400 => 'Bad Request',
  404 => 'Not Found',
  500 => 'Internal Server Error'
}.freeze

# In-memory combat sessions (Stateful Combat stage).
SESSIONS = {}
STATE_MUTEX = Mutex.new

# Encounter multiplier based on total monster count.
def multiplier_for(count)
  case count
  when 1 then 1
  when 2 then 1.5
  when 3..6 then 2
  when 7..10 then 2.5
  when 11..14 then 3
  else 4 # 15+ (and defensive default)
  end
end

# POST /v1/dice/stats
def dice_stats(body)
  data = JSON.parse(body)
  expr = data['expression'].to_s.strip
  m = expr.match(/\A(\d+)d(\d+)(?:([+-])(\d+))?\z/)
  return [400, { error: 'invalid expression' }] unless m

  count = m[1].to_i
  sides = m[2].to_i
  modifier = m[3] ? (m[3] == '-' ? -m[4].to_i : m[4].to_i) : 0
  return [400, { error: 'invalid expression' }] if count <= 0 || sides <= 0

  min = count + modifier
  max = count * sides + modifier
  avg = (min + max) / 2.0
  average = avg == avg.to_i ? avg.to_i : avg
  [200, {
    dice_count: count,
    sides: sides,
    modifier: modifier,
    min: min,
    max: max,
    average: average
  }]
end

# POST /v1/checks/ability
def ability_check(body)
  data = JSON.parse(body)
  roll = data['roll'].to_i
  modifier = data['modifier'].to_i
  dc = data['dc'].to_i
  total = roll + modifier
  [200, {
    total: total,
    success: total >= dc,
    margin: total - dc
  }]
end

# POST /v1/encounters/adjusted-xp
def adjusted_xp(body)
  data = JSON.parse(body)
  party = data['party'] || []
  monsters = data['monsters'] || []

  base_xp = 0
  monster_count = 0
  monsters.each do |mon|
    cr = mon['cr'].to_s
    xp = CR_XP[cr]
    return [400, { error: "unsupported cr: #{cr}" }] unless xp
    cnt = mon['count'].to_i
    base_xp += xp * cnt
    monster_count += cnt
  end

  mult = multiplier_for(monster_count)
  adj = base_xp * mult
  adj = adj.to_i if adj.is_a?(Float) && adj == adj.to_i

  threshold = lambda do |key|
    party.sum { |p| (LEVEL_THRESHOLDS[p['level'].to_i] || LEVEL_THRESHOLDS[3])[key] }
  end
  thresholds = {
    easy: threshold.call(:easy),
    medium: threshold.call(:medium),
    hard: threshold.call(:hard),
    deadly: threshold.call(:deadly)
  }

  difficulty = if adj >= thresholds[:deadly]
                 'deadly'
               elsif adj >= thresholds[:hard]
                 'hard'
               elsif adj >= thresholds[:medium]
                 'medium'
               elsif adj >= thresholds[:easy]
                 'easy'
               else
                 'trivial'
               end

  [200, {
    base_xp: base_xp,
    monster_count: monster_count,
    multiplier: mult,
    adjusted_xp: adj,
    difficulty: difficulty,
    thresholds: thresholds
  }]
end

# POST /v1/initiative/order
def initiative_order(body)
  data = JSON.parse(body)
  combatants = data['combatants'] || []
  list = combatants.map do |c|
    dex = c['dex'].to_i
    roll = c['roll'].to_i
    { name: c['name'], dex: dex, roll: roll, score: roll + dex }
  end
  # score desc, then dex desc, then name asc
  list.sort_by! { |c| [-c[:score], -c[:dex], c[:name].to_s] }
  [200, { order: list.map { |c| { name: c[:name], score: c[:score] } } }]
end

# Ability modifier: floor((score - 10) / 2).
# Ruby integer division floors toward negative infinity.
def ability_modifier(score)
  (score - 10) / 2
end

# Proficiency bonus by character level tier.
def proficiency_bonus(level)
  case level
  when 1..4 then 2
  when 5..8 then 3
  when 9..12 then 4
  when 13..16 then 5
  when 17..20 then 6
  end
end

# Validate that +value+ is an Integer within +range+ (inclusive).
def int_in_range(value, range)
  value.is_a?(Integer) && range.cover?(value)
end

# POST /v1/characters/ability-modifier
def char_ability_modifier(body)
  data = JSON.parse(body)
  score = data['score']
  return [400, { error: 'invalid score' }] unless int_in_range(score, 1..30)
  [200, { score: score, modifier: ability_modifier(score) }]
end

# POST /v1/characters/proficiency
def char_proficiency(body)
  data = JSON.parse(body)
  level = data['level']
  return [400, { error: 'invalid level' }] unless int_in_range(level, 1..20)
  [200, { level: level, proficiency_bonus: proficiency_bonus(level) }]
end

ABILITY_KEYS = %w[str dex con int wis cha].freeze

# POST /v1/characters/derived-stats
def char_derived_stats(body)
  data = JSON.parse(body)
  level = data['level']
  return [400, { error: 'invalid level' }] unless int_in_range(level, 1..20)

  abilities = data['abilities']
  return [400, { error: 'invalid abilities' }] unless abilities.is_a?(Hash)

  modifiers = {}
  ABILITY_KEYS.each do |ab|
    val = abilities[ab]
    return [400, { error: "invalid ability: #{ab}" }] unless int_in_range(val, 1..30)
    modifiers[ab] = ability_modifier(val)
  end

  armor = data['armor']
  return [400, { error: 'invalid armor' }] unless armor.is_a?(Hash)
  base = armor['base']
  dex_cap = armor['dex_cap']
  return [400, { error: 'invalid armor base' }] unless base.is_a?(Integer)
  return [400, { error: 'invalid dex_cap' }] unless dex_cap.is_a?(Integer)

  shield_bonus = armor['shield'] ? 2 : 0
  armor_class = base + [modifiers['dex'], dex_cap].min + shield_bonus
  hp_max = level * (6 + modifiers['con'])

  [200, {
    level: level,
    proficiency_bonus: proficiency_bonus(level),
    hp_max: hp_max,
    armor_class: armor_class,
    modifiers: modifiers
  }]
end

# --- Stateful Combat ---

# Active combatant at the current turn index, as {name, score} or nil.
def session_active(s)
  c = s[:order][s[:turn_index]]
  c ? { name: c[:name], score: c[:score] } : nil
end

# Public view for session creation: id, round, turn_index, active, order.
def session_view(s)
  {
    id: s[:id],
    round: s[:round],
    turn_index: s[:turn_index],
    active: session_active(s),
    order: s[:order].map { |c| { name: c[:name], score: c[:score] } }
  }
end

# Map of combatant name -> conditions.
# A combatant that has ever had a condition keeps its key (even when the
# list is now empty after expiry), so callers can see the combatant still
# exists in the conditions map. Combatants that never received a
# condition are absent.
def conditions_view(s)
  map = {}
  s[:conditions].each do |name, conds|
    list = conds || []
    map[name] = list.map { |c| { condition: c[:condition], remaining_rounds: c[:remaining_rounds] } }
  end
  map
end

# POST /v1/combat/sessions
def create_combat_session(body)
  data = JSON.parse(body)
  id = data['id']
  return [400, { error: 'invalid id' }] unless id.is_a?(String) && !id.empty?
  combatants = data['combatants']
  return [400, { error: 'invalid combatants' }] unless combatants.is_a?(Array)

  entries = combatants.map do |c|
    return [400, { error: 'invalid combatant' }] unless c.is_a?(Hash)
    name = c['name']
    dex = c['dex']
    roll = c['roll']
    return [400, { error: 'invalid combatant name' }] unless name.is_a?(String) && !name.empty?
    return [400, { error: 'invalid dex' }] unless dex.is_a?(Integer)
    return [400, { error: 'invalid roll' }] unless roll.is_a?(Integer)
    { name: name, dex: dex, roll: roll, score: roll + dex }
  end
  # Initiative: score desc, then dex desc, then name asc.
  entries.sort_by! { |c| [-c[:score], -c[:dex], c[:name]] }
  order = entries.map { |c| { name: c[:name], score: c[:score] } }

  session = {
    id: id,
    round: 1,
    turn_index: 0,
    order: order,
    conditions: {}
  }
  STATE_MUTEX.synchronize { SESSIONS[id] = session }
  [200, session_view(session)]
end

# POST /v1/combat/sessions/{id}/conditions
def add_condition(session_id, body)
  session = SESSIONS[session_id]
  return [404, { error: 'session not found' }] unless session

  data = JSON.parse(body)
  target = data['target']
  condition = data['condition']
  duration = data['duration_rounds']
  return [400, { error: 'invalid target' }] unless target.is_a?(String) && !target.empty?
  return [400, { error: 'unknown target' }] unless session[:order].any? { |c| c[:name] == target }
  return [400, { error: 'invalid condition' }] unless condition.is_a?(String) && !condition.empty?
  return [400, { error: 'invalid duration_rounds' }] unless duration.is_a?(Integer) && duration > 0

  conds = STATE_MUTEX.synchronize do
    list = (session[:conditions][target] ||= [])
    list << { condition: condition, remaining_rounds: duration }
    list
  end
  [200, {
    target: target,
    conditions: conds.map { |c| { condition: c[:condition], remaining_rounds: c[:remaining_rounds] } }
  }]
end

# POST /v1/combat/sessions/{id}/advance
def advance_turn(session_id)
  session = SESSIONS[session_id]
  return [404, { error: 'session not found' }] unless session

  STATE_MUTEX.synchronize do
    session[:turn_index] += 1
    if session[:turn_index] >= session[:order].size
      session[:turn_index] = 0
      session[:round] += 1
    end
    active = session[:order][session[:turn_index]]
    if active
      conds = session[:conditions][active[:name]]
      if conds
        conds.each { |c| c[:remaining_rounds] -= 1 }
        conds.reject! { |c| c[:remaining_rounds] <= 0 }
        # Keep the (now possibly empty) list so the combatant's key remains
        # present in the conditions view after its conditions expire.
      end
    end
  end

  [200, {
    id: session[:id],
    round: session[:round],
    turn_index: session[:turn_index],
    active: session_active(session),
    conditions: conditions_view(session)
  }]
end

# Route a parsed request to a handler.
def route(method, path, body)
  result =
    case [method, path]
    when ['GET', '/health']
      [200, { ok: true }]
    when ['POST', '/v1/dice/stats']
      dice_stats(body)
    when ['POST', '/v1/checks/ability']
      ability_check(body)
    when ['POST', '/v1/encounters/adjusted-xp']
      adjusted_xp(body)
    when ['POST', '/v1/initiative/order']
      initiative_order(body)
    when ['POST', '/v1/characters/ability-modifier']
      char_ability_modifier(body)
    when ['POST', '/v1/characters/proficiency']
      char_proficiency(body)
    when ['POST', '/v1/characters/derived-stats']
      char_derived_stats(body)
    end
  return result if result

  if method == 'POST'
    return create_combat_session(body) if path == '/v1/combat/sessions'
    if (m = %r{\A/v1/combat/sessions/([^/]+)/conditions\z}.match(path))
      return add_condition(m[1], body)
    end
    if (m = %r{\A/v1/combat/sessions/([^/]+)/advance\z}.match(path))
      return advance_turn(m[1])
    end
  end
  [404, { error: 'not found' }]
end

def send_response(client, status, obj)
  payload = JSON.generate(obj)
  client.write("HTTP/1.1 #{status} #{REASON[status] || 'OK'}\r\n")
  client.write("Content-Type: application/json\r\n")
  client.write("Content-Length: #{payload.bytesize}\r\n")
  client.write("Connection: close\r\n")
  client.write("\r\n")
  client.write(payload)
end

def handle(client)
  request_line = client.gets
  return unless request_line

  method, path = request_line.split(' ')
  headers = {}
  while (line = client.gets)
    line = line.strip
    break if line.empty?
    key, val = line.split(':', 2)
    headers[key.downcase] = val.to_s.strip
  end

  content_length = headers['content-length'].to_i
  body = content_length.positive? ? client.read(content_length) : ''

  status, obj = route(method, path, body)
  send_response(client, status, obj)
rescue JSON::ParserError
  begin
    send_response(client, 400, { error: 'invalid json' })
  rescue StandardError
    nil
  end
rescue => e
  begin
    send_response(client, 500, { error: e.message })
  rescue StandardError
    nil
  end
ensure
  begin
    client.close
  rescue StandardError
    nil
  end
end

server = TCPServer.new(HOST, PORT)
STDERR.puts "dnd-rest listening on #{HOST}:#{PORT}"

loop do
  client = server.accept
  Thread.new(client) { |c| handle(c) }
end
