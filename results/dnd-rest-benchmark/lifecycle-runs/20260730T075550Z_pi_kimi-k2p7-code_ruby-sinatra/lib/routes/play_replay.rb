# frozen_string_literal: true

# Route definitions for campaign-scoped deterministic replay events.

# --- Append replay event ---

post '/v1/play/campaigns/:id/replay-events' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  body = parse_json_body
  validate_replay_event_body!(body)

  event_id = body['event_id']
  kind = body['kind']
  text = body['text']

  json_error(409, 'duplicate event_id') if Storage.play_campaign_replay_event_exists?(campaign_id, event_id)

  event = Storage.create_replay_event(campaign_id, event_id, kind, text)
  json_error(409, 'duplicate event_id') unless event

  status 201
  JSON.dump(event)
end

# --- Read replay ---

get '/v1/play/campaigns/:id/replay' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  JSON.dump(Storage.compute_replay(campaign_id))
end

# --- Check replay ---

get '/v1/play/campaigns/:id/replay/check' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  JSON.dump(Storage.compute_replay(campaign_id))
end
