# Character-to-character whispers: private messages between owned
# characters in a campaign. The DM sees every whisper; players only see
# whispers where their own character is the sender or the recipient.

def play_whisper_payload(row)
  {
    whisper_id: row['whisper_id'],
    from_character_id: row['from_character_id'],
    to_character_id: row['to_character_id'],
    text: row['text']
  }
end

def next_play_whisper_sequence(campaign_id)
  db.execute(
    'SELECT COALESCE(MAX(sequence), 0) + 1 AS n FROM play_whispers WHERE campaign_id = ?',
    [campaign_id]
  ).first['n']
end

def find_play_member_by_username(campaign_id, username)
  db.execute(
    'SELECT * FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
    [campaign_id, username]
  ).first
end

post '/v1/play/campaigns/:id/whispers' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  is_owner = require_play_participant!(campaign, user, 'not a campaign member')
  halt 403, { error: 'forbidden' }.to_json if is_owner

  sender = find_play_member_by_username(campaign['id'], user['username'])
  halt 403, { error: 'forbidden' }.to_json unless sender

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  whisper_id = body['whisper_id']
  to_character_id = body['to_character_id']
  text = body['text']

  halt 400, { error: 'invalid whisper_id' }.to_json unless whisper_id.is_a?(String) && !whisper_id.empty?
  halt 400, { error: 'invalid to_character_id' }.to_json unless to_character_id.is_a?(String) && !to_character_id.empty?
  halt 400, { error: 'invalid text' }.to_json unless text.is_a?(String) && !text.empty?

  recipient = db.execute(
    'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
    [campaign['id'], to_character_id]
  ).first
  halt 400, { error: 'invalid to_character_id' }.to_json unless recipient

  existing = db.execute(
    'SELECT 1 FROM play_whispers WHERE campaign_id = ? AND whisper_id = ?',
    [campaign['id'], whisper_id]
  ).first
  halt 409, { error: 'whisper_id already exists' }.to_json if existing

  from_character_id = sender['character_id']
  sequence = next_play_whisper_sequence(campaign['id'])
  db.execute(
    'INSERT INTO play_whispers (campaign_id, sequence, whisper_id, from_character_id, to_character_id, text) ' \
    'VALUES (?, ?, ?, ?, ?, ?)',
    [campaign['id'], sequence, whisper_id, from_character_id, to_character_id, text]
  )

  status 201
  { whisper_id: whisper_id, from_character_id: from_character_id, to_character_id: to_character_id, text: text }.to_json
end

get '/v1/play/campaigns/:id/whispers' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  is_owner = require_play_participant!(campaign, user, 'not a campaign member')

  rows = db.execute(
    'SELECT * FROM play_whispers WHERE campaign_id = ? ORDER BY sequence ASC',
    [campaign['id']]
  )

  records = rows.map { |row| play_whisper_payload(row) }
  unless is_owner
    member = find_play_member_by_username(campaign['id'], user['username'])
    character_id = member && member['character_id']
    records = records.select { |w| w[:from_character_id] == character_id || w[:to_character_id] == character_id }
  end

  { whispers: records }.to_json
end
