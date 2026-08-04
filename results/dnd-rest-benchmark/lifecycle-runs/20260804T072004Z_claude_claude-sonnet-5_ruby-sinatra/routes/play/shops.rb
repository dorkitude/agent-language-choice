# DM-managed settlement shops with deterministic stock/prices, and player
# buy/sell operations backed by campaign inventory and currency.

def play_shop_payload(shop)
  {
    shop_id: shop['shop_id'],
    name: shop['name'],
    stock: JSON.parse(shop['stock_json']),
    buy_price: shop['buy_price'],
    sell_price: shop['sell_price']
  }
end

# Validates the create payload and returns the normalized
# [shop_id, name, stock, buy_price, sell_price] tuple.
def validate_shop_fields!(body)
  shop_id = body['shop_id']
  name = body['name']
  stock = body['stock']
  buy_price = body['buy_price']
  sell_price = body['sell_price']

  halt 400, { error: 'invalid shop_id' }.to_json unless shop_id.is_a?(String) && !shop_id.empty?
  halt 400, { error: 'invalid name' }.to_json unless name.is_a?(String) && !name.empty?
  halt 400, { error: 'invalid stock' }.to_json unless stock.is_a?(Hash) && !stock.empty?

  normalized_stock = {}
  stock.each do |item_id, quantity|
    halt 400, { error: 'invalid stock' }.to_json unless VALID_INVENTORY_ITEM_IDS.include?(item_id)
    halt 400, { error: 'invalid stock' }.to_json unless integerish(quantity) && quantity.to_i.positive?

    normalized_stock[item_id] = quantity.to_i
  end

  halt 400, { error: 'invalid buy_price' }.to_json unless integerish(buy_price) && buy_price.to_i.positive?
  halt 400, { error: 'invalid sell_price' }.to_json unless integerish(sell_price) && sell_price.to_i >= 0

  [shop_id, name, normalized_stock, buy_price.to_i, sell_price.to_i]
end

def find_play_shop!(campaign_id, settlement_id, shop_id)
  shop = db.execute(
    'SELECT * FROM play_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?',
    [campaign_id, settlement_id, shop_id]
  ).first
  halt 404, { error: 'shop not found' }.to_json unless shop
  shop
end

post '/v1/play/campaigns/:id/settlements/:settlement_id/shops' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  settlement = find_play_settlement!(campaign['id'], params[:settlement_id])

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  shop_id, name, stock, buy_price, sell_price = validate_shop_fields!(body)

  existing = db.execute(
    'SELECT 1 FROM play_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?',
    [campaign['id'], settlement['settlement_id'], shop_id]
  ).first
  halt 409, { error: 'shop already exists' }.to_json if existing

  db.execute(
    'INSERT INTO play_shops (campaign_id, settlement_id, shop_id, name, stock_json, buy_price, sell_price) VALUES (?, ?, ?, ?, ?, ?, ?)',
    [campaign['id'], settlement['settlement_id'], shop_id, name, stock.to_json, buy_price, sell_price]
  )

  status 201
  play_shop_payload(find_play_shop!(campaign['id'], settlement['settlement_id'], shop_id)).to_json
end

get '/v1/play/campaigns/:id/settlements/:settlement_id/shops/:shop_id' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  is_owner = require_play_participant!(campaign, user, 'not a campaign member')

  settlement = find_play_settlement!(campaign['id'], params[:settlement_id])
  shop = find_play_shop!(campaign['id'], settlement['settlement_id'], params[:shop_id])

  unless is_owner
    member = db.execute(
      'SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
      [campaign['id'], user['username']]
    ).first
    character_id = member && member['character_id']
    discovered_by = JSON.parse(settlement['discovered_by_json'])

    halt 404, { error: 'shop not found' }.to_json unless character_id && discovered_by.include?(character_id)
  end

  play_shop_payload(shop).to_json
end

post '/v1/play/campaigns/:id/settlements/:settlement_id/shops/:shop_id/buy' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  settlement = find_play_settlement!(campaign['id'], params[:settlement_id])
  shop = find_play_shop!(campaign['id'], settlement['settlement_id'], params[:shop_id])

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  character_id = body['character_id']
  item_id = body['item_id']
  quantity = body['quantity']

  halt 400, { error: 'invalid character_id' }.to_json unless character_id.is_a?(String) && !character_id.empty?

  member = find_play_member_by_character!(campaign['id'], character_id)
  owner = play_character_owner(campaign['id'], character_id, member)
  halt 403, { error: 'not the character owner' }.to_json unless owner == user['username']

  halt 400, { error: 'invalid item_id' }.to_json unless VALID_INVENTORY_ITEM_IDS.include?(item_id)
  halt 400, { error: 'invalid quantity' }.to_json unless integerish(quantity) && quantity.to_i.positive?
  quantity = quantity.to_i

  stock = JSON.parse(shop['stock_json'])
  available = stock[item_id] || 0
  halt 409, { error: 'insufficient stock' }.to_json if quantity > available

  cost = shop['buy_price'] * quantity

  gold_row = db.execute(
    'SELECT gold FROM play_character_gold WHERE campaign_id = ? AND character_id = ?',
    [campaign['id'], character_id]
  ).first
  gold = gold_row ? gold_row['gold'] : 0
  halt 409, { error: 'insufficient gold' }.to_json if cost > gold

  gold_after = gold - cost
  stock_after = available - quantity
  stock[item_id] = stock_after

  existing_item = db.execute(
    'SELECT quantity FROM play_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
    [campaign['id'], character_id, item_id]
  ).first
  item_total = (existing_item ? existing_item['quantity'] : 0) + quantity

  db.execute(
    'INSERT INTO play_character_gold (campaign_id, character_id, gold) VALUES (?, ?, ?) ' \
    'ON CONFLICT (campaign_id, character_id) DO UPDATE SET gold = excluded.gold',
    [campaign['id'], character_id, gold_after]
  )
  db.execute(
    'INSERT INTO play_character_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) ' \
    'ON CONFLICT (campaign_id, character_id, item_id) DO UPDATE SET quantity = excluded.quantity',
    [campaign['id'], character_id, item_id, item_total]
  )
  db.execute(
    'UPDATE play_shops SET stock_json = ? WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?',
    [stock.to_json, campaign['id'], settlement['settlement_id'], shop['shop_id']]
  )

  {
    character_id: character_id,
    item_id: item_id,
    quantity: quantity,
    gold: gold_after,
    stock: stock_after
  }.to_json
end

post '/v1/play/campaigns/:id/settlements/:settlement_id/shops/:shop_id/sell' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  settlement = find_play_settlement!(campaign['id'], params[:settlement_id])
  shop = find_play_shop!(campaign['id'], settlement['settlement_id'], params[:shop_id])

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  character_id = body['character_id']
  item_id = body['item_id']
  quantity = body['quantity']

  halt 400, { error: 'invalid character_id' }.to_json unless character_id.is_a?(String) && !character_id.empty?

  member = find_play_member_by_character!(campaign['id'], character_id)
  owner = play_character_owner(campaign['id'], character_id, member)
  halt 403, { error: 'not the character owner' }.to_json unless owner == user['username']

  halt 400, { error: 'invalid item_id' }.to_json unless VALID_INVENTORY_ITEM_IDS.include?(item_id)
  halt 400, { error: 'invalid quantity' }.to_json unless integerish(quantity) && quantity.to_i.positive?
  quantity = quantity.to_i

  existing_item = db.execute(
    'SELECT quantity FROM play_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
    [campaign['id'], character_id, item_id]
  ).first
  held = existing_item ? existing_item['quantity'] : 0
  halt 409, { error: 'insufficient inventory' }.to_json if quantity > held

  proceeds = shop['sell_price'] * quantity

  gold_row = db.execute(
    'SELECT gold FROM play_character_gold WHERE campaign_id = ? AND character_id = ?',
    [campaign['id'], character_id]
  ).first
  gold = gold_row ? gold_row['gold'] : 0
  gold_after = gold + proceeds

  held_after = held - quantity

  stock = JSON.parse(shop['stock_json'])
  stock_after = (stock[item_id] || 0) + quantity
  stock[item_id] = stock_after

  if held_after.zero?
    db.execute(
      'DELETE FROM play_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
      [campaign['id'], character_id, item_id]
    )
  else
    db.execute(
      'UPDATE play_character_inventory_items SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
      [held_after, campaign['id'], character_id, item_id]
    )
  end

  db.execute(
    'INSERT INTO play_character_gold (campaign_id, character_id, gold) VALUES (?, ?, ?) ' \
    'ON CONFLICT (campaign_id, character_id) DO UPDATE SET gold = excluded.gold',
    [campaign['id'], character_id, gold_after]
  )
  db.execute(
    'UPDATE play_shops SET stock_json = ? WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?',
    [stock.to_json, campaign['id'], settlement['settlement_id'], shop['shop_id']]
  )

  {
    character_id: character_id,
    item_id: item_id,
    quantity: quantity,
    gold: gold_after,
    stock: stock_after
  }.to_json
end
