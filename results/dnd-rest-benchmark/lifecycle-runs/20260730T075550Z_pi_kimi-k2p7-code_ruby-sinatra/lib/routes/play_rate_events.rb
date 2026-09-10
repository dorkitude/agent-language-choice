# frozen_string_literal: true

# Route definitions for campaign-scoped deterministic rate events.

# --- Create rate event ---

post '/v1/play/campaigns/:id/rate-events' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  body = parse_json_body
  validate_rate_event_body!(body)

  event_id = body['event_id']
  result = Storage.accept_rate_event(campaign_id, event_id, username)

  case result[:status]
  when :limit_exceeded
    Storage.record_rejected_rate_event(campaign_id, event_id, username)
    status 429
    return JSON.dump(limit: 2, remaining: 0)
  when :duplicate
    json_error(400, 'event already exists')
  end

  status 201
  JSON.dump(
    event_id: result[:event_id],
    actor: result[:actor],
    remaining: result[:remaining]
  )
end

# --- List rate events ---

get '/v1/play/campaigns/:id/rate-events' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  events = Storage.load_rate_events(campaign_id)
  remaining = Storage.remaining_rate_events(campaign_id, username)

  JSON.dump(
    events: events.map { |event| { event_id: event[:event_id], actor: event[:actor] } },
    remaining: remaining
  )
end
