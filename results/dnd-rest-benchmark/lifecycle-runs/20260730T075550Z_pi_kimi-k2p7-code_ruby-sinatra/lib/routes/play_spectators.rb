# frozen_string_literal: true

# Route definitions for spectator access to play campaigns.

# --- Create spectator token ---

post '/v1/play/campaigns/:id/spectators' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  validate_spectator_body!(body)

  spectator_id = body['spectator_id']
  json_error(409, 'duplicate spectator_id') if Storage.spectator_exists?(spectator_id)

  Storage.create_spectator(campaign_id, spectator_id)

  status 201
  JSON.dump(
    spectator_id: spectator_id,
    token: "spectator-#{spectator_id}"
  )
end

# --- Spectator projection ---

get '/v1/play/campaigns/:id/spectator-view' do
  content_type :json
  campaign_id = params[:id]

  spectator_id = authenticate_spectator_view!
  validate_campaign_id!(campaign_id)

  campaign = load_play_campaign!(campaign_id)

  spectator = Storage.load_spectator(spectator_id)
  json_error(401, 'missing or invalid credentials') unless spectator
  json_error(403, 'forbidden') unless spectator[:campaign_id] == campaign_id

  JSON.dump(
    campaign_id: campaign_id,
    name: campaign[:name],
    status: campaign[:status],
    party_size: Storage.play_campaign_member_count(campaign_id),
    story: campaign[:story] || ''
  )
end
