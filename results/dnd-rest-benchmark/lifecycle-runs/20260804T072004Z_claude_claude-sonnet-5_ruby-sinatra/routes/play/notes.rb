# Campaign notes: player-authored, role-filtered by visibility. The DM sees
# every note; players see all "party" notes plus only their own "private"
# ones. Ownership is derived from the authenticated actor, never the body.

def play_note_payload(row)
  {
    note_id: row['note_id'],
    text: row['text'],
    visibility: row['visibility'],
    owner: row['owner']
  }
end

def valid_note_visibility?(visibility)
  %w[private party].include?(visibility)
end

def next_play_note_sequence(campaign_id)
  db.execute(
    'SELECT COALESCE(MAX(sequence), 0) + 1 AS n FROM play_notes WHERE campaign_id = ?',
    [campaign_id]
  ).first['n']
end

def find_play_note!(campaign_id, note_id)
  note = db.execute(
    'SELECT * FROM play_notes WHERE campaign_id = ? AND note_id = ?',
    [campaign_id, note_id]
  ).first
  halt 404, { error: 'note not found' }.to_json unless note
  note
end

post '/v1/play/campaigns/:id/notes' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  note_id = body['note_id']
  text = body['text']
  visibility = body['visibility']

  halt 400, { error: 'invalid note_id' }.to_json unless note_id.is_a?(String) && !note_id.empty?
  halt 400, { error: 'invalid text' }.to_json unless text.is_a?(String) && !text.empty?
  halt 400, { error: 'invalid visibility' }.to_json unless valid_note_visibility?(visibility)

  existing = db.execute(
    'SELECT 1 FROM play_notes WHERE campaign_id = ? AND note_id = ?',
    [campaign['id'], note_id]
  ).first
  halt 409, { error: 'note_id already exists' }.to_json if existing

  sequence = next_play_note_sequence(campaign['id'])
  db.execute(
    'INSERT INTO play_notes (campaign_id, sequence, note_id, text, visibility, owner) VALUES (?, ?, ?, ?, ?, ?)',
    [campaign['id'], sequence, note_id, text, visibility, user['username']]
  )

  status 201
  { note_id: note_id, text: text, visibility: visibility, owner: user['username'] }.to_json
end

get '/v1/play/campaigns/:id/notes' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  is_owner = require_play_participant!(campaign, user, 'not a campaign member')

  rows = db.execute(
    'SELECT * FROM play_notes WHERE campaign_id = ? ORDER BY sequence ASC',
    [campaign['id']]
  )

  records = rows.map { |row| play_note_payload(row) }
  unless is_owner
    records = records.select { |n| n[:visibility] == 'party' || n[:owner] == user['username'] }
  end

  { notes: records }.to_json
end

get '/v1/play/campaigns/:id/notes/:note_id' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  is_owner = require_play_participant!(campaign, user, 'not a campaign member')

  note = find_play_note!(campaign['id'], params[:note_id])
  halt 403, { error: 'forbidden' }.to_json if !is_owner && note['visibility'] == 'private' && note['owner'] != user['username']

  play_note_payload(note).to_json
end

put '/v1/play/campaigns/:id/notes/:note_id' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  note = find_play_note!(campaign['id'], params[:note_id])
  halt 403, { error: 'not the note owner' }.to_json unless note['owner'] == user['username']

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  text = body['text']
  visibility = body['visibility']

  halt 400, { error: 'invalid text' }.to_json unless text.is_a?(String) && !text.empty?
  halt 400, { error: 'invalid visibility' }.to_json unless valid_note_visibility?(visibility)

  db.execute(
    'UPDATE play_notes SET text = ?, visibility = ? WHERE campaign_id = ? AND note_id = ?',
    [text, visibility, campaign['id'], params[:note_id]]
  )

  updated = find_play_note!(campaign['id'], params[:note_id])
  play_note_payload(updated).to_json
end
