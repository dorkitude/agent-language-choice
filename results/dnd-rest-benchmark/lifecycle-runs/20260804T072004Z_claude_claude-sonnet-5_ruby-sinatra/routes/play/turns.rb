# The exploration turn loop: DM narrations, the active player's action,
# the DM's resolution (which advances current_actor to the next party
# member), plus read-only turn/status views and short/long rests.
#
# Turn order outside combat is always "each party member in join order,
# then the DM" — actions hand control to the DM, resolutions hand it to
# the next player in that rotation (see play_member_usernames).

# Fixed number of logical ticks a turn has before its deadline — a pure
# function of turn_number, never wall-clock time, so the API stays
# deterministic across runs.
TURN_TIMEOUT_LOGICAL_TICKS = 1

post '/v1/play/campaigns/:id/narrations' do
  user = authenticate_play_request!
  campaign = find_play_campaign!(params[:id])

  is_owner = campaign['owner'] == user['username']
  is_narrate_delegate = play_active_delegate_power?(campaign['id'], user['username'], 'narrate')
  halt 403, { error: 'forbidden' }.to_json unless is_owner || is_narrate_delegate

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  text = body['text']
  halt 400, { error: 'invalid text' }.to_json unless text.is_a?(String) && !text.empty?

  actor = is_owner ? 'dm' : user['username']
  sequence = insert_play_event(campaign['id'], kind: 'narration', actor: actor, text: text)

  status 201
  { sequence: sequence, kind: 'narration', actor: actor, text: text }.to_json
end

post '/v1/play/campaigns/:id/actions' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  is_active_player = user['role'] == 'player' && campaign['current_actor'] == user['username']
  halt 409, { error: 'not your turn' }.to_json unless is_active_player

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  type = body['type']
  text = body['text']
  halt 400, { error: 'invalid type' }.to_json unless type.is_a?(String) && !type.empty?
  halt 400, { error: 'invalid text' }.to_json unless text.is_a?(String) && !text.empty?

  sequence = insert_play_event(campaign['id'], kind: 'action', actor: user['username'], text: text, type: type)

  db.execute(
    'UPDATE play_campaigns SET current_actor = ? WHERE id = ?',
    [campaign['owner'], campaign['id']]
  )

  status 201
  {
    sequence: sequence,
    kind: 'action',
    actor: user['username'],
    type: type,
    text: text,
    next_actor: 'dm'
  }.to_json
end

post '/v1/play/campaigns/:id/resolutions' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])

  is_owner = campaign['owner'] == user['username']
  halt 409, { error: 'not your turn' }.to_json unless is_owner
  halt 409, { error: 'not your turn' }.to_json unless campaign['current_actor'] == campaign['owner']

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  text = body['text']
  halt 400, { error: 'invalid text' }.to_json unless text.is_a?(String) && !text.empty?

  members = play_member_usernames(campaign['id'])
  current_index = campaign['turn_index'] || 0
  next_index = (current_index + 1) % members.length
  next_actor = members[next_index]
  next_turn_number = campaign['turn_number'].to_i + 1

  sequence = insert_play_event(campaign['id'], kind: 'resolution', actor: 'dm', text: text)

  db.execute(
    'UPDATE play_campaigns SET current_actor = ?, turn_index = ?, turn_number = ? WHERE id = ?',
    [next_actor, next_index, next_turn_number, campaign['id']]
  )

  status 201
  {
    sequence: sequence,
    kind: 'resolution',
    actor: 'dm',
    text: text,
    next_actor: next_actor,
    turn_number: next_turn_number
  }.to_json
end

get '/v1/play/campaigns/:id/turn' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  actor_role = if campaign['current_actor'] == campaign['owner']
                 'dm'
               else
                 db.execute('SELECT role FROM users WHERE username = ?', [campaign['current_actor']]).first&.fetch('role', nil)
               end

  queue = play_member_usernames(campaign['id']).flat_map { |username| [username, 'dm'] }

  turn_number = campaign['turn_number'].to_i
  deadline = turn_number + TURN_TIMEOUT_LOGICAL_TICKS

  {
    campaign_id: campaign['id'],
    current_actor: campaign['current_actor'],
    phase: actor_role,
    turn_number: campaign['turn_number'],
    queue: queue,
    overdue: false,
    logical_deadline: deadline
  }.to_json
end

post '/v1/play/campaigns/:id/turn/nudge' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  message = body['message']
  halt 400, { error: 'invalid message' }.to_json unless message.is_a?(String) && !message.empty?

  next_nudge_count = campaign['nudge_count'].to_i + 1

  db.execute(
    'UPDATE play_campaigns SET nudge_count = ? WHERE id = ?',
    [next_nudge_count, campaign['id']]
  )

  insert_play_event(campaign['id'], kind: 'nudge', actor: user['username'], text: message)

  status 201
  {
    actor: user['username'],
    target: campaign['current_actor'],
    message: message,
    nudge_count: next_nudge_count
  }.to_json
end

get '/v1/play/campaigns/:id/gm/status' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  party = db.execute(
    'SELECT username, character_id, name, class FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid ASC',
    [campaign['id']]
  ).map do |member|
    {
      username: member['username'],
      character_id: member['character_id'],
      name: member['name'],
      class: member['class']
    }
  end

  {
    needs_attention: campaign['current_actor'] == campaign['owner'],
    current_actor: campaign['current_actor'],
    party: party,
    recent_events: recent_play_events(campaign['id'])
  }.to_json
end

get '/v1/play/campaigns/:id/my-turn' do
  user = authenticate_play_request!
  halt 403, { error: 'forbidden' }.to_json unless user['role'] == 'player'

  campaign = find_play_campaign!(params[:id])

  member = db.execute(
    'SELECT * FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
    [campaign['id'], user['username']]
  ).first
  halt 403, { error: 'not a campaign member' }.to_json unless member

  {
    is_my_turn: campaign['current_actor'] == user['username'],
    current_actor: campaign['current_actor'],
    character: { id: member['character_id'], name: member['name'] },
    recent_events: recent_play_events(campaign['id'])
  }.to_json
end

post '/v1/play/campaigns/:id/turn/rest' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  is_active_player = user['role'] == 'player' && campaign['current_actor'] == user['username']
  halt 409, { error: 'not your turn' }.to_json unless is_active_player

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  type = body['type']
  halt 400, { error: 'invalid type' }.to_json unless %w[short long].include?(type)

  member = db.execute(
    'SELECT * FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
    [campaign['id'], user['username']]
  ).first

  hp_current = type == 'long' ? member['hp_max'] : member['hp_current']

  if hp_current != member['hp_current']
    db.execute(
      'UPDATE play_campaign_members SET hp_current = ? WHERE campaign_id = ? AND username = ?',
      [hp_current, campaign['id'], user['username']]
    )
  end

  sequence = insert_play_event(campaign['id'], kind: 'rest', actor: user['username'], text: type, type: type)

  db.execute(
    'UPDATE play_campaigns SET current_actor = ? WHERE id = ?',
    [campaign['owner'], campaign['id']]
  )

  status 201
  {
    sequence: sequence,
    kind: 'rest',
    actor: user['username'],
    type: type,
    hp_current: hp_current,
    hp_max: member['hp_max'],
    next_actor: 'dm'
  }.to_json
end
