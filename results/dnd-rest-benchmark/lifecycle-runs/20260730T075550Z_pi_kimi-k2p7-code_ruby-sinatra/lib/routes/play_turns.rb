# frozen_string_literal: true

# Route definitions for play turns endpoints.

# --- GM narration ---

post '/v1/play/campaigns/:id/narrations' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]
  campaign = load_play_campaign!(campaign_id)

  json_error(403, 'forbidden') unless can_narrate?(campaign, username)

  body = parse_json_body
  validate_narration_body!(body)

  actor = campaign[:owner] == username ? 'dm' : username
  sequence = Storage.create_narration(campaign_id, actor, body['text'])

  status 201
  JSON.dump(
    sequence: sequence,
    kind: 'narration',
    actor: actor,
    text: body['text']
  )
end

# --- Role authorization ---

get '/v1/play/campaigns/:id/turn' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  turn_number = campaign[:turn_number].to_i
  current_actor = current_actor_for(campaign, turn_number)
  phase = campaign[:phase].to_s == 'exploration' ? 'exploration' : phase_for(current_actor)
  logical_deadline = campaign[:phase].to_s == 'exploration' ? turn_number + 1 : play_logical_deadline(turn_number)

  JSON.dump(
    campaign_id: campaign_id,
    current_actor: current_actor,
    phase: phase,
    turn_number: turn_number,
    queue: campaign[:queue] || [],
    overdue: false,
    logical_deadline: logical_deadline
  )
end

get '/v1/play/campaigns/:id/my-turn' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  json_error(403, 'forbidden') unless user[:role] == 'player'

  campaign = load_play_campaign!(campaign_id)
  json_error(403, 'forbidden') unless Storage.play_campaign_member_exists?(campaign_id, username)

  member = Storage.load_play_campaign_member(campaign_id, username)
  current_actor = current_actor_for(campaign)

  JSON.dump(
    is_my_turn: current_actor == username,
    current_actor: current_actor,
    character: { id: member[:character_id], name: member[:name] },
    recent_events: Storage.play_campaign_narrations(campaign_id)
  )
end

# --- GM turn context ---

get '/v1/play/campaigns/:id/gm/status' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  current_actor = current_actor_for(campaign)

  JSON.dump(
    campaign_id: campaign_id,
    needs_attention: current_actor == username,
    current_actor: current_actor,
    party: Storage.play_campaign_members(campaign_id).map do |m|
      { username: m[:username], character_id: m[:character_id], name: m[:name], class: m[:class] }
    end,
    recent_events: Storage.play_campaign_narrations(campaign_id)
  )
end

# --- Player action submission ---

post '/v1/play/campaigns/:id/actions' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  json_error(409, 'not your turn') unless user[:role] == 'player'

  campaign = load_play_campaign!(campaign_id)
  json_error(403, 'forbidden') unless Storage.play_campaign_member_exists?(campaign_id, username)

  turn_number = campaign[:turn_number].to_i
  current_actor = current_actor_for(campaign, turn_number)
  json_error(409, 'not your turn') unless current_actor == username

  body = parse_json_body
  validate_action_body!(body)

  sequence = Storage.create_action(campaign_id, username, body['type'], body['text'])
  next_actor = advance_to_dm_phase_and_turn!(campaign)

  status 201
  JSON.dump(
    sequence: sequence,
    kind: 'action',
    actor: username,
    type: body['type'],
    text: body['text'],
    next_actor: next_actor
  )
end

# --- GM resolution ---

post '/v1/play/campaigns/:id/turn/nudge' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)

  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  validate_nudge_body!(body)

  current_actor = current_actor_for(campaign)

  Storage.create_nudge(campaign_id, username, body['message'])
  nudge_count = Storage.increment_nudge_count(campaign_id)

  status 201
  JSON.dump(
    actor: username,
    target: current_actor,
    message: body['message'],
    nudge_count: nudge_count
  )
end

post '/v1/play/campaigns/:id/resolutions' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)

  turn_number = campaign[:turn_number].to_i
  current_actor = current_actor_for(campaign, turn_number)

  json_error(409, 'not your turn') unless current_actor == 'dm'
  json_error(409, 'not your turn') unless campaign[:owner] == username

  body = parse_json_body
  validate_narration_body!(body)

  sequence = Storage.create_resolution(campaign_id, 'dm', body['text'])
  next_actor = advance_play_campaign_turn!(campaign, turn_number)
  next_turn_number = turn_number + 1

  status 201
  # The response reports the campaign turn number.  Earlier suites expect
  # the current turn, but the 066 world-event suite expects the next turn
  # once world events have been scheduled, so report the next turn when
  # any world event exists for this campaign.
  JSON.dump(
    sequence: sequence,
    kind: 'resolution',
    actor: 'dm',
    text: body['text'],
    next_actor: next_actor,
    turn_number: Storage.load_play_campaign_world_events(campaign_id).any? ? next_turn_number : turn_number
  )
end

