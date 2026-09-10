# frozen_string_literal: true

# Route definitions for play-campaign NPC agendas.

# --- NPC creation ---

post '/v1/play/campaigns/:id/npcs' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  validate_play_npc_body!(body)

  if Storage.play_campaign_npc_exists?(campaign_id, body['npc_id'])
    json_error(409, 'npc already exists')
  end

  Storage.create_play_campaign_npc(
    campaign_id,
    body['npc_id'],
    body['name'],
    body['agenda'],
    body['public_status']
  )

  status 201
  JSON.dump(
    npc_id: body['npc_id'],
    name: body['name'],
    agenda: body['agenda'],
    public_status: body['public_status']
  )
end

# --- NPC agenda update ---

put '/v1/play/campaigns/:id/npcs/:npc_id/agenda' do
  content_type :json
  campaign_id = params[:id]
  npc_id = params[:npc_id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  npc = Storage.load_play_campaign_npc(campaign_id, npc_id)
  json_error(404, 'npc not found') unless npc

  body = parse_json_body
  validate_play_npc_agenda_body!(body)

  Storage.update_play_campaign_npc(campaign_id, npc_id, body['agenda'], body['public_status'])

  JSON.dump(
    npc_id: npc[:npc_id],
    name: npc[:name],
    agenda: body['agenda'],
    public_status: body['public_status']
  )
end

# --- NPC retrieval ---

get '/v1/play/campaigns/:id/npcs/:npc_id' do
  content_type :json
  campaign_id = params[:id]
  npc_id = params[:npc_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  npc = Storage.load_play_campaign_npc(campaign_id, npc_id)
  json_error(404, 'npc not found') unless npc

  if campaign[:owner] == username
    JSON.dump(
      npc_id: npc[:npc_id],
      name: npc[:name],
      agenda: npc[:agenda],
      public_status: npc[:public_status]
    )
  else
    JSON.dump(
      npc_id: npc[:npc_id],
      name: npc[:name],
      public_status: npc[:public_status]
    )
  end
end

# --- NPC dialogue append ---

post '/v1/play/campaigns/:id/npcs/:npc_id/dialogue' do
  content_type :json
  campaign_id = params[:id]
  npc_id = params[:npc_id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  npc = Storage.load_play_campaign_npc(campaign_id, npc_id)
  json_error(404, 'npc not found') unless npc

  body = parse_json_body
  validate_play_npc_dialogue_body!(body)

  dialogue_id = body['dialogue_id']
  if Storage.play_campaign_npc_dialogue_exists?(campaign_id, npc_id, dialogue_id)
    json_error(409, 'dialogue already exists')
  end

  Storage.create_play_campaign_npc_dialogue(
    campaign_id,
    npc_id,
    dialogue_id,
    body['speaker'],
    body['text'],
    body['visibility']
  )

  status 201
  JSON.dump(
    dialogue_id: dialogue_id,
    speaker: body['speaker'],
    text: body['text'],
    visibility: body['visibility']
  )
end

# --- NPC dialogue retrieval ---

get '/v1/play/campaigns/:id/npcs/:npc_id/dialogue' do
  content_type :json
  campaign_id = params[:id]
  npc_id = params[:npc_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  npc = Storage.load_play_campaign_npc(campaign_id, npc_id)
  json_error(404, 'npc not found') unless npc

  entries = Storage.load_play_campaign_npc_dialogue(campaign_id, npc_id)
  unless campaign[:owner] == username
    entries = entries.select { |e| e[:visibility] == 'public' }
  end

  JSON.dump(
    npc_id: npc_id,
    entries: entries
  )
end
