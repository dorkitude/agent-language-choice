# frozen_string_literal: true

# Route definitions for core endpoints.

# Public API schema (static, no auth, no state).
SCHEMA_RESPONSE = {
  version: '2026-07-29',
  endpoints: [
    { method: 'GET', path: '/v1/play/campaigns/{id}/rng-ledger', auth: 'member' },
    { method: 'GET', path: '/v1/schema', auth: 'public' },
    { method: 'POST', path: '/v1/play/campaigns', auth: 'dm' },
    { method: 'POST', path: '/v1/play/campaigns/{id}/fixture-seeds', auth: 'dm' },
    { method: 'POST', path: '/v1/play/campaigns/{id}/members', auth: 'member' },
    { method: 'POST', path: '/v1/play/campaigns/{id}/moderation/reports', auth: 'member' },
    { method: 'POST', path: '/v1/play/campaigns/{id}/rng-rolls', auth: 'member' },
    { method: 'PUT', path: '/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution', auth: 'dm' },
    { method: 'PUT', path: '/v1/play/campaigns/{id}/rng-seed', auth: 'dm' },
    { method: 'PUT', path: '/v1/play/campaigns/{id}/safety-boundaries', auth: 'dm' }
  ].sort_by { |e| [e[:method], e[:path]] }
}.freeze

# --- Health ---

get '/health' do
  content_type :json
  JSON.dump(ok: true)
end

get '/healthz' do
  content_type :json
  JSON.dump(status: 'ok')
end

get '/readyz' do
  content_type :json
  if Maintenance.enabled?
    halt 503, JSON.dump(status: 'maintenance', schema_version: 2)
  else
    JSON.dump(status: 'ready', schema_version: 2)
  end
end

# --- API schema ---

get '/v1/schema' do
  content_type :json
  JSON.dump(SCHEMA_RESPONSE)
end

# --- Core dice and checks ---

post '/v1/dice/stats' do
  content_type :json
  body = parse_json_body
  expression = body['expression'].to_s

  match = expression.match(/^(\d+)d(\d+)(?:([+-])(\d+))?$/)
  unless match && match[1].to_i.positive? && match[2].to_i.positive?
    halt 400, JSON.dump(error: 'invalid expression')
  end

  modifier = 0
  if match[3]
    modifier = match[4].to_i
    modifier = -modifier if match[3] == '-'
  end

  dice_count = match[1].to_i
  sides = match[2].to_i

  min = dice_count + modifier
  max = dice_count * sides + modifier
  average = (min + max).even? ? (min + max) / 2 : (min + max) / 2.0

  JSON.dump(
    dice_count: dice_count,
    sides: sides,
    modifier: modifier,
    min: min,
    max: max,
    average: average
  )
end

post '/v1/checks/ability' do
  content_type :json
  body = parse_json_body

  roll = body['roll'].to_i
  modifier = body['modifier'].to_i
  dc = body['dc'].to_i

  total = roll + modifier
  success = total >= dc
  margin = total - dc

  JSON.dump(total: total, success: success, margin: margin)
end

post '/v1/encounters/adjusted-xp' do
  content_type :json
  body = parse_json_body

  party = body['party'] || []
  monsters = body['monsters'] || []

  thresholds = encounter_thresholds(party)
  base_xp, monster_count = encounter_base_xp(monsters)
  multiplier = encounter_multiplier(monster_count)
  adjusted_xp = (base_xp * multiplier).to_i
  difficulty = encounter_difficulty(adjusted_xp, thresholds)

  JSON.dump(
    base_xp: base_xp,
    monster_count: monster_count,
    multiplier: multiplier,
    adjusted_xp: adjusted_xp,
    difficulty: difficulty,
    thresholds: thresholds
  )
end

post '/v1/initiative/order' do
  content_type :json
  body = parse_json_body

  combatants = body['combatants'] || []
  order = combat_order(combatants)

  JSON.dump(order: order)
end

