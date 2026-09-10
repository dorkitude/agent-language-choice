# frozen_string_literal: true

# Route definitions for sessions endpoints.

# --- Session scheduling ---

post '/v1/campaigns/:id/sessions' do
  content_type :json
  campaign_id = params[:id]
  require_campaign_exists!(campaign_id)

  body = parse_json_body
  validate_session_body!(body)

  json_error(409, 'session already exists') if Storage.campaign_session_exists?(campaign_id, body['id'])

  Storage.create_campaign_session(
    campaign_id,
    body['id'],
    body['starts_at'],
    body['duration_minutes'],
    body['agenda']
  )

  status 201
  JSON.dump(
    id: body['id'],
    starts_at: body['starts_at'],
    duration_minutes: body['duration_minutes'],
    agenda_count: body['agenda'].length
  )
end

post '/v1/campaigns/:id/sessions/:session_id/attendance' do
  content_type :json
  campaign_id = params[:id]
  session_id = params[:session_id]
  require_campaign_exists!(campaign_id)

  session = Storage.load_campaign_session(campaign_id, session_id)
  json_error(404, 'session not found') unless session

  body = parse_json_body
  validate_attendance_body!(body)

  Storage.save_attendance(campaign_id, session_id, body['present'], body['absent'])

  JSON.dump(
    session_id: session_id,
    present_count: body['present'].length,
    absent_count: body['absent'].length
  )
end

get '/v1/campaigns/:id/sessions/next' do
  content_type :json
  campaign_id = params[:id]
  require_campaign_exists!(campaign_id)

  session = Storage.next_campaign_session(campaign_id)
  json_error(404, 'session not found') unless session

  JSON.dump(
    id: session[:id],
    starts_at: session[:starts_at],
    agenda_count: session[:agenda].length
  )
end

# --- Audit and export ---

get '/v1/campaigns/:id/audit' do
  content_type :json
  campaign_id = params[:id]
  require_campaign_exists!(campaign_id)

  JSON.dump(
    campaign_id: campaign_id,
    events: Storage.campaign_log_count(campaign_id),
    quests: Storage.campaign_quests_count(campaign_id),
    npcs: Storage.campaign_npcs_count(campaign_id),
    sessions: Storage.campaign_sessions_count(campaign_id)
  )
end

get '/v1/campaigns/:id/export' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  campaign = Storage.load_campaign(campaign_id)
  json_error(404, 'campaign not found') unless campaign

  JSON.dump(
    campaign_id: campaign_id,
    name: campaign[:name],
    characters: Storage.campaign_characters_count(campaign_id),
    quests: Storage.campaign_quests_count(campaign_id),
    npcs: Storage.campaign_npcs_count(campaign_id),
    inventory_items: Storage.campaign_inventory_items_count(campaign_id),
    sessions: Storage.campaign_sessions_count(campaign_id),
    schema_version: Storage::SCHEMA_VERSION
  )
end

# --- Campaign analytics ---

get '/v1/campaigns/:id/analytics/summary' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  campaign = Storage.load_campaign(campaign_id)
  json_error(404, 'campaign not found') unless campaign

  signals, open_quests = campaign_readiness_signals(campaign_id, campaign)
  friendly_npcs = Storage.campaign_friendly_npcs_count(campaign_id)
  scheduled_sessions = Storage.campaign_sessions_count(campaign_id)
  inventory_items = Storage.campaign_inventory_items_count(campaign_id)

  readiness_score = 20 * signals.values.count(true) + (friendly_npcs > 0 ? 5 : 0)

  JSON.dump(
    campaign_id: campaign_id,
    readiness_score: readiness_score,
    open_quests: open_quests,
    friendly_npcs: friendly_npcs,
    scheduled_sessions: scheduled_sessions,
    inventory_items: inventory_items
  )
end

post '/v1/campaigns/:id/analytics/risk-report' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  campaign = Storage.load_campaign(campaign_id)
  json_error(404, 'campaign not found') unless campaign

  body = parse_json_body
  include_zeroes = body['include_zeroes'] == true

  signals, _open_quests = campaign_readiness_signals(campaign_id, campaign)

  signal_names = { has_dm: 'dm', has_characters: 'characters', has_next_session: 'next_session', has_active_quest: 'active_quest' }
  missing = []
  signals.each { |key, value| missing << signal_names[key] unless value }

  risk_level = case missing.length
               when 0 then 'low'
               when 1..2 then 'medium'
               else 'high'
               end

  response_signals = include_zeroes ? signals : signals.select { |_, value| value }

  JSON.dump(
    campaign_id: campaign_id,
    risk_level: risk_level,
    missing: missing,
    signals: response_signals
  )
end

