# frozen_string_literal: true

# Route definitions for the campaign calendar and deterministic weather.

# --- Initialize calendar ---
post '/v1/play/campaigns/:id/calendar' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  validate_calendar_body!(body)

  json_error(409, 'calendar already initialized') if Storage.load_calendar(campaign_id)

  day = body['day']
  season = body['season']

  Storage.create_calendar(campaign_id, day, season)

  status 201
  JSON.dump(
    day: day,
    season: season,
    weather: weather_for(day, season)
  )
end

# --- Get calendar ---
get '/v1/play/campaigns/:id/calendar' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  calendar = Storage.load_calendar(campaign_id)
  json_error(404, 'calendar not found') unless calendar

  JSON.dump(
    day: calendar[:day],
    season: calendar[:season],
    weather: weather_for(calendar[:day], calendar[:season])
  )
end

# --- Advance calendar ---
post '/v1/play/campaigns/:id/calendar/advance' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  validate_calendar_advance_body!(body)

  calendar = Storage.advance_calendar(campaign_id, body['days'])
  json_error(404, 'calendar not found') unless calendar

  status 200
  JSON.dump(
    day: calendar[:day],
    season: calendar[:season],
    weather: weather_for(calendar[:day], calendar[:season])
  )
end
