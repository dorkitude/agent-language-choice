# Directed relationship graph among campaign entities (campaign member
# characters and NPCs). Edges are keyed by (source_id, target_id, kind).

def play_relationship_entity_exists?(campaign_id, entity_id)
  char = db.execute(
    'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
    [campaign_id, entity_id]
  ).first
  return true if char

  npc = db.execute(
    'SELECT 1 FROM play_npcs WHERE campaign_id = ? AND npc_id = ?',
    [campaign_id, entity_id]
  ).first
  !npc.nil?
end

def find_play_relationship!(campaign_id, source_id, target_id, kind)
  edge = db.execute(
    'SELECT * FROM play_relationships WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?',
    [campaign_id, source_id, target_id, kind]
  ).first
  halt 404, { error: 'relationship not found' }.to_json unless edge
  edge
end

def play_relationship_payload(edge)
  {
    source_id: edge['source_id'],
    target_id: edge['target_id'],
    kind: edge['kind'],
    score: edge['score']
  }
end

post '/v1/play/campaigns/:id/relationships' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  source_id = body['source_id']
  target_id = body['target_id']
  kind = body['kind']
  score = body['score']

  halt 400, { error: 'invalid source_id' }.to_json unless source_id.is_a?(String) && !source_id.empty?
  halt 400, { error: 'invalid target_id' }.to_json unless target_id.is_a?(String) && !target_id.empty?
  halt 400, { error: 'invalid kind' }.to_json unless kind.is_a?(String) && !kind.empty?
  halt 400, { error: 'invalid score' }.to_json unless integerish(score) && score.to_i.between?(-100, 100)
  halt 400, { error: 'source_id and target_id must differ' }.to_json if source_id == target_id

  halt 404, { error: 'unknown source entity' }.to_json unless play_relationship_entity_exists?(campaign['id'], source_id)
  halt 404, { error: 'unknown target entity' }.to_json unless play_relationship_entity_exists?(campaign['id'], target_id)

  existing = db.execute(
    'SELECT 1 FROM play_relationships WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?',
    [campaign['id'], source_id, target_id, kind]
  ).first
  halt 409, { error: 'relationship already exists' }.to_json if existing

  sequence = db.execute(
    'SELECT COALESCE(MAX(sequence), -1) + 1 AS seq FROM play_relationships WHERE campaign_id = ?',
    [campaign['id']]
  ).first['seq']

  db.execute(
    'INSERT INTO play_relationships (campaign_id, sequence, source_id, target_id, kind, score) VALUES (?, ?, ?, ?, ?, ?)',
    [campaign['id'], sequence, source_id, target_id, kind, score.to_i]
  )

  status 201
  { source_id: source_id, target_id: target_id, kind: kind, score: score.to_i }.to_json
end

put '/v1/play/campaigns/:id/relationships/:source_id/:target_id/:kind' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  edge = find_play_relationship!(campaign['id'], params[:source_id], params[:target_id], params[:kind])

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  score = body['score']
  halt 400, { error: 'invalid score' }.to_json unless integerish(score) && score.to_i.between?(-100, 100)

  db.execute(
    'UPDATE play_relationships SET score = ? WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?',
    [score.to_i, campaign['id'], edge['source_id'], edge['target_id'], edge['kind']]
  )

  { source_id: edge['source_id'], target_id: edge['target_id'], kind: edge['kind'], score: score.to_i }.to_json
end

get '/v1/play/campaigns/:id/relationships' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  edges = db.execute(
    'SELECT * FROM play_relationships WHERE campaign_id = ? ORDER BY sequence ASC',
    [campaign['id']]
  ).map { |edge| play_relationship_payload(edge) }

  { edges: edges }.to_json
end
