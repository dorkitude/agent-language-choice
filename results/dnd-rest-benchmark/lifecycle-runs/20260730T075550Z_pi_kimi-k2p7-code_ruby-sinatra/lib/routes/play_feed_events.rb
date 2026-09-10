# frozen_string_literal: true

# Route definitions for campaign-scoped append-only feed events.

# --- Append feed event ---

post '/v1/play/campaigns/:id/feed-events' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  body = parse_json_body
  validate_feed_event_body!(body)

  result = Storage.create_feed_event(campaign_id, body['event_id'], body['text'])
  json_error(409, 'duplicate event_id') if result[:status] == :conflict

  status 201
  JSON.dump(result[:event])
end

# --- Read event feed ---

get '/v1/play/campaigns/:id/event-feed' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  cursor = validate_feed_cursor!(params['cursor'])
  limit = validate_feed_limit!(params['limit'])

  events = Storage.load_feed_events(campaign_id, cursor, limit)

  JSON.dump(
    events: events,
    next_cursor: cursor + events.length
  )
end
