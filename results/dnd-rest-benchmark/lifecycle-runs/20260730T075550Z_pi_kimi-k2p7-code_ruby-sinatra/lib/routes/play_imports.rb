# frozen_string_literal: true

# Route definitions for play campaign import validation.

# --- Import a versioned snapshot ---
post '/v1/play/campaigns/:id/imports' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  validate_import_snapshot!(body)

  story = body['story']
  import_status = body['status']

  Storage.apply_play_campaign_import!(campaign_id, 1, story, import_status)

  JSON.dump(version: 1, story: story, status: import_status)
end

# --- Read imported state ---
get '/v1/play/campaigns/:id/import-state' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  imported = Storage.load_play_campaign_import(campaign_id)
  json_error(404, 'import state not found') unless imported

  JSON.dump(imported)
end
