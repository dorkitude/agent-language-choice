# Deterministic campaign calendar: the DM initializes a day/season once,
# advances it in bounded increments, and members read the current day,
# season, and derived weather.

SEASON_OFFSETS = { 'spring' => 0, 'summer' => 1, 'autumn' => 2, 'winter' => 3 }.freeze
WEATHER_BY_INDEX = %w[clear rain wind snow].freeze

def play_calendar_weather(day, season)
  index = (day + SEASON_OFFSETS.fetch(season)) % 4
  WEATHER_BY_INDEX[index]
end

def play_calendar_payload(calendar)
  {
    day: calendar['day'],
    season: calendar['season'],
    weather: play_calendar_weather(calendar['day'], calendar['season'])
  }
end

def find_play_calendar(campaign_id)
  db.execute('SELECT * FROM play_calendars WHERE campaign_id = ?', [campaign_id]).first
end

post '/v1/play/campaigns/:id/calendar' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  day = body['day']
  season = body['season']

  halt 400, { error: 'invalid day' }.to_json unless integerish(day) && day.to_i >= 1
  day = day.to_i
  halt 400, { error: 'invalid season' }.to_json unless SEASON_OFFSETS.key?(season)

  existing = find_play_calendar(campaign['id'])
  halt 409, { error: 'calendar already initialized' }.to_json if existing

  db.execute(
    'INSERT INTO play_calendars (campaign_id, day, season) VALUES (?, ?, ?)',
    [campaign['id'], day, season]
  )

  status 201
  play_calendar_payload('day' => day, 'season' => season).to_json
end

get '/v1/play/campaigns/:id/calendar' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  calendar = find_play_calendar(campaign['id'])
  halt 404, { error: 'calendar not initialized' }.to_json unless calendar

  play_calendar_payload(calendar).to_json
end

post '/v1/play/campaigns/:id/calendar/advance' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  calendar = find_play_calendar(campaign['id'])
  halt 404, { error: 'calendar not initialized' }.to_json unless calendar

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  days = body['days']
  halt 400, { error: 'invalid days' }.to_json unless integerish(days) && days.to_i >= 1 && days.to_i <= 30
  days = days.to_i

  new_day = calendar['day'].to_i + days
  db.execute(
    'UPDATE play_calendars SET day = ? WHERE campaign_id = ?',
    [new_day, campaign['id']]
  )

  calendar['day'] = new_day
  play_calendar_payload(calendar).to_json
end
