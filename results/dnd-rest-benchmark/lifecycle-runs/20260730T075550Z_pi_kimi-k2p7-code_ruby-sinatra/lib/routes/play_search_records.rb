# frozen_string_literal: true

# Route definitions for play-campaign search records with pagination and
# case-insensitive text filtering.

# --- Create search record ---
post '/v1/play/campaigns/:id/search-records' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  validate_search_record_body!(body)

  record_id = body['record_id']
  text = body['text']

  json_error(400, 'record already exists') if Storage.search_record_exists?(campaign_id, record_id)
  json_error(400, 'text already exists') if Storage.search_record_text_exists?(campaign_id, text)

  Storage.create_search_record(campaign_id, record_id, text)

  status 201
  JSON.dump(record_id: record_id, text: text)
end

# --- List search records ---
get '/v1/play/campaigns/:id/search-records' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  q, limit, cursor = validate_search_query!(params)

  records = Storage.load_search_records(campaign_id)

  if q
    query = q.downcase
    records = records.select { |r| r[:text].downcase.include?(query) }
  end

  paged = records[cursor, limit] || []
  next_cursor = (cursor + limit < records.length) ? (cursor + limit) : nil

  JSON.dump(records: paged, next_cursor: next_cursor)
end
