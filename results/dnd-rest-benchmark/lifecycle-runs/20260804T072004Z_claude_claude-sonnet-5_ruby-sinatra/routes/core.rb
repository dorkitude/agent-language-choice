# Health check plus stateless dice/probability/encounter-math tools that
# don't belong to a specific domain (auth, compendium, campaigns, ...).

get '/health' do
  { ok: true }.to_json
end

post '/v1/dice/stats' do
  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  expression = body['expression']
  halt 400, { error: 'missing expression' }.to_json unless expression.is_a?(String)

  match = /\A(\d+)d(\d+)([+-]\d+)?\z/.match(expression)
  halt 400, { error: 'invalid expression' }.to_json unless match

  count = match[1].to_i
  sides = match[2].to_i
  modifier = match[3] ? match[3].to_i : 0

  halt 400, { error: 'count and sides must be positive' }.to_json if count <= 0 || sides <= 0

  min = count * 1 + modifier
  max = count * sides + modifier
  average = (count * (sides + 1) / 2.0) + modifier
  average = average.to_i if average == average.to_i

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
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  roll = body['roll']
  modifier = body['modifier']
  dc = body['dc']

  halt 400, { error: 'missing fields' }.to_json unless numericish(roll) && numericish(modifier) && numericish(dc)

  total = roll + modifier
  success = total >= dc
  margin = total - dc

  { total: total, success: success, margin: margin }.to_json
end

post '/v1/encounters/adjusted-xp' do
  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  party = body['party']
  monsters = body['monsters']

  halt 400, { error: 'missing party or monsters' }.to_json unless party.is_a?(Array) && monsters.is_a?(Array)

  base_xp = 0
  monster_count = 0

  monsters.each do |m|
    cr = m['cr'].to_s
    count = m['count']
    halt 400, { error: 'invalid monster count' }.to_json unless numericish(count)
    xp = CR_XP[cr]
    halt 400, { error: "unsupported cr #{cr}" }.to_json unless xp

    base_xp += xp * count
    monster_count += count
  end

  multiplier = count_multiplier(monster_count)
  adjusted_xp = base_xp * multiplier

  thresholds = party_xp_thresholds(party)
  difficulty = difficulty_for_xp(adjusted_xp, thresholds)

  {
    base_xp: base_xp,
    monster_count: monster_count,
    multiplier: multiplier,
    adjusted_xp: adjusted_xp,
    difficulty: difficulty,
    thresholds: thresholds
  }.to_json
end

post '/v1/initiative/order' do
  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  combatants = body['combatants']
  halt 400, { error: 'missing combatants' }.to_json unless combatants.is_a?(Array)

  ordered = order_combatants(combatants)

  { order: ordered.map { |c| { name: c[:name], score: c[:score] } } }.to_json
end
