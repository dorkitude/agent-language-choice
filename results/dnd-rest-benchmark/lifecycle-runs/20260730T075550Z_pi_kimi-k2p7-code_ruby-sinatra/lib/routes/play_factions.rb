# frozen_string_literal: true

# Route definitions for play-campaign factions and character reputation.

# --- Faction creation ---

post '/v1/play/campaigns/:id/factions' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  validate_play_faction_body!(body)

  if Storage.play_campaign_faction_exists?(campaign_id, body['faction_id'])
    json_error(409, 'faction already exists')
  end

  Storage.create_play_campaign_faction(campaign_id, body['faction_id'], body['name'])

  status 201
  JSON.dump(
    faction_id: body['faction_id'],
    name: body['name']
  )
end

# --- Reputation change ---

post '/v1/play/campaigns/:id/factions/:faction_id/reputation' do
  content_type :json
  campaign_id = params[:id]
  faction_id = params[:faction_id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  faction = Storage.load_play_campaign_faction(campaign_id, faction_id)
  json_error(404, 'faction not found') unless faction

  body = parse_json_body
  validate_reputation_body!(body)

  character_id = body['character_id']
  unless Storage.play_campaign_character_exists?(campaign_id, character_id)
    json_error(400, 'invalid character_id')
  end

  delta = body['delta']
  current = Storage.current_reputation(campaign_id, faction_id, character_id)
  new_total = (current + delta).clamp(-100, 100)

  record = Storage.record_reputation_change(
    campaign_id,
    faction_id,
    character_id,
    delta,
    new_total,
    body['reason']
  )

  status 201
  JSON.dump(record)
end

# --- Reputation retrieval ---

get '/v1/play/campaigns/:id/factions/:faction_id/reputation' do
  content_type :json
  campaign_id = params[:id]
  faction_id = params[:faction_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  faction = Storage.load_play_campaign_faction(campaign_id, faction_id)
  json_error(404, 'faction not found') unless faction

  entries = if campaign[:owner] == username
              Storage.load_reputation_history(campaign_id, faction_id)
            else
              member = Storage.load_play_campaign_member(campaign_id, username)
              if member
                Storage.load_reputation_history_for_character(campaign_id, faction_id, member[:character_id])
              else
                []
              end
            end

  JSON.dump(
    faction_id: faction_id,
    entries: entries
  )
end
