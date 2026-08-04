# Campaign-scoped GM delegation: the campaign owner can grant/revoke a
# member limited co-GM authority. The only delegated power in this ticket
# is 'narrate', which lets the delegate use POST .../narrations alongside
# the owner (see routes/play/turns.rb and play_active_delegate_power?).

VALID_DELEGATION_POWERS = ['narrate'].freeze

def play_delegation_payload(row)
  {
    username: row['username'],
    powers: JSON.parse(row['powers_json']),
    active: row['active'] == 1
  }
end

def next_play_delegation_audit_sequence(campaign_id)
  db.execute(
    'SELECT COALESCE(MAX(sequence), 0) + 1 AS n FROM play_delegation_audit WHERE campaign_id = ?',
    [campaign_id]
  ).first['n']
end

def insert_play_delegation_audit(campaign_id, username, action, powers)
  sequence = next_play_delegation_audit_sequence(campaign_id)
  db.execute(
    'INSERT INTO play_delegation_audit (campaign_id, sequence, username, action, powers_json) VALUES (?, ?, ?, ?, ?)',
    [campaign_id, sequence, username, action, powers.to_json]
  )
end

post '/v1/play/campaigns/:id/delegations' do
  user = authenticate_play_request!
  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  username = body['username']
  powers = body['powers']

  halt 400, { error: 'invalid username' }.to_json unless username.is_a?(String) && !username.empty?
  halt 400, { error: 'unknown or non-member username' }.to_json unless play_campaign_member?(campaign, username)
  halt 400, { error: 'invalid powers' }.to_json unless powers.is_a?(Array) && !powers.empty?
  halt 400, { error: 'invalid powers' }.to_json unless powers.uniq.length == powers.length
  halt 400, { error: 'invalid powers' }.to_json unless powers.all? { |p| VALID_DELEGATION_POWERS.include?(p) }

  existing = db.execute(
    'SELECT active FROM play_delegations WHERE campaign_id = ? AND username = ?',
    [campaign['id'], username]
  ).first
  halt 409, { error: 'delegate already active' }.to_json if existing && existing['active'] == 1

  db.execute(
    'INSERT INTO play_delegations (campaign_id, username, powers_json, active) VALUES (?, ?, ?, 1) ' \
    'ON CONFLICT(campaign_id, username) DO UPDATE SET powers_json = excluded.powers_json, active = 1',
    [campaign['id'], username, powers.to_json]
  )
  insert_play_delegation_audit(campaign['id'], username, 'granted', powers)

  status 201
  { username: username, powers: powers, active: true }.to_json
end

delete '/v1/play/campaigns/:id/delegations/:username' do
  user = authenticate_play_request!
  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  username = params[:username]
  delegation = db.execute(
    'SELECT * FROM play_delegations WHERE campaign_id = ? AND username = ? AND active = 1',
    [campaign['id'], username]
  ).first
  halt 404, { error: 'delegation not found' }.to_json unless delegation

  db.execute(
    'UPDATE play_delegations SET active = 0 WHERE campaign_id = ? AND username = ?',
    [campaign['id'], username]
  )

  powers = JSON.parse(delegation['powers_json'])
  insert_play_delegation_audit(campaign['id'], username, 'revoked', powers)

  { username: username, powers: powers, active: false }.to_json
end

get '/v1/play/campaigns/:id/delegations/audit' do
  user = authenticate_play_request!
  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  rows = db.execute(
    'SELECT username, action, powers_json FROM play_delegation_audit WHERE campaign_id = ? ORDER BY sequence ASC',
    [campaign['id']]
  )

  entries = rows.map do |row|
    { username: row['username'], action: row['action'], powers: JSON.parse(row['powers_json']) }
  end

  { entries: entries }.to_json
end
