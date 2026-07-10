# frozen_string_literal: true

require 'sinatra'
require 'json'

# Use Puma as the HTTP server (pinned to 8.0.2 in the Gemfile).
set :server, :puma
# Bind to loopback by default; the `-o` CLI flag in run.sh overrides this.
set :bind, '127.0.0.1'
set :port, (ENV['PORT'] || 4567).to_i

# ---------------------------------------------------------------------------
# D&D 5e reference data
# ---------------------------------------------------------------------------

# XP per challenge rating (first benchmark suite CRs).
XP_BY_CR = {
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

# Accept decimal aliases in addition to the canonical fractional strings.
CR_ALIASES = {
  '0.125' => '1/8',
  '0.25' => '1/4',
  '0.5' => '1/2'
}.freeze

# Encounter-difficulty XP thresholds per character level: [easy, medium, hard, deadly].
THRESHOLDS_BY_LEVEL = {
  1 => [25, 50, 75, 100],
  2 => [50, 100, 150, 200],
  3 => [75, 150, 225, 400],
  4 => [125, 250, 375, 500],
  5 => [250, 500, 750, 1100],
  6 => [300, 600, 900, 1400],
  7 => [350, 750, 1100, 1700],
  8 => [450, 900, 1400, 2100],
  9 => [550, 1100, 1600, 2400],
  10 => [600, 1200, 1900, 2800],
  11 => [800, 1600, 2400, 3600],
  12 => [1000, 2000, 3000, 4500],
  13 => [1100, 2200, 3400, 5100],
  14 => [1250, 2500, 3800, 5700],
  15 => [1400, 2800, 4300, 6400],
  16 => [1600, 3200, 4800, 7200],
  17 => [2000, 3900, 5900, 8800],
  18 => [2100, 4200, 6300, 9500],
  19 => [2400, 4700, 7200, 10900],
  20 => [2800, 5700, 8500, 12700]
}.freeze

# Encounter multiplier based on the total number of monsters.
def multiplier_for(monster_count)
  case monster_count
  when 0..1 then Rational(1)
  when 2 then Rational(3, 2)
  when 3..6 then Rational(2)
  when 7..10 then Rational(5, 2)
  when 11..14 then Rational(3)
  else Rational(4)
  end
end

# Render a Rational/Integer as int when whole, otherwise as float.
def as_number(value)
  value.denominator == 1 ? value.to_i : value.to_f
end

# D&D 5e ability modifier: floor((score - 10) / 2).
# Ruby Integer division floors toward negative infinity, so score 9 -> -1.
def ability_modifier(score)
  (score - 10) / 2
end

# D&D 5e proficiency bonus by character level (1-20).
def proficiency_bonus(level)
  case level
  when 1..4 then 2
  when 5..8 then 3
  when 9..12 then 4
  when 13..16 then 5
  when 17..20 then 6
  end
end

# ---------------------------------------------------------------------------
# Stateful combat (Stage 2) — in-memory sessions keyed by client-supplied id.
# ---------------------------------------------------------------------------

SESSIONS = {}
SESSIONS_MUTEX = Mutex.new

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

helpers do
  def json_body
    raw = request.body.read.to_s
    halt_json_error(400, 'invalid JSON') if raw.strip.empty?
    JSON.parse(raw)
  rescue JSON::ParserError
    halt_json_error(400, 'invalid JSON')
  end

  def halt_json_error(code, message)
    halt code, { 'Content-Type' => 'application/json' }, JSON.generate({ 'error' => message })
  end

  def json_response(obj, code = 200)
    content_type :json
    status code
    JSON.generate(obj)
  end

  # Serialize one initiative-order entry as {"name": ..., "score": ...}.
  def combatant_json(entry)
    { 'name' => entry[:name], 'score' => entry[:score] }
  end

  # Build the conditions map for a session. Includes every combatant that
  # has an entry in the session's conditions table (even if its list is now
  # empty after expiry), ordered by initiative order. Combatants that never
  # had a condition attached do not appear.
  def conditions_map(session)
    map = {}
    session[:order].each do |entry|
      name = entry[:name]
      next unless session[:conditions].key?(name)
      list = session[:conditions][name]
      map[name] = list.map do |c|
        { 'condition' => c[:condition], 'remaining_rounds' => c[:remaining_rounds] }
      end
    end
    map
  end

  # Look up a combat session by id or halt with 404.
  def find_session(id)
    session = SESSIONS[id]
    halt_json_error(404, 'session not found') unless session
    session
  end
end

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

get '/health' do
  content_type :json
  JSON.generate('ok' => true)
end

# POST /v1/dice/stats
# Grammar: <count>d<sides>[+<modifier>|-<modifier>]
post '/v1/dice/stats' do
  data = json_body
  halt_json_error(400, 'invalid input') unless data.is_a?(Hash)

  expr = data['expression']
  halt_json_error(400, 'invalid expression') unless expr.is_a?(String)

  match = expr.match(/\A(\d+)d(\d+)(?:([+-])(\d+))?\z/)
  halt_json_error(400, 'invalid expression') unless match

  count = match[1].to_i
  sides = match[2].to_i
  if match[3] && match[4]
    modifier = match[4].to_i
    modifier = -modifier if match[3] == '-'
  else
    modifier = 0
  end

  halt_json_error(400, 'invalid expression') unless count > 0 && sides > 0

  min = count + modifier
  max = (count * sides) + modifier
  total = min + max
  average = total.even? ? (total / 2) : (total / 2.0)

  json_response(
    'dice_count' => count,
    'sides' => sides,
    'modifier' => modifier,
    'min' => min,
    'max' => max,
    'average' => average
  )
end

# POST /v1/checks/ability
post '/v1/checks/ability' do
  data = json_body
  halt_json_error(400, 'invalid input') unless data.is_a?(Hash)

  roll = data['roll']
  modifier = data['modifier']
  dc = data['dc']
  unless roll.is_a?(Integer) && modifier.is_a?(Integer) && dc.is_a?(Integer)
    halt_json_error(400, 'invalid input')
  end

  total = roll + modifier
  success = total >= dc
  margin = total - dc

  json_response(
    'total' => total,
    'success' => success,
    'margin' => margin
  )
end

# POST /v1/encounters/adjusted-xp
post '/v1/encounters/adjusted-xp' do
  data = json_body
  halt_json_error(400, 'invalid input') unless data.is_a?(Hash)

  party = data['party']
  monsters = data['monsters']
  unless party.is_a?(Array) && monsters.is_a?(Array)
    halt_json_error(400, 'invalid input')
  end

  easy = medium = hard = deadly = 0
  party.each do |member|
    halt_json_error(400, 'invalid party') unless member.is_a?(Hash)
    level = member['level']
    halt_json_error(400, 'invalid party') unless level.is_a?(Integer)
    row = THRESHOLDS_BY_LEVEL[level]
    halt_json_error(400, 'unsupported level') unless row
    easy += row[0]
    medium += row[1]
    hard += row[2]
    deadly += row[3]
  end

  base_xp = 0
  monster_count = 0
  monsters.each do |mon|
    halt_json_error(400, 'invalid monster') unless mon.is_a?(Hash)
    cr = mon['cr']
    count = mon['count']
    unless cr.is_a?(String) && count.is_a?(Integer) && count > 0
      halt_json_error(400, 'invalid monster')
    end
    cr_key = CR_ALIASES[cr] || cr
    xp = XP_BY_CR[cr_key]
    halt_json_error(400, 'unsupported cr') unless xp
    base_xp += xp * count
    monster_count += count
  end

  multiplier = multiplier_for(monster_count)
  adjusted = base_xp * multiplier
  adjusted_val = as_number(adjusted)
  multiplier_val = as_number(multiplier)

  difficulty = if adjusted_val >= deadly
                 'deadly'
               elsif adjusted_val >= hard
                 'hard'
               elsif adjusted_val >= medium
                 'medium'
               elsif adjusted_val >= easy
                 'easy'
               else
                 'trivial'
               end

  json_response(
    'base_xp' => base_xp,
    'monster_count' => monster_count,
    'multiplier' => multiplier_val,
    'adjusted_xp' => adjusted_val,
    'difficulty' => difficulty,
    'thresholds' => {
      'easy' => easy,
      'medium' => medium,
      'hard' => hard,
      'deadly' => deadly
    }
  )
end

# POST /v1/initiative/order
post '/v1/initiative/order' do
  data = json_body
  halt_json_error(400, 'invalid input') unless data.is_a?(Hash)

  combatants = data['combatants']
  halt_json_error(400, 'invalid input') unless combatants.is_a?(Array)

  entries = combatants.map do |c|
    halt_json_error(400, 'invalid combatant') unless c.is_a?(Hash)
    name = c['name']
    dex = c['dex']
    roll = c['roll']
    unless name.is_a?(String) && dex.is_a?(Integer) && roll.is_a?(Integer)
      halt_json_error(400, 'invalid combatant')
    end
    { name: name, dex: dex, roll: roll, score: roll + dex }
  end

  sorted = entries.sort_by { |e| [-e[:score], -e[:dex], e[:name]] }

  json_response(
    'order' => sorted.map { |e| { 'name' => e[:name], 'score' => e[:score] } }
  )
end

# POST /v1/characters/ability-modifier
post '/v1/characters/ability-modifier' do
  data = json_body
  halt_json_error(400, 'invalid input') unless data.is_a?(Hash)

  score = data['score']
  halt_json_error(400, 'invalid score') unless score.is_a?(Integer)
  halt_json_error(400, 'invalid score') unless score.between?(1, 30)

  json_response('score' => score, 'modifier' => ability_modifier(score))
end

# POST /v1/characters/proficiency
post '/v1/characters/proficiency' do
  data = json_body
  halt_json_error(400, 'invalid input') unless data.is_a?(Hash)

  level = data['level']
  halt_json_error(400, 'invalid level') unless level.is_a?(Integer)
  halt_json_error(400, 'invalid level') unless level.between?(1, 20)

  json_response('level' => level, 'proficiency_bonus' => proficiency_bonus(level))
end

# POST /v1/characters/derived-stats
post '/v1/characters/derived-stats' do
  data = json_body
  halt_json_error(400, 'invalid input') unless data.is_a?(Hash)

  level = data['level']
  unless level.is_a?(Integer) && level.between?(1, 20)
    halt_json_error(400, 'invalid level')
  end

  abilities = data['abilities']
  halt_json_error(400, 'invalid abilities') unless abilities.is_a?(Hash)

  modifiers = {}
  %w[str dex con int wis cha].each do |abbr|
    score = abilities[abbr]
    unless score.is_a?(Integer) && score.between?(1, 30)
      halt_json_error(400, 'invalid abilities')
    end
    modifiers[abbr] = ability_modifier(score)
  end

  armor = data['armor']
  halt_json_error(400, 'invalid armor') unless armor.is_a?(Hash)

  base = armor['base']
  dex_cap = armor['dex_cap']
  unless base.is_a?(Integer) && dex_cap.is_a?(Integer)
    halt_json_error(400, 'invalid armor')
  end

  shield_bonus = armor['shield'] == true ? 2 : 0

  hp_max = level * (6 + modifiers['con'])
  armor_class = base + [modifiers['dex'], dex_cap].min + shield_bonus

  json_response(
    'level' => level,
    'proficiency_bonus' => proficiency_bonus(level),
    'hp_max' => hp_max,
    'armor_class' => armor_class,
    'modifiers' => modifiers
  )
end

# ---------------------------------------------------------------------------
# Stateful combat routes (Stage 2)
# ---------------------------------------------------------------------------

# POST /v1/combat/sessions
# Create a combat session with a client-supplied id and initiative order.
post '/v1/combat/sessions' do
  data = json_body
  halt_json_error(400, 'invalid input') unless data.is_a?(Hash)

  id = data['id']
  halt_json_error(400, 'invalid id') unless id.is_a?(String) && !id.empty?

  combatants = data['combatants']
  halt_json_error(400, 'invalid combatants') unless combatants.is_a?(Array) && !combatants.empty?

  entries = combatants.map do |c|
    halt_json_error(400, 'invalid combatant') unless c.is_a?(Hash)
    name = c['name']
    dex = c['dex']
    roll = c['roll']
    unless name.is_a?(String) && dex.is_a?(Integer) && roll.is_a?(Integer)
      halt_json_error(400, 'invalid combatant')
    end
    { name: name, dex: dex, roll: roll, score: roll + dex }
  end

  order = entries.sort_by { |e| [-e[:score], -e[:dex], e[:name]] }

  session = {
    id: id,
    order: order,
    round: 1,
    turn_index: 0,
    conditions: {}
  }

  SESSIONS_MUTEX.synchronize { SESSIONS[id] = session }

  json_response(
    'id' => id,
    'round' => 1,
    'turn_index' => 0,
    'active' => combatant_json(order[0]),
    'order' => order.map { |e| combatant_json(e) }
  )
end

# POST /v1/combat/sessions/:id/conditions
# Attach a timed condition to a combatant in the session.
post '/v1/combat/sessions/:id/conditions' do
  session = find_session(params[:id])

  data = json_body
  halt_json_error(400, 'invalid input') unless data.is_a?(Hash)

  target = data['target']
  condition = data['condition']
  duration = data['duration_rounds']

  halt_json_error(400, 'invalid condition') unless condition.is_a?(String) && !condition.empty?
  halt_json_error(400, 'invalid duration_rounds') unless duration.is_a?(Integer) && duration > 0
  unless target.is_a?(String) && session[:order].any? { |e| e[:name] == target }
    halt_json_error(400, 'unknown target')
  end

  SESSIONS_MUTEX.synchronize do
    list = (session[:conditions][target] ||= [])
    list << { condition: condition, remaining_rounds: duration }
  end

  list = session[:conditions][target]
  json_response(
    'target' => target,
    'conditions' => list.map do |c|
      { 'condition' => c[:condition], 'remaining_rounds' => c[:remaining_rounds] }
    end
  )
end

# POST /v1/combat/sessions/:id/advance
# Advance to the next combatant, ticking down the active combatant's conditions.
post '/v1/combat/sessions/:id/advance' do
  session = find_session(params[:id])
  order = session[:order]
  halt_json_error(400, 'empty order') if order.empty?

  active = nil
  SESSIONS_MUTEX.synchronize do
    next_index = session[:turn_index] + 1
    if next_index >= order.length
      next_index = 0
      session[:round] += 1
    end
    session[:turn_index] = next_index
    active = order[next_index]

    # At the start of the active combatant's turn, decrement their conditions
    # and remove any whose remaining duration has reached 0. The combatant's
    # key is retained (with an empty list) so callers can still see that the
    # combatant once held conditions that have since expired.
    list = session[:conditions][active[:name]]
    if list
      list.each { |c| c[:remaining_rounds] -= 1 }
      list.reject! { |c| c[:remaining_rounds] <= 0 }
    end
  end

  json_response(
    'id' => session[:id],
    'round' => session[:round],
    'turn_index' => session[:turn_index],
    'active' => combatant_json(active),
    'conditions' => conditions_map(session)
  )
end
