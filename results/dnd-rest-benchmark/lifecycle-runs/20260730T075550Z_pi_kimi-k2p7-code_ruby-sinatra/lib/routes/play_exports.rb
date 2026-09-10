# frozen_string_literal: true

# Route definitions for play campaign versioned exports.

# --- Create export ---
post '/v1/play/campaigns/:id/exports' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]
  campaign = load_play_campaign!(campaign_id)

  require_play_campaign_owner!(campaign, username)

  document = Storage.load_play_campaign_document(campaign_id)
  version = Storage.next_play_campaign_export_version(campaign_id)

  Storage.create_play_campaign_export(campaign_id, version, document[:story], campaign[:status])

  status 201
  JSON.dump(version: version, story: document[:story], status: campaign[:status])
end

# --- List exports ---
get '/v1/play/campaigns/:id/exports' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]
  campaign = load_play_campaign!(campaign_id)

  require_play_campaign_owner!(campaign, username)

  exports = Storage.play_campaign_exports(campaign_id)
  JSON.dump(exports: exports)
end

# --- Read export ---
get '/v1/play/campaigns/:id/exports/:version' do
  content_type :json
  campaign_id = params[:id]
  version_param = params[:version]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]
  campaign = load_play_campaign!(campaign_id)

  require_play_campaign_owner!(campaign, username)

  unless version_param.match?(/\A[1-9]\d*\z/)
    json_error(400, 'invalid version')
  end

  version = version_param.to_i
  export = Storage.load_play_campaign_export(campaign_id, version)
  json_error(404, 'export not found') unless export

  JSON.dump(export)
end
