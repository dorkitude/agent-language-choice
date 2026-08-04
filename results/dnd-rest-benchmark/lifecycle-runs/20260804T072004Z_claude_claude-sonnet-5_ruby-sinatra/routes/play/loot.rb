# Campaign-scoped loot records for the /v1/play surface: the DM opens loot,
# players vote on a recipient character, and the DM assigns it exactly once.

def find_play_loot!(campaign_id, loot_id)
  loot = db.execute(
    'SELECT * FROM play_loot WHERE campaign_id = ? AND loot_id = ?',
    [campaign_id, loot_id]
  ).first
  halt 404, { error: 'loot not found' }.to_json unless loot
  loot
end

def play_loot_vote_tallies(campaign_id, loot_id)
  db.execute(
    'SELECT recipient_character_id, COUNT(*) AS n FROM play_loot_votes WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id',
    [campaign_id, loot_id]
  ).each_with_object({}) { |row, acc| acc[row['recipient_character_id']] = row['n'] }
end

def play_loot_payload(loot)
  {
    loot_id: loot['loot_id'],
    item_id: loot['item_id'],
    quantity: loot['quantity'],
    status: loot['status'],
    recipient_character_id: loot['recipient_character_id'],
    votes: play_loot_vote_tallies(loot['campaign_id'], loot['loot_id'])
  }
end

post '/v1/play/campaigns/:id/loot' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  loot_id = body['loot_id']
  item_id = body['item_id']
  quantity = body['quantity']

  halt 400, { error: 'invalid loot_id' }.to_json unless valid_slug?(loot_id)
  halt 400, { error: 'invalid item_id' }.to_json unless VALID_INVENTORY_ITEM_IDS.include?(item_id)
  halt 400, { error: 'invalid quantity' }.to_json unless integerish(quantity) && quantity.to_i.positive?
  quantity = quantity.to_i

  existing = db.execute(
    'SELECT 1 FROM play_loot WHERE campaign_id = ? AND loot_id = ?',
    [campaign['id'], loot_id]
  ).first
  halt 409, { error: 'loot_id already exists' }.to_json if existing

  db.execute(
    'INSERT INTO play_loot (campaign_id, loot_id, item_id, quantity, status) VALUES (?, ?, ?, ?, ?)',
    [campaign['id'], loot_id, item_id, quantity, 'open']
  )

  status 201
  { loot_id: loot_id, item_id: item_id, quantity: quantity, status: 'open' }.to_json
end

post '/v1/play/campaigns/:id/loot/:loot_id/votes' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  is_owner = require_play_participant!(campaign, user, 'not a campaign member')
  halt 403, { error: 'forbidden' }.to_json if is_owner

  loot = find_play_loot!(campaign['id'], params[:loot_id])

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  recipient_character_id = body['recipient_character_id']
  halt 400, { error: 'invalid recipient_character_id' }.to_json unless recipient_character_id.is_a?(String) && !recipient_character_id.empty?

  recipient_member = db.execute(
    'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
    [campaign['id'], recipient_character_id]
  ).first
  halt 400, { error: 'invalid recipient_character_id' }.to_json unless recipient_member

  existing_vote = db.execute(
    'SELECT * FROM play_loot_votes WHERE campaign_id = ? AND loot_id = ? AND voter = ?',
    [campaign['id'], loot['loot_id'], user['username']]
  ).first
  halt 409, { error: 'already voted' }.to_json if existing_vote

  db.execute(
    'INSERT INTO play_loot_votes (campaign_id, loot_id, voter, recipient_character_id) VALUES (?, ?, ?, ?)',
    [campaign['id'], loot['loot_id'], user['username'], recipient_character_id]
  )

  votes_for_recipient = db.execute(
    'SELECT COUNT(*) AS n FROM play_loot_votes WHERE campaign_id = ? AND loot_id = ? AND recipient_character_id = ?',
    [campaign['id'], loot['loot_id'], recipient_character_id]
  ).first['n']

  status 201
  {
    loot_id: loot['loot_id'],
    voter: user['username'],
    recipient_character_id: recipient_character_id,
    votes_for_recipient: votes_for_recipient
  }.to_json
end

post '/v1/play/campaigns/:id/loot/:loot_id/assign' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  loot = find_play_loot!(campaign['id'], params[:loot_id])

  halt 409, { error: 'loot is not open' }.to_json unless loot['status'] == 'open'

  tallies = db.execute(
    'SELECT recipient_character_id, COUNT(*) AS n FROM play_loot_votes WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id',
    [campaign['id'], loot['loot_id']]
  )
  halt 409, { error: 'no votes cast' }.to_json if tallies.empty?

  max_votes = tallies.map { |row| row['n'] }.max
  top = tallies.select { |row| row['n'] == max_votes }
  halt 409, { error: 'tied vote, cannot assign' }.to_json if top.size > 1

  recipient_character_id = top.first['recipient_character_id']

  existing_qty = db.execute(
    'SELECT quantity FROM play_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
    [campaign['id'], recipient_character_id, loot['item_id']]
  ).first

  total_quantity = (existing_qty ? existing_qty['quantity'] : 0) + loot['quantity']

  db.execute(
    'INSERT INTO play_character_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) ' \
    'ON CONFLICT (campaign_id, character_id, item_id) DO UPDATE SET quantity = excluded.quantity',
    [campaign['id'], recipient_character_id, loot['item_id'], total_quantity]
  )

  db.execute(
    'UPDATE play_loot SET status = ?, recipient_character_id = ? WHERE campaign_id = ? AND loot_id = ?',
    ['assigned', recipient_character_id, campaign['id'], loot['loot_id']]
  )

  {
    loot_id: loot['loot_id'],
    recipient_character_id: recipient_character_id,
    item_id: loot['item_id'],
    quantity: loot['quantity'],
    votes: max_votes,
    status: 'assigned'
  }.to_json
end

get '/v1/play/campaigns/:id/loot/:loot_id' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  loot = find_play_loot!(campaign['id'], params[:loot_id])

  play_loot_payload(loot).to_json
end
