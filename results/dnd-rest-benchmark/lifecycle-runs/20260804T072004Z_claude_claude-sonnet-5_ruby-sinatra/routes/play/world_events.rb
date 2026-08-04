# Deterministic campaign-level world events scheduled by the DM for a
# future campaign turn and resolved exactly once that turn is reached.

def play_world_event_payload(event)
  payload = {
    event_id: event['event_id'],
    turn_number: event['turn_number'],
    title: event['title'],
    text: event['text'],
    status: event['status']
  }

  if event['status'] == 'resolved'
    payload[:resolution] = {
      turn_number: event['resolution_turn_number'],
      text: event['resolution_text']
    }
  end

  payload
end

post '/v1/play/campaigns/:id/world-events' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  event_id = body['event_id']
  turn_number = body['turn_number']
  title = body['title']
  text = body['text']

  halt 400, { error: 'invalid event_id' }.to_json unless event_id.is_a?(String) && !event_id.empty?
  halt 400, { error: 'invalid title' }.to_json unless title.is_a?(String) && !title.empty?
  halt 400, { error: 'invalid text' }.to_json unless text.is_a?(String) && !text.empty?
  halt 400, { error: 'invalid turn_number' }.to_json unless integerish(turn_number)
  turn_number = turn_number.to_i
  halt 400, { error: 'invalid turn_number' }.to_json if turn_number < campaign['turn_number'].to_i

  existing = db.execute(
    'SELECT 1 FROM play_world_events WHERE campaign_id = ? AND event_id = ?',
    [campaign['id'], event_id]
  ).first
  halt 409, { error: 'world event already exists' }.to_json if existing

  sequence = db.execute(
    'SELECT COALESCE(MAX(sequence), -1) + 1 AS seq FROM play_world_events WHERE campaign_id = ?',
    [campaign['id']]
  ).first['seq']

  db.execute(
    'INSERT INTO play_world_events (campaign_id, sequence, event_id, turn_number, title, text, status) VALUES (?, ?, ?, ?, ?, ?, ?)',
    [campaign['id'], sequence, event_id, turn_number, title, text, 'scheduled']
  )

  status 201
  { event_id: event_id, turn_number: turn_number, title: title, text: text, status: 'scheduled' }.to_json
end

post '/v1/play/campaigns/:id/world-events/:event_id/resolve' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  event = db.execute(
    'SELECT * FROM play_world_events WHERE campaign_id = ? AND event_id = ?',
    [campaign['id'], params[:event_id]]
  ).first
  halt 404, { error: 'world event not found' }.to_json unless event

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  text = body['text']
  halt 400, { error: 'invalid text' }.to_json unless text.is_a?(String) && !text.empty?

  halt 409, { error: 'world event already resolved' }.to_json if event['status'] == 'resolved'
  halt 409, { error: 'turn mismatch' }.to_json unless campaign['turn_number'].to_i == event['turn_number']

  db.execute(
    'UPDATE play_world_events SET status = ?, resolution_turn_number = ?, resolution_text = ? WHERE campaign_id = ? AND event_id = ?',
    ['resolved', event['turn_number'], text, campaign['id'], params[:event_id]]
  )

  event['status'] = 'resolved'
  event['resolution_turn_number'] = event['turn_number']
  event['resolution_text'] = text

  status 201
  play_world_event_payload(event).to_json
end

get '/v1/play/campaigns/:id/world-events' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  events = db.execute(
    'SELECT * FROM play_world_events WHERE campaign_id = ? ORDER BY turn_number ASC, sequence ASC',
    [campaign['id']]
  )

  { events: events.map { |event| play_world_event_payload(event) } }.to_json
end
