# frozen_string_literal: true

# Route definitions for play document endpoints.

# --- Campaign document ---

get '/v1/play/campaigns/:id/document' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  document = Storage.load_play_campaign_document(campaign_id)

  if campaign[:owner] == username
    JSON.dump(story: document[:story], dm_notes: document[:dm_notes])
  else
    JSON.dump(story: document[:story])
  end
end

put '/v1/play/campaigns/:id/document' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)

  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  validate_document_body!(body)

  Storage.update_play_campaign_document(campaign_id, body['story'].to_s, body['dm_notes'].to_s)

  JSON.dump(story: body['story'].to_s, dm_notes: body['dm_notes'].to_s)
end

