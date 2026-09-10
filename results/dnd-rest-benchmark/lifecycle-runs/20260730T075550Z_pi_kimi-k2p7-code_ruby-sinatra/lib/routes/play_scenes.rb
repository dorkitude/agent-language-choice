# frozen_string_literal: true

# Route definitions for play scenes endpoints.

# --- Scene state ---

post '/v1/play/campaigns/:id/scenes' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  validate_scene_body!(body)

  json_error(409, 'scene already exists') if Storage.scene_exists?(campaign_id, body['id'])

  Storage.create_scene(campaign_id, body['id'], body['name'])

  status 201
  JSON.dump(
    id: body['id'],
    name: body['name'],
    status: 'open'
  )
end

post '/v1/play/campaigns/:id/scenes/:scene_id/enter' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  scene = Storage.load_scene(campaign_id, params[:scene_id])
  json_error(404, 'scene not found') unless scene

  json_error(409, 'scene is closed') if scene[:status] == 'closed'

  Storage.set_current_scene(campaign_id, scene[:id])
  Storage.create_scene_event(campaign_id, username, scene[:id])

  JSON.dump(
    current_scene_id: scene[:id],
    name: scene[:name]
  )
end

post '/v1/play/campaigns/:id/scenes/:scene_id/close' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  scene = Storage.load_scene(campaign_id, params[:scene_id])
  json_error(404, 'scene not found') unless scene

  Storage.close_scene(campaign_id, scene[:id])

  JSON.dump(
    id: scene[:id],
    status: 'closed'
  )
end

get '/v1/play/campaigns/:id/scenes/current' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  current_scene_id = Storage.load_current_scene(campaign_id)
  json_error(404, 'scene not found') unless current_scene_id

  scene = Storage.load_scene(campaign_id, current_scene_id)
  json_error(404, 'scene not found') unless scene && scene[:status] == 'open'

  JSON.dump(
    id: scene[:id],
    name: scene[:name],
    status: scene[:status]
  )
end

