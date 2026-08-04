# Pre-start session-zero settings: rules version, tone, and consent
# boundaries. DM-only to set, readable by any campaign member, and only
# changeable while the campaign is still in its lobby.

def play_session_zero_payload(row)
  { rules: row['rules'], tone: row['tone'], consent: JSON.parse(row['consent_json']) }
end

def valid_session_zero_consent?(consent)
  return false unless consent.is_a?(Array) && !consent.empty?
  return false unless consent.all? { |c| c.is_a?(String) && !c.empty? }

  consent.uniq.length == consent.length
end

put '/v1/play/campaigns/:id/session-zero' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  halt 409, { error: 'campaign already started' }.to_json unless campaign['status'] == 'lobby'

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  rules = body['rules']
  tone = body['tone']
  consent = body['consent']

  halt 400, { error: 'invalid rules' }.to_json unless rules.is_a?(String) && !rules.empty?
  halt 400, { error: 'invalid tone' }.to_json unless tone.is_a?(String) && !tone.empty?
  halt 400, { error: 'invalid consent' }.to_json unless valid_session_zero_consent?(consent)

  db.execute(
    'INSERT INTO play_session_zero_settings (campaign_id, rules, tone, consent_json) VALUES (?, ?, ?, ?) ' \
    'ON CONFLICT(campaign_id) DO UPDATE SET rules = excluded.rules, tone = excluded.tone, consent_json = excluded.consent_json',
    [campaign['id'], rules, tone, consent.to_json]
  )

  { rules: rules, tone: tone, consent: consent }.to_json
end

get '/v1/play/campaigns/:id/session-zero' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  settings = db.execute(
    'SELECT * FROM play_session_zero_settings WHERE campaign_id = ?',
    [campaign['id']]
  ).first
  halt 404, { error: 'session-zero settings not set' }.to_json unless settings

  play_session_zero_payload(settings).to_json
end
