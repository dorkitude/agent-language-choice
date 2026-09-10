# frozen_string_literal: true

# Route definitions for transactional currency transfers.

post '/v1/play/campaigns/:id/transactional-transfers' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  body = parse_json_body
  validate_transactional_transfer_body!(body)

  from_character_id = body['from_character_id']
  to_character_id = body['to_character_id']
  amount = body['amount']
  simulate_failure = body['simulate_failure']

  source = Storage.load_play_campaign_member_by_character_id(campaign_id, from_character_id)
  json_error(400, 'invalid from_character_id') unless source

  destination = Storage.load_play_campaign_member_by_character_id(campaign_id, to_character_id)
  json_error(400, 'invalid to_character_id') unless destination

  json_error(400, 'invalid transfer') if from_character_id == to_character_id

  json_error(403, 'forbidden') unless source[:owner] == username

  if simulate_failure
    source_gold = Storage.load_character_currency(campaign_id, from_character_id)
    json_error(409, 'insufficient gold') if source_gold < amount
    json_error(500, 'simulated failure')
  end

  result = Storage.transactional_transfer_gold(campaign_id, from_character_id, to_character_id, amount)
  json_error(409, 'insufficient gold') unless result

  status 201
  JSON.dump(result)
end

get '/v1/play/campaigns/:id/transactional-transfers' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  transfers = Storage.load_transactional_transfers(campaign_id)

  JSON.dump(transfers: transfers)
end
