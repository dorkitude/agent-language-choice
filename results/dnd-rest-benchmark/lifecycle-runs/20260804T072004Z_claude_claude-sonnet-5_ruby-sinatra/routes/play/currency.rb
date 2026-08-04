# Per-character gold balances and campaign-local transfers for the
# /v1/play surface.

get '/v1/play/campaigns/:id/characters/:char_id/currency' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  find_play_member_by_character!(campaign['id'], params[:char_id])

  gold = db.execute(
    'SELECT gold FROM play_character_gold WHERE campaign_id = ? AND character_id = ?',
    [campaign['id'], params[:char_id]]
  ).first

  { character_id: params[:char_id], gold: gold ? gold['gold'] : 0 }.to_json
end

post '/v1/play/campaigns/:id/characters/:char_id/currency/transfers' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  from_member = find_play_member_by_character!(campaign['id'], params[:char_id])
  owner = play_character_owner(campaign['id'], params[:char_id], from_member)

  halt 403, { error: 'not the character owner' }.to_json unless owner == user['username']

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  to_character_id = body['to_character_id']
  gold = body['gold']

  halt 400, { error: 'invalid to_character_id' }.to_json unless to_character_id.is_a?(String) && !to_character_id.empty?
  halt 400, { error: 'cannot transfer to self' }.to_json if to_character_id == params[:char_id]

  to_member = db.execute(
    'SELECT * FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
    [campaign['id'], to_character_id]
  ).first
  halt 400, { error: 'unknown destination character' }.to_json unless to_member

  halt 400, { error: 'invalid gold' }.to_json unless integerish(gold) && gold.to_i.positive?
  gold = gold.to_i

  from_gold_row = db.execute(
    'SELECT gold FROM play_character_gold WHERE campaign_id = ? AND character_id = ?',
    [campaign['id'], params[:char_id]]
  ).first
  from_gold = from_gold_row ? from_gold_row['gold'] : 0

  halt 409, { error: 'insufficient gold' }.to_json if gold > from_gold

  to_gold_row = db.execute(
    'SELECT gold FROM play_character_gold WHERE campaign_id = ? AND character_id = ?',
    [campaign['id'], to_character_id]
  ).first
  to_gold = to_gold_row ? to_gold_row['gold'] : 0

  from_gold_after = from_gold - gold
  to_gold_after = to_gold + gold

  db.execute(
    'INSERT INTO play_character_gold (campaign_id, character_id, gold) VALUES (?, ?, ?) ' \
    'ON CONFLICT (campaign_id, character_id) DO UPDATE SET gold = excluded.gold',
    [campaign['id'], params[:char_id], from_gold_after]
  )
  db.execute(
    'INSERT INTO play_character_gold (campaign_id, character_id, gold) VALUES (?, ?, ?) ' \
    'ON CONFLICT (campaign_id, character_id) DO UPDATE SET gold = excluded.gold',
    [campaign['id'], to_character_id, to_gold_after]
  )

  transfer_id = db.execute(
    'SELECT COALESCE(MAX(transfer_id), 0) + 1 AS n FROM play_gold_transfers WHERE campaign_id = ?',
    [campaign['id']]
  ).first['n']

  db.execute(
    'INSERT INTO play_gold_transfers (campaign_id, transfer_id, from_character_id, to_character_id, gold) VALUES (?, ?, ?, ?, ?)',
    [campaign['id'], transfer_id, params[:char_id], to_character_id, gold]
  )

  status 201
  {
    from_character_id: params[:char_id],
    to_character_id: to_character_id,
    gold: gold,
    from_gold: from_gold_after,
    to_gold: to_gold_after,
    transfer_id: transfer_id
  }.to_json
end
