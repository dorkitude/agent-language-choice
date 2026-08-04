# Campaign inventory and per-character equipment assignment.

post '/v1/campaigns/:campaign_id/inventory' do
  halt 404, { error: 'unknown campaign' }.to_json unless campaign_exists?(params[:campaign_id])

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  item_slug = body['item_slug']
  quantity = body['quantity']
  owner = body['owner']

  halt 400, { error: 'invalid item_slug' }.to_json unless valid_slug?(item_slug)
  halt 400, { error: 'invalid quantity' }.to_json unless integerish(quantity) && quantity.to_i > 0
  halt 400, { error: 'invalid owner' }.to_json unless owner.is_a?(String) && !owner.empty?

  quantity = quantity.to_i

  db.execute(
    'INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES (?, ?, ?, ?)',
    [params[:campaign_id], item_slug, owner, quantity]
  )

  status 201
  { item_slug: item_slug, quantity: quantity, owner: owner }.to_json
end

post '/v1/campaigns/:campaign_id/characters/:character_id/equipment' do
  halt 404, { error: 'unknown campaign' }.to_json unless campaign_exists?(params[:campaign_id])

  character = db.execute(
    'SELECT 1 FROM campaign_characters WHERE campaign_id = ? AND id = ?',
    [params[:campaign_id], params[:character_id]]
  ).first
  halt 404, { error: 'unknown character' }.to_json unless character

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  item_slug = body['item_slug']
  quantity = body['quantity']

  halt 400, { error: 'invalid item_slug' }.to_json unless valid_slug?(item_slug)
  halt 400, { error: 'invalid quantity' }.to_json unless integerish(quantity) && quantity.to_i > 0

  quantity = quantity.to_i

  db.execute(
    'INSERT INTO campaign_equipment (campaign_id, character_id, item_slug, quantity) VALUES (?, ?, ?, ?)',
    [params[:campaign_id], params[:character_id], item_slug, quantity]
  )

  { character_id: params[:character_id], item_slug: item_slug, quantity: quantity }.to_json
end

get '/v1/campaigns/:campaign_id/inventory/summary' do
  halt 404, { error: 'unknown campaign' }.to_json unless campaign_exists?(params[:campaign_id])

  party_items = db.execute(
    "SELECT COUNT(*) AS cnt FROM campaign_inventory WHERE campaign_id = ? AND owner = 'party'",
    [params[:campaign_id]]
  ).first['cnt']

  assigned_items = db.execute(
    'SELECT COUNT(*) AS cnt FROM campaign_equipment WHERE campaign_id = ?',
    [params[:campaign_id]]
  ).first['cnt']

  party_potions = db.execute(
    "SELECT COALESCE(SUM(quantity), 0) AS total FROM campaign_inventory " \
    "WHERE campaign_id = ? AND owner = 'party' AND item_slug = 'healing-potion'",
    [params[:campaign_id]]
  ).first['total']

  assigned_potions = db.execute(
    "SELECT COALESCE(SUM(quantity), 0) AS total FROM campaign_equipment " \
    "WHERE campaign_id = ? AND item_slug = 'healing-potion'",
    [params[:campaign_id]]
  ).first['total']

  {
    campaign_id: params[:campaign_id],
    party_items: party_items,
    assigned_items: assigned_items,
    healing_potions_available: party_potions - assigned_potions
  }.to_json
end
