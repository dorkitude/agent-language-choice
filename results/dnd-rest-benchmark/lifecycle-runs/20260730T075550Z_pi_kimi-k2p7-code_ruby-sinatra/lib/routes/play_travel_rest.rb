# frozen_string_literal: true

# Route definitions for play travel rest endpoints.

# --- Travel turns ---

post '/v1/play/campaigns/:id/turn/travel' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_player_actor!

  campaign = load_play_campaign!(campaign_id)
  json_error(403, 'forbidden') unless Storage.play_campaign_member_exists?(campaign_id, username)

  turn_number = campaign[:turn_number].to_i
  current_actor = current_actor_for(campaign, turn_number)
  json_error(409, 'not your turn') unless current_actor == username

  body = parse_json_body
  validate_travel_body!(body)
  destination_id = body['destination_id']

  current_location_id = Storage.load_current_location(campaign_id)
  json_error(409, 'invalid destination') if current_location_id.nil? || current_location_id.to_s.empty?

  connection = Storage.load_connection(campaign_id, current_location_id, destination_id)
  json_error(409, 'invalid destination') unless connection

  sequence = Storage.create_travel(campaign_id, username, destination_id)
  next_actor = advance_to_dm_phase!(campaign)
  Storage.set_current_location(campaign_id, destination_id)

  status 201
  JSON.dump(
    sequence: sequence,
    kind: 'travel',
    actor: username,
    destination_id: destination_id,
    travel_turns: connection[:travel_turns],
    next_actor: next_actor
  )
end

# --- Rest turns ---

post '/v1/play/campaigns/:id/turn/rest' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_player_actor!

  campaign = load_play_campaign!(campaign_id)
  json_error(403, 'forbidden') unless Storage.play_campaign_member_exists?(campaign_id, username)

  turn_number = campaign[:turn_number].to_i
  current_actor = current_actor_for(campaign, turn_number)
  json_error(409, 'not your turn') unless current_actor == username

  body = parse_json_body
  validate_rest_body!(body)

  member = Storage.load_play_campaign_member(campaign_id, username)
  hp_current = member[:hp_current]
  hp_max = member[:hp_max]

  if body['type'] == 'long'
    hp_current = hp_max
    Storage.update_play_campaign_member_hp(campaign_id, username, hp_current)

    if spell_valid_for_class?(member[:class])
      slots = max_spell_slots(member[:class], member[:level])
      Storage.save_character_spell_slots(campaign_id, member[:character_id], slots)
    end
  end

  sequence = Storage.create_rest(campaign_id, username, body['type'])
  next_actor = advance_to_dm_phase_and_turn!(campaign)

  status 201
  JSON.dump(
    sequence: sequence,
    kind: 'rest',
    actor: username,
    type: body['type'],
    hp_current: hp_current,
    hp_max: hp_max,
    next_actor: next_actor
  )
end

