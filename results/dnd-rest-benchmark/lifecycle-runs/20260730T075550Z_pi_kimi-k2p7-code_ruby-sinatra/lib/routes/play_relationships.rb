# frozen_string_literal: true

# Route definitions for play-campaign relationship graph edges.

# --- Create relationship edge ---
post '/v1/play/campaigns/:id/relationships' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  validate_relationship_body!(body)

  source_id = body['source_id']
  target_id = body['target_id']
  kind = body['kind']
  score = body['score']

  json_error(400, 'self-edges are not allowed') if source_id == target_id

  unless Storage.play_campaign_entity_exists?(campaign_id, source_id) && Storage.play_campaign_entity_exists?(campaign_id, target_id)
    json_error(404, 'entity not found')
  end

  if Storage.play_campaign_relationship_exists?(campaign_id, source_id, target_id, kind)
    json_error(409, 'relationship already exists')
  end

  Storage.create_play_campaign_relationship(campaign_id, source_id, target_id, kind, score)

  status 201
  JSON.dump(
    source_id: source_id,
    target_id: target_id,
    kind: kind,
    score: score
  )
end

# --- Update relationship edge ---
put '/v1/play/campaigns/:id/relationships/:source_id/:target_id/:kind' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  score = body['score']
  unless score.is_a?(Integer) && (-100..100).cover?(score)
    json_error(400, 'invalid score')
  end

  relationship = Storage.load_play_campaign_relationship(campaign_id, params[:source_id], params[:target_id], params[:kind])
  json_error(404, 'relationship not found') unless relationship

  Storage.update_play_campaign_relationship(campaign_id, relationship[:source_id], relationship[:target_id], relationship[:kind], score)

  JSON.dump(
    source_id: relationship[:source_id],
    target_id: relationship[:target_id],
    kind: relationship[:kind],
    score: score
  )
end

# --- List relationship edges ---
get '/v1/play/campaigns/:id/relationships' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  edges = Storage.load_play_campaign_relationships(campaign_id)

  JSON.dump(edges: edges)
end
