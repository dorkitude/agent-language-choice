# frozen_string_literal: true

# Route definitions for DM-managed settlement shops.

# --- Create shop ---
post '/v1/play/campaigns/:id/settlements/:settlement_id/shops' do
  content_type :json
  campaign_id = params[:id]
  settlement_id = params[:settlement_id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  json_error(404, 'settlement not found') unless Storage.settlement_exists?(campaign_id, settlement_id)

  body = parse_json_body
  validate_shop_body!(body)

  json_error(409, 'shop already exists') if Storage.shop_exists?(campaign_id, settlement_id, body['shop_id'])

  Storage.create_shop(campaign_id, settlement_id, body['shop_id'], body['name'], body['stock'], body['buy_price'], body['sell_price'])

  status 201
  JSON.dump(shop_response(Storage.load_shop(campaign_id, settlement_id, body['shop_id'])))
end

# --- Get shop ---
get '/v1/play/campaigns/:id/settlements/:settlement_id/shops/:shop_id' do
  content_type :json
  campaign_id = params[:id]
  settlement_id = params[:settlement_id]
  shop_id = params[:shop_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  settlement = Storage.load_settlement(campaign_id, settlement_id)
  json_error(404, 'settlement not found') unless settlement

  unless campaign[:owner] == username
    member = Storage.load_play_campaign_member(campaign_id, username)
    character_id = member ? member[:character_id] : nil
    json_error(404, 'shop not found') unless settlement[:discovered_by].include?(character_id)
  end

  shop = Storage.load_shop(campaign_id, settlement_id, shop_id)
  json_error(404, 'shop not found') unless shop

  JSON.dump(shop_response(shop))
end

# --- Buy from shop ---
post '/v1/play/campaigns/:id/settlements/:settlement_id/shops/:shop_id/buy' do
  content_type :json
  campaign_id = params[:id]
  settlement_id = params[:settlement_id]
  shop_id = params[:shop_id]
  validate_campaign_id!(campaign_id)

  username = require_player_actor!

  campaign = load_play_campaign!(campaign_id)
  json_error(403, 'forbidden') unless Storage.play_campaign_member_exists?(campaign_id, username)

  settlement = Storage.load_settlement(campaign_id, settlement_id)
  json_error(404, 'settlement not found') unless settlement

  shop = Storage.load_shop(campaign_id, settlement_id, shop_id)
  json_error(404, 'shop not found') unless shop

  body = parse_json_body
  validate_shop_transaction_body!(body)

  character_id = body['character_id']
  character = Storage.load_play_campaign_member_by_character_id(campaign_id, character_id)
  json_error(404, 'character not found') unless character

  json_error(403, 'forbidden') unless character[:owner] == username

  result = Storage.shop_buy(campaign_id, settlement_id, shop_id, character_id, body['item_id'], body['quantity'])
  json_error(409, 'insufficient stock or funds') unless result

  status 200
  JSON.dump(
    character_id: character_id,
    item_id: body['item_id'],
    quantity: body['quantity'],
    gold: result[:gold],
    stock: result[:stock]
  )
end

# --- Sell to shop ---
post '/v1/play/campaigns/:id/settlements/:settlement_id/shops/:shop_id/sell' do
  content_type :json
  campaign_id = params[:id]
  settlement_id = params[:settlement_id]
  shop_id = params[:shop_id]
  validate_campaign_id!(campaign_id)

  username = require_player_actor!

  campaign = load_play_campaign!(campaign_id)
  json_error(403, 'forbidden') unless Storage.play_campaign_member_exists?(campaign_id, username)

  settlement = Storage.load_settlement(campaign_id, settlement_id)
  json_error(404, 'settlement not found') unless settlement

  shop = Storage.load_shop(campaign_id, settlement_id, shop_id)
  json_error(404, 'shop not found') unless shop

  body = parse_json_body
  validate_shop_transaction_body!(body)

  character_id = body['character_id']
  character = Storage.load_play_campaign_member_by_character_id(campaign_id, character_id)
  json_error(404, 'character not found') unless character

  json_error(403, 'forbidden') unless character[:owner] == username

  result = Storage.shop_sell(campaign_id, settlement_id, shop_id, character_id, body['item_id'], body['quantity'])
  json_error(409, 'insufficient inventory') unless result

  status 200
  JSON.dump(
    character_id: character_id,
    item_id: body['item_id'],
    quantity: body['quantity'],
    gold: result[:gold],
    stock: result[:stock]
  )
end
