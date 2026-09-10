# frozen_string_literal: true

# Route definitions for campaign-scoped idempotent events.

# --- Create idempotent event ---

post '/v1/play/campaigns/:id/idempotent-events' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  idempotency_key = request.env['HTTP_IDEMPOTENCY_KEY'].to_s.strip
  json_error(400, 'invalid idempotency key') if idempotency_key == ''

  body = parse_json_body
  validate_idempotent_event_body!(body)

  result = Storage.create_idempotent_event(campaign_id, body['event_id'], body['value'], idempotency_key)

  case result[:status]
  when :event_id_conflict, :key_conflict
    json_error(409, 'idempotency conflict')
  when :existing
    status 200
  when :created
    status 201
  end

  JSON.dump(result[:event])
end

# --- Read idempotent events ---

get '/v1/play/campaigns/:id/idempotent-events' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  events = Storage.load_idempotent_events(campaign_id)

  JSON.dump(events: events)
end
