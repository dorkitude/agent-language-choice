# frozen_string_literal: true

# Route definitions for campaign-scoped projection events and deterministic projections.

# --- Append projection event ---

post '/v1/play/campaigns/:id/projection-events' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)

  json_error(403, 'forbidden') if campaign[:owner] == username
  json_error(403, 'forbidden') unless Storage.play_campaign_member_exists?(campaign_id, username)

  body = parse_json_body
  validate_projection_event_body!(body)

  event_id = body['event_id']
  kind = body['kind']
  value = kind == 'set-story' ? body['value'] : nil

  json_error(409, 'duplicate event_id') if Storage.projection_event_exists?(campaign_id, event_id)

  event = Storage.create_projection_event(campaign_id, event_id, kind, value)
  json_error(409, 'duplicate event_id') unless event

  status 201
  JSON.dump(event)
end

# --- Read projection ---

get '/v1/play/campaigns/:id/projection' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  projection = Storage.compute_projection(campaign_id)

  JSON.dump(projection)
end

# --- Rebuild projection ---

get '/v1/play/campaigns/:id/projection/rebuild' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  projection = Storage.compute_projection(campaign_id)

  JSON.dump(projection)
end
