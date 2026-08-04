# Campaign invitations: a DM invites a registered player identity to join
# the campaign with a specific character_id, and only that identity may
# accept. Acceptance mirrors the regular join flow (routes/play/campaigns.rb
# POST /members) so an accepted invitation leaves the campaign in the same
# state a self-service join would have.

def play_invitation_payload(row)
  {
    invitation_id: row['invitation_id'],
    username: row['username'],
    character_id: row['character_id'],
    status: row['status']
  }
end

def next_play_invitation_sequence(campaign_id)
  db.execute(
    'SELECT COALESCE(MAX(sequence), 0) + 1 AS n FROM play_invitations WHERE campaign_id = ?',
    [campaign_id]
  ).first['n']
end

def find_play_invitation!(campaign_id, invitation_id)
  invitation = db.execute(
    'SELECT * FROM play_invitations WHERE campaign_id = ? AND invitation_id = ?',
    [campaign_id, invitation_id]
  ).first
  halt 404, { error: 'invitation not found' }.to_json unless invitation
  invitation
end

post '/v1/play/campaigns/:id/invitations' do
  user = authenticate_play_request!
  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  invitation_id = body['invitation_id']
  username = body['username']
  character_id = body['character_id']

  halt 400, { error: 'invalid invitation_id' }.to_json unless invitation_id.is_a?(String) && !invitation_id.empty?
  halt 400, { error: 'invalid username' }.to_json unless username.is_a?(String) && !username.empty?
  halt 400, { error: 'invalid character_id' }.to_json unless character_id.is_a?(String) && !character_id.empty?

  target = db.execute('SELECT * FROM users WHERE username = ?', [username]).first
  halt 400, { error: 'invalid username' }.to_json unless target && target['role'] == 'player'

  existing = db.execute(
    'SELECT 1 FROM play_invitations WHERE campaign_id = ? AND invitation_id = ?',
    [campaign['id'], invitation_id]
  ).first
  halt 409, { error: 'invitation_id already exists' }.to_json if existing

  active = db.execute(
    "SELECT 1 FROM play_invitations WHERE campaign_id = ? AND username = ? AND status = 'pending'",
    [campaign['id'], username]
  ).first
  halt 409, { error: 'invitation already pending for this user' }.to_json if active

  sequence = next_play_invitation_sequence(campaign['id'])
  db.execute(
    'INSERT INTO play_invitations (campaign_id, sequence, invitation_id, username, character_id, status) ' \
    "VALUES (?, ?, ?, ?, ?, 'pending')",
    [campaign['id'], sequence, invitation_id, username, character_id]
  )

  status 201
  { invitation_id: invitation_id, username: username, character_id: character_id, status: 'pending' }.to_json
end

post '/v1/play/campaigns/:id/invitations/:invitation_id/accept' do
  user = authenticate_play_request!
  campaign = find_play_campaign!(params[:id])
  invitation = find_play_invitation!(campaign['id'], params[:invitation_id])

  halt 403, { error: 'forbidden' }.to_json unless invitation['username'] == user['username']
  halt 409, { error: 'invitation already accepted' }.to_json unless invitation['status'] == 'pending'

  character_id = invitation['character_id']

  db.execute(
    'INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class) VALUES (?, ?, ?, ?, ?)',
    [campaign['id'], user['username'], character_id, user['username'], 'Adventurer']
  )
  db.execute(
    'INSERT INTO play_character_owners (campaign_id, character_id, owner) VALUES (?, ?, ?)',
    [campaign['id'], character_id, user['username']]
  )
  db.execute(
    'INSERT INTO play_character_gold (campaign_id, character_id, gold) VALUES (?, ?, ?)',
    [campaign['id'], character_id, 10]
  )
  db.execute(
    "UPDATE play_invitations SET status = 'accepted' WHERE campaign_id = ? AND invitation_id = ?",
    [campaign['id'], invitation['invitation_id']]
  )

  { invitation_id: invitation['invitation_id'], username: invitation['username'], character_id: character_id, status: 'accepted' }.to_json
end

get '/v1/play/campaigns/:id/invitations' do
  user = authenticate_play_request!
  campaign = find_play_campaign!(params[:id])

  is_owner = campaign['owner'] == user['username']

  rows = db.execute(
    'SELECT * FROM play_invitations WHERE campaign_id = ? ORDER BY sequence ASC',
    [campaign['id']]
  )

  records = if is_owner
              rows
            else
              rows.select { |row| row['username'] == user['username'] }
            end

  { invitations: records.map { |row| play_invitation_payload(row) } }.to_json
end
