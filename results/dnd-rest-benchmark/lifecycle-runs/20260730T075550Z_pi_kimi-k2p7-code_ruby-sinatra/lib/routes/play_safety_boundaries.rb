# frozen_string_literal: true

# Route definitions for campaign-scoped safety boundaries and accepted safety
# events.

helpers do
  # Returns the public safety-event shape, preserving submitted tag order.
  def safety_event_response(event)
    {
      event_id: event[:event_id],
      kind: event[:kind],
      text: event[:text],
      tags: event[:tags],
      sequence: event[:sequence]
    }
  end
end

# --- Replace safety boundaries ---

put '/v1/play/campaigns/:id/safety-boundaries' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  validate_safety_boundary_body!(body)

  result = Storage.save_safety_boundaries(campaign_id, body['blocked_tags'])
  JSON.dump(result)
end

# --- Read safety boundaries ---

get '/v1/play/campaigns/:id/safety-boundaries' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  JSON.dump(Storage.load_safety_boundaries(campaign_id))
end

# --- Submit safety check ---

post '/v1/play/campaigns/:id/safety-checks' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  body = parse_json_body
  validate_safety_check_body!(body)

  result = Storage.submit_safety_event(
    campaign_id,
    body['event_id'],
    body['kind'],
    body['text'],
    body['tags']
  )

  case result[:status]
  when :duplicate
    json_error(409, 'duplicate event_id')
  when :blocked
    json_error(409, 'blocked tag')
  when :accepted
    status 201
    JSON.dump(safety_event_response(result))
  else
    json_error(500, 'unexpected error')
  end
end

# --- Read safety events ---

get '/v1/play/campaigns/:id/safety-events' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  events = Storage.load_safety_events(campaign_id)
  JSON.dump(events: events.map { |event| safety_event_response(event) })
end
