# Campaign clues the DM may reveal to one character, the party, or nobody
# (hidden). Clue IDs are unique per campaign.

def play_clue_payload(clue)
  payload = { clue_id: clue['clue_id'], text: clue['text'], audience: clue['audience'] }
  payload[:character_id] = clue['character_id'] if clue['audience'] == 'character'
  payload
end

post '/v1/play/campaigns/:id/clues' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  clue_id = body['clue_id']
  text = body['text']
  audience = body['audience']
  character_id = body['character_id']

  halt 400, { error: 'invalid clue_id' }.to_json unless clue_id.is_a?(String) && !clue_id.empty?
  halt 400, { error: 'invalid text' }.to_json unless text.is_a?(String) && !text.empty?
  halt 400, { error: 'invalid audience' }.to_json unless %w[character party hidden].include?(audience)

  if audience == 'character'
    halt 400, { error: 'character_id required' }.to_json unless character_id.is_a?(String) && !character_id.empty?
    halt 400, { error: 'unknown character' }.to_json unless db.execute(
      'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
      [campaign['id'], character_id]
    ).first
  else
    halt 400, { error: 'character_id must be omitted' }.to_json unless character_id.nil?
  end

  existing = db.execute(
    'SELECT 1 FROM play_clues WHERE campaign_id = ? AND clue_id = ?',
    [campaign['id'], clue_id]
  ).first
  halt 409, { error: 'clue already exists' }.to_json if existing

  sequence = db.execute(
    'SELECT COALESCE(MAX(sequence), -1) + 1 AS seq FROM play_clues WHERE campaign_id = ?',
    [campaign['id']]
  ).first['seq']

  db.execute(
    'INSERT INTO play_clues (campaign_id, sequence, clue_id, text, audience, character_id) VALUES (?, ?, ?, ?, ?, ?)',
    [campaign['id'], sequence, clue_id, text, audience, audience == 'character' ? character_id : nil]
  )

  status 201
  payload = { clue_id: clue_id, text: text, audience: audience }
  payload[:character_id] = character_id if audience == 'character'
  payload.to_json
end

get '/v1/play/campaigns/:id/clues' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  is_owner = require_play_participant!(campaign, user, 'not a campaign member')

  clues = db.execute(
    'SELECT * FROM play_clues WHERE campaign_id = ? ORDER BY sequence ASC',
    [campaign['id']]
  )

  unless is_owner
    member = db.execute(
      'SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
      [campaign['id'], user['username']]
    ).first
    own_character_id = member && member['character_id']

    clues = clues.select do |clue|
      case clue['audience']
      when 'party' then true
      when 'character' then clue['character_id'] == own_character_id
      else false
      end
    end
  end

  { clues: clues.map { |clue| play_clue_payload(clue) } }.to_json
end
