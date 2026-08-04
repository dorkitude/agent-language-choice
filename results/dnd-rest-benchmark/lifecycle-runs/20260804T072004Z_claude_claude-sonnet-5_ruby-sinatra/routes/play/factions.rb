# Campaign-scoped factions and bounded character reputation history for
# the /v1/play surface. The DM creates factions and records reputation
# changes; each change is clamped into [-100, 100] and appended to an
# immutable per-faction/character history.

def find_play_faction!(campaign_id, faction_id)
  faction = db.execute(
    'SELECT * FROM play_factions WHERE campaign_id = ? AND faction_id = ?',
    [campaign_id, faction_id]
  ).first
  halt 404, { error: 'faction not found' }.to_json unless faction
  faction
end

def next_play_faction_reputation_sequence(campaign_id, faction_id)
  db.execute(
    'SELECT COALESCE(MAX(sequence), 0) + 1 AS n FROM play_faction_reputation_history WHERE campaign_id = ? AND faction_id = ?',
    [campaign_id, faction_id]
  ).first['n']
end

def play_faction_reputation_entry(row)
  {
    faction_id: row['faction_id'],
    character_id: row['character_id'],
    reputation: row['reputation'],
    delta: row['delta'],
    reason: row['reason']
  }
end

post '/v1/play/campaigns/:id/factions' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  faction_id = body['faction_id']
  name = body['name']

  halt 400, { error: 'invalid faction_id' }.to_json unless faction_id.is_a?(String) && !faction_id.empty?
  halt 400, { error: 'invalid name' }.to_json unless name.is_a?(String) && !name.empty?

  existing = db.execute(
    'SELECT 1 FROM play_factions WHERE campaign_id = ? AND faction_id = ?',
    [campaign['id'], faction_id]
  ).first
  halt 409, { error: 'faction_id already exists' }.to_json if existing

  db.execute(
    'INSERT INTO play_factions (campaign_id, faction_id, name) VALUES (?, ?, ?)',
    [campaign['id'], faction_id, name]
  )

  status 201
  { faction_id: faction_id, name: name }.to_json
end

post '/v1/play/campaigns/:id/factions/:faction_id/reputation' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  faction = find_play_faction!(campaign['id'], params[:faction_id])

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  character_id = body['character_id']
  delta = body['delta']
  reason = body['reason']

  halt 400, { error: 'invalid character_id' }.to_json unless character_id.is_a?(String) && !character_id.empty?

  member = db.execute(
    'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
    [campaign['id'], character_id]
  ).first
  halt 400, { error: 'unknown character' }.to_json unless member

  halt 400, { error: 'invalid delta' }.to_json unless integerish(delta) && delta.to_i != 0 && delta.to_i.between?(-25, 25)
  delta = delta.to_i

  halt 400, { error: 'invalid reason' }.to_json unless reason.is_a?(String) && !reason.empty?

  current_row = db.execute(
    'SELECT reputation FROM play_faction_reputation WHERE campaign_id = ? AND faction_id = ? AND character_id = ?',
    [campaign['id'], faction['faction_id'], character_id]
  ).first
  current = current_row ? current_row['reputation'] : 0

  reputation = [[current + delta, -100].max, 100].min

  db.execute(
    'INSERT INTO play_faction_reputation (campaign_id, faction_id, character_id, reputation) VALUES (?, ?, ?, ?) ' \
    'ON CONFLICT (campaign_id, faction_id, character_id) DO UPDATE SET reputation = excluded.reputation',
    [campaign['id'], faction['faction_id'], character_id, reputation]
  )

  sequence = next_play_faction_reputation_sequence(campaign['id'], faction['faction_id'])
  db.execute(
    'INSERT INTO play_faction_reputation_history ' \
    '(campaign_id, faction_id, character_id, sequence, reputation, delta, reason) VALUES (?, ?, ?, ?, ?, ?, ?)',
    [campaign['id'], faction['faction_id'], character_id, sequence, reputation, delta, reason]
  )

  status 201
  { faction_id: faction['faction_id'], character_id: character_id, reputation: reputation, delta: delta, reason: reason }.to_json
end

get '/v1/play/campaigns/:id/factions/:faction_id/reputation' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  is_owner = require_play_participant!(campaign, user, 'not a campaign member')

  faction = find_play_faction!(campaign['id'], params[:faction_id])

  rows = db.execute(
    'SELECT * FROM play_faction_reputation_history WHERE campaign_id = ? AND faction_id = ? ORDER BY sequence ASC',
    [campaign['id'], faction['faction_id']]
  )

  unless is_owner
    own_member = db.execute(
      'SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
      [campaign['id'], user['username']]
    ).first
    own_character_id = own_member ? own_member['character_id'] : nil
    rows = rows.select { |row| row['character_id'] == own_character_id }
  end

  { faction_id: faction['faction_id'], entries: rows.map { |row| play_faction_reputation_entry(row) } }.to_json
end
