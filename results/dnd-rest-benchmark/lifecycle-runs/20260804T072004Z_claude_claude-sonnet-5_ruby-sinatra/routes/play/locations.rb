# The location graph: DM-defined places and one-directional travel
# connections between them, plus the player-facing travel action.
#
# A campaign's current_location_id is set implicitly to the first location
# the DM creates (there is no separate "set current location" route) so
# travel always has a deterministic place to start from.

post '/v1/play/campaigns/:id/locations' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  id = body['id']
  name = body['name']
  halt 400, { error: 'invalid id' }.to_json unless id.is_a?(String) && !id.empty?
  halt 400, { error: 'invalid name' }.to_json unless name.is_a?(String) && !name.empty?

  existing = db.execute(
    'SELECT 1 FROM play_locations WHERE campaign_id = ? AND id = ?',
    [campaign['id'], id]
  ).first
  halt 409, { error: 'location id already exists' }.to_json if existing

  db.execute(
    'INSERT INTO play_locations (campaign_id, id, name) VALUES (?, ?, ?)',
    [campaign['id'], id, name]
  )

  if campaign['current_location_id'].nil?
    db.execute('UPDATE play_campaigns SET current_location_id = ? WHERE id = ?', [id, campaign['id']])
  end

  status 201
  { id: id, name: name }.to_json
end

post '/v1/play/campaigns/:id/locations/:from_id/connections' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  from_id = params[:from_id]
  from_location = db.execute(
    'SELECT 1 FROM play_locations WHERE campaign_id = ? AND id = ?',
    [campaign['id'], from_id]
  ).first
  halt 400, { error: 'unknown from location' }.to_json unless from_location

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  to_id = body['to_id']
  travel_turns = body['travel_turns']
  halt 400, { error: 'invalid to_id' }.to_json unless to_id.is_a?(String) && !to_id.empty?
  halt 400, { error: 'invalid travel_turns' }.to_json unless integerish(travel_turns)

  to_location = db.execute(
    'SELECT 1 FROM play_locations WHERE campaign_id = ? AND id = ?',
    [campaign['id'], to_id]
  ).first
  halt 400, { error: 'unknown to location' }.to_json unless to_location

  existing = db.execute(
    'SELECT 1 FROM play_location_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?',
    [campaign['id'], from_id, to_id]
  ).first
  halt 400, { error: 'connection already exists' }.to_json if existing

  db.execute(
    'INSERT INTO play_location_connections (campaign_id, from_id, to_id, travel_turns) VALUES (?, ?, ?, ?)',
    [campaign['id'], from_id, to_id, travel_turns.to_i]
  )

  status 201
  { from_id: from_id, to_id: to_id, travel_turns: travel_turns.to_i }.to_json
end

get '/v1/play/campaigns/:id/locations/:loc_id/travel' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  destinations = db.execute(
    <<~SQL, [campaign['id'], params[:loc_id]]
      SELECT loc.id AS id, loc.name AS name, conn.travel_turns AS travel_turns
      FROM play_location_connections conn
      JOIN play_locations loc ON loc.campaign_id = conn.campaign_id AND loc.id = conn.to_id
      WHERE conn.campaign_id = ? AND conn.from_id = ?
      ORDER BY conn.to_id ASC
    SQL
  ).map { |row| { id: row['id'], name: row['name'], travel_turns: row['travel_turns'] } }

  { destinations: destinations }.to_json
end

post '/v1/play/campaigns/:id/turn/travel' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  is_active_player = user['role'] == 'player' && campaign['current_actor'] == user['username']
  halt 409, { error: 'not your turn' }.to_json unless is_active_player

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  destination_id = body['destination_id']
  halt 400, { error: 'invalid destination_id' }.to_json unless destination_id.is_a?(String) && !destination_id.empty?

  connection = db.execute(
    'SELECT travel_turns FROM play_location_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?',
    [campaign['id'], campaign['current_location_id'], destination_id]
  ).first
  halt 409, { error: 'invalid destination' }.to_json unless connection

  sequence = insert_play_event(campaign['id'], kind: 'travel', actor: user['username'], text: destination_id)

  db.execute(
    'UPDATE play_campaigns SET current_actor = ?, current_location_id = ? WHERE id = ?',
    [campaign['owner'], destination_id, campaign['id']]
  )

  status 201
  {
    sequence: sequence,
    kind: 'travel',
    actor: user['username'],
    destination_id: destination_id,
    travel_turns: connection['travel_turns'],
    next_actor: 'dm'
  }.to_json
end
