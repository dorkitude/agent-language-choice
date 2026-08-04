# Campaign session scheduling: schedule sessions, record attendance, and
# find the next upcoming session.

def valid_timestamp?(value)
  return false unless value.is_a?(String) && !value.empty?

  Time.iso8601(value)
  true
rescue ArgumentError
  false
end

post '/v1/campaigns/:campaign_id/sessions' do
  campaign = db.execute('SELECT 1 FROM campaigns WHERE id = ?', [params[:campaign_id]]).first
  halt 404, { error: 'unknown campaign' }.to_json unless campaign

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  id = body['id']
  starts_at = body['starts_at']
  duration_minutes = body['duration_minutes']
  agenda = body.key?('agenda') ? body['agenda'] : []

  halt 400, { error: 'invalid id' }.to_json unless id.is_a?(String) && !id.empty?
  halt 400, { error: 'invalid starts_at' }.to_json unless valid_timestamp?(starts_at)
  halt 400, { error: 'invalid duration_minutes' }.to_json unless integerish(duration_minutes) && duration_minutes.to_i > 0
  unless agenda.is_a?(Array) && agenda.all? { |a| a.is_a?(String) && !a.empty? }
    halt 400, { error: 'invalid agenda' }.to_json
  end
  if db.execute('SELECT 1 FROM campaign_sessions WHERE campaign_id = ? AND id = ?', [params[:campaign_id], id]).first
    halt 409, { error: 'id already exists' }.to_json
  end

  duration_minutes = duration_minutes.to_i

  db.execute(
    'INSERT INTO campaign_sessions (campaign_id, id, starts_at, duration_minutes, agenda_json, created_at) VALUES (?, ?, ?, ?, ?, ?)',
    [params[:campaign_id], id, starts_at, duration_minutes, agenda.to_json, Time.now.utc.iso8601]
  )

  status 201
  {
    id: id,
    starts_at: starts_at,
    duration_minutes: duration_minutes,
    agenda_count: agenda.length
  }.to_json
end

post '/v1/campaigns/:campaign_id/sessions/:session_id/attendance' do
  campaign = db.execute('SELECT 1 FROM campaigns WHERE id = ?', [params[:campaign_id]]).first
  halt 404, { error: 'unknown campaign' }.to_json unless campaign

  session = db.execute(
    'SELECT 1 FROM campaign_sessions WHERE campaign_id = ? AND id = ?',
    [params[:campaign_id], params[:session_id]]
  ).first
  halt 404, { error: 'unknown session' }.to_json unless session

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  present = body.key?('present') ? body['present'] : []
  absent = body.key?('absent') ? body['absent'] : []

  unless present.is_a?(Array) && present.all? { |c| c.is_a?(String) && !c.empty? }
    halt 400, { error: 'invalid present' }.to_json
  end
  unless absent.is_a?(Array) && absent.all? { |c| c.is_a?(String) && !c.empty? }
    halt 400, { error: 'invalid absent' }.to_json
  end

  db.execute(
    'INSERT INTO campaign_session_attendance (campaign_id, session_id, present_json, absent_json) VALUES (?, ?, ?, ?) ' \
    'ON CONFLICT(campaign_id, session_id) DO UPDATE SET present_json = excluded.present_json, absent_json = excluded.absent_json',
    [params[:campaign_id], params[:session_id], present.to_json, absent.to_json]
  )

  {
    session_id: params[:session_id],
    present_count: present.length,
    absent_count: absent.length
  }.to_json
end

get '/v1/campaigns/:campaign_id/sessions/next' do
  campaign = db.execute('SELECT 1 FROM campaigns WHERE id = ?', [params[:campaign_id]]).first
  halt 404, { error: 'unknown campaign' }.to_json unless campaign

  sessions = db.execute(
    'SELECT id, starts_at, agenda_json FROM campaign_sessions WHERE campaign_id = ?',
    [params[:campaign_id]]
  )
  halt 404, { error: 'no upcoming session' }.to_json if sessions.empty?

  next_session = sessions.min_by { |s| Time.iso8601(s['starts_at']) }
  agenda = JSON.parse(next_session['agenda_json'])

  {
    id: next_session['id'],
    starts_at: next_session['starts_at'],
    agenda_count: agenda.length
  }.to_json
end
