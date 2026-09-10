# frozen_string_literal: true

# Route definitions for recurring downtime activities and allocations.

# --- Downtime activities ---

post '/v1/play/campaigns/:id/downtime/activities' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  validate_downtime_activity_body!(body)

  json_error(409, 'activity already exists') if Storage.downtime_activity_exists?(campaign_id, body['activity_id'])

  activity = Storage.create_downtime_activity(campaign_id, body['activity_id'], body['name'], body['cycles_required'])

  status 201
  JSON.dump(activity)
end

# --- Downtime allocations ---

post '/v1/play/campaigns/:id/characters/:character_id/downtime/allocations' do
  content_type :json
  campaign_id = params[:id]
  character_id = params[:character_id]
  validate_campaign_id!(campaign_id)

  username = require_player_actor!

  campaign = load_play_campaign!(campaign_id)
  json_error(403, 'forbidden') unless Storage.play_campaign_member_exists?(campaign_id, username)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, character_id)
  json_error(404, 'character not found') unless member

  json_error(403, 'forbidden') unless member[:owner] == username

  body = parse_json_body
  validate_downtime_allocation_body!(body)

  activity_id = body['activity_id']
  json_error(404, 'activity not found') unless Storage.downtime_activity_exists?(campaign_id, activity_id)

  json_error(409, 'allocation already exists') if Storage.downtime_allocation_exists?(campaign_id, character_id, activity_id)

  allocation = Storage.create_downtime_allocation(campaign_id, character_id, activity_id)

  status 201
  JSON.dump(allocation)
end

post '/v1/play/campaigns/:id/characters/:character_id/downtime/allocations/:activity_id/progress' do
  content_type :json
  campaign_id = params[:id]
  character_id = params[:character_id]
  activity_id = params[:activity_id]
  validate_campaign_id!(campaign_id)

  username = require_player_actor!

  campaign = load_play_campaign!(campaign_id)
  json_error(403, 'forbidden') unless Storage.play_campaign_member_exists?(campaign_id, username)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, character_id)
  json_error(404, 'character not found') unless member

  json_error(403, 'forbidden') unless member[:owner] == username

  json_error(404, 'activity not found') unless Storage.downtime_activity_exists?(campaign_id, activity_id)
  json_error(404, 'allocation not found') unless Storage.downtime_allocation_exists?(campaign_id, character_id, activity_id)

  allocation = Storage.progress_downtime_allocation(campaign_id, character_id, activity_id)
  json_error(404, 'allocation not found') unless allocation

  status 200
  JSON.dump(allocation)
end

get '/v1/play/campaigns/:id/characters/:character_id/downtime/allocations/:activity_id' do
  content_type :json
  campaign_id = params[:id]
  character_id = params[:character_id]
  activity_id = params[:activity_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  json_error(404, 'character not found') unless Storage.play_campaign_character_exists?(campaign_id, character_id)
  json_error(404, 'activity not found') unless Storage.downtime_activity_exists?(campaign_id, activity_id)

  allocation = Storage.load_downtime_allocation(campaign_id, character_id, activity_id)
  json_error(404, 'allocation not found') unless allocation

  JSON.dump(allocation)
end
