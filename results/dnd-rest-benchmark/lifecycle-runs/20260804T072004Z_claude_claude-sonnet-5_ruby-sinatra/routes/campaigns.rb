# Campaigns and their nested characters/event log. State is queried fresh
# from SQLite on every request (no in-memory cache).

post '/v1/campaigns' do
  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  id = body['id']
  name = body['name']
  dm = body['dm']

  halt 400, { error: 'invalid id' }.to_json unless id.is_a?(String) && !id.empty?
  halt 400, { error: 'invalid name' }.to_json unless name.is_a?(String) && !name.empty?
  halt 400, { error: 'invalid dm' }.to_json unless dm.is_a?(String) && !dm.empty?
  halt 409, { error: 'id already exists' }.to_json if db.execute('SELECT 1 FROM campaigns WHERE id = ?', [id]).first

  db.execute('INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)', [id, name, dm])

  status 201
  { id: id, name: name, dm: dm }.to_json
end

post '/v1/campaigns/:campaign_id/characters' do
  campaign = db.execute('SELECT 1 FROM campaigns WHERE id = ?', [params[:campaign_id]]).first
  halt 404, { error: 'unknown campaign' }.to_json unless campaign

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  id = body['id']
  name = body['name']
  level = body['level']
  klass = body['class']

  halt 400, { error: 'invalid id' }.to_json unless id.is_a?(String) && !id.empty?
  halt 400, { error: 'invalid name' }.to_json unless name.is_a?(String) && !name.empty?
  halt 400, { error: 'invalid level' }.to_json unless integerish(level)
  halt 400, { error: 'invalid class' }.to_json unless klass.is_a?(String) && !klass.empty?
  if db.execute('SELECT 1 FROM campaign_characters WHERE campaign_id = ? AND id = ?', [params[:campaign_id], id]).first
    halt 409, { error: 'id already exists' }.to_json
  end

  level = level.to_i

  db.execute(
    'INSERT INTO campaign_characters (campaign_id, id, name, level, class) VALUES (?, ?, ?, ?, ?)',
    [params[:campaign_id], id, name, level, klass]
  )

  status 201
  { id: id, name: name, level: level, class: klass }.to_json
end

post '/v1/campaigns/:campaign_id/events' do
  campaign = db.execute('SELECT 1 FROM campaigns WHERE id = ?', [params[:campaign_id]]).first
  halt 404, { error: 'unknown campaign' }.to_json unless campaign

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  id = body['id']
  kind = body['kind']
  summary = body['summary']

  halt 400, { error: 'invalid id' }.to_json unless id.is_a?(String) && !id.empty?
  halt 400, { error: 'invalid kind' }.to_json unless kind.is_a?(String) && !kind.empty?
  halt 400, { error: 'invalid summary' }.to_json unless summary.nil? || summary.is_a?(String)
  if db.execute('SELECT 1 FROM campaign_events WHERE campaign_id = ? AND id = ?', [params[:campaign_id], id]).first
    halt 409, { error: 'id already exists' }.to_json
  end

  db.execute(
    'INSERT INTO campaign_events (campaign_id, id, kind, summary) VALUES (?, ?, ?, ?)',
    [params[:campaign_id], id, kind, summary]
  )

  status 201
  { id: id, kind: kind }.to_json
end

get '/v1/campaigns/:campaign_id/state' do
  campaign = db.execute('SELECT * FROM campaigns WHERE id = ?', [params[:campaign_id]]).first
  halt 404, { error: 'unknown campaign' }.to_json unless campaign

  characters = db.execute(
    'SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY rowid',
    [params[:campaign_id]]
  ).map { |c| { id: c['id'], name: c['name'], level: c['level'], class: c['class'] } }

  log_count = db.execute('SELECT COUNT(*) AS cnt FROM campaign_events WHERE campaign_id = ?', [params[:campaign_id]]).first['cnt']

  {
    id: campaign['id'],
    name: campaign['name'],
    dm: campaign['dm'],
    characters: characters,
    log_count: log_count
  }.to_json
end
