require 'sinatra'
require 'json'

set :bind, '127.0.0.1'
set :port, ENV.fetch('PORT', '4567').to_i

COMBAT_SESSIONS = {}

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

LEVEL_3_THRESHOLDS = { easy: 75, medium: 150, hard: 225, deadly: 400 }.freeze
ABILITIES = %w[str dex con int wis cha].freeze

helpers do
  def parsed_body
    JSON.parse(request.body.read)
  rescue JSON::ParserError
    nil
  end

  def json_response(data, status = 200)
    content_type :json
    status status
    data.to_json
  end

  def ability_modifier(score)
    (score - 10).div(2)
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

  def valid_ability?(value)
    value.is_a?(Integer) && value >= 1 && value <= 30
  end

  def active_combatant(session)
    session[:order][session[:turn_index]]
  end

  def serialize_conditions(session)
    session[:conditions].transform_values do |conds|
      conds.map { |c| { condition: c[:condition], remaining_rounds: c[:remaining_rounds] } }
    end
  end
end

get '/health' do
  json_response({ ok: true })
end

post '/v1/dice/stats' do
  body = parsed_body
  halt 400, json_response({ error: 'invalid request body' }) unless body.is_a?(Hash)

  expression = body['expression'].to_s
  match = expression.match(/\A\s*([1-9]\d*)d([1-9]\d*)(?:([+-])(\d+))?\s*\z/)
  halt 400, json_response({ error: 'invalid expression' }) unless match

  dice_count = match[1].to_i
  sides = match[2].to_i
  modifier = match[3] ? (match[3] == '+' ? match[4].to_i : -match[4].to_i) : 0

  min = dice_count + modifier
  max = dice_count * sides + modifier
  average = (min + max).even? ? (min + max) / 2 : (min + max) / 2.0

  json_response({
    dice_count: dice_count,
    sides: sides,
    modifier: modifier,
    min: min,
    max: max,
    average: average
  })
end

post '/v1/checks/ability' do
  body = parsed_body
  halt 400, json_response({ error: 'invalid request body' }) unless body.is_a?(Hash)

  begin
    roll = Integer(body['roll'])
    modifier = Integer(body['modifier'])
    dc = Integer(body['dc'])
  rescue ArgumentError, TypeError
    halt 400, json_response({ error: 'invalid integers' })
  end

  total = roll + modifier
  success = total >= dc
  margin = total - dc

  json_response({ total: total, success: success, margin: margin })
end

post '/v1/encounters/adjusted-xp' do
  body = parsed_body
  halt 400, json_response({ error: 'invalid request body' }) unless body.is_a?(Hash)

  party = body['party']
  monsters = body['monsters']
  halt 400, json_response({ error: 'invalid party' }) unless party.is_a?(Array) && !party.empty?
  halt 400, json_response({ error: 'invalid monsters' }) unless monsters.is_a?(Array) && !monsters.empty?

  thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 }
  party.each do |member|
    halt 400, json_response({ error: 'invalid party member' }) unless member.is_a?(Hash)
    level = member['level']
    halt 400, json_response({ error: 'unsupported party level' }) unless level == 3
    LEVEL_3_THRESHOLDS.each { |k, v| thresholds[k] += v }
  end

  base_xp = 0
  monster_count = 0
  monsters.each do |monster|
    halt 400, json_response({ error: 'invalid monster' }) unless monster.is_a?(Hash)
    cr = monster['cr'].to_s
    count = monster['count']
    halt 400, json_response({ error: 'unsupported challenge rating' }) unless CR_XP.key?(cr)
    begin
      count = Integer(count)
    rescue ArgumentError, TypeError
      halt 400, json_response({ error: 'invalid monster count' })
    end
    halt 400, json_response({ error: 'invalid monster count' }) unless count.positive?

    base_xp += CR_XP[cr] * count
    monster_count += count
  end

  multiplier = case monster_count
               when 1 then 1
               when 2 then 1.5
               when 3..6 then 2
               when 7..10 then 2.5
               when 11..14 then 3
               else 4
               end

  adjusted_xp = (base_xp * multiplier).to_i

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

  json_response({
    base_xp: base_xp,
    monster_count: monster_count,
    multiplier: multiplier,
    adjusted_xp: adjusted_xp,
    difficulty: difficulty,
    thresholds: thresholds
  })
end

post '/v1/initiative/order' do
  body = parsed_body
  halt 400, json_response({ error: 'invalid request body' }) unless body.is_a?(Hash)

  combatants = body['combatants']
  halt 400, json_response({ error: 'invalid combatants' }) unless combatants.is_a?(Array)

  scored = combatants.map do |c|
    halt 400, json_response({ error: 'invalid combatant' }) unless c.is_a?(Hash)
    name = c['name']
    dex = c['dex']
    roll = c['roll']
    halt 400, json_response({ error: 'missing combatant fields' }) if name.nil? || dex.nil? || roll.nil?
    begin
      dex = Integer(dex)
      roll = Integer(roll)
    rescue ArgumentError, TypeError
      halt 400, json_response({ error: 'invalid combatant fields' })
    end
    { name: name.to_s, score: roll + dex, dex: dex }
  end

  order = scored.sort do |a, b|
    cmp = b[:score] <=> a[:score]
    cmp = b[:dex] <=> a[:dex] if cmp.zero?
    cmp = a[:name] <=> b[:name] if cmp.zero?
    cmp
  end

  json_response({ order: order.map { |c| { name: c[:name], score: c[:score] } } })
end

post '/v1/characters/ability-modifier' do
  body = parsed_body
  halt 400, json_response({ error: 'invalid request body' }) unless body.is_a?(Hash)

  score = body['score']
  halt 400, json_response({ error: 'invalid score' }) unless score.is_a?(Integer) && score >= 1 && score <= 30

  json_response({ score: score, modifier: ability_modifier(score) })
end

post '/v1/characters/proficiency' do
  body = parsed_body
  halt 400, json_response({ error: 'invalid request body' }) unless body.is_a?(Hash)

  level = body['level']
  halt 400, json_response({ error: 'invalid level' }) unless level.is_a?(Integer) && level >= 1 && level <= 20

  json_response({ level: level, proficiency_bonus: proficiency_bonus(level) })
end

post '/v1/characters/derived-stats' do
  body = parsed_body
  halt 400, json_response({ error: 'invalid request body' }) unless body.is_a?(Hash)

  level = body['level']
  halt 400, json_response({ error: 'invalid level' }) unless level.is_a?(Integer) && level >= 1 && level <= 20

  abilities = body['abilities']
  halt 400, json_response({ error: 'invalid abilities' }) unless abilities.is_a?(Hash)
  ABILITIES.each do |ability|
    score = abilities[ability]
    halt 400, json_response({ error: 'invalid ability score' }) unless valid_ability?(score)
  end

  armor = body['armor']
  halt 400, json_response({ error: 'invalid armor' }) unless armor.is_a?(Hash)
  base = armor['base']
  dex_cap = armor['dex_cap']
  shield = armor['shield']
  halt 400, json_response({ error: 'invalid armor base' }) unless base.is_a?(Integer) && base >= 0
  halt 400, json_response({ error: 'invalid armor dex_cap' }) unless dex_cap.is_a?(Integer) && dex_cap >= 0
  halt 400, json_response({ error: 'invalid armor shield' }) unless shield == true || shield == false

  modifiers = {}
  ABILITIES.each { |ability| modifiers[ability] = ability_modifier(abilities[ability]) }

  shield_bonus = shield ? 2 : 0
  armor_class = base + [modifiers['dex'], dex_cap].min + shield_bonus
  hp_max = level * (6 + modifiers['con'])

  json_response({
    level: level,
    proficiency_bonus: proficiency_bonus(level),
    hp_max: hp_max,
    armor_class: armor_class,
    modifiers: modifiers
  })
end

post '/v1/combat/sessions' do
  body = parsed_body
  halt 400, json_response({ error: 'invalid request body' }) unless body.is_a?(Hash)

  id = body['id']
  halt 400, json_response({ error: 'missing id' }) if id.nil? || id.to_s.empty?
  halt 400, json_response({ error: 'duplicate session id' }) if COMBAT_SESSIONS.key?(id.to_s)

  combatants = body['combatants']
  halt 400, json_response({ error: 'invalid combatants' }) unless combatants.is_a?(Array) && !combatants.empty?

  scored = combatants.map do |c|
    halt 400, json_response({ error: 'invalid combatant' }) unless c.is_a?(Hash)
    name = c['name']
    dex = c['dex']
    roll = c['roll']
    halt 400, json_response({ error: 'missing combatant fields' }) if name.nil? || dex.nil? || roll.nil?
    begin
      dex = Integer(dex)
      roll = Integer(roll)
    rescue ArgumentError, TypeError
      halt 400, json_response({ error: 'invalid combatant fields' })
    end
    { name: name.to_s, score: roll + dex, dex: dex }
  end

  order = scored.sort do |a, b|
    cmp = b[:score] <=> a[:score]
    cmp = b[:dex] <=> a[:dex] if cmp.zero?
    cmp = a[:name] <=> b[:name] if cmp.zero?
    cmp
  end

  session = {
    id: id.to_s,
    round: 1,
    turn_index: 0,
    order: order.map { |c| { name: c[:name], score: c[:score] } },
    conditions: Hash.new { |h, k| h[k] = [] }
  }
  COMBAT_SESSIONS[id.to_s] = session

  json_response({
    id: session[:id],
    round: session[:round],
    turn_index: session[:turn_index],
    active: session[:order][0],
    order: session[:order]
  })
end

post '/v1/combat/sessions/:id/conditions' do
  session = COMBAT_SESSIONS[params[:id]]
  halt 404, json_response({ error: 'session not found' }) unless session

  body = parsed_body
  halt 400, json_response({ error: 'invalid request body' }) unless body.is_a?(Hash)

  target = body['target']
  condition_name = body['condition']
  duration = body['duration_rounds']

  halt 400, json_response({ error: 'missing target' }) if target.nil?
  halt 400, json_response({ error: 'unknown target' }) unless session[:order].any? { |c| c[:name] == target.to_s }
  halt 400, json_response({ error: 'missing condition' }) if condition_name.nil?
  halt 400, json_response({ error: 'invalid duration_rounds' }) unless duration.is_a?(Integer) && duration.positive?

  session[:conditions][target.to_s] << { condition: condition_name.to_s, remaining_rounds: duration }

  json_response({
    target: target.to_s,
    conditions: session[:conditions][target.to_s].map { |c| { condition: c[:condition], remaining_rounds: c[:remaining_rounds] } }
  })
end

post '/v1/combat/sessions/:id/advance' do
  session = COMBAT_SESSIONS[params[:id]]
  halt 404, json_response({ error: 'session not found' }) unless session

  session[:turn_index] += 1
  if session[:turn_index] >= session[:order].length
    session[:turn_index] = 0
    session[:round] += 1
  end

  active = active_combatant(session)
  active_name = active[:name]

  conds = session[:conditions].fetch(active_name, [])
  conds.each { |cond| cond[:remaining_rounds] -= 1 }
  conds.reject! { |cond| cond[:remaining_rounds] <= 0 }

  json_response({
    id: session[:id],
    round: session[:round],
    turn_index: session[:turn_index],
    active: active,
    conditions: serialize_conditions(session)
  })
end
