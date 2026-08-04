# DM-managed campaign settlements: validated services and availability,
# discovered per player character.

VALID_SETTLEMENT_AVAILABILITY = %w[open limited closed].freeze

def play_settlement_payload(settlement, viewer_character_id: nil)
  discovered_by = JSON.parse(settlement['discovered_by_json'])
  discovered_by = discovered_by.include?(viewer_character_id) ? [viewer_character_id] : [] if viewer_character_id

  {
    settlement_id: settlement['settlement_id'],
    name: settlement['name'],
    services: JSON.parse(settlement['services_json']),
    availability: settlement['availability'],
    discovered_by: discovered_by
  }
end

# Validates name/services/availability shared by create and replace, and
# returns the normalized [name, services, availability] tuple.
def validate_settlement_fields!(body)
  name = body['name']
  services = body['services']
  availability = body['availability']

  halt 400, { error: 'invalid name' }.to_json unless name.is_a?(String) && !name.empty?
  halt 400, { error: 'invalid services' }.to_json unless services.is_a?(Array) && !services.empty?

  normalized = services.map { |s| s.is_a?(String) ? s.strip : nil }
  halt 400, { error: 'invalid services' }.to_json unless normalized.all? { |s| s && !s.empty? }
  halt 400, { error: 'invalid services' }.to_json unless normalized.uniq.length == normalized.length

  halt 400, { error: 'invalid availability' }.to_json unless VALID_SETTLEMENT_AVAILABILITY.include?(availability)

  [name, normalized, availability]
end

def find_play_settlement!(campaign_id, settlement_id)
  settlement = db.execute(
    'SELECT * FROM play_settlements WHERE campaign_id = ? AND settlement_id = ?',
    [campaign_id, settlement_id]
  ).first
  halt 404, { error: 'settlement not found' }.to_json unless settlement
  settlement
end

post '/v1/play/campaigns/:id/settlements' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  settlement_id = body['settlement_id']
  halt 400, { error: 'invalid settlement_id' }.to_json unless settlement_id.is_a?(String) && !settlement_id.empty?

  name, services, availability = validate_settlement_fields!(body)

  existing = db.execute(
    'SELECT 1 FROM play_settlements WHERE campaign_id = ? AND settlement_id = ?',
    [campaign['id'], settlement_id]
  ).first
  halt 409, { error: 'settlement already exists' }.to_json if existing

  sequence = db.execute(
    'SELECT COALESCE(MAX(sequence), -1) + 1 AS seq FROM play_settlements WHERE campaign_id = ?',
    [campaign['id']]
  ).first['seq']

  db.execute(
    'INSERT INTO play_settlements (campaign_id, sequence, settlement_id, name, services_json, availability, discovered_by_json) VALUES (?, ?, ?, ?, ?, ?, ?)',
    [campaign['id'], sequence, settlement_id, name, services.to_json, availability, '[]']
  )

  status 201
  play_settlement_payload(find_play_settlement!(campaign['id'], settlement_id)).to_json
end

put '/v1/play/campaigns/:id/settlements/:settlement_id' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  settlement = find_play_settlement!(campaign['id'], params[:settlement_id])

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  name, services, availability = validate_settlement_fields!(body)

  db.execute(
    'UPDATE play_settlements SET name = ?, services_json = ?, availability = ? WHERE campaign_id = ? AND settlement_id = ?',
    [name, services.to_json, availability, campaign['id'], settlement['settlement_id']]
  )

  play_settlement_payload(find_play_settlement!(campaign['id'], settlement['settlement_id'])).to_json
end

post '/v1/play/campaigns/:id/settlements/:settlement_id/discover' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  is_owner = require_play_participant!(campaign, user, 'not a campaign member')
  halt 403, { error: 'forbidden' }.to_json if is_owner

  settlement = find_play_settlement!(campaign['id'], params[:settlement_id])

  member = db.execute(
    'SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
    [campaign['id'], user['username']]
  ).first
  character_id = member['character_id']

  discovered_by = JSON.parse(settlement['discovered_by_json'])

  if discovered_by.include?(character_id)
    status 200
  else
    discovered_by << character_id
    db.execute(
      'UPDATE play_settlements SET discovered_by_json = ? WHERE campaign_id = ? AND settlement_id = ?',
      [discovered_by.to_json, campaign['id'], settlement['settlement_id']]
    )
    status 201
  end

  settlement = find_play_settlement!(campaign['id'], settlement['settlement_id'])
  play_settlement_payload(settlement, viewer_character_id: character_id).to_json
end

get '/v1/play/campaigns/:id/settlements' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  is_owner = require_play_participant!(campaign, user, 'not a campaign member')

  settlements = db.execute(
    'SELECT * FROM play_settlements WHERE campaign_id = ? ORDER BY sequence ASC',
    [campaign['id']]
  )

  if is_owner
    { settlements: settlements.map { |s| play_settlement_payload(s) } }.to_json
  else
    member = db.execute(
      'SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
      [campaign['id'], user['username']]
    ).first
    own_character_id = member && member['character_id']

    visible = settlements.select { |s| JSON.parse(s['discovered_by_json']).include?(own_character_id) }
    { settlements: visible.map { |s| play_settlement_payload(s, viewer_character_id: own_character_id) } }.to_json
  end
end
