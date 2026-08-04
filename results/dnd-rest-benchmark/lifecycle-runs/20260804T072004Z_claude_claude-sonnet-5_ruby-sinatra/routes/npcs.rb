# Campaign NPCs, factions, and a derived relationship summary.

STANCES = %w[friendly neutral hostile].freeze

post '/v1/campaigns/:campaign_id/factions' do
  halt 404, { error: 'unknown campaign' }.to_json unless campaign_exists?(params[:campaign_id])

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  id = body['id']
  name = body['name']
  stance = body['stance']

  halt 400, { error: 'invalid id' }.to_json unless id.is_a?(String) && !id.empty?
  halt 400, { error: 'invalid name' }.to_json unless name.is_a?(String) && !name.empty?
  halt 400, { error: 'invalid stance' }.to_json unless STANCES.include?(stance)
  if db.execute('SELECT 1 FROM campaign_factions WHERE campaign_id = ? AND id = ?', [params[:campaign_id], id]).first
    halt 409, { error: 'id already exists' }.to_json
  end

  db.execute(
    'INSERT INTO campaign_factions (campaign_id, id, name, stance) VALUES (?, ?, ?, ?)',
    [params[:campaign_id], id, name, stance]
  )

  status 201
  { id: id, name: name, stance: stance }.to_json
end

post '/v1/campaigns/:campaign_id/npcs' do
  halt 404, { error: 'unknown campaign' }.to_json unless campaign_exists?(params[:campaign_id])

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  id = body['id']
  name = body['name']
  faction_id = body['faction_id']
  disposition = body['disposition']

  halt 400, { error: 'invalid id' }.to_json unless id.is_a?(String) && !id.empty?
  halt 400, { error: 'invalid name' }.to_json unless name.is_a?(String) && !name.empty?
  unless faction_id.nil? || (faction_id.is_a?(String) && !faction_id.empty?)
    halt 400, { error: 'invalid faction_id' }.to_json
  end
  halt 400, { error: 'invalid disposition' }.to_json unless integerish(disposition)
  if !faction_id.nil? && !db.execute('SELECT 1 FROM campaign_factions WHERE campaign_id = ? AND id = ?', [params[:campaign_id], faction_id]).first
    halt 404, { error: 'unknown faction' }.to_json
  end
  if db.execute('SELECT 1 FROM campaign_npcs WHERE campaign_id = ? AND id = ?', [params[:campaign_id], id]).first
    halt 409, { error: 'id already exists' }.to_json
  end

  disposition = disposition.to_i

  db.execute(
    'INSERT INTO campaign_npcs (campaign_id, id, name, faction_id, disposition) VALUES (?, ?, ?, ?, ?)',
    [params[:campaign_id], id, name, faction_id, disposition]
  )

  status 201
  { id: id, name: name, faction_id: faction_id, disposition: disposition }.to_json
end

get '/v1/campaigns/:campaign_id/relationships' do
  halt 404, { error: 'unknown campaign' }.to_json unless campaign_exists?(params[:campaign_id])

  factions = db.execute('SELECT COUNT(*) AS cnt FROM campaign_factions WHERE campaign_id = ?', [params[:campaign_id]]).first['cnt']
  npcs = db.execute('SELECT COUNT(*) AS cnt FROM campaign_npcs WHERE campaign_id = ?', [params[:campaign_id]]).first['cnt']
  friendly_npcs = db.execute(
    'SELECT COUNT(*) AS cnt FROM campaign_npcs WHERE campaign_id = ? AND disposition > 0',
    [params[:campaign_id]]
  ).first['cnt']

  {
    campaign_id: params[:campaign_id],
    factions: factions,
    npcs: npcs,
    friendly_npcs: friendly_npcs
  }.to_json
end
