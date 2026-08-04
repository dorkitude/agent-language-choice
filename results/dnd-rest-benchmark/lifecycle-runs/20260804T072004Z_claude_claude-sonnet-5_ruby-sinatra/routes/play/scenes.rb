# Scenes: DM-defined story beats within a campaign. At most one scene is
# "current" at a time (tracked on play_campaigns.current_scene_id); closing
# a scene does not clear that pointer, it just makes it stop resolving to
# an active scene for GET .../scenes/current.

post '/v1/play/campaigns/:id/scenes' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  id = body['id']
  name = body['name']
  halt 400, { error: 'invalid id' }.to_json unless id.is_a?(String) && !id.empty?
  halt 400, { error: 'invalid name' }.to_json unless name.is_a?(String) && !name.empty?

  existing = db.execute(
    'SELECT 1 FROM play_scenes WHERE campaign_id = ? AND id = ?',
    [campaign['id'], id]
  ).first
  halt 409, { error: 'scene id already exists' }.to_json if existing

  db.execute(
    'INSERT INTO play_scenes (campaign_id, id, name, status) VALUES (?, ?, ?, ?)',
    [campaign['id'], id, name, 'open']
  )

  status 201
  { id: id, name: name, status: 'open' }.to_json
end

post '/v1/play/campaigns/:id/scenes/:scene_id/enter' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  scene = db.execute(
    'SELECT * FROM play_scenes WHERE campaign_id = ? AND id = ?',
    [campaign['id'], params[:scene_id]]
  ).first
  halt 404, { error: 'scene not found' }.to_json unless scene
  halt 409, { error: 'scene is closed' }.to_json if scene['status'] == 'closed'

  db.execute(
    'UPDATE play_campaigns SET current_scene_id = ? WHERE id = ?',
    [scene['id'], campaign['id']]
  )

  insert_play_event(campaign['id'], kind: 'scene', actor: user['username'], text: scene['id'])

  { current_scene_id: scene['id'], name: scene['name'] }.to_json
end

post '/v1/play/campaigns/:id/scenes/:scene_id/close' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  scene = db.execute(
    'SELECT * FROM play_scenes WHERE campaign_id = ? AND id = ?',
    [campaign['id'], params[:scene_id]]
  ).first
  halt 404, { error: 'scene not found' }.to_json unless scene

  db.execute(
    'UPDATE play_scenes SET status = ? WHERE campaign_id = ? AND id = ?',
    ['closed', campaign['id'], scene['id']]
  )

  { id: scene['id'], status: 'closed' }.to_json
end

get '/v1/play/campaigns/:id/scenes/current' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  halt 404, { error: 'no current scene' }.to_json unless campaign['current_scene_id']

  scene = db.execute(
    'SELECT * FROM play_scenes WHERE campaign_id = ? AND id = ?',
    [campaign['id'], campaign['current_scene_id']]
  ).first
  halt 404, { error: 'no current scene' }.to_json unless scene && scene['status'] == 'open'

  { id: scene['id'], name: scene['name'], status: scene['status'] }.to_json
end
