# frozen_string_literal: true

# Route definitions for play locations endpoints.

# --- Location graph ---

post '/v1/play/campaigns/:id/locations' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  validate_location_body!(body)

  json_error(409, 'location already exists') if Storage.location_exists?(campaign_id, body['id'])

  Storage.create_location(campaign_id, body['id'], body['name'])

  status 201
  JSON.dump(
    id: body['id'],
    name: body['name']
  )
end

post '/v1/play/campaigns/:id/locations/:from_id/connections' do
  content_type :json
  campaign_id = params[:id]
  from_id = params[:from_id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  validate_connection_body!(body)

  json_error(400, 'location not found') unless Storage.location_exists?(campaign_id, from_id)
  json_error(400, 'location not found') unless Storage.location_exists?(campaign_id, body['to_id'])
  json_error(400, 'connection already exists') if Storage.connection_exists?(campaign_id, from_id, body['to_id'])

  Storage.create_connection(campaign_id, from_id, body['to_id'], body['travel_turns'])

  status 201
  JSON.dump(
    from_id: from_id,
    to_id: body['to_id'],
    travel_turns: body['travel_turns']
  )
end

get '/v1/play/campaigns/:id/locations/:loc_id/travel' do
  content_type :json
  campaign_id = params[:id]
  loc_id = params[:loc_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  json_error(404, 'location not found') unless Storage.location_exists?(campaign_id, loc_id)

  destinations = Storage.load_connections(campaign_id, loc_id)

  JSON.dump(
    destinations: destinations
  )
end

