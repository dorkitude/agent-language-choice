# Campaign lifecycle: creation, joining the party, and starting play.
#
# Shared campaign/membership lookups and event-log helpers live in
# lib/play_campaigns.rb — every route in routes/play/*.rb fetches its
# campaign via find_play_campaign! (404 if missing) before doing anything
# else. All routes here require a Bearer session-<username> token (see
# lib/play_auth.rb).

post '/v1/play/campaigns' do
  user = authenticate_play_request!
  halt 403, { error: 'forbidden' }.to_json unless user['role'] == 'dm'

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  id = body['id']
  name = body['name']
  max_players = body['max_players']

  halt 400, { error: 'invalid id' }.to_json unless id.is_a?(String) && !id.empty?
  halt 400, { error: 'invalid name' }.to_json unless name.is_a?(String) && !name.empty?
  halt 400, { error: 'invalid max_players' }.to_json unless integerish(max_players)
  halt 409, { error: 'id already exists' }.to_json if db.execute('SELECT 1 FROM play_campaigns WHERE id = ?', [id]).first

  max_players = max_players.to_i

  db.execute(
    'INSERT INTO play_campaigns (id, name, owner, status, max_players) VALUES (?, ?, ?, ?, ?)',
    [id, name, user['username'], 'lobby', max_players]
  )

  status 201
  { id: id, name: name, owner: user['username'], status: 'lobby', max_players: max_players }.to_json
end

post '/v1/play/campaigns/:id/members' do
  user = authenticate_play_request!
  halt 403, { error: 'forbidden' }.to_json unless user['role'] == 'player'

  campaign = find_play_campaign!(params[:id])

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  character_id = body['character_id']
  name = body['name']
  klass = body['class']

  halt 400, { error: 'invalid character_id' }.to_json unless character_id.is_a?(String) && !character_id.empty?
  halt 400, { error: 'invalid name' }.to_json unless name.is_a?(String) && !name.empty?
  halt 400, { error: 'invalid class' }.to_json unless klass.is_a?(String) && !klass.empty?

  halt 409, { error: 'already a member' }.to_json if play_campaign_member?(campaign, user['username'])

  duplicate_character = db.execute(
    'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
    [campaign['id'], character_id]
  ).first
  halt 409, { error: 'character id already in use' }.to_json if duplicate_character

  member_count = db.execute(
    'SELECT COUNT(*) AS n FROM play_campaign_members WHERE campaign_id = ?',
    [campaign['id']]
  ).first['n']
  halt 409, { error: 'party is full' }.to_json if member_count >= campaign['max_players']

  db.execute(
    'INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class) VALUES (?, ?, ?, ?, ?)',
    [campaign['id'], user['username'], character_id, name, klass]
  )
  db.execute(
    'INSERT INTO play_character_owners (campaign_id, character_id, owner) VALUES (?, ?, ?)',
    [campaign['id'], character_id, user['username']]
  )
  db.execute(
    'INSERT INTO play_character_gold (campaign_id, character_id, gold) VALUES (?, ?, ?)',
    [campaign['id'], character_id, 10]
  )

  status 201
  { username: user['username'], character_id: character_id, name: name, class: klass }.to_json
end

post '/v1/play/campaigns/:id/start' do
  user = authenticate_play_request!
  halt 403, { error: 'forbidden' }.to_json unless user['role'] == 'dm'

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  halt 409, { error: 'campaign not in lobby' }.to_json unless campaign['status'] == 'lobby'

  member_count = db.execute(
    'SELECT COUNT(*) AS n FROM play_campaign_members WHERE campaign_id = ?',
    [campaign['id']]
  ).first['n']
  halt 409, { error: 'party is under-populated' }.to_json if member_count < 2

  first_member = db.execute(
    'SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid ASC LIMIT 1',
    [campaign['id']]
  ).first

  db.execute(
    'UPDATE play_campaigns SET status = ?, current_actor = ?, turn_number = ?, turn_index = ? WHERE id = ?',
    ['active', first_member['username'], 1, 0, campaign['id']]
  )

  { id: campaign['id'], status: 'active', current_actor: first_member['username'], turn_number: 1 }.to_json
end
