# frozen_string_literal: true

# Route definitions for deterministic campaign-level world events.

# --- Schedule world event ---
post '/v1/play/campaigns/:id/world-events' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  validate_world_event_body!(body)

  event_id = body['event_id']
  turn_number = body['turn_number']
  title = body['title']
  text = body['text']

  current_turn = campaign[:turn_number].to_i
  unless turn_number >= current_turn
    json_error(400, 'invalid turn_number')
  end

  if Storage.play_campaign_world_event_exists?(campaign_id, event_id)
    json_error(409, 'event already exists')
  end

  Storage.create_play_campaign_world_event(campaign_id, event_id, turn_number, title, text)

  status 201
  JSON.dump(
    event_id: event_id,
    turn_number: turn_number,
    title: title,
    text: text,
    status: 'scheduled'
  )
end

# --- Resolve world event ---
post '/v1/play/campaigns/:id/world-events/:event_id/resolve' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  event = Storage.load_play_campaign_world_event(campaign_id, params[:event_id])
  json_error(404, 'event not found') unless event

  body = parse_json_body
  validate_world_event_resolution_body!(body)

  current_turn = campaign[:turn_number].to_i
  unless current_turn == event[:turn_number]
    json_error(409, 'turn number mismatch')
  end

  if event[:status] == 'resolved'
    json_error(409, 'event already resolved')
  end

  Storage.resolve_play_campaign_world_event(campaign_id, event[:event_id], current_turn, body['text'])

  status 201
  JSON.dump(
    event_id: event[:event_id],
    turn_number: event[:turn_number],
    title: event[:title],
    text: event[:text],
    status: 'resolved',
    resolution: {
      turn_number: current_turn,
      text: body['text']
    }
  )
end

# --- List world events ---
get '/v1/play/campaigns/:id/world-events' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  events = Storage.load_play_campaign_world_events(campaign_id)

  JSON.dump(events: events)
end
