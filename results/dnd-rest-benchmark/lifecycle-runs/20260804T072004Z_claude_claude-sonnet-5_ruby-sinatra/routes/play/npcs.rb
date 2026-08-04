# Campaign-scoped NPC records for the /v1/play surface: the DM tracks a
# private agenda alongside a player-visible public status.

def find_play_npc!(campaign_id, npc_id)
  npc = db.execute(
    'SELECT * FROM play_npcs WHERE campaign_id = ? AND npc_id = ?',
    [campaign_id, npc_id]
  ).first
  halt 404, { error: 'npc not found' }.to_json unless npc
  npc
end

def play_npc_dm_payload(npc)
  {
    npc_id: npc['npc_id'],
    name: npc['name'],
    agenda: npc['agenda'],
    public_status: npc['public_status']
  }
end

def play_npc_player_payload(npc)
  {
    npc_id: npc['npc_id'],
    name: npc['name'],
    public_status: npc['public_status']
  }
end

post '/v1/play/campaigns/:id/npcs' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  npc_id = body['npc_id']
  name = body['name']
  agenda = body['agenda']
  public_status = body['public_status']

  halt 400, { error: 'invalid npc_id' }.to_json unless npc_id.is_a?(String) && !npc_id.empty?
  halt 400, { error: 'invalid name' }.to_json unless name.is_a?(String) && !name.empty?
  halt 400, { error: 'invalid agenda' }.to_json unless agenda.is_a?(String) && !agenda.empty?
  halt 400, { error: 'invalid public_status' }.to_json unless public_status.is_a?(String) && !public_status.empty?

  existing = db.execute(
    'SELECT 1 FROM play_npcs WHERE campaign_id = ? AND npc_id = ?',
    [campaign['id'], npc_id]
  ).first
  halt 409, { error: 'npc_id already exists' }.to_json if existing

  db.execute(
    'INSERT INTO play_npcs (campaign_id, npc_id, name, agenda, public_status) VALUES (?, ?, ?, ?, ?)',
    [campaign['id'], npc_id, name, agenda, public_status]
  )

  status 201
  { npc_id: npc_id, name: name, agenda: agenda, public_status: public_status }.to_json
end

put '/v1/play/campaigns/:id/npcs/:npc_id/agenda' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  npc = find_play_npc!(campaign['id'], params[:npc_id])

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  agenda = body['agenda']
  public_status = body['public_status']

  halt 400, { error: 'invalid agenda' }.to_json unless agenda.is_a?(String) && !agenda.empty?
  halt 400, { error: 'invalid public_status' }.to_json unless public_status.is_a?(String) && !public_status.empty?

  db.execute(
    'UPDATE play_npcs SET agenda = ?, public_status = ? WHERE campaign_id = ? AND npc_id = ?',
    [agenda, public_status, campaign['id'], npc['npc_id']]
  )

  { npc_id: npc['npc_id'], name: npc['name'], agenda: agenda, public_status: public_status }.to_json
end

get '/v1/play/campaigns/:id/npcs/:npc_id' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  is_owner = require_play_participant!(campaign, user, 'not a campaign member')

  npc = find_play_npc!(campaign['id'], params[:npc_id])

  (is_owner ? play_npc_dm_payload(npc) : play_npc_player_payload(npc)).to_json
end

post '/v1/play/campaigns/:id/npcs/:npc_id/dialogue' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  npc = find_play_npc!(campaign['id'], params[:npc_id])

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  dialogue_id = body['dialogue_id']
  speaker = body['speaker']
  text = body['text']
  visibility = body['visibility']

  halt 400, { error: 'invalid dialogue_id' }.to_json unless dialogue_id.is_a?(String) && !dialogue_id.empty?
  halt 400, { error: 'invalid speaker' }.to_json unless speaker.is_a?(String) && !speaker.empty?
  halt 400, { error: 'invalid text' }.to_json unless text.is_a?(String) && !text.empty?
  halt 400, { error: 'invalid visibility' }.to_json unless %w[public private].include?(visibility)

  existing = db.execute(
    'SELECT 1 FROM play_npc_dialogue WHERE campaign_id = ? AND npc_id = ? AND dialogue_id = ?',
    [campaign['id'], npc['npc_id'], dialogue_id]
  ).first
  halt 409, { error: 'dialogue_id already exists' }.to_json if existing

  next_sequence = db.execute(
    'SELECT COALESCE(MAX(sequence), -1) + 1 AS seq FROM play_npc_dialogue WHERE campaign_id = ? AND npc_id = ?',
    [campaign['id'], npc['npc_id']]
  ).first['seq']

  db.execute(
    'INSERT INTO play_npc_dialogue (campaign_id, npc_id, sequence, dialogue_id, speaker, text, visibility) VALUES (?, ?, ?, ?, ?, ?, ?)',
    [campaign['id'], npc['npc_id'], next_sequence, dialogue_id, speaker, text, visibility]
  )

  status 201
  { dialogue_id: dialogue_id, speaker: speaker, text: text, visibility: visibility }.to_json
end

get '/v1/play/campaigns/:id/npcs/:npc_id/dialogue' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  is_owner = require_play_participant!(campaign, user, 'not a campaign member')

  npc = find_play_npc!(campaign['id'], params[:npc_id])

  rows = db.execute(
    'SELECT * FROM play_npc_dialogue WHERE campaign_id = ? AND npc_id = ? ORDER BY sequence ASC',
    [campaign['id'], npc['npc_id']]
  )
  rows = rows.select { |row| row['visibility'] == 'public' } unless is_owner

  entries = rows.map do |row|
    {
      dialogue_id: row['dialogue_id'],
      speaker: row['speaker'],
      text: row['text'],
      visibility: row['visibility']
    }
  end

  { npc_id: npc['npc_id'], entries: entries }.to_json
end
