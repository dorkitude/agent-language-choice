# frozen_string_literal: true

# Route definitions for DM-managed campaign settlements.

# --- Create settlement ---
post '/v1/play/campaigns/:id/settlements' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  settlement_id = body['settlement_id']
  validate_settlement_id!(settlement_id)
  name, services, availability = validate_and_normalize_settlement_body!(body)

  json_error(409, 'settlement already exists') if Storage.settlement_exists?(campaign_id, settlement_id)

  Storage.create_settlement(campaign_id, settlement_id, name, services, availability)

  status 201
  JSON.dump(settlement_response(Storage.load_settlement(campaign_id, settlement_id)))
end

# --- Replace settlement ---
put '/v1/play/campaigns/:id/settlements/:settlement_id' do
  content_type :json
  campaign_id = params[:id]
  settlement_id = params[:settlement_id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  json_error(404, 'settlement not found') unless Storage.settlement_exists?(campaign_id, settlement_id)

  body = parse_json_body
  name, services, availability = validate_and_normalize_settlement_body!(body)

  Storage.update_settlement(campaign_id, settlement_id, name, services, availability)

  JSON.dump(settlement_response(Storage.load_settlement(campaign_id, settlement_id)))
end

# --- Discover settlement ---
post '/v1/play/campaigns/:id/settlements/:settlement_id/discover' do
  content_type :json
  campaign_id = params[:id]
  settlement_id = params[:settlement_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]
  json_error(403, 'forbidden') unless user[:role] == 'player'

  campaign = load_play_campaign!(campaign_id)
  json_error(403, 'forbidden') unless Storage.play_campaign_member_exists?(campaign_id, username)

  settlement = Storage.load_settlement(campaign_id, settlement_id)
  json_error(404, 'settlement not found') unless settlement

  member = Storage.load_play_campaign_member(campaign_id, username)
  character_id = member[:character_id]

  newly_discovered = Storage.discover_settlement(campaign_id, settlement_id, character_id)

  settlement = Storage.load_settlement(campaign_id, settlement_id)
  status newly_discovered ? 201 : 200
  JSON.dump(settlement_response(settlement, character_id))
end

# --- List settlements ---
get '/v1/play/campaigns/:id/settlements' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  settlements = Storage.load_settlements(campaign_id)
  is_dm = campaign[:owner] == username

  list = if is_dm
           settlements.map { |s| settlement_response(s) }
         else
           member = Storage.load_play_campaign_member(campaign_id, username)
           character_id = member ? member[:character_id] : nil
           discovered = settlements.select { |s| s[:discovered_by].include?(character_id) }
           discovered.map { |s| settlement_response(s, character_id) }
         end
  JSON.dump(settlements: list)
end
