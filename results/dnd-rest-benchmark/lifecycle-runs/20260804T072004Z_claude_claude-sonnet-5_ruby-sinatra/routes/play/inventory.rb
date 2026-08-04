# Per-character inventory item stacks for the /v1/play surface.

VALID_INVENTORY_ITEM_IDS = %w[healing-potion torch leather-armor ring-of-protection amulet-of-health].freeze

CONSUMABLE_ITEM_EFFECTS = {
  'healing-potion' => { type: 'healing', hp_restored: 5 }
}.freeze

post '/v1/play/campaigns/:id/characters/:char_id/inventory/items' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  member = find_play_member_by_character!(campaign['id'], params[:char_id])
  owner = play_character_owner(campaign['id'], params[:char_id], member)

  halt 403, { error: 'not the character owner' }.to_json unless owner == user['username']

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  item_id = body['item_id']
  quantity = body['quantity']

  halt 400, { error: 'invalid item_id' }.to_json unless VALID_INVENTORY_ITEM_IDS.include?(item_id)
  halt 400, { error: 'invalid quantity' }.to_json unless integerish(quantity) && quantity.to_i.positive?

  quantity = quantity.to_i

  existing = db.execute(
    'SELECT quantity FROM play_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
    [campaign['id'], params[:char_id], item_id]
  ).first

  total_quantity = (existing ? existing['quantity'] : 0) + quantity

  db.execute(
    'INSERT INTO play_character_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) ' \
    'ON CONFLICT (campaign_id, character_id, item_id) DO UPDATE SET quantity = excluded.quantity',
    [campaign['id'], params[:char_id], item_id, total_quantity]
  )

  status 201
  {
    character_id: params[:char_id],
    item_id: item_id,
    quantity: quantity,
    total_quantity: total_quantity
  }.to_json
end

post '/v1/play/campaigns/:id/characters/:char_id/inventory/items/:item_id/consume' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  member = find_play_member_by_character!(campaign['id'], params[:char_id])
  owner = play_character_owner(campaign['id'], params[:char_id], member)

  halt 403, { error: 'not the character owner' }.to_json unless owner == user['username']

  item_id = params[:item_id]
  halt 400, { error: 'invalid item_id' }.to_json unless VALID_INVENTORY_ITEM_IDS.include?(item_id)
  halt 400, { error: 'item is not consumable' }.to_json unless CONSUMABLE_ITEM_EFFECTS.key?(item_id)

  existing = db.execute(
    'SELECT quantity FROM play_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
    [campaign['id'], params[:char_id], item_id]
  ).first

  held = existing ? existing['quantity'] : 0
  halt 409, { error: 'no held quantity to consume' }.to_json if held.zero?

  total_quantity = held - 1

  if total_quantity.zero?
    db.execute(
      'DELETE FROM play_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
      [campaign['id'], params[:char_id], item_id]
    )
  else
    db.execute(
      'UPDATE play_character_inventory_items SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
      [total_quantity, campaign['id'], params[:char_id], item_id]
    )
  end

  {
    character_id: params[:char_id],
    item_id: item_id,
    quantity_consumed: 1,
    total_quantity: total_quantity,
    effect: CONSUMABLE_ITEM_EFFECTS[item_id]
  }.to_json
end

get '/v1/play/campaigns/:id/characters/:char_id/inventory/items' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  find_play_member_by_character!(campaign['id'], params[:char_id])

  items = db.execute(
    'SELECT item_id, quantity FROM play_character_inventory_items WHERE campaign_id = ? AND character_id = ? ORDER BY item_id ASC',
    [campaign['id'], params[:char_id]]
  ).map { |row| { item_id: row['item_id'], quantity: row['quantity'] } }

  { character_id: params[:char_id], items: items }.to_json
end

delete '/v1/play/campaigns/:id/characters/:char_id/inventory/items/:item_id' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  member = find_play_member_by_character!(campaign['id'], params[:char_id])
  owner = play_character_owner(campaign['id'], params[:char_id], member)

  halt 403, { error: 'not the character owner' }.to_json unless owner == user['username']

  item_id = params[:item_id]
  halt 400, { error: 'invalid item_id' }.to_json unless VALID_INVENTORY_ITEM_IDS.include?(item_id)

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  quantity = body['quantity']
  halt 400, { error: 'invalid quantity' }.to_json unless integerish(quantity) && quantity.to_i.positive?
  quantity = quantity.to_i

  existing = db.execute(
    'SELECT quantity FROM play_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
    [campaign['id'], params[:char_id], item_id]
  ).first

  held = existing ? existing['quantity'] : 0
  halt 409, { error: 'insufficient quantity' }.to_json if quantity > held

  total_quantity = held - quantity

  if total_quantity.zero?
    db.execute(
      'DELETE FROM play_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
      [campaign['id'], params[:char_id], item_id]
    )
  else
    db.execute(
      'UPDATE play_character_inventory_items SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
      [total_quantity, campaign['id'], params[:char_id], item_id]
    )
  end

  {
    character_id: params[:char_id],
    item_id: item_id,
    quantity: quantity,
    total_quantity: total_quantity
  }.to_json
end
