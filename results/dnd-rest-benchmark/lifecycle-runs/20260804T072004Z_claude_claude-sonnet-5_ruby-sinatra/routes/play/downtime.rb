# Recurring downtime activities that campaign members allocate to owned
# characters and progress repeatedly (cycles_completed resets to 0 and
# completions increments each time cycles_required is reached).

def play_downtime_activity_payload(activity)
  {
    activity_id: activity['activity_id'],
    name: activity['name'],
    cycles_required: activity['cycles_required']
  }
end

def play_downtime_allocation_payload(allocation)
  {
    character_id: allocation['character_id'],
    activity_id: allocation['activity_id'],
    cycles_completed: allocation['cycles_completed'],
    completions: allocation['completions']
  }
end

def validate_downtime_activity_fields!(body)
  activity_id = body['activity_id']
  name = body['name']
  cycles_required = body['cycles_required']

  halt 400, { error: 'invalid activity_id' }.to_json unless activity_id.is_a?(String) && !activity_id.empty?
  halt 400, { error: 'invalid name' }.to_json unless name.is_a?(String) && !name.empty?
  unless integerish(cycles_required) && cycles_required.to_i.between?(1, 10)
    halt 400, { error: 'invalid cycles_required' }.to_json
  end

  [activity_id, name, cycles_required.to_i]
end

def find_play_downtime_activity!(campaign_id, activity_id)
  activity = db.execute(
    'SELECT * FROM play_downtime_activities WHERE campaign_id = ? AND activity_id = ?',
    [campaign_id, activity_id]
  ).first
  halt 404, { error: 'activity not found' }.to_json unless activity
  activity
end

def find_play_downtime_allocation!(campaign_id, character_id, activity_id)
  allocation = db.execute(
    'SELECT * FROM play_downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?',
    [campaign_id, character_id, activity_id]
  ).first
  halt 404, { error: 'allocation not found' }.to_json unless allocation
  allocation
end

post '/v1/play/campaigns/:id/downtime/activities' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  activity_id, name, cycles_required = validate_downtime_activity_fields!(body)

  existing = db.execute(
    'SELECT 1 FROM play_downtime_activities WHERE campaign_id = ? AND activity_id = ?',
    [campaign['id'], activity_id]
  ).first
  halt 409, { error: 'activity already exists' }.to_json if existing

  sequence = db.execute(
    'SELECT COALESCE(MAX(sequence), 0) + 1 AS n FROM play_downtime_activities WHERE campaign_id = ?',
    [campaign['id']]
  ).first['n']

  db.execute(
    'INSERT INTO play_downtime_activities (campaign_id, sequence, activity_id, name, cycles_required) VALUES (?, ?, ?, ?, ?)',
    [campaign['id'], sequence, activity_id, name, cycles_required]
  )

  status 201
  play_downtime_activity_payload(find_play_downtime_activity!(campaign['id'], activity_id)).to_json
end

post '/v1/play/campaigns/:id/characters/:character_id/downtime/allocations' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  member = find_play_member_by_character!(campaign['id'], params[:character_id])
  owner = play_character_owner(campaign['id'], params[:character_id], member)
  halt 403, { error: 'not the character owner' }.to_json unless owner == user['username']

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  activity_id = body['activity_id']
  halt 400, { error: 'invalid activity_id' }.to_json unless activity_id.is_a?(String) && !activity_id.empty?

  find_play_downtime_activity!(campaign['id'], activity_id)

  existing = db.execute(
    'SELECT 1 FROM play_downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?',
    [campaign['id'], params[:character_id], activity_id]
  ).first
  halt 409, { error: 'allocation already exists' }.to_json if existing

  db.execute(
    'INSERT INTO play_downtime_allocations (campaign_id, character_id, activity_id, cycles_completed, completions) VALUES (?, ?, ?, 0, 0)',
    [campaign['id'], params[:character_id], activity_id]
  )

  status 201
  play_downtime_allocation_payload(
    find_play_downtime_allocation!(campaign['id'], params[:character_id], activity_id)
  ).to_json
end

post '/v1/play/campaigns/:id/characters/:character_id/downtime/allocations/:activity_id/progress' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  member = find_play_member_by_character!(campaign['id'], params[:character_id])
  owner = play_character_owner(campaign['id'], params[:character_id], member)
  halt 403, { error: 'not the character owner' }.to_json unless owner == user['username']

  activity = find_play_downtime_activity!(campaign['id'], params[:activity_id])
  allocation = find_play_downtime_allocation!(campaign['id'], params[:character_id], params[:activity_id])

  cycles_completed = allocation['cycles_completed'] + 1
  completions = allocation['completions']

  if cycles_completed >= activity['cycles_required']
    cycles_completed = 0
    completions += 1
  end

  db.execute(
    'UPDATE play_downtime_allocations SET cycles_completed = ?, completions = ? WHERE campaign_id = ? AND character_id = ? AND activity_id = ?',
    [cycles_completed, completions, campaign['id'], params[:character_id], params[:activity_id]]
  )

  play_downtime_allocation_payload(
    find_play_downtime_allocation!(campaign['id'], params[:character_id], params[:activity_id])
  ).to_json
end

get '/v1/play/campaigns/:id/characters/:character_id/downtime/allocations/:activity_id' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  find_play_downtime_activity!(campaign['id'], params[:activity_id])
  find_play_member_by_character!(campaign['id'], params[:character_id])
  allocation = find_play_downtime_allocation!(campaign['id'], params[:character_id], params[:activity_id])

  play_downtime_allocation_payload(allocation).to_json
end
