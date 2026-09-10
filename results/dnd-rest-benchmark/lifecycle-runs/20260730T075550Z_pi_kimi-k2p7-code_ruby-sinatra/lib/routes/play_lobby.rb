# frozen_string_literal: true

# Route definitions for play lobby endpoints.

# --- Play campaigns ---

post '/v1/play/campaigns' do
  content_type :json
  body = parse_json_body

  owner = require_dm_actor!

  validate_play_campaign_body!(body)

  json_error(409, 'campaign already exists') if Storage.play_campaign_exists?(body['id'])

  Storage.create_play_campaign(body['id'], body['name'], owner, body['max_players'])

  status 201
  JSON.dump(
    id: body['id'],
    name: body['name'],
    owner: owner,
    status: 'lobby',
    max_players: body['max_players']
  )
end

# --- Party membership ---

post '/v1/play/campaigns/:id/members' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_player_actor!
  campaign = load_play_campaign!(campaign_id)

  body = parse_json_body
  validate_membership_body!(body)

  json_error(409, 'party is full') if Storage.play_campaign_member_count(campaign_id) >= campaign[:max_players]
  json_error(409, 'player already joined') if Storage.play_campaign_member_exists?(campaign_id, username)
  json_error(409, 'character already exists') if Storage.play_campaign_character_exists?(campaign_id, body['character_id'])

  Storage.create_play_campaign_member(campaign_id, username, body['character_id'], body['name'], body['class'])

  if spell_valid_for_class?(body['class'])
    slots = max_spell_slots(body['class'], 1)
    Storage.save_character_spell_slots(campaign_id, body['character_id'], slots)
  end

  status 201
  JSON.dump(
    username: username,
    character_id: body['character_id'],
    name: body['name'],
    class: body['class']
  )
end

# --- Session-zero settings ---

put '/v1/play/campaigns/:id/session-zero' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  validate_session_zero_body!(body)

  json_error(409, 'campaign already active') unless campaign[:status] == 'lobby'

  settings = {
    rules: body['rules'],
    tone: body['tone'],
    consent: body['consent']
  }
  Storage.save_session_zero(campaign_id, settings)

  JSON.dump(settings)
end

get '/v1/play/campaigns/:id/session-zero' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  settings = Storage.load_session_zero(campaign_id)
  json_error(404, 'session zero not found') unless settings

  JSON.dump(settings)
end

# --- Campaign start ---

post '/v1/play/campaigns/:id/start' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)

  require_play_campaign_owner!(campaign, username)

  json_error(409, 'campaign already active') unless campaign[:status] == 'lobby'

  members = Storage.play_campaign_members(campaign_id)
  json_error(409, 'insufficient party members') if members.length < 2

  queue = members.flat_map { |m| [m[:username], 'dm'] }
  Storage.start_play_campaign(campaign_id, queue, 1)
  current_actor = queue.first

  JSON.dump(
    id: campaign_id,
    status: 'active',
    current_actor: current_actor,
    turn_number: 1
  )
end

# --- Campaign onboarding ---

get '/v1/play/campaigns/:id/onboarding' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  if campaign[:owner] == username
    JSON.dump(
      role: 'dm',
      next_steps: %w[configure-safety invite-players start-campaign],
      can_mutate: true
    )
  else
    JSON.dump(
      role: 'player',
      next_steps: %w[review-party take-turn submit-action],
      can_mutate: true
    )
  end
end

