# frozen_string_literal: true

# Route definitions for play-campaign content records with deterministic tags.

# --- Create content ---
post '/v1/play/campaigns/:id/content' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  validate_content_body!(body)

  content_id = body['content_id']
  kind = body['kind']
  text = body['text']
  tags = body['tags']

  json_error(409, 'content already exists') if Storage.content_exists?(campaign_id, content_id)

  Storage.create_content(campaign_id, content_id, kind, text, tags)

  status 201
  JSON.dump(content_response(Storage.load_content(campaign_id, content_id)))
end

# --- Replace content tags ---
put '/v1/play/campaigns/:id/content/:content_id/tags' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  content = Storage.load_content(campaign_id, params[:content_id])
  json_error(404, 'content not found') unless content

  body = parse_json_body
  tags = body['tags']
  validate_content_tags!(tags, allow_empty: true)

  Storage.update_content_tags(campaign_id, content[:content_id], tags)

  JSON.dump(content_response(Storage.load_content(campaign_id, content[:content_id])))
end

# --- List content ---
get '/v1/play/campaigns/:id/content' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  exclude_tag = params['exclude_tag']
  if !exclude_tag.nil?
    unless exclude_tag.is_a?(String) && exclude_tag != ''
      json_error(400, 'invalid exclude_tag')
    end
  end

  content = Storage.load_campaign_content(campaign_id)
  is_owner = campaign[:owner] == username

  list = if is_owner || exclude_tag.nil?
           content
         else
           content.reject { |c| c[:tags].include?(exclude_tag) }
         end

  JSON.dump(content: list.map { |c| content_response(c) })
end
